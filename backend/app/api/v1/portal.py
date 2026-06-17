""" 
Supplier Portal API — authenticated with supplier JWT.
Token payload: {"sub": str(supplier_id), "role": "supplier"}
"""
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.core.config import settings
from app.core.database import get_db
from app.core.security import verify_password, create_access_token, decode_token
from app.models.supplier import Supplier, Invoice, SupplierProduct
from app.models.product import Product, ProductSupplier, ProductComponent
from app.models.order import Order, OrderLineItem, ShippingLabel, FulfillStatus, OrderFulfillmentItem
from app.api.v1.orders import _recalculate_order_status
from app.api.v1.easypost import ParcelIn, RateOut, RatesResponse, DebugInfo
from app.integrations.easypost.client import (
    EasyPostClient, EasyPostError,
    supplier_to_ep_address, shipping_addr_to_ep,
)
from app.schemas.order import ShippingLabelOut

router = APIRouter(prefix="/portal", tags=["supplier-portal"])


# --- Auth ---

@router.post("/login")
async def supplier_login(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    username = body.get("username", "")
    password = body.get("password", "")
    result = await db.execute(select(Supplier).where(Supplier.username == username))
    supplier = result.scalar_one_or_none()
    if not supplier or not supplier.hashed_password:
        raise HTTPException(401, "Invalid credentials")
    if not verify_password(password, supplier.hashed_password):
        raise HTTPException(401, "Invalid credentials")
    token = create_access_token(supplier.id, extra={"role": "supplier"})
    return {
        "access_token": token,
        "token_type": "bearer",
        "supplier_id": supplier.id,
        "name": supplier.name,
        "can_buy_labels": supplier.can_buy_labels,
    }


async def get_current_supplier(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> Supplier:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Invalid auth header")
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(401, "Invalid token")
    if payload.get("role") != "supplier":
        raise HTTPException(403, "Supplier access only")
    supplier = await db.get(Supplier, int(payload["sub"]))
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    return supplier


@router.get("/me")
async def portal_me(supplier: Supplier = Depends(get_current_supplier)):
    return {
        "id": supplier.id,
        "name": supplier.name,
        "email": supplier.email,
        "can_buy_labels": supplier.can_buy_labels,
    }


# --- Catalog (supplier's own products) ---

@router.get("/products")
async def portal_products(
    supplier: Supplier = Depends(get_current_supplier),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SupplierProduct)
        .where(SupplierProduct.supplier_id == supplier.id)
        .order_by(SupplierProduct.name)
    )
    items = result.scalars().all()
    return [
        {
            "id": sp.id,
            "name": sp.name,
            "short_name": sp.short_name,
            "sku": sp.sku,
            "unit_price": float(sp.unit_price),
            "stock_quantity": sp.stock_quantity,
            "weight": float(sp.weight) if sp.weight is not None else None,
            "length": float(sp.length) if sp.length is not None else None,
            "width": float(sp.width) if sp.width is not None else None,
            "height": float(sp.height) if sp.height is not None else None,
            "image_url": sp.image_url,
            "updated_at": sp.updated_at.isoformat() if sp.updated_at else None,
        }
        for sp in items
    ]


# --- Orders to fulfill ---

def _supplier_status(fulfill_status: FulfillStatus, label_id: int | None) -> str:
    """Map DB fulfill_status + label presence to supplier-facing status string."""
    if fulfill_status in (FulfillStatus.shipped, FulfillStatus.delivered):
        return "shipped"
    if fulfill_status == FulfillStatus.drop_off:
        return "fulfilled"
    if fulfill_status == FulfillStatus.pending or label_id is not None:
        return "unfulfilled"
    return "pending_label"


@router.get("/orders")
async def portal_orders(
    supplier_status: str | None = None,
    supplier: Supplier = Depends(get_current_supplier),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import or_, and_
    q = select(OrderLineItem).where(OrderLineItem.supplier_id == supplier.id)
    if supplier_status == "pending_label":
        q = q.where(
            OrderLineItem.fulfill_status == FulfillStatus.unfulfilled,
            OrderLineItem.label_id.is_(None),
        )
    elif supplier_status == "unfulfilled":
        q = q.where(
            or_(
                OrderLineItem.fulfill_status == FulfillStatus.pending,
                and_(
                    OrderLineItem.fulfill_status == FulfillStatus.unfulfilled,
                    OrderLineItem.label_id.isnot(None),
                ),
            )
        )
    elif supplier_status == "fulfilled":
        q = q.where(OrderLineItem.fulfill_status == FulfillStatus.drop_off)
    elif supplier_status == "shipped":
        q = q.where(
            OrderLineItem.fulfill_status.in_([FulfillStatus.shipped, FulfillStatus.delivered])
        )
    result = await db.execute(q.order_by(OrderLineItem.id.desc()))
    lis = result.scalars().all()
    out = []
    created_ofi = False  # backfill flag: persist resolved catalog links so they survive
    for li in lis:
        order = await db.get(Order, li.order_id)
        label = await db.get(ShippingLabel, li.label_id) if li.label_id else None
        base = {
            "order_id": li.order_id,
            "order_line_item_id": li.id,
            "external_order_id": order.external_order_id if order else None,
            "marketplace": order.marketplace if order else None,
            "ordered_at": order.ordered_at.isoformat() if order else None,
            "buyer_name": order.buyer_name if order else None,
            "shipping_address": order.shipping_address if order else None,
            "label_id": li.label_id,
            "label_url": label.label_url if label else None,
            "label_has_pdf": bool(label and label.label_data) if label else False,
        }
        fi_res = await db.execute(
            select(OrderFulfillmentItem).where(OrderFulfillmentItem.order_line_item_id == li.id)
        )
        fis = fi_res.scalars().all()
        if fis:
            for fi in fis:
                sp = await db.get(SupplierProduct, fi.supplier_product_id)
                out.append({
                    **base,
                    "item_key": f"fi_{fi.id}",
                    "product_name": (sp.short_name or sp.name) if sp else li.product_name,
                    "sku": sp.sku if sp else li.sku,
                    "image_url": sp.image_url if sp else None,
                    "quantity": fi.quantity,
                    "supplier_status": _supplier_status(fi.fulfill_status, li.label_id),
                    "tracking_number": fi.tracking_number or li.tracking_number,
                    "fulfilled_at": (fi.fulfilled_at.isoformat() if fi.fulfilled_at
                                     else (li.fulfilled_at.isoformat() if li.fulfilled_at else None)),
                })
        else:
            resolved = False
            if li.product_id:
                comp_res = await db.execute(
                    select(ProductComponent)
                    .join(SupplierProduct, ProductComponent.supplier_product_id == SupplierProduct.id)
                    .where(
                        ProductComponent.product_id == li.product_id,
                        SupplierProduct.supplier_id == supplier.id,
                    )
                )
                comps = list(comp_res.scalars().all())
                if comps:
                    for comp in comps:
                        sp = await db.get(SupplierProduct, comp.supplier_product_id)
                        # Backfill: persist the catalog link so future loads/parcel
                        # estimates/label overlays resolve via OrderFulfillmentItem.
                        db.add(OrderFulfillmentItem(
                            order_line_item_id=li.id,
                            supplier_product_id=comp.supplier_product_id,
                            quantity=comp.quantity * li.quantity,
                            fulfill_status=li.fulfill_status.value,
                            tracking_number=li.tracking_number,
                            label_id=li.label_id,
                            fulfilled_at=li.fulfilled_at,
                        ))
                        created_ofi = True
                        out.append({
                            **base,
                            "item_key": f"comp_{comp.id}_{li.id}",
                            "product_name": (sp.short_name or sp.name) if sp else li.product_name,
                            "sku": sp.sku if sp else li.sku,
                            "image_url": sp.image_url if sp else None,
                            "quantity": comp.quantity * li.quantity,
                            "supplier_status": _supplier_status(li.fulfill_status, li.label_id),
                            "tracking_number": li.tracking_number,
                            "fulfilled_at": li.fulfilled_at.isoformat() if li.fulfilled_at else None,
                        })
                    resolved = True
            if not resolved:
                # Tertiary fallback: match a SupplierProduct by SKU for this supplier
                # (case-insensitive + trimmed, since marketplace SKUs vary in casing/whitespace)
                if li.sku:
                    from sqlalchemy import func
                    norm_sku = li.sku.strip().lower()
                    sp_res = await db.execute(
                        select(SupplierProduct).where(
                            SupplierProduct.supplier_id == supplier.id,
                            func.lower(func.trim(SupplierProduct.sku)) == norm_sku,
                        )
                    )
                    sp = sp_res.scalars().first()
                    if sp:
                        # Backfill: persist the catalog link via OrderFulfillmentItem.
                        db.add(OrderFulfillmentItem(
                            order_line_item_id=li.id,
                            supplier_product_id=sp.id,
                            quantity=li.quantity,
                            fulfill_status=li.fulfill_status.value,
                            tracking_number=li.tracking_number,
                            label_id=li.label_id,
                            fulfilled_at=li.fulfilled_at,
                        ))
                        created_ofi = True
                        out.append({
                            **base,
                            "item_key": f"li_{li.id}",
                            "product_name": sp.short_name or sp.name,
                            "sku": sp.sku,
                            "image_url": sp.image_url,
                            "quantity": li.quantity,
                            "supplier_status": _supplier_status(li.fulfill_status, li.label_id),
                            "tracking_number": li.tracking_number,
                            "fulfilled_at": li.fulfilled_at.isoformat() if li.fulfilled_at else None,
                        })
                        resolved = True
            if not resolved:
                out.append({
                    **base,
                    "item_key": f"li_{li.id}",
                    "product_name": li.product_name,
                    "sku": li.sku,
                    "image_url": None,
                    "quantity": li.quantity,
                    "supplier_status": _supplier_status(li.fulfill_status, li.label_id),
                    "tracking_number": li.tracking_number,
                    "fulfilled_at": li.fulfilled_at.isoformat() if li.fulfilled_at else None,
                })
    if created_ofi:
        await db.commit()
    return out


def _addr_name(addr: dict | None) -> str | None:
    if not addr:
        return None
    parts = [addr.get("name"), addr.get("city"), addr.get("state")]
    return ", ".join(p for p in parts if p) or None


@router.get("/orders/batch-labels.pdf")
async def portal_batch_labels(
    label_ids: str | None = Query(None, description="Comma-separated label IDs; omit = all printable unfulfilled labels"),
    supplier: Supplier = Depends(get_current_supplier),
    db: AsyncSession = Depends(get_db),
):
    """Combine every unfulfilled label for this supplier into one PDF with catalog overlay.

    For labels that already have label_data (overlay baked in at buy time) those
    pages are used directly. For labels that only have a label_url, the PDF/PNG is
    fetched from EasyPost's CDN as-is.
    """
    import httpx
    import base64
    from app.integrations.pdf_labels import decode_label_data, concat_label_pdfs, image_to_label_pdf

    wanted_ids: set[int] | None = None
    if label_ids:
        try:
            wanted_ids = {int(x) for x in label_ids.split(",") if x.strip()}
        except ValueError:
            raise HTTPException(400, "Invalid label_ids")

    q = select(OrderLineItem).where(
        OrderLineItem.supplier_id == supplier.id,
        OrderLineItem.label_id.isnot(None),
        OrderLineItem.fulfill_status.in_([FulfillStatus.unfulfilled, FulfillStatus.pending]),
    ).order_by(OrderLineItem.order_id)
    lis = (await db.execute(q)).scalars().all()

    from collections import defaultdict
    label_to_lis: dict[int, list] = defaultdict(list)
    for li in lis:
        if li.label_id is None:
            continue
        if wanted_ids is not None and li.label_id not in wanted_ids:
            continue
        label_to_lis[li.label_id].append(li)

    pdf_pages: list[bytes] = []

    for label_id, label_lis in label_to_lis.items():
        label = await db.get(ShippingLabel, label_id)
        if not label or label.supplier_id != supplier.id:
            continue

        if label.label_data:
            pdf = decode_label_data(label.label_data)
            if pdf:
                pdf_pages.append(pdf)
                continue

        if not label.label_url:
            continue
        try:
            async with httpx.AsyncClient(timeout=20) as http:
                r = await http.get(label.label_url)
            if not r.is_success:
                continue
            content = r.content
        except Exception:
            continue

        try:
            if content[:5] == b"%PDF-":
                pdf_pages.append(content)
            else:
                pdf_pages.append(image_to_label_pdf(content))
        except Exception:
            continue

    if not pdf_pages:
        raise HTTPException(404, "No printable labels found")

    return Response(
        content=concat_label_pdfs(pdf_pages),
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="batch_labels.pdf"'},
    )


@router.patch("/orders/{item_id}/ship")
async def mark_shipped(
    item_id: int,
    body: dict,
    supplier: Supplier = Depends(get_current_supplier),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(OrderLineItem).where(
            OrderLineItem.id == item_id,
            OrderLineItem.supplier_id == supplier.id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Order item not found")
    item.fulfill_status = FulfillStatus.shipped
    item.tracking_number = body.get("tracking_number") or item.tracking_number
    item.fulfilled_at = datetime.now(timezone.utc)

    # Update OFIs and deduct stock
    fi_res = await db.execute(
        select(OrderFulfillmentItem).where(OrderFulfillmentItem.order_line_item_id == item.id)
    )
    for fi in fi_res.scalars().all():
        if fi.fulfill_status not in (FulfillStatus.shipped, FulfillStatus.delivered):
            fi.fulfill_status = FulfillStatus.shipped.value
            fi.fulfilled_at = item.fulfilled_at
            if item.tracking_number and not fi.tracking_number:
                fi.tracking_number = item.tracking_number
            sp = await db.get(SupplierProduct, fi.supplier_product_id)
            if sp:
                sp.stock_quantity = max(0, sp.stock_quantity - fi.quantity)

    order = await db.get(Order, item.order_id)
    if order:
        await _recalculate_order_status(order, db)

    await db.commit()
    return {"status": "shipped", "tracking_number": item.tracking_number}


# --- EasyPost label purchase (supplier self-service) ---

class PortalRatesRequest(BaseModel):
    order_id: int
    parcel: ParcelIn


class PortalBuyRequest(BaseModel):
    order_id: int
    shipment_id: str
    rate_id: str


def _require_can_buy_labels(supplier: Supplier) -> None:
    if not supplier.can_buy_labels:
        raise HTTPException(
            403,
            "Label purchase is not enabled for your account. Please contact the platform admin.",
        )


async def _supplier_line_items_for_order(
    db: AsyncSession, order_id: int, supplier_id: int
) -> list[OrderLineItem]:
    res = await db.execute(
        select(OrderLineItem).where(
            OrderLineItem.order_id == order_id,
            OrderLineItem.supplier_id == supplier_id,
            OrderLineItem.fulfill_status.in_([FulfillStatus.unfulfilled, FulfillStatus.pending]),
        )
    )
    return list(res.scalars().all())


@router.post("/orders/{order_id}/labels/{label_id}/mark-printed")
async def portal_mark_label_printed(
    order_id: int,
    label_id: int,
    supplier: Supplier = Depends(get_current_supplier),
    db: AsyncSession = Depends(get_db),
):
    """Supplier prints the label → move linked line items to shipped and recalculate order status."""
    label = await db.get(ShippingLabel, label_id)
    if not label or label.supplier_id != supplier.id:
        raise HTTPException(404, "Label not found")

    now = datetime.now(timezone.utc)
    li_res = await db.execute(
        select(OrderLineItem).where(
            OrderLineItem.label_id == label_id,
            OrderLineItem.order_id == order_id,
        )
    )
    line_items = li_res.scalars().all()
    for li in line_items:
        if li.fulfill_status not in (FulfillStatus.shipped, FulfillStatus.delivered):
            li.fulfill_status = FulfillStatus.shipped
            li.fulfilled_at = now
            if label.tracking_number and not li.tracking_number:
                li.tracking_number = label.tracking_number
            # Update OFIs and deduct stock
            fi_res = await db.execute(
                select(OrderFulfillmentItem).where(OrderFulfillmentItem.order_line_item_id == li.id)
            )
            for fi in fi_res.scalars().all():
                if fi.fulfill_status not in (FulfillStatus.shipped, FulfillStatus.delivered):
                    fi.fulfill_status = FulfillStatus.shipped.value
                    fi.fulfilled_at = now
                    if label.tracking_number and not fi.tracking_number:
                        fi.tracking_number = label.tracking_number
                    sp = await db.get(SupplierProduct, fi.supplier_product_id)
                    if sp:
                        sp.stock_quantity = max(0, sp.stock_quantity - fi.quantity)

    if line_items:
        order = await db.get(Order, order_id)
        if order:
            await _recalculate_order_status(order, db)

    await db.commit()
    return {"status": "ok", "label_id": label_id, "items_shipped": len(line_items)}


@router.get("/orders/{order_id}/parcel-estimate")
async def portal_parcel_estimate(
    order_id: int,
    supplier: Supplier = Depends(get_current_supplier),
    db: AsyncSession = Depends(get_db),
):
    """Same parcel estimate as the admin endpoint but scoped to the current supplier."""
    from app.api.v1.orders import estimate_parcel
    return await estimate_parcel(
        order_id=order_id,
        supplier_id=supplier.id,
        line_item_ids=None,
        db=db,
    )


@router.post("/orders/easypost/rates", response_model=RatesResponse)
async def portal_easypost_rates(
    body: PortalRatesRequest,
    supplier: Supplier = Depends(get_current_supplier),
    db: AsyncSession = Depends(get_db),
):
    _require_can_buy_labels(supplier)
    if not settings.EASYPOST_API_KEY:
        raise HTTPException(503, "EasyPost API key not configured")

    order = await db.get(Order, body.order_id)
    if not order:
        raise HTTPException(404, "Order not found")

    items = await _supplier_line_items_for_order(db, body.order_id, supplier.id)
    if not items:
        raise HTTPException(404, "No unshipped items in this order belong to you")
    if not order.shipping_address:
        raise HTTPException(400, "Order has no shipping address")
    if not supplier.street1:
        raise HTTPException(400, "Your supplier address is incomplete — ask the admin to update it")

    ep = EasyPostClient(settings.EASYPOST_API_KEY)
    from_addr = supplier_to_ep_address(supplier)
    to_addr = shipping_addr_to_ep(order.shipping_address)
    parcel = {
        "weight": body.parcel.weight,
        "length": body.parcel.length,
        "width": body.parcel.width,
        "height": body.parcel.height,
    }
    carrier_accounts = [
        x.strip() for x in settings.EASYPOST_CARRIER_ACCOUNT_IDS.split(",") if x.strip()
    ] or None
    try:
        shipment = await ep.create_shipment(to_addr, from_addr, parcel, carrier_accounts)
    except EasyPostError as e:
        raise HTTPException(e.status, str(e))

    # Return all rates from all carriers — no filtering
    all_rates = shipment.get("rates", [])
    print(f"[PORTAL RATES] EasyPost returned {len(all_rates)} rates total", flush=True)
    for r in all_rates:
        print(f"  carrier={r.get('carrier')} service={r.get('service')} rate={r.get('rate')}", flush=True)

    rates_out = []
    for r in all_rates:
        try:
            rates_out.append(RateOut(
                id=r["id"],
                carrier=r.get("carrier", ""),
                service=r.get("service", ""),
                rate=r.get("rate") or "0",
                currency=r.get("currency", "USD"),
                delivery_days=r.get("delivery_days"),
                delivery_date=r.get("delivery_date"),
                est_delivery_days=r.get("est_delivery_days"),
            ))
        except Exception as e:
            print(f"  [SKIP] rate build failed: {e} — raw: {r}", flush=True)

    print(f"[PORTAL RATES] rates_out has {len(rates_out)} items after build", flush=True)
    rates_out = sorted(rates_out, key=lambda r: float(r.rate))
    debug = DebugInfo(
        from_address=from_addr,
        to_address=to_addr,
        parcel=parcel,
        total_rates=len(all_rates),
        filtered_rates=len(rates_out),
        line_item_ids=[li.id for li in items],
    )
    return RatesResponse(shipment_id=shipment["id"], rates=rates_out, debug=debug)


@router.post("/orders/easypost/buy", response_model=ShippingLabelOut, status_code=201)
async def portal_easypost_buy(
    body: PortalBuyRequest,
    supplier: Supplier = Depends(get_current_supplier),
    db: AsyncSession = Depends(get_db),
):
    _require_can_buy_labels(supplier)
    if not settings.EASYPOST_API_KEY:
        raise HTTPException(503, "EasyPost API key not configured")

    order = await db.get(Order, body.order_id)
    if not order:
        raise HTTPException(404, "Order not found")

    items = await _supplier_line_items_for_order(db, body.order_id, supplier.id)
    if not items:
        raise HTTPException(404, "No unshipped items in this order belong to you")

    from decimal import InvalidOperation
    import base64

    ep = EasyPostClient(settings.EASYPOST_API_KEY)
    try:
        bought = await ep.buy_shipment(body.shipment_id, body.rate_id)
    except EasyPostError as e:
        raise HTTPException(e.status, str(e))

    selected_rate = bought.get("selected_rate") or {}
    postage_label = bought.get("postage_label") or {}
    tracking = bought.get("tracking_code") or selected_rate.get("tracking_code")
    label_url = postage_label.get("label_url") or postage_label.get("label_pdf_url")
    try:
        cost_val = Decimal(str(selected_rate.get("rate") or "0"))
    except (InvalidOperation, ValueError):
        cost_val = Decimal("0")

    # Download carrier label and stamp product info
    carrier_raw: bytes | None = None
    if label_url:
        try:
            import httpx as _httpx
            async with _httpx.AsyncClient(timeout=20) as _http:
                _r = await _http.get(label_url)
            if _r.is_success:
                carrier_raw = _r.content
        except Exception:
            pass

    if not carrier_raw:
        carrier_png_b64 = await ep.fetch_label_pdf_b64(bought)
        if carrier_png_b64:
            carrier_raw = base64.b64decode(carrier_png_b64)

    label_data = None
    if carrier_raw:
        try:
            from app.api.v1.orders import _catalog_items_for_line_item
            from app.integrations.pdf_labels import LabelEntry, stamp_label, image_to_label_pdf, PackItem
            pack_items = []
            for li in items:
                pack_items.extend(await _catalog_items_for_line_item(li, db))
            if pack_items:
                entry = LabelEntry(
                    order_label=(order.external_order_id or f"Order #{body.order_id}"),
                    ship_to=_addr_name(order.shipping_address),
                    tracking_number=tracking,
                    label_pdf=None,
                    items=pack_items,
                    supplier_name=supplier.name,
                )
                label_data = base64.b64encode(stamp_label(carrier_raw, entry)).decode()
            elif carrier_raw[:5] == b"%PDF-":
                label_data = base64.b64encode(carrier_raw).decode()
            else:
                label_data = base64.b64encode(image_to_label_pdf(carrier_raw)).decode()
        except Exception:
            label_data = base64.b64encode(carrier_raw).decode() if carrier_raw[:5] == b"%PDF-" else None

    label = ShippingLabel(
        supplier_id=supplier.id,
        carrier=selected_rate.get("carrier", "USPS"),
        service=selected_rate.get("service", ""),
        tracking_number=tracking,
        shipment_id=bought.get("id") or body.shipment_id,
        label_url=label_url,
        label_data=label_data,
        cost=cost_val,
        from_address=bought.get("from_address"),
        to_address=bought.get("to_address"),
    )
    db.add(label)
    await db.flush()

    for li in items:
        li.label_id = label.id
        li.tracking_number = tracking
        if li.fulfill_status == FulfillStatus.unfulfilled:
            li.fulfill_status = FulfillStatus.pending

    await _recalculate_order_status(order, db)
    await db.commit()
    await db.refresh(label)
    return label


# --- Invoices ---

@router.get("/invoices")
async def portal_invoices(
    supplier: Supplier = Depends(get_current_supplier),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Invoice).where(Invoice.supplier_id == supplier.id).order_by(Invoice.created_at.desc())
    )
    invoices = result.scalars().all()
    return [
        {
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "period_start": inv.period_start.isoformat(),
            "period_end": inv.period_end.isoformat(),
            "total_amount": float(inv.total_amount),
            "status": inv.status,
            "paid_at": inv.paid_at.isoformat() if inv.paid_at else None,
            "created_at": inv.created_at.isoformat(),
        }
        for inv in invoices
    ]
