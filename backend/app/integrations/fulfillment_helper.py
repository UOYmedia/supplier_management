from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.product import ProductComponent
from app.models.order import OrderFulfillmentItem, OrderLineItem


async def create_fulfillment_items_for_line_item(db: AsyncSession, line_item: OrderLineItem) -> int:
    """Create OrderFulfillmentItem records based on product components. Returns count created."""
    if not line_item.product_id or not line_item.id:
        return 0

    comp_result = await db.execute(
        select(ProductComponent).where(ProductComponent.product_id == line_item.product_id)
    )
    components = comp_result.scalars().all()
    for comp in components:
        db.add(OrderFulfillmentItem(
            order_line_item_id=line_item.id,
            supplier_product_id=comp.supplier_product_id,
            quantity=comp.quantity * line_item.quantity,
        ))
    return len(components)
