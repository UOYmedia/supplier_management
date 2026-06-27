from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, exists as sa_exists, or_, func
from datetime import datetime, timezone, timedelta
import base64
import io
import os
import re
import asyncio
import logging
import pytesseract
from PIL import Image, ImageDraw, ImageFont
from app.core.database import get_db
from app.models.order import Order, OrderLineItem, ShippingLabel, FulfillStatus, OrderStatus, OrderFulfillmentItem, OrderEvent
from app.models.product import Product, ProductSupplier, ProductComponent
from app.models.supplier import Supplier, SupplierProduct
from app.models.scan_log import ScanLog
from app.schemas.order import (
    OrderCreate, OrderUpdate, OrderOut, OrderLineItemUpdate,
    OrderLineItemOut, ShippingLabelCreate, ShippingLabelOut, ShippingLabelUpdate,
    AssignSupplierBody, MarkShippedBody, UploadLabelB64, ScanLabelBody,
)

router = APIRouter(prefix="/orders", tags=["orders"])
logger = logging.getLogger("orders")


def _apply_order_filters(q, *, marketplace, status, supplier_id, from_date, to_date, search):
    """Áp dụng các điều kiện lọc dùng chung cho cả list và count."""
    if search:
        s = search.strip()
        conds = [
            Order.external_order_id.ilike(f"%{s}%"),
            Order.order_name.ilike(f"%{s}%"),
        ]
        if s.isdigit():
            conds.append(Order.id == int(s))
        q = q.where(or_(*conds))
    if marketplace:
        q = q.where(Order.marketplace == marketplace)
    if status:
        q = q.where(Order.status == status)
    if supplier_id:
        q = q.where(Order.line_items.any(OrderLineItem.supplier_id == supplier_id))
    if from_date:
        q = q.where(Order.ordered_at >= from_date)
    if to_date:
        q = q.where(Order.ordered_at <= to_date)
    return q


