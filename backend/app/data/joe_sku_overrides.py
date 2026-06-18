"""
Danh sách SKU thuộc supplier JOE nhưng KHÔNG có "Joe" ở vị trí 3
(do team đặt thiếu supplier lúc tạo listing).

TODO: Nếu danh sách vượt 100 SKU hoặc cần team tự sửa thường xuyên,
chuyển sang bảng database sku_supplier_overrides + giao diện quản lý.
"""

JOE_SKU_OVERRIDES = {
    "Jane-GGL-Pink Easter-10",
    "Jane-GGL-Pink Easter-11",
    "Jane-GGL-Pink Easter-11a",
    "Jane-GGL-Pink Easter-12",
    "Jane-GGL-Red Easter-10",
    "Jane-GGL-Red Easter-11",
    "Jane-GGL-Red Easter-12",
    "Jane-GGL-Thai Constellation-10",
    "Jane-GGL-Thai Constellation-11",
    "Jenny-GGL-Guava-pink-1",
    "Jenny-GGL-bayleaf-1",
    "Jenny-GGL-bleeding-heart-1",
    "Jenny-GGL-bleeding-heart-2",
    "Jenny-GGL-bleeding-heart-3",
    "Jenny-GGL-christmas-cactus-Pink-1",
    "Jenny-GGL-christmas-cactus-orange-2",
    "Jenny-GGL-christmas-cactus-pink-2",
    "Jenny-GGL-christmas-cactus-purple-1",
    "Jenny-GGL-christmas-cactus-purple-s2",
    "Jenny-GGL-christmas-cactus-red-1",
    "Jenny-GGL-christmas-cactus-red-2",
    "Jenny-GGL-christmas-cactus-sunset-1",
    "Jenny-GGL-christmas-cactus-sunset-2",
    "Jenny-GGL-christmas-cactus-white-2",
    "Jenny-GGL-christmas-cactus-yellow-1",
    "Jenny-GGL-christmas-cactus-yellow-2",
    "Jenny-GGL-christmas-cactus-yellow-2b",
    "Jenny-GGL-christmas-cactus-yellow-3",
    "Jenny-GGL-christmas-varA",
    "Jenny-GGL-christmas-yellow-B3",
    "Jenny-GGL-jasmine-1",
    "Jenny-GGL-jasmine-4",
    "Jenny-GGL-jasmine-b1",
    "Jenny-GGL-jasmine-belle-1",
    "Jenny-GGL-jasmine-belle-indian-2",
    "Jenny-GGL-jasmine-bridal-1",
    "Jenny-GGL-jasmine-confer-1",
    "Jenny-GGL-jasmine-downy",
    "Jenny-GGL-jasmine-frostproof-1",
    "Jenny-GGL-jasmine-night-3",
    "Jenny-GGL-jasmine-olean-1",
    "Jenny-GGL-jasmine-varAA",
    "Jenny-GGL-monstera-1",
    "Jenny-GGL-monstera-2",
    "Jenny-GGL-passion-flower-1",
    "Jenny-GGL-philo-combo-2",
    "Jenny-GGL-philo-red-1",
    "Jenny-GGL-philo-red-2",
    "Zoe-GGL-Pink Guava-4",
}


def _normalize(sku: str) -> str:
    """Strip + collapse whitespace để khớp tolerant với spacing."""
    return " ".join(sku.split()) if sku else ""
