from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.models.product import Product, ProductSupplier, ProductComponent
from app.models.supplier import Supplier, SupplierProduct
from app.schemas.product import (
    ProductCreate, ProductUpdate, ProductOut, ProductListOut,
    ProductSupplierCreate, ProductSupplierUpdate, ProductSupplierOut
)
from app.schemas.supplier_product import (
    ProductComponentCreate, ProductComponentUpdate, ProductComponentOut
)
import pandas as pd
import io

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductListOut])
async def list_products(
    search: str | None = Query(None),
    supplier_id: int | None = Query(None),
    is_active: bool | None = Query(None),
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    q = select(Product)
    if search:
        q = q.where(Product.name.ilike(f"%{search}%") | Product.sku.ilike(f"%{search}%"))
    if is_active is not None:
        q = q.where(Product.is_active == is_active)
    if supplier_id:
        q = q.where(Product.product_suppliers.any(ProductSupplier.supplier_id == supplier_id))
    q = q.offset(skip).limit(limit)
    result = await db.execute(q)
    products = result.scalars().all()

    out = []
    for p in products:
        ps_q = await db.execute(select(ProductSupplier).where(ProductSupplier.product_id == p.id))
        ps_list = ps_q.scalars().all()
        out.append(ProductListOut(
            id=p.id, name=p.name, sku=p.sku, base_cost=p.base_cost,
            is_active=p.is_active,
            supplier_count=len(ps_list),
            total_stock=sum(ps.stock for ps in ps_list),
        ))
    return out


@router.post("", response_model=ProductOut, status_code=201)
async def create_product(body: ProductCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Product).where(Product.sku == body.sku))
    if existing.scalar_one_or_none():
        raise HTTPException(400, f"SKU '{body.sku}' already exists")

    product = Product(**body.model_dump(exclude={"suppliers"}))
    db.add(product)
    await db.flush()

    for s in body.suppliers:
        s_data = s.model_dump()
        sp_id = s_data.pop("supplier_product_id", None)
        units = s_data.pop("units", 1)
        db.add(ProductSupplier(product_id=product.id, **s_data))
        if sp_id is not None:
            db.add(ProductComponent(
                product_id=product.id,
                supplier_product_id=sp_id,
                quantity=units,
            ))

    await db.commit()
    await db.refresh(product)
    return await _product_out(product, db)


@router.get("/{product_id}", response_model=ProductOut)
async def get_product(product_id: int, db: AsyncSession = Depends(get_db)):
    product = await _get_or_404(product_id, db)
    return await _product_out(product, db)


@router.patch("/{product_id}", response_model=ProductOut)
async def update_product(product_id: int, body: ProductUpdate, db: AsyncSession = Depends(get_db)):
    product = await _get_or_404(product_id, db)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(product, k, v)
    await db.commit()
    await db.refresh(product)
    return await _product_out(product, db)


@router.delete("/{product_id}", status_code=204)
async def delete_product(product_id: int, db: AsyncSession = Depends(get_db)):
    product = await _get_or_404(product_id, db)
    await db.delete(product)
    await db.commit()


# --- Supplier assignments ---

@router.get("/{product_id}/suppliers", response_model=list[ProductSupplierOut])
async def list_product_suppliers(product_id: int, db: AsyncSession = Depends(get_db)):
    await _get_or_404(product_id, db)
    result = await db.execute(select(ProductSupplier).where(ProductSupplier.product_id == product_id))
    ps_list = result.scalars().all()
    out = []
    for ps in ps_list:
        sup = await db.get(Supplier, ps.supplier_id)
        out.append(ProductSupplierOut(**ps.__dict__, supplier_name=sup.name if sup else None))
    return out


