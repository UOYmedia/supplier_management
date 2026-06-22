# READ-ONLY DIAGNOSTIC SCRIPT - NO DATA MODIFICATION
"""
Chẩn đoán mức độ "sạch" của database (CHỈ ĐỌC).

An toàn:
- Chỉ dùng SQLAlchemy select() / text() với câu lệnh SELECT/SHOW.
- KHÔNG update()/delete()/insert(), KHÔNG session.add()/delete(),
  KHÔNG commit(), KHÔNG raw SQL ghi dữ liệu.
- Tự mở engine với asyncpg `default_transaction_read_only=on` nên mọi
  transaction đều read-only ở tầng database (ghi sẽ bị chính DB từ chối).
- In tên database đang kết nối để user xác nhận trước khi chạy.
- Có thể huỷ an toàn bằng Ctrl+C bất kỳ lúc nào.

Cách chạy:
    DATABASE_URL=postgresql+asyncpg://... python backend/scripts/diagnose_data_health.py
    (thêm --yes để bỏ qua bước xác nhận)
"""
import argparse
import asyncio
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

# Cho phép `import app...` khi chạy trực tiếp file này.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.supplier import Supplier, SupplierProduct
from app.models.product import Product, ProductComponent
from app.models.marketplace import MarketplaceListing
from app.models.order import Order, OrderLineItem, OrderFulfillmentItem

PENDING_STATUSES = ["unfulfilled", "pending"]


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
def hr(title: str) -> None:
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)


def pct(n: int, d: int) -> str:
    return f"{(100.0 * n / d):.1f}%" if d else "0.0%"


def mask_url(url: str) -> str:
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:***@", url)


def make_engine(url: str):
    connect_args: dict = {}
    if "asyncpg" in url:
        # DB-enforced read-only: bất kỳ lệnh ghi nào cũng bị từ chối.
        connect_args["server_settings"] = {"default_transaction_read_only": "on"}
    return create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)


# --------------------------------------------------------------------------- #
# Phần 1: Định danh                                                            #
# --------------------------------------------------------------------------- #
async def part1(s: AsyncSession) -> None:
    hr("PHẦN 1: ĐỊNH DANH")

    total_sup = (await s.execute(select(func.count(Supplier.id)))).scalar()
    print(f"Tổng Supplier: {total_sup}")
    rows = (await s.execute(
        select(Supplier.id, Supplier.name, Supplier.username, Supplier.hashed_password)
        .order_by(Supplier.id)
    )).all()
    for sid, name, username, hpw in rows:
        login = "yes" if (username and hpw) else "no"
        print(f"  #{sid:<4} {(name or '—'):<22} username={(username or '—'):<14} login={login}")

    total_sp = (await s.execute(select(func.count(SupplierProduct.id)))).scalar()
    print(f"\nTổng SupplierProduct: {total_sp}")
    per = (await s.execute(
        select(Supplier.name, func.count(SupplierProduct.id))
        .select_from(SupplierProduct)
        .join(Supplier, Supplier.id == SupplierProduct.supplier_id)
        .group_by(Supplier.name)
        .order_by(func.count(SupplierProduct.id).desc())
    )).all()
    print("  Theo supplier:")
    for name, c in per:
        print(f"    {(name or '—'):<22} {c}")
    miss_sku = (await s.execute(select(func.count(SupplierProduct.id)).where(
        or_(SupplierProduct.sku.is_(None), func.trim(SupplierProduct.sku) == "")))).scalar()
    miss_name = (await s.execute(select(func.count(SupplierProduct.id)).where(
        or_(SupplierProduct.name.is_(None), func.trim(SupplierProduct.name) == "")))).scalar()
    miss_stock = (await s.execute(select(func.count(SupplierProduct.id)).where(
        SupplierProduct.stock_quantity.is_(None)))).scalar()
    print(f"  Thiếu sku: {miss_sku}  |  thiếu name: {miss_name}  |  stock NULL: {miss_stock}")

    total_l = (await s.execute(select(func.count(MarketplaceListing.id)))).scalar()
    with_pid = (await s.execute(select(func.count(MarketplaceListing.id)).where(
        MarketplaceListing.product_id.isnot(None)))).scalar()
    with_msku = (await s.execute(select(func.count(MarketplaceListing.id)).where(
        and_(MarketplaceListing.marketplace_sku.isnot(None),
             func.trim(MarketplaceListing.marketplace_sku) != "")))).scalar()
    print(f"\nMarketplaceListing: tổng {total_l}")
    print(f"  có product_id: {with_pid} ({pct(with_pid, total_l)})  |  không: {total_l - with_pid}")
    print(f"  có marketplace_sku: {with_msku} ({pct(with_msku, total_l)})  |  không: {total_l - with_msku}")
    samples = (await s.execute(
        select(MarketplaceListing.marketplace_sku)
        .where(MarketplaceListing.marketplace_sku.isnot(None),
               func.trim(MarketplaceListing.marketplace_sku) != "")
        .limit(10)
    )).scalars().all()
    print("  Sample 10 marketplace_sku (xem cấu trúc):")
    for sk in samples:
        print(f"    {sk}")