@router.get("/count")
async def count_orders(
    marketplace: str | None = Query(None),
    status: str | None = Query(None),
    supplier_id: int | None = Query(None),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = _apply_order_filters(
        select(func.count(Order.id)),
        marketplace=marketplace, status=status, supplier_id=supplier_id,
        from_date=from_date, to_date=to_date, search=search,
    )
    total = (await db.execute(q)).scalar_one()
    return {"total": total}


@router.get("", response_model=list[OrderOut])
async def list_orders(
    marketplace: str | None = Query(None),
    status: str | None = Query(None),
    supplier_id: int | None = Query(None),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    search: str | None = Query(None),
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    q = _apply_order_filters(
        select(Order),
        marketplace=marketplace, status=status, supplier_id=supplier_id,
        from_date=from_date, to_date=to_date, search=search,
    )
    effective_limit = 500 if (from_date or to_date) else limit
    result = await db.execute(q.order_by(Order.ordered_at.desc()).offset(skip).limit(effective_limit))
    orders = result.scalars().all()
    return [await _order_out(o, db) for o in orders]


@router.post("", response_model=OrderOut, status_code=201)
async def create_order(body: OrderCreate, db: AsyncSession = Depends(get_db)):
    order = Order(
        marketplace=body.marketplace,
        buyer_name=body.buyer_name,
        buyer_email=body.buyer_email,
        shipping_address=body.shipping_address.model_dump() if body.shipping_address else None,
        currency=body.currency,
        notes=body.notes,
        total=sum(li.price * li.quantity for li in body.line_items),
    )
    db.add(order)
    await db.flush()

    for li in body.line_items:
        supplier_id = li.supplier_id
        base_cost = li.base_cost
        if not supplier_id and li.product_id:
            ps_result = await db.execute(
                select(ProductSupplier)
                .where(ProductSupplier.product_id == li.product_id, ProductSupplier.is_preferred == True)
            )
            ps = ps_result.scalar_one_or_none()
            if ps:
                supplier_id = ps.supplier_id
                base_cost = ps.cost

        db.add(OrderLineItem(
            order_id=order.id,
            product_id=li.product_id,
            supplier_id=supplier_id,
            listing_id=li.listing_id,
            product_name=li.product_name,
            sku=li.sku,
            quantity=li.quantity,
            price=li.price,
            base_cost=base_cost,
        ))

    await db.commit()
    await db.refresh(order)
    return await _order_out(order, db)


# Full US state / territory name -> 2-letter code (labels use either form)
_STATES = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
    "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE",
    "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID",
    "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
    "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
    "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT",
    "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV",
    "WISCONSIN": "WI", "WYOMING": "WY", "DISTRICT OF COLUMBIA": "DC",
    "PUERTO RICO": "PR",
}
_ABBRS = set(_STATES.values())


def _parse_csz(line: str) -> dict | None:
    """Parse a "CITY STATE ZIP" line. STATE may be a 2-letter code or full name."""
    m = re.search(r"\b(\d{5})(?:-\d{4})?\s*$", line)
    if not m:
        return None
    zipc = line[m.start():].strip()
    head = line[:m.start()].strip(" ,.")
    if not head:
        return None
    words = head.split()
    state = city = None
    # Two-word state name (e.g. "NEW JERSEY")
    if len(words) >= 3 and " ".join(words[-2:]).upper() in _STATES:
        state = _STATES[" ".join(words[-2:]).upper()]
        city = " ".join(words[:-2])
    elif words:
        last = words[-1].upper()
        if last in _STATES:                       # full single-word state name
            state = _STATES[last]
        elif len(last) == 2 and last.isalpha():    # 2-letter code (NJ, IA, ...)
            state = last
        if state:
            city = " ".join(words[:-1])
    if not state or not city:
        return None
    return {"city": city.strip(), "state": state, "zip": zipc}


def _ocr_text(png_bytes: bytes) -> str:
    """Run Tesseract OCR over a shipping-label PNG and return the raw text."""
    img = Image.open(io.BytesIO(png_bytes)).convert("L")  # grayscale
    # Upscale small images so Tesseract reads the smaller fonts more reliably
    if img.width < 1200:
        scale = 1200 / img.width
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    return pytesseract.image_to_string(img)


def _parse_ship_to(text: str) -> dict | None:
    """Extract recipient name / street / city-state-zip from the SHIP TO block.

    Handles labels where OCR splits the heading (e.g. "SHIP" on one line with the
    name, "TO:" on the next with the street) and where the state is written out
    in full (e.g. "MURRAY IOWA 50174-1003").
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # Anchor on the first "SHIP" line that is not "SHIP FROM"
    start = None
    for i, ln in enumerate(lines):
        up = ln.upper()
        if "SHIP" in up and "FROM" not in up:
            start = i
            break
    if start is None:
        return None

    block: list[str] = []
    csz = None
    for ln in lines[start:]:
        # Strip the SHIP / SHIP TO / TO: labels off the start of the line
        cleaned = re.sub(r"^\s*SHIP\b\s*(?:TO\b)?\s*:?\s*", "", ln, flags=re.I)
        cleaned = re.sub(r"^\s*TO\b\s*:?\s*", "", cleaned, flags=re.I)
        cleaned = cleaned.strip(" :,")
        if not cleaned:
            continue
        parsed = _parse_csz(cleaned)
        if parsed:
            csz = parsed
            break
        # Skip OCR noise from nearby 2D barcodes (almost no letters/digits) and
        # numeric reference lines (e.g. an order number printed above the name) —
        # real name/street lines always contain letters.
        if sum(c.isalnum() for c in cleaned) < 3 or not any(c.isalpha() for c in cleaned):
            continue
        block.append(cleaned)
        if len(block) >= 6:  # safety stop
            break

    result: dict = {}
    if block:
        result["name"] = block[0]
        if len(block) >= 2:
            result["line1"] = block[1]
        if len(block) >= 3:
            result["line2"] = " ".join(block[2:])
    if csz:
        result["city"] = csz["city"]
        result["state"] = csz["state"]
        result["zip"] = csz["zip"]
    return result or None


# ---------------------------------------------------------------------------
# Carrier / service / tracking number extracted from the scanned label.
# FIRST PASS — refine the carrier/service normalization with real sample data.
# ---------------------------------------------------------------------------

# Service phrases as they appear on the label -> normalized service value.
_SERVICE_MAP = [
    ("GROUND ADVANTAGE", "GroundAdvantage"),
    ("PRIORITY MAIL EXPRESS", "PriorityExpress"),
    ("PRIORITY MAIL", "Priority"),
    ("PRIORITY", "Priority"),
    ("FIRST CLASS", "FirstClass"),
    ("2ND DAY AIR", "2ndDayAir"),
    ("NEXT DAY AIR", "NextDayAir"),
    ("3 DAY SELECT", "3DaySelect"),
    ("GROUND", "Ground"),
]


def _clean_tracking(s: str) -> str | None:
    """Pull a UPS (1Z…) or numeric (USPS/FedEx) tracking number out of a string."""
    up = s.upper()
    m = re.search(r"1Z[0-9A-Z ]{12,}", up)   # UPS: 1Z + ~16 alnum
    if m:
        t = re.sub(r"\s+", "", m.group(0))
        if 16 <= len(t) <= 20:
            return t
    digits = re.sub(r"[^0-9]", "", s)         # USPS/FedEx: long digit run
    if len(digits) >= 12:
        return digits
    return None


def _parse_tracking(lines: list[str]) -> str | None:
    """Find the tracking number near a 'TRACKING #' line."""
    for i, ln in enumerate(lines):
        if "TRACKING" in ln.upper():
            after = ln.split("#", 1)[1] if "#" in ln else ""
            for c in [after, *lines[i + 1:i + 3]]:   # same line after #, or next 2 lines
                t = _clean_tracking(c)
                if t:
                    return t
    return None


def _parse_label_meta(text: str) -> dict:
    """Extract {carrier, service, tracking_number} from a shipping-label OCR text."""
    up = text.upper()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    carrier = None
    if "USPS" in up:
        carrier = "USPS"
    elif "UPS" in up:
        carrier = "UPS"
    elif "FEDEX" in up:
        carrier = "FedEx"
    elif "DHL" in up:
        carrier = "DHL"

    service = None
    for phrase, norm in _SERVICE_MAP:
        if phrase in up:
            service = norm
            break

    return {"carrier": carrier, "service": service, "tracking_number": _parse_tracking(lines)}


def _to_address_payload(addr: dict | None) -> dict | None:
    """Build an EasyPost-style address object from a parsed order address.

    Stores only the fields we actually have (empty ones are dropped), so a
    partial address is fine.
    """
    if not isinstance(addr, dict):
        return None
    mapping = {
        "name": addr.get("name"),
        "company": addr.get("company"),
        "street1": addr.get("line1"),
        "street2": addr.get("line2"),
        "city": addr.get("city"),
        "state": addr.get("state"),
        "zip": addr.get("zip"),
        "country": addr.get("country") or "US",
        "phone": addr.get("phone"),
        "email": addr.get("email"),
    }
    payload = {k: v for k, v in mapping.items() if v not in (None, "")}
    if not payload:
        return None
    payload["object"] = "Address"
    return payload


def _is_prestamped_label_url(url: str | None) -> bool:
    """Scanned labels stored on our R2 CDN already have the product info stamped,
    so the Print Label / bulk pipeline must NOT stamp them again."""
    return bool(url) and "cdn.podgasus.com" in url


async def _create_scan_shipping_label(order: Order, label_url: str | None, meta: dict, db: AsyncSession):
    """Create a shipping_labels row from a scanned label and link the order's
    assigned line items (label_id + tracking_number) — so the scanned label feeds
    the existing bulk-print flow. Supplier = the order's (primary) assigned supplier.

    Does NOT commit; the caller owns the transaction.
    """
    lis = (await db.execute(
        select(OrderLineItem).where(OrderLineItem.order_id == order.id)
    )).scalars().all()
    assigned = [li for li in lis if li.supplier_id]
    if not assigned:
        return None

    supplier_id = assigned[0].supplier_id   # one physical label per order → primary supplier
    tracking = meta.get("tracking_number")
    label = ShippingLabel(
        supplier_id=supplier_id,
        carrier=meta.get("carrier") or "",
        service=meta.get("service"),
        tracking_number=tracking,
        label_url=label_url,
        to_address=_to_address_payload(order.shipping_address),
        purchased_at=datetime.now(timezone.utc),
    )
    db.add(label)
    await db.flush()

    for li in assigned:
        li.label_id = label.id
        if tracking:
            li.tracking_number = tracking

    print(
        f"scan_label: order={order.external_order_id} shipping_label id={label.id} "
        f"supplier={supplier_id} carrier={label.carrier!r} service={label.service!r} "
        f"tracking={tracking!r}",
        flush=True,
    )
    return label


# ---------------------------------------------------------------------------
# JOE label stamping: when a JOE order moves to "processing", draw the product
# line(s) into the blank area at the bottom of its scanned label, then store it.
# ---------------------------------------------------------------------------

def _build_stamp_lines(items: list[tuple[int, str]], when: datetime, with_date: bool) -> list[str]:
    """Build the stamp text — one line per catalog item.

    Format: "<quantity> <NAME>" and, for JOE orders only, "<quantity> <NAME> - <DATE>"
      - quantity : fulfillment quantity
      - NAME     : supplier_products.short_name (upper-cased)
      - DATE     : upload date, e.g. "JUN 26" (appended only when with_date)
    """
    date_str = when.strftime("%b").upper() + " " + str(when.day)
    lines: list[str] = []
    for qty, name in items:
        nm = (name or "").strip().upper()
        if not nm:
            continue
        line = f"{qty} {nm}"
        if with_date:
            line += f" - {date_str}"
        lines.append(line)
    return lines


def _stamp_text_on_png(png_bytes: bytes, lines: list[str], color: str = "black") -> bytes:
    """Draw the given text lines into the blank area at the bottom of a label PNG.

    color is used to highlight orders that need manual review (red).
    """
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    draw = ImageDraw.Draw(img)
    w, h = img.size

    font_size = max(16, int(w * 0.032))
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    margin = int(w * 0.05)
    line_h = int(font_size * 1.35)
    total_h = line_h * len(lines)
    # Sit the block near the bottom edge with a small margin.
    y = h - int(h * 0.04) - total_h
    for ln in lines:
        draw.text((margin, y), ln, fill=color, font=font)
        y += line_h

    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


async def _stamp_items(order: Order, db: AsyncSession) -> tuple[list[tuple[int, str]], bool]:
    """Collect (quantity, supplier_products.name) for an order's assigned items.

    Applies to every supplier. Also returns is_joe = True when the order is
    fulfilled by supplier JOE (used to decide whether to append the date).
    """
    lis = (await db.execute(
        select(OrderLineItem).where(OrderLineItem.order_id == order.id)
    )).scalars().all()

    items: list[tuple[int, str]] = []
    is_joe = False
    for li in lis:
        if not li.supplier_id:
            continue
        sup = await db.get(Supplier, li.supplier_id)
        if sup and (sup.name or "").strip().upper() == "JOE":
            is_joe = True
        ofis = (await db.execute(
            select(OrderFulfillmentItem).where(OrderFulfillmentItem.order_line_item_id == li.id)
        )).scalars().all()
        for ofi in ofis:
            sp = await db.get(SupplierProduct, ofi.supplier_product_id)
            if sp:
                # Use short_name; fall back to name if it's empty
                items.append((ofi.quantity, sp.short_name or sp.name))

    # Drop exact-duplicate lines (guards against duplicate fulfillment items
    # producing the same product line twice on the label)
    seen: set = set()
    deduped: list[tuple[int, str]] = []
    for qty, name in items:
        key = (qty, (name or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append((qty, name))
    return deduped, is_joe


def _r2_put_object(key: str, png_bytes: bytes) -> None:
    """Blocking R2 (S3-compatible) upload — run via asyncio.to_thread."""
    import boto3
    client = boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )
    client.put_object(
        Bucket=os.environ["R2_BUCKET_NAME"],
        Key=key,
        Body=png_bytes,
        ContentType="image/png",
    )


async def _upload_label_to_r2(order_id: str, png_bytes: bytes) -> str | None:
    """Upload the stamped label PNG to Cloudflare R2 under MAGA/label/ and return
    its public CDN URL. Returns None if R2 is not configured or the upload fails.
    """
    if not os.environ.get("R2_ACCOUNT_ID"):
        print("stamp_label: R2 not configured — skipping upload", flush=True)
        return None
    key = f"MAGA/label/{order_id}.png"
    try:
        await asyncio.to_thread(_r2_put_object, key, png_bytes)
    except Exception as e:
        print(f"stamp_label: R2 upload failed for {key} — {e}", flush=True)
        return None
    cdn = (os.environ.get("R2_CDN") or "").rstrip("/")
    url = f"{cdn}/{key}"
    print(f"stamp_label: uploaded -> {url}", flush=True)
    return url


_MAX_STAMP_LINES = 3


async def _stamp_label_for_processing(order: Order, raw: bytes | None, db: AsyncSession) -> dict | None:
    """Stamp + store a JOE order's label when it has just moved to processing.

    Prints one line per item (max 3). Orders with more than 3 lines are stamped
    with the first 3 and flagged for manual editing (an OrderEvent is recorded so
    they can be found later).

    Returns a small summary, or None when nothing was stamped (no image, or the
    order has no assigned items).
    """
    if not raw:
        return None
    items, is_joe = await _stamp_items(order, db)
    if not items:
        return None
    # Date is appended only for JOE orders; other suppliers get name + qty only.
    all_lines = _build_stamp_lines(items, datetime.now(), with_date=is_joe)
    if not all_lines:
        return None

    needs_manual = len(all_lines) > _MAX_STAMP_LINES
    lines = all_lines[:_MAX_STAMP_LINES]
    # Red text highlights orders that need manual editing (> 3 item lines)
    color = "red" if needs_manual else "black"

    try:
        stamped = _stamp_text_on_png(raw, lines, color=color)
        url = await _upload_label_to_r2(order.external_order_id or str(order.id), stamped)
    except Exception as e:
        print(f"stamp_label: order={order.external_order_id} failed — {e}", flush=True)
        return {"stamped": False, "error": str(e)}

    # Persist the public label URL on the order
    if url:
        order.label_url = url

    if needs_manual:
        # More items than fit on the label — flag for manual editing.
        db.add(OrderEvent(
            order_id=order.id,
            event_type="label_manual_review",
            level="warn",
            message=f"Label has {len(all_lines)} item lines (> {_MAX_STAMP_LINES}) — needs manual editing",
            payload={"all_lines": all_lines},
        ))
        print(
            f"stamp_label: order={order.external_order_id} NEEDS MANUAL — "
            f"{len(all_lines)} item lines (printed first {_MAX_STAMP_LINES})",
            flush=True,
        )

    return {
        "stamped": True,
        "lines": lines,
        "label_url": url,
        "item_count": len(all_lines),
        "needs_manual_review": needs_manual,
    }


@router.post("/scan-label")
async def scan_label_address(body: ScanLabelBody, db: AsyncSession = Depends(get_db)):
    """Scan a shipping label, then record the outcome to the scan-log audit trail."""
    result = await _scan_label_impl(body, db)
    try:
        db.add(ScanLog(
            order_id=(result.get("order_id") or None),
            status=result.get("status") or "unknown",
            error=result.get("error"),
            filled=result.get("filled"),
            address=result.get("address"),
        ))
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.warning(f"scan_label: failed to record scan log — {e}")
    return result


async def _scan_label_impl(body: ScanLabelBody, db: AsyncSession) -> dict:
    """Read the SHIP TO block from a shipping-label PNG and, if the matching
    Amazon order has no address yet, fill it in.

    `order_id` is the Amazon order id (the PNG filename without extension).
    Returns {order_id, status, address?} where status is one of:
      not_found | already_has_address | updated | scan_failed | no_api_key
    """
    order_id = (body.order_id or "").strip()
    if not order_id:
        return {"order_id": order_id, "status": "not_found"}

    # 1. Find the order by Amazon external id
    res = await db.execute(select(Order).where(Order.external_order_id == order_id).limit(1))
    order = res.scalar_one_or_none()
    if not order:
        return {"order_id": order_id, "status": "not_found"}

    # Decode the uploaded label image up-front — used for OCR (address + tracking)
    # and for the stamping step. None if it isn't a valid PNG.
    raw = None
    try:
        _decoded = base64.b64decode(body.image_b64)
        if _decoded[:8] == b"\x89PNG\r\n\x1a\n":
            raw = _decoded
    except Exception:
        raw = None

    # OCR once — the text feeds both address parsing and label-meta (carrier /
    # service / tracking) extraction, so it must run even when the address is
    # already complete.
    ocr_text = ""
    if raw is not None:
        try:
            ocr_text = _ocr_text(raw)
        except Exception as e:
            print(f"scan_label: order={order_id} OCR error — {e}", flush=True)
            ocr_text = ""
    label_meta = _parse_label_meta(ocr_text)

    async def _finalize_label(order_obj, assignment, db):
        """Stamp + store image, then create the shipping_labels row + link items.

        shipping_labels.label_url points at the already-stamped R2 image; the
        Print Label / bulk pipeline detects the cdn.podgasus.com host and skips
        re-stamping it (see _is_prestamped_label_url).
        """
        stamp = None
        if assignment.get("moved_to_processing"):
            stamp = await _stamp_label_for_processing(order_obj, raw, db)
            label_url = stamp.get("label_url") if stamp else None
            await _create_scan_shipping_label(order_obj, label_url, label_meta, db)
        return stamp

    # 2. Skip only if the address is already complete. An address counts as
    #    complete when all key fields are present — a partial record (e.g. only
    #    city/state) should still be filled in from the label.
    addr = order.shipping_address if isinstance(order.shipping_address, dict) else {}
    required = ["name", "line1", "city", "state", "zip"]
    missing = [k for k in required if not str(addr.get(k) or "").strip()]
    if not missing:
        # Address already complete — still advance assignment / status
        assignment = await _post_scan_assign(order, db)
        stamp = await _finalize_label(order, assignment, db)
        await db.commit()
        return {"order_id": order_id, "status": "already_has_address",
                "assignment": assignment, "stamp": stamp, "label_meta": label_meta}

    # 3. Need a valid PNG to OCR the address
    if raw is None:
        return {"order_id": order_id, "status": "scan_failed", "error": "not a PNG"}

    # 4. Parse the SHIP TO block from the OCR text (local Tesseract — no AI)
    data = _parse_ship_to(ocr_text)
    if not data or not (data.get("line1") or data.get("city")):
        # Dump OCR text only on failure, to help diagnose unreadable labels
        print(f"scan_label: order={order_id} no address parsed; OCR text:\n{ocr_text}", flush=True)
        return {"order_id": order_id, "status": "scan_failed", "error": "no address parsed"}

    # 6. Merge: keep existing non-empty fields, fill only the missing ones
    scanned = {
        "name": data.get("name"),
        "line1": data.get("line1"),
        "line2": data.get("line2"),
        "city": data.get("city"),
        "state": data.get("state"),
        "zip": data.get("zip"),
    }
    address = dict(addr)  # start from what's already there
    filled = []
    for k, v in scanned.items():
        if not str(address.get(k) or "").strip() and v:
            address[k] = v
            filled.append(k)
    address.setdefault("country", addr.get("country") or "US")
    address.setdefault("phone", addr.get("phone"))

    order.shipping_address = address
    if not str(order.buyer_name or "").strip() and address.get("name"):
        order.buyer_name = address.get("name")
    order.updated_at = datetime.now(timezone.utc)

    # Continue: assign supplier by SKU and/or move the order to processing
    assignment = await _post_scan_assign(order, db)

    # On transition to processing: stamp + store image, create shipping label
    stamp = await _finalize_label(order, assignment, db)

    await db.commit()
    logger.info(f"scan_label: order={order_id} filled {filled or 'nothing'}")
    return {"order_id": order_id, "status": "updated", "address": address,
            "filled": filled, "assignment": assignment, "stamp": stamp, "label_meta": label_meta}


@router.get("/bulk-labels")
async def bulk_labels(
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    supplier_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Download purchased labels for a given date merged per supplier.
    supplier_id specified → single PDF. Omitted → zip of all suppliers."""
    import io as _io
    import zipfile
    import httpx
    from collections import defaultdict
    from app.integrations.pdf_labels import decode_label_data, concat_label_pdfs, image_to_label_pdf

    try:
        d = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Invalid date — use YYYY-MM-DD.")
    start = d.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
    end = d.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc)

    # Only labels linked to processing orders (via OrderLineItem → Order)
    processing_label_ids_q = (
        select(OrderLineItem.label_id)
        .join(Order, Order.id == OrderLineItem.order_id)
        .where(
            OrderLineItem.label_id.isnot(None),
            Order.status == OrderStatus.processing,
        )
    )
    q = (
        select(ShippingLabel)
        .where(
            ShippingLabel.purchased_at >= start,
            ShippingLabel.purchased_at <= end,
            ShippingLabel.id.in_(processing_label_ids_q),
        )
        .order_by(ShippingLabel.supplier_id)
    )
    if supplier_id is not None:
        q = q.where(ShippingLabel.supplier_id == supplier_id)

    labels = (await db.execute(q)).scalars().all()
    if not labels:
        detail = f"No processing orders with labels on {date}"
        if supplier_id:
            detail += f" for supplier {supplier_id}"
        raise HTTPException(404, detail)

    date_label = start.strftime("%b").upper() + " " + str(start.day)

    async def _pdf_for_label(label: ShippingLabel) -> bytes | None:
        try:
            # Prefer stamping fresh from the pristine carrier PDF (label_url) so
            # the product info (Qty + NAME + (size/pot) + date for JOE) is always
            # on the label — even for older labels whose stored label_data was
            # saved before the stamp existed. label_url is the clean carrier
            # label, so this never double-stamps.
            if label.label_url:
                async with httpx.AsyncClient(timeout=20) as http:
                    r = await http.get(label.label_url)
                if r.is_success and r.content:
                    carrier = (r.content if r.content[:5] == b"%PDF-"
                               else image_to_label_pdf(r.content))
                    # Scanned labels on our CDN are already stamped — don't re-stamp.
                    if _is_prestamped_label_url(label.label_url):
                        return carrier
                    try:
                        return await _stamp_carrier_for_label(carrier, label, db)
                    except Exception as _se:
                        print(f"bulk_labels: stamp failed label={label.id} — {_se}", flush=True)
                        return carrier
            # No usable label_url — fall back to stored label_data.
            if label.label_data:
                return decode_label_data(label.label_data)
            return None
        except Exception as _e:
            import traceback as _tb
            print(f"bulk_labels: _pdf_for_label label={label.id} failed — {_e}\n{_tb.format_exc()}", flush=True)
            return None

    async def _supplier_pdf(sup_labels: list) -> tuple[bytes | None, int]:
        label_ids = [lbl.id for lbl in sup_labels]
        oid_res = await db.execute(
            select(OrderLineItem.order_id)
            .where(OrderLineItem.label_id.in_(label_ids))
            .distinct()
        )
        n_orders = len(oid_res.scalars().all())
        pages = []
        for lbl in sup_labels:
            pdf = await _pdf_for_label(lbl)
            if pdf:
                pages.append(pdf)
            else:
                print(
                    f"bulk_labels: label {lbl.id} skipped — "
                    f"has_data={bool(lbl.label_data)} has_url={bool(lbl.label_url)}",
                    flush=True,
                )
        if not pages:
            return None, n_orders
        try:
            return concat_label_pdfs(pages), n_orders
        except Exception as e:
            import traceback as _tb
            print(f"bulk_labels: concat_label_pdfs failed — {e}\n{_tb.format_exc()}", flush=True)
            raise

    by_sup: dict[int, list] = defaultdict(list)
    for lbl in labels:
        by_sup[lbl.supplier_id].append(lbl)

    if supplier_id is not None:
        sup = await db.get(Supplier, supplier_id)
        sup_name = (sup.name if sup else str(supplier_id)).upper()
        try:
            pdf, n_orders = await _supplier_pdf(list(by_sup.get(supplier_id, [])))
        except Exception as e:
            print(f"bulk_labels: _supplier_pdf crashed for supplier={supplier_id} date={date} — {e}", flush=True)
            raise HTTPException(500, f"Error building label PDF: {e}")
        if not pdf:
            raise HTTPException(404, "No printable label data found for this supplier/date")
        fname = f"{date_label} - {n_orders} ORDERS - {sup_name}.pdf"
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{fname}"'},
        )

    try:
        zip_buf = _io.BytesIO()
        total = 0
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for sid, sup_labels in by_sup.items():
                sup = await db.get(Supplier, sid)
                sup_name = (sup.name if sup else str(sid)).upper()
                try:
                    pdf, n_orders = await _supplier_pdf(sup_labels)
                except Exception as e:
                    print(f"bulk_labels: _supplier_pdf failed for supplier={sid} — {e}", flush=True)
                    continue
                if not pdf:
                    continue
                fname = f"{date_label} - {n_orders} ORDERS - {sup_name}.pdf"
                zf.writestr(fname, pdf)
                total += 1
        if total == 0:
            raise HTTPException(404, "No printable label data found for any supplier on this date")
        zip_buf.seek(0)
        return Response(
            content=zip_buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{date_label} - labels.zip"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"bulk_labels: zip path crashed — {traceback.format_exc()}", flush=True)
        raise HTTPException(500, f"Error building zip: {e}")


@router.post("/bulk-fulfill")
async def bulk_fulfill(
    date: str = Query(...),
    supplier_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Mark all labels (and their line items) for a given date/supplier as shipped."""
    try:
        d = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Invalid date — use YYYY-MM-DD.")
    start = d.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
    end = d.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc)

    processing_label_ids_q = (
        select(OrderLineItem.label_id)
        .join(Order, Order.id == OrderLineItem.order_id)
        .where(
            OrderLineItem.label_id.isnot(None),
            Order.status == OrderStatus.processing,
        )
    )
    q = select(ShippingLabel).where(
        ShippingLabel.purchased_at >= start,
        ShippingLabel.purchased_at <= end,
        ShippingLabel.id.in_(processing_label_ids_q),
    )
    if supplier_id is not None:
        q = q.where(ShippingLabel.supplier_id == supplier_id)

    labels = (await db.execute(q)).scalars().all()
    if not labels:
        raise HTTPException(404, "No processing labels found for this date/supplier")

    now = datetime.now(timezone.utc)
    marked_orders: set[int] = set()

    for label in labels:
        li_res = await db.execute(
            select(OrderLineItem).where(OrderLineItem.label_id == label.id)
        )
        lis = list(li_res.scalars().all())
        for li in lis:
            if li.fulfill_status not in (FulfillStatus.shipped, FulfillStatus.delivered):
                li.fulfill_status = FulfillStatus.shipped
                if not li.fulfilled_at:
                    li.fulfilled_at = now
            if label.tracking_number and not li.tracking_number:
                li.tracking_number = label.tracking_number
            fi_res = await db.execute(
                select(OrderFulfillmentItem).where(OrderFulfillmentItem.order_line_item_id == li.id)
            )
            for fi in fi_res.scalars().all():
                if fi.fulfill_status not in (FulfillStatus.shipped, FulfillStatus.delivered):
                    fi.fulfill_status = FulfillStatus.shipped
                    if not fi.fulfilled_at:
                        fi.fulfilled_at = now
                    sp_stock = await db.get(SupplierProduct, fi.supplier_product_id)
                    if sp_stock:
                        sp_stock.stock_quantity = max(0, sp_stock.stock_quantity - fi.quantity)
            marked_orders.add(li.order_id)

    # Recalculate order statuses
    for order_id in marked_orders:
        order = await db.get(Order, order_id)
        if order:
            await _recalculate_order_status(order, db)

    await db.commit()

    # Best-effort push tracking to marketplace for each order
    for order_id in marked_orders:
        order = await db.get(Order, order_id)
        if order:
            try:
                await _try_push_marketplace_tracking(order, db)
            except Exception:
                pass

    return {"marked_orders": len(marked_orders), "labels_processed": len(labels)}



@router.get("/delayed")
async def list_delayed_orders(db: AsyncSession = Depends(get_db)):
    """Orders where a shipping label was purchased 3+ days ago but line items are still 'shipped' (not delivered)."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=3)

    has_shipped_items = sa_exists().where(
        OrderLineItem.label_id == ShippingLabel.id,
        OrderLineItem.fulfill_status == FulfillStatus.shipped,
    )

    labels_res = await db.execute(
        select(ShippingLabel)
        .where(
            ShippingLabel.purchased_at <= cutoff,
            has_shipped_items,
        )
        .order_by(ShippingLabel.purchased_at.asc())
    )
    labels = labels_res.scalars().all()

    result = []
    for label in labels:
        li_res = await db.execute(
            select(OrderLineItem)
            .where(
                OrderLineItem.label_id == label.id,
                OrderLineItem.fulfill_status == FulfillStatus.shipped,
            )
            .limit(1)
        )
        li = li_res.scalar_one_or_none()
        if not li:
            continue

        order = await db.get(Order, li.order_id)
        if not order:
            continue
        supplier = await db.get(Supplier, label.supplier_id) if label.supplier_id else None

        days = (now - label.purchased_at).days
        status = "urgent" if days >= 5 else "warning"

        result.append({
            "order_id": order.id,
            "order_name": order.order_name or order.external_order_id or f"#{order.id}",
            "supplier_name": supplier.name if supplier else None,
            "purchased_at": label.purchased_at.isoformat(),
            "days_delayed": days,
            "status": status,
        })

    return result


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: int, db: AsyncSession = Depends(get_db)):
    order = await _get_or_404(order_id, db)
    return await _order_out(order, db)


@router.patch("/{order_id}", response_model=OrderOut)
async def update_order(order_id: int, body: OrderUpdate, db: AsyncSession = Depends(get_db)):
    order = await _get_or_404(order_id, db)
    data = body.model_dump(exclude_none=True)
    if "shipping_address" in data and data["shipping_address"]:
        data["shipping_address"] = data["shipping_address"].model_dump() if hasattr(data["shipping_address"], "model_dump") else data["shipping_address"]
    for k, v in data.items():
        setattr(order, k, v)
    await db.commit()
    await db.refresh(order)
    return await _order_out(order, db)


@router.delete("/{order_id}", status_code=204)
async def delete_order(order_id: int, db: AsyncSession = Depends(get_db)):
    order = await _get_or_404(order_id, db)
    await db.delete(order)
    await db.commit()


# --- Line items ---

@router.patch("/{order_id}/line-items/{li_id}", response_model=OrderLineItemOut)
async def update_line_item(order_id: int, li_id: int, body: OrderLineItemUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(OrderLineItem).where(OrderLineItem.id == li_id, OrderLineItem.order_id == order_id)
    )
    li = result.scalar_one_or_none()
    if not li:
        raise HTTPException(404, "Line item not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(li, k, v)
    if body.fulfill_status and body.fulfill_status == "shipped" and not li.fulfilled_at:
        li.fulfilled_at = datetime.now(timezone.utc)

    order = await _get_or_404(order_id, db)
    await _recalculate_order_status(order, db)
    await db.commit()
    await db.refresh(li)
    return await _line_item_out(li, db)


@router.post("/{order_id}/mark-shipped", response_model=OrderOut)
async def mark_shipped(order_id: int, body: MarkShippedBody, db: AsyncSession = Depends(get_db)):
    """Admin override: mark unshipped line items as shipped without buying a label.

    Use for orders already shipped outside the system. Targets the explicitly
    provided line_item_ids, or all unshipped items for a given supplier_id, or
    every unshipped item in the order when neither is supplied. Cascades the
    shipped status (and optional tracking number) to any fulfillment items.
    """
    order = await _get_or_404(order_id, db)

    q = select(OrderLineItem).where(
        OrderLineItem.order_id == order_id,
        OrderLineItem.fulfill_status.in_([FulfillStatus.unfulfilled, FulfillStatus.pending]),
    )
    if body.line_item_ids:
        q = q.where(OrderLineItem.id.in_(body.line_item_ids))
    elif body.supplier_id is not None:
        q = q.where(OrderLineItem.supplier_id == body.supplier_id)

    result = await db.execute(q)
    items = list(result.scalars().all())
    if not items:
        raise HTTPException(404, "No unshipped line items match this request")

    now = datetime.now(timezone.utc)
    for li in items:
        li.fulfill_status = FulfillStatus.shipped
        li.fulfilled_at = now
        if body.tracking_number:
            li.tracking_number = body.tracking_number

        fi_res = await db.execute(
            select(OrderFulfillmentItem).where(OrderFulfillmentItem.order_line_item_id == li.id)
        )
        for fi in fi_res.scalars().all():
            if fi.fulfill_status not in (FulfillStatus.shipped, FulfillStatus.delivered):
                fi.fulfill_status = FulfillStatus.shipped
                fi.fulfilled_at = now
                if body.tracking_number:
                    fi.tracking_number = body.tracking_number
                sp_stock = await db.get(SupplierProduct, fi.supplier_product_id)
                if sp_stock:
                    sp_stock.stock_quantity = max(0, sp_stock.stock_quantity - fi.quantity)

    await _recalculate_order_status(order, db)
    await db.commit()
    await _try_push_marketplace_tracking(order, db)
    return await _order_out(order, db)


@router.patch("/{order_id}/line-items/{li_id}/assign-supplier", response_model=OrderLineItemOut)
async def assign_supplier_to_line_item(
    order_id: int,
    li_id: int,
    body: AssignSupplierBody,
    db: AsyncSession = Depends(get_db),
):
    """Assign a supplier to a line item. Optionally creates ProductSupplier for future auto-assignment."""
    result = await db.execute(
        select(OrderLineItem).where(OrderLineItem.id == li_id, OrderLineItem.order_id == order_id)
    )
    li = result.scalar_one_or_none()
    if not li:
        raise HTTPException(404, "Line item not found")

    supplier = await db.get(Supplier, body.supplier_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found")

    # Validate supplier_product_id belongs to this supplier
    sp = await db.get(SupplierProduct, body.supplier_product_id)
    if not sp or sp.supplier_id != body.supplier_id:
        raise HTTPException(400, "Catalog item not found for this supplier")

    # Remove stale OFIs when re-assigning to a different catalog item
    old_fi_res = await db.execute(
        select(OrderFulfillmentItem).where(
            OrderFulfillmentItem.order_line_item_id == li.id,
            OrderFulfillmentItem.supplier_product_id != sp.id,
        )
    )
    for old_fi in old_fi_res.scalars().all():
        await db.delete(old_fi)

    li.supplier_id = body.supplier_id
    effective_cost = body.base_cost if body.base_cost is not None else (sp.unit_price * body.units)
    li.base_cost = effective_cost

    # If line item has no product_id, try to resolve it from SKU now so the
    # ProductComponent link can be stored for future orders with the same product.
    if not li.product_id and li.sku:
        from sqlalchemy import func as sqlfunc
        prod_res = await db.execute(
            select(Product).where(sqlfunc.lower(sqlfunc.trim(Product.sku)) == li.sku.strip().lower())
        )
        product = prod_res.scalar_one_or_none()
        if product:
            li.product_id = product.id

    # Upsert ProductComponent (product → supplier catalog item) — reusable for all
    # future orders that carry the same product_id.
    if li.product_id:
        comp_res = await db.execute(
            select(ProductComponent).where(
                ProductComponent.product_id == li.product_id,
                ProductComponent.supplier_product_id == sp.id,
            )
        )
        comp = comp_res.scalar_one_or_none()
        if not comp:
            db.add(ProductComponent(
                product_id=li.product_id,
                supplier_product_id=sp.id,
                quantity=body.units,
            ))
        else:
            comp.quantity = body.units

        # Create ProductSupplier relationship for future auto-assignment
        if body.create_product_supplier:
            ps_result = await db.execute(
                select(ProductSupplier).where(
                    ProductSupplier.product_id == li.product_id,
                    ProductSupplier.supplier_id == body.supplier_id,
                )
            )
            ps_link = ps_result.scalar_one_or_none()
            if not ps_link:
                ps_link = ProductSupplier(
                    product_id=li.product_id,
                    supplier_id=body.supplier_id,
                    cost=effective_cost,
                    is_preferred=body.is_preferred,
                )
                db.add(ps_link)
            elif body.is_preferred:
                all_ps = await db.execute(
                    select(ProductSupplier).where(ProductSupplier.product_id == li.product_id)
                )
                for other in all_ps.scalars().all():
                    other.is_preferred = False
                ps_link.is_preferred = True

    # Always create/upsert OrderFulfillmentItem for this specific line item,
    # whether or not product_id exists — this is what the supplier sees immediately.
    fi_res = await db.execute(
        select(OrderFulfillmentItem).where(
            OrderFulfillmentItem.order_line_item_id == li.id,
            OrderFulfillmentItem.supplier_product_id == sp.id,
        )
    )
    fi = fi_res.scalar_one_or_none()
    if not fi:
        db.add(OrderFulfillmentItem(
            order_line_item_id=li.id,
            supplier_product_id=sp.id,
            quantity=body.units * li.quantity,
        ))
    else:
        fi.quantity = body.units * li.quantity

    await db.commit()
    await db.refresh(li)
    return await _line_item_out(li, db)


# --- Shipping labels ---

@router.post("/{order_id}/labels", response_model=ShippingLabelOut, status_code=201)
async def create_label(order_id: int, body: ShippingLabelCreate, db: AsyncSession = Depends(get_db)):
    order = await _get_or_404(order_id, db)
    label = ShippingLabel(
        supplier_id=body.supplier_id,
        carrier=body.carrier,
        service=body.service,
        tracking_number=body.tracking_number,
        label_url=body.label_url,
        cost=body.cost,
        from_address=body.from_address,
        to_address=body.to_address,
    )
    db.add(label)
    await db.flush()

    # Determine which line items to link:
    # Use explicitly provided IDs, or auto-select all unshipped items for this supplier
    li_ids = body.line_item_ids
    if not li_ids:
        auto_result = await db.execute(
            select(OrderLineItem).where(
                OrderLineItem.order_id == order_id,
                OrderLineItem.supplier_id == body.supplier_id,
                OrderLineItem.fulfill_status.in_([FulfillStatus.unfulfilled, FulfillStatus.pending]),
            )
        )
        li_ids = [li.id for li in auto_result.scalars().all()]

    for li_id in li_ids:
        result = await db.execute(
            select(OrderLineItem).where(OrderLineItem.id == li_id, OrderLineItem.order_id == order_id)
        )
        li = result.scalar_one_or_none()
        if li:
            li.label_id = label.id
            if body.tracking_number:
                li.tracking_number = body.tracking_number
            # Label bought → move to pending (awaiting shipment by supplier)
            if li.fulfill_status == FulfillStatus.unfulfilled:
                li.fulfill_status = FulfillStatus.pending

    await _recalculate_order_status(order, db)
    await db.commit()
    await db.refresh(label)
    if body.tracking_number:
        await _try_push_marketplace_tracking(order, db)
    return label


@router.get("/{order_id}/labels", response_model=list[ShippingLabelOut])
async def list_labels(order_id: int, db: AsyncSession = Depends(get_db)):
    await _get_or_404(order_id, db)
    label_ids_q = select(OrderLineItem.label_id).where(
        OrderLineItem.order_id == order_id,
        OrderLineItem.label_id.isnot(None),
    ).distinct()
    result = await db.execute(select(ShippingLabel).where(ShippingLabel.id.in_(label_ids_q)))
    return result.scalars().all()


@router.post("/{order_id}/labels/{label_id}/mark-printed")
async def mark_label_printed(order_id: int, label_id: int, db: AsyncSession = Depends(get_db)):
    """After the supplier prints the label we treat the items as shipped
    (label is committed at the carrier the moment it's purchased). Flip all
    line items + fulfillment items attached to this label, decrement supplier
    stock, then best-effort push tracking back to the marketplace (Shopify)."""
    label = await db.get(ShippingLabel, label_id)
    if not label:
        raise HTTPException(404, "Label not found")
    order = await _get_or_404(order_id, db)

    li_res = await db.execute(
        select(OrderLineItem).where(
            OrderLineItem.order_id == order_id,
            OrderLineItem.label_id == label_id,
        )
    )
    lis = list(li_res.scalars().all())
    now = datetime.now(timezone.utc)
    flipped = 0
    for li in lis:
        if li.fulfill_status not in (FulfillStatus.shipped, FulfillStatus.delivered):
            li.fulfill_status = FulfillStatus.shipped
            if not li.fulfilled_at:
                li.fulfilled_at = now
            flipped += 1
        if label.tracking_number and not li.tracking_number:
            li.tracking_number = label.tracking_number
        fi_res = await db.execute(
            select(OrderFulfillmentItem).where(OrderFulfillmentItem.order_line_item_id == li.id)
        )
        for fi in fi_res.scalars().all():
            if fi.fulfill_status not in (FulfillStatus.shipped, FulfillStatus.delivered):
                fi.fulfill_status = FulfillStatus.shipped
                if not fi.fulfilled_at:
                    fi.fulfilled_at = now
                sp_stock = await db.get(SupplierProduct, fi.supplier_product_id)
                if sp_stock:
                    sp_stock.stock_quantity = max(0, sp_stock.stock_quantity - fi.quantity)

    await _recalculate_order_status(order, db)
    await db.commit()
    await _try_push_marketplace_tracking(order, db)
    return {"status": "ok", "label_id": label_id, "marked_shipped": flipped}


@router.patch("/{order_id}/labels/{label_id}", response_model=ShippingLabelOut)
async def update_label(
    order_id: int, label_id: int, body: ShippingLabelUpdate, db: AsyncSession = Depends(get_db)
):
    """Edit an existing label (manual override / replay).

    Lets an admin fix the carrier/service/cost, swap in a new tracking number,
    or point label_url at a manually-provided label. The new tracking number
    cascades to every line item (and fulfillment item) linked to this label.
    """
    order = await _get_or_404(order_id, db)
    label = await db.get(ShippingLabel, label_id)
    if not label:
        raise HTTPException(404, "Label not found")

    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(label, k, v)

    # Cascade a changed tracking number to the linked line/fulfillment items
    if "tracking_number" in data:
        li_res = await db.execute(
            select(OrderLineItem).where(
                OrderLineItem.order_id == order_id,
                OrderLineItem.label_id == label_id,
            )
        )
        for li in li_res.scalars().all():
            li.tracking_number = data["tracking_number"]
        fi_res = await db.execute(
            select(OrderFulfillmentItem).where(OrderFulfillmentItem.label_id == label_id)
        )
        for fi in fi_res.scalars().all():
            fi.tracking_number = data["tracking_number"]

    await db.commit()
    await db.refresh(label)
    if "tracking_number" in data and data["tracking_number"]:
        await _try_push_marketplace_tracking(order, db)
    return label


@router.post("/{order_id}/labels/{label_id}/upload", response_model=ShippingLabelOut)
async def upload_label_pdf(
    order_id: int, label_id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)
):
    """Attach a manually-provided PDF label to an existing label record.

    Useful when a label was bought outside the system, or when the archived
    PDF is missing and needs to be re-supplied (\"replay\"). The PDF is stored
    base64-encoded so it can be served same-origin for printing.
    """
    await _get_or_404(order_id, db)
    label = await db.get(ShippingLabel, label_id)
    if not label:
        raise HTTPException(404, "Label not found")

    raw = await file.read()
    print(f"upload_label_pdf: order={order_id} label={label_id} filename={file.filename!r} content_type={file.content_type!r} size={len(raw)}", flush=True)
    if not raw:
        raise HTTPException(400, "Uploaded file is empty")
    if raw[:5] != b"%PDF-":
        print(f"upload_label_pdf: rejected — first 8 bytes = {raw[:8]!r}", flush=True)
        raise HTTPException(400, f"Please upload a PDF file (got {raw[:4]!r})")

    label.label_data = base64.b64encode(raw).decode()
    await db.commit()
    await db.refresh(label)
    print(f"upload_label_pdf: saved OK label_data len={len(label.label_data)}", flush=True)
    return label


@router.post("/{order_id}/labels/{label_id}/upload-b64", response_model=ShippingLabelOut)
async def upload_label_pdf_b64(
    order_id: int, label_id: int, body: UploadLabelB64, db: AsyncSession = Depends(get_db)
):
    """Upload a PDF label as base64-encoded JSON — avoids multipart proxy issues."""
    await _get_or_404(order_id, db)
    label = await db.get(ShippingLabel, label_id)
    if not label:
        raise HTTPException(404, "Label not found")
    try:
        raw = base64.b64decode(body.data)
    except Exception:
        raise HTTPException(400, "Invalid base64 data")
    if not raw:
        raise HTTPException(400, "Uploaded file is empty")
    if raw[:5] != b"%PDF-":
        raise HTTPException(400, f"Please upload a PDF file (got {raw[:4]!r})")
    label.label_data = base64.b64encode(raw).decode()
    await db.commit()
    await db.refresh(label)
    print(f"upload_label_pdf_b64: saved OK order={order_id} label={label_id} size={len(raw)}", flush=True)
    return label


@router.post("/{order_id}/labels/{label_id}/regenerate", response_model=ShippingLabelOut)
async def regenerate_label(
    order_id: int,
    label_id: int,
    size: str = Query("4x6", description="EasyPost label size, e.g. 4x6 or 7x3"),
    db: AsyncSession = Depends(get_db),
):
    """Re-fetch the carrier label from EasyPost and store it as-is."""
    label = await db.get(ShippingLabel, label_id)
    if not label:
        raise HTTPException(404, "Label not found")

    from app.core.config import settings
    from app.integrations.pdf_labels import image_to_label_pdf

    raw: bytes | None = None

    # Preferred: fetch PDF directly from label_url
    if label.label_url:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
                r = await http.get(label.label_url)
            if r.is_success:
                raw = r.content
        except Exception as e:
            raise HTTPException(502, f"Could not fetch the stored label URL: {e}")

    # Fallback: regenerate from EasyPost
    if not raw and label.shipment_id and settings.EASYPOST_API_KEY:
        from app.integrations.easypost.client import EasyPostClient, EasyPostError
        ep = EasyPostClient(settings.EASYPOST_API_KEY)
        try:
            png_b64, png_url = await ep.regenerate_label(label.shipment_id, size)
        except EasyPostError as e:
            raise HTTPException(e.status, str(e))
        if png_b64:
            raw = base64.b64decode(png_b64)
            if png_url:
                label.label_url = png_url

    if not raw:
        raise HTTPException(400, "No label URL or EasyPost shipment to regenerate from.")

    # Stamp product info into blank space
    try:
        lis_res = await db.execute(
            select(OrderLineItem).where(
                OrderLineItem.order_id == order_id,
                OrderLineItem.label_id == label_id,
            )
        )
        lis = lis_res.scalars().all()
        pack_items = []
        for li in lis:
            pack_items.extend(await _catalog_items_for_line_item(li, db))
        sup = await db.get(Supplier, label.supplier_id) if label.supplier_id else None
        if pack_items:
            from app.integrations.pdf_labels import LabelEntry, stamp_label
            entry = LabelEntry(
                order_label=(order.external_order_id or f"Order #{order_id}"),
                ship_to=None,
                tracking_number=label.tracking_number,
                label_pdf=None,
                items=pack_items,
                supplier_name=sup.name if sup else None,
            )
            raw = stamp_label(raw, entry)
        elif raw[:4] != b"%PDF":
            raw = image_to_label_pdf(raw)
    except Exception:
        if raw[:5] != b"%PDF-":
            raw = image_to_label_pdf(raw)

    label.label_data = base64.b64encode(raw).decode()
    await db.commit()
    await db.refresh(label)
    return label


async def _push_shopify_tracking(order: Order, db: AsyncSession) -> dict:
    """Internal helper — push tracking back to Shopify via FulfillmentOrders API.
    Returns dict with synced/errors/tracking_number. Caller decides whether to
    raise HTTPException or just log."""
    if order.marketplace != "shopify":
        return {"skipped": "not a shopify order"}
    if not order.external_order_id:
        return {"skipped": "no external order id"}
    if not order.connection_id:
        return {"skipped": "no connection"}

    from app.models.marketplace import MarketplaceConnection
    conn = await db.get(MarketplaceConnection, order.connection_id)
    if not conn:
        return {"error": "connection not found"}
    creds = conn.credentials or {}
    access_token = creds.get("access_token")
    shop_url = conn.shop_url or creds.get("shop_url")
    if not access_token or not shop_url:
        return {"error": "shopify credentials incomplete"}

    li_res = await db.execute(
        select(OrderLineItem).where(
            OrderLineItem.order_id == order.id,
            OrderLineItem.label_id.isnot(None),
        )
    )
    lis = li_res.scalars().all()
    label_ids = list({li.label_id for li in lis if li.label_id})
    if not label_ids:
        return {"skipped": "no labels yet"}

    labels_map: dict[int, ShippingLabel] = {}
    for lid in label_ids:
        lbl = await db.get(ShippingLabel, lid)
        if lbl:
            labels_map[lid] = lbl
    tracking_label = next((l for l in labels_map.values() if l.tracking_number), None)
    if not tracking_label:
        return {"skipped": "no label has tracking yet"}

    from app.integrations.shopify.client import ShopifyClient
    client = ShopifyClient(shop_url, access_token)

    try:
        fulfillment_orders = await client.get_fulfillment_orders(order.external_order_id)
    except Exception as e:
        err_str = str(e)
        if "403" in err_str:
            return {"error": "Shopify connection needs re-authorization: the current token is missing fulfillment scopes (read_fulfillments / write_fulfillments). Go to Marketplace → your Shopify connection → Re-authorize to fix this."}
        return {"error": f"get_fulfillment_orders failed: {e}"}

    open_fos = [fo for fo in fulfillment_orders if fo.get("status") in ("open", "in_progress")]
    if not open_fos:
        return {"skipped": "no open fulfillment orders on Shopify (already fulfilled?)"}

    synced, errors = [], []
    for fo in open_fos:
        fo_id = fo["id"]
        try:
            result = await client.post("/fulfillments.json", {
                "fulfillment": {
                    "line_items_by_fulfillment_order": [{"fulfillment_order_id": fo_id}],
                    "tracking_info": {
                        "number": tracking_label.tracking_number,
                        "company": tracking_label.carrier or "USPS",
                    },
                    "notify_customer": True,
                }
            })
            synced.append({
                "fulfillment_order_id": fo_id,
                "fulfillment_id": result.get("fulfillment", {}).get("id"),
            })
        except Exception as e:
            errors.append({"fulfillment_order_id": fo_id, "error": str(e)[:300]})

    return {"synced": synced, "errors": errors, "tracking_number": tracking_label.tracking_number}


async def _try_push_marketplace_tracking(order: Order, db: AsyncSession) -> None:
    """Best-effort marketplace tracking sync, called after a line item flips to
    shipped. Never raises — just logs the outcome."""
    try:
        if order.marketplace == "shopify":
            result = await _push_shopify_tracking(order, db)
            if result.get("error"):
                print(f"Shopify tracking push order={order.id}: {result['error']}", flush=True)
            elif result.get("skipped"):
                print(f"Shopify tracking push order={order.id}: skipped — {result['skipped']}", flush=True)
            elif result.get("synced"):
                print(f"Shopify tracking push order={order.id}: synced {len(result['synced'])} fulfillment order(s), tracking={result.get('tracking_number')}", flush=True)
    except Exception as e:
        print(f"Marketplace tracking push order={order.id} crashed: {e}", flush=True)


@router.post("/{order_id}/sync-tracking")
async def sync_tracking_to_shopify(
    order_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Manual: push tracking to Shopify. Raises on hard error so the UI can show
    a meaningful message. Auto-sync after mark-shipped/print-label uses the
    silent helper."""
    order = await _get_or_404(order_id, db)
    if order.marketplace != "shopify":
        raise HTTPException(400, "Only Shopify orders support tracking sync")
    result = await _push_shopify_tracking(order, db)
    if result.get("error"):
        err = result["error"]
        status = 403 if "re-authorization" in err else 502
        raise HTTPException(status, err)
    if result.get("skipped"):
        raise HTTPException(400, result["skipped"])
    if not result.get("synced") and result.get("errors"):
        raise HTTPException(502, f"Shopify sync failed: {result['errors'][0]['error']}")
    return result


@router.get("/{order_id}/parcel-estimate")
async def estimate_parcel(
    order_id: int,
    supplier_id: int | None = Query(None),
    line_item_ids: str | None = Query(None, description="Comma-separated line item IDs"),
    db: AsyncSession = Depends(get_db),
):
    """Estimate parcel weight (oz) and dimensions (in) from SupplierProduct shipping data."""
    await _get_or_404(order_id, db)

    li_q = select(OrderLineItem).where(OrderLineItem.order_id == order_id)
    if supplier_id is not None:
        li_q = li_q.where(OrderLineItem.supplier_id == supplier_id)
    if line_item_ids:
        try:
            ids = [int(x) for x in line_item_ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(400, "Invalid line_item_ids")
        li_q = li_q.where(OrderLineItem.id.in_(ids))
    li_res = await db.execute(li_q)
    lis = list(li_res.scalars().all())
    if not lis:
        raise HTTPException(404, "No matching line items")

    weight_oz = 0.0
    max_length_in = 0.0
    max_width_in = 0.0
    height_in_total = 0.0
    covered: list[int] = []
    missing: list[dict] = []

    KG_TO_OZ = 35.274
    CM_TO_IN = 0.393701

    for li in lis:
        fi_res = await db.execute(
            select(OrderFulfillmentItem).where(OrderFulfillmentItem.order_line_item_id == li.id)
        )
        fis = list(fi_res.scalars().all())

        if fis:
            for fi in fis:
                sp = await db.get(SupplierProduct, fi.supplier_product_id)
                if not sp:
                    missing.append({"line_item_id": li.id, "reason": "supplier_product_missing"})
                    continue
                qty = fi.quantity
                if sp.weight is None:
                    missing.append({
                        "line_item_id": li.id,
                        "supplier_product_id": sp.id,
                        "supplier_product_name": sp.name,
                        "reason": "no_weight",
                    })
                else:
                    weight_oz += float(sp.weight) * qty
                if sp.length is not None:
                    max_length_in = max(max_length_in, float(sp.length))
                if sp.width is not None:
                    max_width_in = max(max_width_in, float(sp.width))
                if sp.height is not None:
                    height_in_total += float(sp.height) * qty
                covered.append(li.id)
        else:
            product = await db.get(Product, li.product_id) if li.product_id else None
            if not product or product.weight is None:
                missing.append({
                    "line_item_id": li.id,
                    "product_name": li.product_name,
                    "reason": "no_component_or_product_dims",
                })
                continue
            qty = li.quantity
            weight_oz += float(product.weight) * KG_TO_OZ * qty
            if product.length is not None:
                max_length_in = max(max_length_in, float(product.length) * CM_TO_IN)
            if product.width is not None:
                max_width_in = max(max_width_in, float(product.width) * CM_TO_IN)
            if product.height is not None:
                height_in_total += float(product.height) * CM_TO_IN * qty
            covered.append(li.id)

    return {
        "weight": round(weight_oz, 2),
        "length": round(max_length_in, 2),
        "width": round(max_width_in, 2),
        "height": round(height_in_total, 2),
        "covered_line_item_ids": list(set(covered)),
        "missing": missing,
        "complete": len(missing) == 0 and weight_oz > 0,
    }


# --- Helpers ---

async def _recalculate_order_status(order: Order, db: AsyncSession):
    """Update order.status based on aggregate of line item fulfill_status values."""
    result = await db.execute(select(OrderLineItem).where(OrderLineItem.order_id == order.id))
    items = result.scalars().all()
    if not items:
        return

    statuses = [li.fulfill_status for li in items]
    active = [s for s in statuses if s != FulfillStatus.cancelled]

    if not active:
        order.status = OrderStatus.cancelled
    elif all(s in (FulfillStatus.shipped, FulfillStatus.delivered) for s in active):
        order.status = OrderStatus.fulfilled
    elif any(s in (FulfillStatus.shipped, FulfillStatus.delivered) for s in active):
        order.status = OrderStatus.partially_fulfilled
    elif any(s == FulfillStatus.pending for s in active):
        order.status = OrderStatus.processing
    else:
        order.status = OrderStatus.pending


async def _get_or_404(order_id: int, db: AsyncSession) -> Order:
    o = await db.get(Order, order_id)
    if not o:
        raise HTTPException(404, "Order not found")
    return o



async def _catalog_items_for_line_item(li: OrderLineItem, db: AsyncSession) -> list:
    """Resolve catalog name/size/qty for a line item via OFI → ProductComponent → SupplierProduct."""
    from app.integrations.pdf_labels import PackItem
    fi_res = await db.execute(
        select(OrderFulfillmentItem).where(OrderFulfillmentItem.order_line_item_id == li.id)
    )
    fis = fi_res.scalars().all()
    if fis:
        items = []
        for fi in fis:
            sp = await db.get(SupplierProduct, fi.supplier_product_id)
            if sp:
                items.append(PackItem(name=sp.short_name or sp.name or li.product_name,
                                      sku=sp.sku, quantity=fi.quantity, size=sp.size if hasattr(sp, 'size') else None))
        if items:
            return items
    if li.product_id:
        comps = (await db.execute(
            select(ProductComponent).where(ProductComponent.product_id == li.product_id)
        )).scalars().all()
        if comps:
            items = []
            for comp in comps:
                sp = await db.get(SupplierProduct, comp.supplier_product_id)
                if sp:
                    items.append(PackItem(name=sp.short_name or sp.name or li.product_name,
                                          sku=sp.sku, quantity=li.quantity * comp.quantity,
                                          size=sp.size if hasattr(sp, 'size') else None))
            if items:
                return items
    return [PackItem(name=li.product_name, sku=li.sku, quantity=li.quantity)]


async def _stamp_carrier_for_label(carrier_pdf: bytes, label: ShippingLabel, db: AsyncSession) -> bytes:
    """Stamp the product info (Qty + NAME + (size/pot) + date for JOE) onto a
    raw carrier PDF, resolving items/supplier from the label's line items."""
    from app.integrations.pdf_labels import LabelEntry, stamp_label

    lis = (await db.execute(
        select(OrderLineItem).where(OrderLineItem.label_id == label.id)
    )).scalars().all()

    pack_items: list = []
    order_obj: Order | None = None
    for li in lis:
        pack_items.extend(await _catalog_items_for_line_item(li, db))
        if order_obj is None and li.order_id:
            order_obj = await db.get(Order, li.order_id)

    if not pack_items:
        return carrier_pdf

    sup = await db.get(Supplier, label.supplier_id) if label.supplier_id else None
    if order_obj is not None:
        order_label = order_obj.external_order_id or f"Order #{order_obj.id}"
    else:
        order_label = ""

    entry = LabelEntry(
        order_label=order_label,
        ship_to=None,
        tracking_number=label.tracking_number,
        label_pdf=None,
        items=pack_items,
        supplier_name=sup.name if sup else None,
    )
    return stamp_label(carrier_pdf, entry)


async def _line_item_out(li: OrderLineItem, db: AsyncSession) -> OrderLineItemOut:
    sup = await db.get(Supplier, li.supplier_id) if li.supplier_id else None
    data = {c.name: getattr(li, c.name) for c in li.__table__.columns}
    data["supplier_name"] = sup.name if sup else None

    catalog_name = None
    if li.supplier_id:
        fi_res = await db.execute(
            select(OrderFulfillmentItem).where(OrderFulfillmentItem.order_line_item_id == li.id).limit(1)
        )
        fi = fi_res.scalars().first()
        if fi:
            sp = await db.get(SupplierProduct, fi.supplier_product_id)
            if sp:
                catalog_name = sp.short_name or sp.name
    data["catalog_name"] = catalog_name

    mapping_suggestion = None
    if not li.supplier_id:
        from sqlalchemy import func as sqlfunc
        product_id = li.product_id
        if not product_id and li.sku:
            prod_res = await db.execute(
                select(Product).where(sqlfunc.lower(sqlfunc.trim(Product.sku)) == li.sku.strip().lower())
            )
            prod = prod_res.scalar_one_or_none()
            if prod:
                product_id = prod.id
        if product_id:
            comp_res = await db.execute(
                select(ProductComponent).where(ProductComponent.product_id == product_id)
            )
            comp = comp_res.scalars().first()
            if comp:
                sp = await db.get(SupplierProduct, comp.supplier_product_id)
                if sp:
                    sp_sup = await db.get(Supplier, sp.supplier_id)
                    mapping_suggestion = {
                        "supplier_id": sp.supplier_id,
                        "supplier_name": sp_sup.name if sp_sup else None,
                        "supplier_product_id": sp.id,
                        "catalog_name": sp.short_name or sp.name,
                        "catalog_sku": sp.sku,
                        "units": comp.quantity,
                    }
    data["mapping_suggestion"] = mapping_suggestion
    return OrderLineItemOut(**data)


async def _order_out(order: Order, db: AsyncSession) -> OrderOut:
    li_result = await db.execute(select(OrderLineItem).where(OrderLineItem.order_id == order.id))
    li_list = li_result.scalars().all()
    line_items = [await _line_item_out(li, db) for li in li_list]
    data = {c.name: getattr(order, c.name) for c in order.__table__.columns}
    data["line_items"] = line_items
    return OrderOut(**data)


async def _auto_assign_line_item(li: OrderLineItem, db: AsyncSession) -> bool:
    """Auto-assign a supplier catalog item to a line item by SKU.

    Two strategies, tried in order:
      A. order SKU → Product.sku → ProductComponent → SupplierProduct (configured mapping)
      B. order SKU == SupplierProduct.sku directly — only when EXACTLY ONE catalog
         item matches; multiple suppliers with the same SKU are skipped to avoid
         guessing wrong.

    Returns True if assignment was made, False if skipped (no/ambiguous match or
    already assigned). Idempotent: skips if li.supplier_id is already set.
    """
    if li.supplier_id or not li.sku:
        return False

    from sqlalchemy import func as sqlfunc
    sku_norm = li.sku.strip().lower()

    sp = None
    units = 1   # supplier-catalog units per ordered unit
    via = None

    # Strategy A: via configured Product → ProductComponent mapping
    product = (await db.execute(
        select(Product).where(sqlfunc.lower(sqlfunc.trim(Product.sku)) == sku_norm)
    )).scalar_one_or_none()
    if product and not li.product_id:
        li.product_id = product.id
    if li.product_id:
        comp = (await db.execute(
            select(ProductComponent).where(ProductComponent.product_id == li.product_id)
        )).scalars().first()
        if comp:
            sp = await db.get(SupplierProduct, comp.supplier_product_id)
            if sp:
                units = comp.quantity
                via = "product"

    # Strategy B: direct match against supplier catalog SKU (unique only)
    if sp is None:
        matches = (await db.execute(
            select(SupplierProduct).where(sqlfunc.lower(sqlfunc.trim(SupplierProduct.sku)) == sku_norm)
        )).scalars().all()
        if len(matches) == 1:
            sp = matches[0]
            units = 1
            via = "direct"
        elif len(matches) > 1:
            print(
                f"auto_assign: line item {li.id} sku={li.sku!r} matches "
                f"{len(matches)} catalog items — skipped (ambiguous)",
                flush=True,
            )
            return False

    if sp is None:
        return False

    # Assign supplier to line item
    li.supplier_id = sp.supplier_id

    # Record the supplier cost so this order's COGS shows in the Daily Report
    # balance even when fulfilled externally (e.g. Amazon). Mirrors the manual
    # assign formula (unit_price × units). Only runs on a confirmed SKU→catalog
    # match, so no fuzzy/guessed costs.
    li.base_cost = sp.unit_price * units

    # Upsert OrderFulfillmentItem
    ofi_res = await db.execute(
        select(OrderFulfillmentItem).where(
            OrderFulfillmentItem.order_line_item_id == li.id,
            OrderFulfillmentItem.supplier_product_id == sp.id,
        )
    )
    ofi = ofi_res.scalar_one_or_none()
    qty = li.quantity * units
    if ofi:
        ofi.quantity = qty
    else:
        db.add(OrderFulfillmentItem(
            order_line_item_id=li.id,
            supplier_product_id=sp.id,
            quantity=qty,
        ))

    print(
        f"Auto-assigned line item {li.id} (sku={li.sku!r}) via {via} → "
        f"supplier_product {sp.id} (supplier_id={sp.supplier_id})",
        flush=True,
    )
    return True


async def _post_scan_assign(order: Order, db: AsyncSession) -> dict:
    """Advance an order right after its label was scanned.

    - If every active line item already has a supplier → mark the order
      "processing".
    - Otherwise auto-assign suppliers by SKU (li.sku → catalog item); if that
      completes the assignment, also mark it "processing".

    Only promotes a "pending" order — never downgrades shipped/fulfilled/
    cancelled ones. Does NOT commit; the caller owns the transaction.
    Returns a small summary for the scan result.
    """
    items = (await db.execute(
        select(OrderLineItem).where(OrderLineItem.order_id == order.id)
    )).scalars().all()
    active = [li for li in items if li.fulfill_status != FulfillStatus.cancelled]
    if not active:
        return {"assigned_before": False, "auto_assigned": 0,
                "fully_assigned": False, "moved_to_processing": False}

    assigned_before = all(li.supplier_id for li in active)

    auto_assigned = 0
    if not assigned_before:
        for li in active:
            if not li.supplier_id and await _auto_assign_line_item(li, db):
                auto_assigned += 1

    fully_assigned = all(li.supplier_id for li in active)
    moved = False
    if fully_assigned and order.status == OrderStatus.pending.value:
        order.status = OrderStatus.processing.value
        order.updated_at = datetime.now(timezone.utc)
        moved = True

    print(
        f"post_scan_assign: order={order.external_order_id} "
        f"assigned_before={assigned_before} auto_assigned={auto_assigned} "
        f"fully_assigned={fully_assigned} -> processing={moved}",
        flush=True,
    )
    return {"assigned_before": assigned_before, "auto_assigned": auto_assigned,
            "fully_assigned": fully_assigned, "moved_to_processing": moved}


@router.post("/backfill-auto-assign")
async def backfill_auto_assign(db: AsyncSession = Depends(get_db)):
    """Run _auto_assign_line_item for all unassigned line items across all orders.

    Safe to run multiple times — idempotent per line item.
    """
    result = await db.execute(
        select(OrderLineItem).where(
            OrderLineItem.supplier_id.is_(None),
            OrderLineItem.sku.isnot(None),
            OrderLineItem.fulfill_status != FulfillStatus.shipped,
        )
    )
    items = result.scalars().all()
    assigned = 0
    skipped = 0
    for li in items:
        ok = await _auto_assign_line_item(li, db)
        if ok:
            assigned += 1
        else:
            skipped += 1
    await db.commit()
    return {"assigned": assigned, "skipped": skipped, "total": len(items)}


@router.post("/backfill-base-cost")
async def backfill_base_cost(db: AsyncSession = Depends(get_db)):
    """Fill base_cost (giá vốn) for line items that have a supplier mapping but
    base_cost = 0 — e.g. Amazon orders auto-assigned before cost was recorded —
    so their COGS shows up in the Daily Report balance.

    Recomputes from existing fulfillment items (unit_price × qty ÷ line qty);
    runs auto-assign for still-unassigned items. Idempotent and never overwrites
    a line item that already has a non-zero base_cost.
    """
    from decimal import Decimal
    from sqlalchemy import or_

    rows = (await db.execute(
        select(OrderLineItem).where(
            or_(OrderLineItem.base_cost == 0, OrderLineItem.base_cost.is_(None)),
            OrderLineItem.fulfill_status != FulfillStatus.shipped,
        )
    )).scalars().all()

    updated = 0
    auto_assigned = 0
    for li in rows:
        if not li.quantity:
            continue
        ofis = (await db.execute(
            select(OrderFulfillmentItem).where(OrderFulfillmentItem.order_line_item_id == li.id)
        )).scalars().all()
        if ofis:
            total = Decimal(0)
            for ofi in ofis:
                sp = await db.get(SupplierProduct, ofi.supplier_product_id)
                if sp and sp.unit_price:
                    total += Decimal(sp.unit_price) * int(ofi.quantity or 0)
            if total > 0:
                li.base_cost = (total / li.quantity).quantize(Decimal("0.01"))
                updated += 1
        elif li.supplier_id is None and li.sku:
            if await _auto_assign_line_item(li, db):
                auto_assigned += 1
    await db.commit()
    return {"updated": updated, "auto_assigned": auto_assigned, "scanned": len(rows)}