@router.post("/{product_id}/suppliers", response_model=ProductSupplierOut, status_code=201)
async def add_product_supplier(product_id: int, body: ProductSupplierCreate, db: AsyncSession = Depends(get_db)):
    await _get_or_404(product_id, db)
    data = body.model_dump()
    supplier_product_id = data.pop("supplier_product_id", None)
    units = data.pop("units", 1)

    if supplier_product_id is not None:
        sp = await db.get(SupplierProduct, supplier_product_id)
        if not sp or sp.supplier_id != body.supplier_id:
            raise HTTPException(400, "Supplier product does not belong to this supplier")
        if units < 1:
            raise HTTPException(400, "Units must be at least 1")

    ps = ProductSupplier(product_id=product_id, **data)
    db.add(ps)
    await db.flush()

    # Also create/update the ProductComponent link so that incoming orders
    # auto-expand into supplier fulfillment items with quantity = units × order_qty.
    if supplier_product_id is not None:
        existing = await db.execute(
            select(ProductComponent).where(
                ProductComponent.product_id == product_id,
                ProductComponent.supplier_product_id == supplier_product_id,
            )
        )
        comp = existing.scalar_one_or_none()
        if comp:
            comp.quantity = units
        else:
            db.add(ProductComponent(
                product_id=product_id,
                supplier_product_id=supplier_product_id,
                quantity=units,
            ))

        # Backfill OrderFulfillmentItem for existing unshipped orders that have
        # this product_id but no OFI yet — so they immediately reflect the mapping.
        from app.models.order import OrderLineItem, OrderFulfillmentItem, FulfillStatus
        li_res = await db.execute(
            select(OrderLineItem).where(
                OrderLineItem.product_id == product_id,
                OrderLineItem.supplier_id == body.supplier_id,
                OrderLineItem.fulfill_status.in_([FulfillStatus.unfulfilled, FulfillStatus.pending]),
            )
        )
        for li in li_res.scalars().all():
            fi_res = await db.execute(
                select(OrderFulfillmentItem).where(
                    OrderFulfillmentItem.order_line_item_id == li.id,
                    OrderFulfillmentItem.supplier_product_id == supplier_product_id,
                )
            )
            if not fi_res.scalar_one_or_none():
                db.add(OrderFulfillmentItem(
                    order_line_item_id=li.id,
                    supplier_product_id=supplier_product_id,
                    quantity=units * li.quantity,
                ))

    await db.commit()
    await db.refresh(ps)
    sup = await db.get(Supplier, ps.supplier_id)
    return ProductSupplierOut(**ps.__dict__, supplier_name=sup.name if sup else None)


@router.patch("/{product_id}/suppliers/{ps_id}", response_model=ProductSupplierOut)
async def update_product_supplier(product_id: int, ps_id: int, body: ProductSupplierUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProductSupplier).where(ProductSupplier.id == ps_id, ProductSupplier.product_id == product_id))
    ps = result.scalar_one_or_none()
    if not ps:
        raise HTTPException(404, "Not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(ps, k, v)
    await db.commit()
    await db.refresh(ps)
    sup = await db.get(Supplier, ps.supplier_id)
    return ProductSupplierOut(**ps.__dict__, supplier_name=sup.name if sup else None)


@router.delete("/{product_id}/suppliers/{ps_id}", status_code=204)
async def remove_product_supplier(product_id: int, ps_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProductSupplier).where(ProductSupplier.id == ps_id, ProductSupplier.product_id == product_id))
    ps = result.scalar_one_or_none()  
    if not ps:
        raise HTTPException(404, "Not found")
    await db.delete(ps)
    await db.commit()


# --- Product components (new inventory linking) ---

@router.get("/{product_id}/components", response_model=list[ProductComponentOut])
async def list_components(product_id: int, db: AsyncSession = Depends(get_db)):
    await _get_or_404(product_id, db)
    result = await db.execute(
        select(ProductComponent).where(ProductComponent.product_id == product_id)
    )
    components = result.scalars().all()
    return [await _component_out(c, db) for c in components]


@router.post("/{product_id}/components", response_model=ProductComponentOut, status_code=201)
async def add_component(product_id: int, body: ProductComponentCreate, db: AsyncSession = Depends(get_db)):
    await _get_or_404(product_id, db)
    sp = await db.get(SupplierProduct, body.supplier_product_id)
    if not sp:
        raise HTTPException(404, "Supplier product not found")
    comp = ProductComponent(product_id=product_id, **body.model_dump())
    db.add(comp)
    try:
        await db.flush()
    except Exception:
        await db.rollback()
        raise HTTPException(400, "This supplier product is already linked to this product")

    # Backfill OrderFulfillmentItem for existing unshipped orders with this product
    # that belong to the same supplier, so they immediately reflect the new mapping.
    from app.models.order import OrderLineItem, OrderFulfillmentItem, FulfillStatus
    li_res = await db.execute(
        select(OrderLineItem).where(
            OrderLineItem.product_id == product_id,
            OrderLineItem.supplier_id == sp.supplier_id,
            OrderLineItem.fulfill_status.in_([FulfillStatus.unfulfilled, FulfillStatus.pending]),
        )
    )
    for li in li_res.scalars().all():
        fi_res = await db.execute(
            select(OrderFulfillmentItem).where(
                OrderFulfillmentItem.order_line_item_id == li.id,
                OrderFulfillmentItem.supplier_product_id == body.supplier_product_id,
            )
        )
        if not fi_res.scalar_one_or_none():
            db.add(OrderFulfillmentItem(
                order_line_item_id=li.id,
                supplier_product_id=body.supplier_product_id,
                quantity=body.quantity * li.quantity,
            ))

    await db.commit()
    await db.refresh(comp)
    return await _component_out(comp, db)