# --------------------------------------------------------------------------- #
# Phần 2: Liên kết                                                             #
# --------------------------------------------------------------------------- #
async def part2(s: AsyncSession) -> None:
    hr("PHẦN 2: LIÊN KẾT")

    total_pc = (await s.execute(select(func.count(ProductComponent.id)))).scalar()
    total_prod = (await s.execute(select(func.count(Product.id)))).scalar()
    print(f"Tổng ProductComponent: {total_pc}  |  Tổng Product: {total_prod}")

    comp_pids = select(ProductComponent.product_id).distinct()

    orphan_count = (await s.execute(
        select(func.count(Product.id)).where(~Product.id.in_(comp_pids)))).scalar()
    orphan_sample = (await s.execute(
        select(Product.id, Product.sku, Product.name)
        .where(~Product.id.in_(comp_pids)).limit(5))).all()
    print(f"\nProduct mồ côi (không có ProductComponent nào): {orphan_count}")
    for pid, sku, name in orphan_sample:
        print(f"  #{pid}  {sku}  — {name}")

    bad_listing_count = (await s.execute(
        select(func.count(MarketplaceListing.id)).where(
            MarketplaceListing.product_id.isnot(None),
            ~MarketplaceListing.product_id.in_(comp_pids)))).scalar()
    bad_listing_sample = (await s.execute(
        select(MarketplaceListing.id, MarketplaceListing.marketplace_sku, MarketplaceListing.product_id)
        .where(MarketplaceListing.product_id.isnot(None),
               ~MarketplaceListing.product_id.in_(comp_pids)).limit(5))).all()
    print(f"\nListing có product_id nhưng Product KHÔNG có component: {bad_listing_count}")
    for lid, msku, pid in bad_listing_sample:
        print(f"  listing#{lid}  sku={msku}  product#{pid}")

    counts = (await s.execute(
        select(ProductComponent.product_id, func.count(ProductComponent.id))
        .group_by(ProductComponent.product_id))).all()
    b0 = total_prod - len(counts)
    b1 = b23 = b4 = 0
    for _, c in counts:
        if c == 1:
            b1 += 1
        elif c <= 3:
            b23 += 1
        else:
            b4 += 1
    print(f"\nPhân bố Product theo số component:")
    print(f"  0 component : {b0}")
    print(f"  1 component : {b1}")
    print(f"  2-3         : {b23}")
    print(f"  4+          : {b4}")


