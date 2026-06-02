from fastapi import APIRouter
from app.api.v1 import products, suppliers, orders, marketplace, reports
from app.api.v1 import shopify_oauth, portal, auth, users

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(products.router)
api_router.include_router(suppliers.router)
api_router.include_router(orders.router)
api_router.include_router(marketplace.router)
api_router.include_router(reports.router)
api_router.include_router(shopify_oauth.router)
api_router.include_router(portal.router)