@router.patch("/{product_id}/components/{comp_id}", response_model=ProductComponentOut)
async def update_component(
    product_id: int, comp_id: int, body: ProductComponentUpdate, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(ProductComponent).where(
            ProductComponent.id == comp_id, ProductComponent.product_id == product_id
        )
    )
    comp = result.scalar_one_or_none()
    if not comp:
        raise HTTPException(404, "Component not found")
    comp.quantity = body.quantity
    await db.commit()
    await db.refresh(comp)
    return await _component_out(comp, db)


@router.delete("/{product_id}/components/{comp_id}", status_code=204)
async def remove_component(product_id: int, comp_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ProductComponent).where(
            ProductComponent.id == comp_id, ProductComponent.product_id == product_id
        )
    )
    comp = result.scalar_one_or_none()
    if not comp:
        raise HTTPException(404, "Component not found")
    await db.delete(comp)
    await db.commit()


# --- CSV Import ---

@router.post("/import/csv", status_code=201)
async def import_csv(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    content = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(400, f"Invalid CSV: {e}")

    required = {"name", "sku"}
    if not required.issubset(df.columns):
        raise HTTPException(400, f"CSV must contain columns: {required}")

    created, skipped, errors = 0, 0, []
    for _, row in df.iterrows():
        sku = str(row["sku"]).strip()
        existing = await db.execute(select(Product).where(Product.sku == sku))
        if existing.scalar_one_or_none():
            skipped += 1
            continue
        try:
            p = Product(
                name=str(row["name"]).strip(),
                sku=sku,
                base_cost=float(row.get("base_cost", 0) or 0),
                weight=float(row["weight"]) if pd.notna(row.get("weight")) else None,
                length=float(row["length"]) if pd.notna(row.get("length")) else None,
                width=float(row["width"]) if pd.notna(row.get("width")) else None,
                height=float(row["height"]) if pd.notna(row.get("height")) else None,
                description=str(row["description"]) if pd.notna(row.get("description")) else None,
            )
            db.add(p)
            created += 1
        except Exception as e:
            errors.append(f"Row {sku}: {e}")

    await db.commit()
    return {"created": created, "skipped": skipped, "errors": errors}


# --- Helpers ---

async def _get_or_404(product_id: int, db: AsyncSession) -> Product:
    p = await db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    return p


async def _component_out(comp: ProductComponent, db: AsyncSession) -> ProductComponentOut:
    sp = await db.get(SupplierProduct, comp.supplier_product_id)
    sup = await db.get(Supplier, sp.supplier_id) if sp else None
    return ProductComponentOut(
        id=comp.id,
        product_id=comp.product_id,
        supplier_product_id=comp.supplier_product_id,
        quantity=comp.quantity,
        supplier_product_name=sp.name if sp else None,
        supplier_product_sku=sp.sku if sp else None,
        supplier_id=sp.supplier_id if sp else None,
        supplier_name=sup.name if sup else None,
        unit_price=sp.unit_price if sp else None,
    )


async def _product_out(product: Product, db: AsyncSession) -> ProductOut:
    ps_result = await db.execute(select(ProductSupplier).where(ProductSupplier.product_id == product.id))
    ps_list = ps_result.scalars().all()
    suppliers_out = []
    for ps in ps_list:
        sup = await db.get(Supplier, ps.supplier_id)
        suppliers_out.append(ProductSupplierOut(**ps.__dict__, supplier_name=sup.name if sup else None))
    data = {c.name: getattr(product, c.name) for c in product.__table__.columns}
    data["product_suppliers"] = suppliers_out
    return ProductOut(**data)