# --------------------------------------------------------------------------- #
# Phần 3: Giao dịch (Orders 30 ngày)                                           #
# --------------------------------------------------------------------------- #
async def part3(s: AsyncSession) -> None:
    hr("PHẦN 3: GIAO DỊCH (ORDERS 30 NGÀY)")
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    def base():
        return (select(func.count(OrderLineItem.id))
                .select_from(OrderLineItem)
                .join(Order, Order.id == OrderLineItem.order_id)
                .where(Order.ordered_at >= cutoff))

    total = (await s.execute(base())).scalar()
    print(f"Tổng OrderLineItem 30 ngày: {total}")
    if not total:
        print("  (Không có line item nào trong 30 ngày.)")
        return

    comp_pids = select(ProductComponent.product_id).distinct()
    no_product = (await s.execute(base().where(OrderLineItem.product_id.is_(None)))).scalar()
    deductible = (await s.execute(base().where(OrderLineItem.product_id.in_(comp_pids)))).scalar()
    has_product = total - no_product
    no_component = has_product - deductible

    print("Phân bố theo tình trạng nối:")
    print(f"  Trừ kho ĐƯỢC (có product_id + Product có component) : {deductible:>6} ({pct(deductible, total)})")
    print(f"  KHÔNG trừ kho — có product_id nhưng thiếu component  : {no_component:>6} ({pct(no_component, total)})")
    print(f"  KHÔNG trừ kho — product_id NULL                      : {no_product:>6} ({pct(no_product, total)})")

    asin_null = (await s.execute(base().where(OrderLineItem.asin.is_(None)))).scalar()
    sku_null = (await s.execute(base().where(
        or_(OrderLineItem.sku.is_(None), func.trim(OrderLineItem.sku) == "")))).scalar()
    print(f"\n  Line item có asin NULL: {asin_null} ({pct(asin_null, total)})")
    print(f"  Line item có sku NULL/rỗng: {sku_null} ({pct(sku_null, total)})")

    top = (await s.execute(
        select(OrderLineItem.sku, func.count(OrderLineItem.id).label("c"))
        .select_from(OrderLineItem)
        .join(Order, Order.id == OrderLineItem.order_id)
        .where(Order.ordered_at >= cutoff)
        .group_by(OrderLineItem.sku)
        .order_by(func.count(OrderLineItem.id).desc())
        .limit(10))).all()
    print("\n  Top 10 SKU xuất hiện nhiều nhất (số line item):")
    for sk, c in top:
        print(f"    {c:>5}  {sk if sk else '(null)'}")


# --------------------------------------------------------------------------- #
# Phần 4: Stock health (chỉ JOE)                                               #
# --------------------------------------------------------------------------- #
async def part4(s: AsyncSession) -> None:
    hr("PHẦN 4: STOCK HEALTH (JOE)")

    joe = (await s.execute(select(Supplier).where(Supplier.username == "Joe"))).scalar_one_or_none()
    if joe is None:
        joe = (await s.execute(
            select(Supplier).where(func.lower(Supplier.name) == "joe"))).scalar_one_or_none()
    if joe is None:
        print("  Không tìm thấy supplier JOE (username='Joe' hoặc name='JOE'). Bỏ qua phần 4.")
        return
    print(f"  JOE = #{joe.id}  {joe.name}  (username={joe.username})")

    neg_count = (await s.execute(select(func.count(SupplierProduct.id)).where(
        SupplierProduct.supplier_id == joe.id, SupplierProduct.stock_quantity < 0))).scalar()
    print(f"\n  Stock ÂM: {neg_count}")
    worst = (await s.execute(
        select(SupplierProduct.sku, SupplierProduct.name, SupplierProduct.stock_quantity)
        .where(SupplierProduct.supplier_id == joe.id, SupplierProduct.stock_quantity < 0)
        .order_by(SupplierProduct.stock_quantity.asc()).limit(5))).all()
    for sku, name, st in worst:
        print(f"    {st:>6}  {sku}  {name}")

    zero = (await s.execute(select(func.count(SupplierProduct.id)).where(
        SupplierProduct.supplier_id == joe.id, SupplierProduct.stock_quantity == 0))).scalar()
    print(f"\n  Stock = 0: {zero}")

    sps = (await s.execute(
        select(SupplierProduct.id, SupplierProduct.sku, SupplierProduct.name, SupplierProduct.stock_quantity)
        .where(SupplierProduct.supplier_id == joe.id))).all()
    pend_rows = (await s.execute(
        select(OrderFulfillmentItem.supplier_product_id, func.sum(OrderFulfillmentItem.quantity))
        .where(OrderFulfillmentItem.fulfill_status.in_(PENDING_STATUSES))
        .group_by(OrderFulfillmentItem.supplier_product_id))).all()
    pending = {spid: int(q or 0) for spid, q in pend_rows}

    ranked = []
    for spid, sku, name, st in sps:
        st = st or 0
        pq = pending.get(spid, 0)
        ranked.append((st - pq, st, pq, sku, name))
    ranked.sort(key=lambda r: r[0])
    print("\n  Top 10 cây JOE theo (stock - pending) THẤP nhất:")
    for avail, st, pq, sku, name in ranked[:10]:
        print(f"    avail={avail:>6}  (stock={st}, pending={pq})  {sku}  {name}")


