"""
Override list cho supplier JOE.

Dùng cho các SKU thực sự thuộc JOE nhưng cấu trúc SKU KHÔNG mang 'Joe' ở vị trí
supplier (vị trí 3) — ví dụ SKU cũ/thiếu vị trí supplier. Khi đó classifier
không tự nhận diện được, nên ta liệt kê SKU đầy đủ ở đây để ép phân loại về JOE.

Cách dùng: thêm nguyên chuỗi marketplace SKU vào JOE_SKU_OVERRIDES. So khớp
được thực hiện sau khi đi qua _normalize() nên không phân biệt hoa/thường và
khoảng trắng thừa.
"""

# Danh sách SKU (đầy đủ) cần ép phân loại về supplier JOE.
# TODO(team): bổ sung các SKU JOE bị thiếu vị trí supplier vào đây.
JOE_SKU_OVERRIDES: list[str] = [
    # "Jenny-GGL-jasmine-1",
]


def _normalize(value: str | None) -> str:
    """Chuẩn hoá SKU để so khớp khoan dung (bỏ khoảng trắng, về chữ thường)."""
    return (value or "").strip().lower()
