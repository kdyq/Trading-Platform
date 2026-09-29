import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from uuid import UUID

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware, SecurityMiddleware
from app.core.rate_limits import RequestLimiter
from app.db.session import create_database_engine, create_session_factory
from app.models.identity import User, UserSession, UserStatus
from app.repositories.identity import session_is_active
from app.services.notifications import NotificationDeliveryCoordinator
from app.services.realtime import (
    InMemoryChatMessageLimiter,
    RealtimeHub,
    RedisChatMessageLimiter,
    RedisRealtimePublisher,
)
from app.workers.order_expiration import OrderExpirationCoordinator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    app.state.database_engine = (
        create_database_engine(settings.database_url, schema=os.getenv("DATABASE_SCHEMA"))
        if settings.database_url
        else None
    )
    app.state.session_factory = (
        create_session_factory(app.state.database_engine)
        if app.state.database_engine is not None
        else None
    )
    app.state.redis = (
        Redis.from_url(settings.redis_url, decode_responses=True) if settings.redis_url else None
    )
    app.state.request_limiter = RequestLimiter(app.state.redis)

    async def active_realtime_session(user_id: UUID, session_id: UUID) -> bool:
        factory = app.state.session_factory
        if factory is None:
            return False
        async with factory() as session:
            row = (
                await session.execute(
                    select(User, UserSession)
                    .join(UserSession, UserSession.user_id == User.id)
                    .where(User.id == user_id, UserSession.id == session_id)
                )
            ).one_or_none()
            return bool(
                row
                and row[0].status == UserStatus.ACTIVE
                and row[0].deleted_at is None
                and session_is_active(row[1])
            )

    app.state.realtime_hub = RealtimeHub(
        active_realtime_session if app.state.session_factory is not None else None
    )
    app.state.realtime_publisher = RedisRealtimePublisher(app.state.realtime_hub, app.state.redis)
    app.state.chat_message_limiter = RedisChatMessageLimiter(
        app.state.redis, InMemoryChatMessageLimiter()
    )
    app.state.notification_delivery = (
        NotificationDeliveryCoordinator(app.state.session_factory, app.state.realtime_publisher)
        if app.state.session_factory is not None
        else None
    )
    app.state.order_expiration = (
        OrderExpirationCoordinator(app.state.session_factory)
        if app.state.session_factory is not None
        else None
    )
    listener_task = (
        asyncio.create_task(app.state.realtime_publisher.listen())
        if app.state.redis is not None
        else None
    )
    notification_retry_task = (
        asyncio.create_task(app.state.notification_delivery.run())
        if app.state.notification_delivery is not None
        else None
    )
    order_expiration_task = (
        asyncio.create_task(app.state.order_expiration.run())
        if app.state.order_expiration is not None
        else None
    )
    yield

    engine: AsyncEngine | None = app.state.database_engine
    redis: Redis | None = app.state.redis
    if listener_task is not None:
        listener_task.cancel()
        with suppress(asyncio.CancelledError):
            await listener_task
    if notification_retry_task is not None:
        notification_retry_task.cancel()
        with suppress(asyncio.CancelledError):
            await notification_retry_task
    if order_expiration_task is not None:
        order_expiration_task.cancel()
        with suppress(asyncio.CancelledError):
            await order_expiration_task
    app.state.session_factory = None
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
    application.add_middleware(SecurityMiddleware)
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