# --------------------------------------------------------------------------- #
# Phần 5: SKU pattern analysis (30 ngày)                                       #
# --------------------------------------------------------------------------- #
async def part5(s: AsyncSession) -> None:
    hr("PHẦN 5: SKU PATTERN (30 NGÀY)")
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    skus = (await s.execute(
        select(OrderLineItem.sku).distinct()
        .select_from(OrderLineItem)
        .join(Order, Order.id == OrderLineItem.order_id)
        .where(Order.ordered_at >= cutoff,
               OrderLineItem.sku.isnot(None),
               func.trim(OrderLineItem.sku) != ""))).scalars().all()
    print(f"Số SKU phân biệt (30 ngày): {len(skus)}")
    if not skus:
        return

    part_counts: Counter = Counter()
    pos3: Counter = Counter()
    for sk in skus:
        parts = sk.split("-")
        n = len(parts)
        part_counts["6+" if n >= 6 else str(n)] += 1
        if n >= 3:
            pos3[parts[2].strip()] += 1

    print("  Phân bố số phần (tách theo '-'):")
    for k in ["2", "3", "4", "5", "6+"]:
        print(f"    {k:>2} phần: {part_counts.get(k, 0)}")
    lt3 = sum(v for k, v in part_counts.items() if k in ("2",))  # < 3 phần (chỉ 2)
    # Lưu ý: các SKU có 1 phần (không có '-') rơi vào key '1' nếu có.
    if part_counts.get("1"):
        print(f"     1 phần: {part_counts.get('1')}")

    print("\n  Top 20 token ở VỊ TRÍ 3:")
    for tok, c in pos3.most_common(20):
        print(f"    {c:>4}  {tok if tok else '(rỗng)'}")

    known = set((await s.execute(
        select(Supplier.username).where(Supplier.username.isnot(None)))).scalars().all())
    match = sum(c for tok, c in pos3.items() if tok in known)
    nomatch = sum(c for tok, c in pos3.items() if tok not in known)
    without_pos3 = len(skus) - sum(pos3.values())
    print(f"\n  SKU có vị trí 3 KHỚP supplier.username : {match}")
    print(f"  SKU có vị trí 3 KHÔNG khớp supplier nào : {nomatch}")
    print(f"  SKU < 3 phần (không có vị trí 3)        : {without_pos3}")


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #
async def main(assume_yes: bool) -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("❌ DATABASE_URL chưa được set. Hãy export DATABASE_URL rồi chạy lại.")
        return 1

    engine = make_engine(url)
    try:
        async with AsyncSession(engine) as s:
            # Định danh database để user xác nhận.
            try:
                dbname = (await s.execute(text("SELECT current_database()"))).scalar()
                dbuser = (await s.execute(text("SELECT current_user"))).scalar()
            except Exception:
                dbname, dbuser = "(unknown)", "(unknown)"
            try:
                ro = (await s.execute(text("SHOW transaction_read_only"))).scalar()
            except Exception:
                ro = "(n/a)"

            print(f"Connected to: {dbname}")
            print(f"  user = {dbuser}   transaction_read_only = {ro}")
            print(f"  url  = {mask_url(url)}")

            if not assume_yes:
                if sys.stdin.isatty():
                    ans = input("\n⚠️  Đúng database cần chẩn đoán? Tiếp tục? [y/N] ").strip().lower()
                    if ans not in ("y", "yes"):
                        print("Đã huỷ — không truy vấn gì thêm.")
                        return 0
                else:
                    print("\n(stdin không phải tty — tự tiếp tục. Dùng --yes để bỏ qua bước này.)")

            await part1(s)
            await part2(s)
            await part3(s)
            await part4(s)
            await part5(s)

        print("\n✅ Hoàn tất chẩn đoán (chỉ đọc, không thay đổi dữ liệu).")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Read-only DB data-health diagnostic.")
    parser.add_argument("-y", "--yes", action="store_true", help="Bỏ qua bước xác nhận database.")
    args = parser.parse_args()
    try:
        sys.exit(asyncio.run(main(args.yes)))
    except KeyboardInterrupt:
        print("\nĐã huỷ (Ctrl+C). Không có thay đổi nào với dữ liệu.")
        sys.exit(130)
