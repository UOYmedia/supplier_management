"""
Gợi ý SupplierProduct (cây gốc) cho một SKU dựa trên match
tokens trong SKU với tên/short_name/sku của cây gốc.

Confidence:
- 95: match >= 2 tokens VÀ match_ratio >= 0.5
- 85: match_ratio >= 0.5 (1 token)
- 70: match từ product_name trên đơn
- 60: match yếu (1 token, ratio < 0.5)
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.supplier import SupplierProduct


# Token cần skip khi parse SKU
SKIP_TOKENS = {
    "jenny", "jane", "zoe", "grace",          # tên người
    "ggl",                                     # tên shop
    "joe", "fairy", "native", "sky", "bota",   # supplier
    "jamie", "vutran", "skygd", "nati", "panter",
}


def _extract_tokens(sku: str) -> list[str]:
    """Lấy các token có thể là tên cây từ SKU."""
    if not sku:
        return []
    parts = sku.replace("--", "-").split("-")
    tokens = []
    for p in parts:
        p = p.strip().lower()
        if not p or p in SKIP_TOKENS:
            continue
        if p.isdigit() or p.startswith("set") or p.startswith("var"):
            continue
        if len(p) <= 2:
            continue
        tokens.append(p)
    return tokens


async def suggest_origin_for_sku(
    sku: str,
    product_name: str | None,
    supplier_id: int,
    db: AsyncSession,
) -> list[dict]:
    """
    Trả về top 3 suggestion sắp xếp theo confidence giảm dần.
    [{supplier_product_id, name, sku, confidence, reason}]
    """
    tokens = _extract_tokens(sku)

    # Lấy tất cả catalog item của supplier
    result = await db.execute(
        select(SupplierProduct).where(
            SupplierProduct.supplier_id == supplier_id
        )
    )
    products = result.scalars().all()

    suggestions = []
    for p in products:
        name_lower = (p.name or "").lower()
        short_lower = (p.short_name or "").lower()
        sku_lower = (p.sku or "").lower()
        searchable = f"{name_lower} {short_lower} {sku_lower}"

        matched = [t for t in tokens if t in searchable]

        if matched:
            ratio = len(matched) / max(len(tokens), 1)
            if len(matched) >= 2 and ratio >= 0.5:
                conf = 95
            elif ratio >= 0.5:
                conf = 85
            else:
                conf = 60
            suggestions.append({
                "supplier_product_id": p.id,
                "name": p.name,
                "sku": p.sku,
                "confidence": conf,
                "reason": f"Match tokens: {', '.join(matched)}",
            })
        elif product_name:
            # Fallback: match từ product_name trên đơn
            pn_lower = product_name.lower()
            if name_lower and len(name_lower) >= 4 and name_lower in pn_lower:
                suggestions.append({
                    "supplier_product_id": p.id,
                    "name": p.name,
                    "sku": p.sku,
                    "confidence": 70,
                    "reason": "Match từ tên sản phẩm trên đơn",
                })

    suggestions.sort(key=lambda x: x["confidence"], reverse=True)
    return suggestions[:3]
