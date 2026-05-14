from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.models.product import Product, ProductSupplier
from app.models.supplier import Supplier
from app.schemas.product import (
    ProductCreate, ProductUpdate, ProductOut, ProductListOut,
    ProductSupplierCreate, ProductSupplierUpdate, ProductSupplierOut
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
        db.add(ProductSupplier(product_id=product.id, **s.model_dump()))

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
    ps = ProductSupplier(product_id=product_id, **body.model_dump())
    db.add(ps)
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
