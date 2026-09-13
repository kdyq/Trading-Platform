from fastapi import APIRouter

from app.api.v1.routes.account import router as account_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.campus import router as campus_router
from app.api.v1.routes.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(account_router, prefix="/account", tags=["account"])
api_router.include_router(campus_router, prefix="/campus", tags=["campus"])
