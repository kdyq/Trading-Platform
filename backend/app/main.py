from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware


def _database_url_for_sqlalchemy(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    app.state.database_engine = (
        create_async_engine(
            _database_url_for_sqlalchemy(settings.database_url),
            pool_pre_ping=True,
            connect_args={"server_settings": {"timezone": "UTC"}},
        )
        if settings.database_url
        else None
    )
    app.state.redis = (
        Redis.from_url(settings.redis_url, decode_responses=True) if settings.redis_url else None
    )
    yield

    engine: AsyncEngine | None = app.state.database_engine
    redis: Redis | None = app.state.redis
    if engine is not None:
        await engine.dispose()
    if redis is not None:
        await redis.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

    application = FastAPI(
        title="拾光集市 API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(application)
    application.include_router(api_router, prefix="/api/v1")
    return application


app = create_app()
