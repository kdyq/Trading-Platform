from fastapi import APIRouter

from app.api.v1.routes.account import router as account_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.campus import router as campus_router
from app.api.v1.routes.catalog import router as catalog_router
from app.api.v1.routes.chat import router as chat_router
from app.api.v1.routes.credit import router as credit_router
from app.api.v1.routes.favorites import router as favorites_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.market import router as market_router
from app.api.v1.routes.moderation import router as moderation_router
from app.api.v1.routes.orders import router as orders_router
from app.api.v1.routes.product_images import router as product_images_router
from app.api.v1.routes.reports import router as reports_router
from app.api.v1.routes.seller_products import router as seller_products_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(favorites_router, prefix="/favorites", tags=["favorites"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(account_router, prefix="/account", tags=["account"])
api_router.include_router(campus_router, prefix="/campus", tags=["campus"])
api_router.include_router(catalog_router, prefix="/catalog", tags=["catalog"])
api_router.include_router(chat_router, prefix="/chat", tags=["chat"])
api_router.include_router(credit_router, prefix="/credit", tags=["credit"])
api_router.include_router(market_router, prefix="/market", tags=["market"])
api_router.include_router(moderation_router, prefix="/moderation", tags=["moderation"])
api_router.include_router(orders_router, prefix="/orders", tags=["orders"])
api_router.include_router(product_images_router, prefix="/product-images", tags=["product-images"])
api_router.include_router(reports_router, prefix="/reports", tags=["reports"])
api_router.include_router(
    seller_products_router, prefix="/seller/products", tags=["seller-products"]
)
