"""
Phân loại SKU theo supplier dựa trên cấu trúc:
{owner}-{shop}-{supplier}-{product}-{info}

Trả về tên supplier nếu nhận diện được, hoặc 'unknown' nếu không.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.supplier import Supplier
from app.data.joe_sku_overrides import JOE_SKU_OVERRIDES, _normalize


async def get_known_supplier_usernames(db: AsyncSession) -> set[str]:
    """Lấy danh sách username của tất cả supplier trong DB."""
    result = await db.execute(
        select(Supplier.username).where(Supplier.username.isnot(None))
    )
    return {row[0] for row in result.all()}


def _parse_sku(sku: str) -> dict:
    """Tách SKU theo dấu '-' và trả về các phần."""
    if not sku:
        return {"valid": False}
    parts = sku.split("-")
    if len(parts) < 4:
        return {"valid": False}
    return {
        "valid": True,
        "owner": parts[0].strip(),
        "shop": parts[1].strip(),
        "supplier_token": parts[2].strip(),
        "rest": "-".join(parts[3:]).strip(),
    }


def classify_sku(sku: str | None, known_suppliers: set[str]) -> dict:
    """
    Trả về:
    {
        "supplier": "Joe" | "Fairy" | ... | None,
        "reason": "position_3" | "override" | "missing_supplier" | "invalid"
    }
    """
    if not sku:
        return {"supplier": None, "reason": "invalid"}

    parsed = _parse_sku(sku)
    if not parsed["valid"]:
        return {"supplier": None, "reason": "invalid"}

    token = parsed["supplier_token"]

    # Case 1: vị trí 3 trùng với supplier đã biết → chắc chắn
    if token in known_suppliers:
        return {"supplier": token, "reason": "position_3"}

    # Case 2: vị trí 3 không phải supplier → SKU thiếu supplier
    # Check override list cho JOE
    if _normalize(sku) in {_normalize(s) for s in JOE_SKU_OVERRIDES}:
        return {"supplier": "Joe", "reason": "override"}

    # Case 3: thiếu supplier và không có override → cần xử lý
    return {"supplier": None, "reason": "missing_supplier"}
