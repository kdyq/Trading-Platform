from functools import lru_cache
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.security import PasswordManager, TokenManager
from app.db.session import get_database_session
from app.repositories.campus import CampusRepository, SqlAlchemyCampusRepository
from app.repositories.catalog import CatalogRepository, SqlAlchemyCatalogRepository
from app.repositories.chat import ChatRepository, SqlAlchemyChatRepository
from app.repositories.identity import (
    AccountRepository,
    IdentityRepository,
    SqlAlchemyIdentityRepository,
)
from app.repositories.market import MarketRepository, SqlAlchemyMarketRepository
from app.repositories.product_images import (
    ProductImageUploadRepository,
    SqlAlchemyProductImageUploadRepository,
)
from app.repositories.seller_products import (
    SellerProductRepository,
    SqlAlchemySellerProductRepository,
)
from app.services.account import AccountService
from app.services.auth import AuthService
from app.services.campus import CampusService
from app.services.catalog import CatalogCache, CatalogService
from app.services.chat import ChatService
from app.services.email_verification import (
    RedisVerificationCodeStore,
    UnavailableVerificationCodeStore,
    VerificationCodeStore,
)
from app.services.mailer import (
    AccountMailer,
    CampusMailer,
    QQVerificationMailer,
    UnavailableAccountMailer,
    UnavailableCampusMailer,
    UnavailableVerificationMailer,
    VerificationMailer,
)
from app.services.market import MarketService
from app.services.notifications import NotificationDeliveryCoordinator
from app.services.private_storage import PrivateAppealStorage
from app.services.product_images import ProductImageProcessor, ProductImageUploadService
from app.services.product_storage import LocalObjectStorage
from app.services.realtime import (
    ChatMessageLimiter,
    RealtimeHub,
    RealtimePublisher,
    RedisWebSocketTicketStore,
    UnavailableWebSocketTicketStore,
    WebSocketTicketStore,
)
from app.services.seller_products import SellerProductService

catalog_cache = CatalogCache()


def get_settings_from_request(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_identity_repository(
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> IdentityRepository:
    return SqlAlchemyIdentityRepository(session)


def get_account_repository(
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> AccountRepository:
    return SqlAlchemyIdentityRepository(session)


def get_campus_repository(
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> CampusRepository:
    return SqlAlchemyCampusRepository(session)


def get_market_repository(
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> MarketRepository:
    return SqlAlchemyMarketRepository(session)


def get_catalog_repository(
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> CatalogRepository:
    return SqlAlchemyCatalogRepository(session)


def get_chat_repository(
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> ChatRepository:
    return SqlAlchemyChatRepository(session)


def get_product_image_upload_repository(
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> ProductImageUploadRepository:
    return SqlAlchemyProductImageUploadRepository(session)


def get_seller_product_repository(
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> SellerProductRepository:
    return SqlAlchemySellerProductRepository(session)


@lru_cache
def get_password_manager() -> PasswordManager:
    return PasswordManager()


def get_token_manager(
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> TokenManager:
    if settings.auth_secret_key is None:
        raise AppError(
            status_code=503, code="authentication_unavailable", message="账户服务尚未配置"
        )
    try:
        return TokenManager(
            settings.auth_secret_key.get_secret_value(),
            access_minutes=settings.access_token_minutes,
            refresh_days=settings.refresh_token_days,
        )
    except ValueError as exc:
        raise AppError(
            status_code=503, code="authentication_unavailable", message="账户服务配置无效"
        ) from exc


def get_verification_store(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> VerificationCodeStore:
    if request.app.state.redis is None or settings.auth_verification_secret is None:
        return UnavailableVerificationCodeStore()
    return RedisVerificationCodeStore(
        request.app.state.redis, settings.auth_verification_secret.get_secret_value()
    )


def get_verification_mailer(
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> VerificationMailer:
    if settings.qq_smtp_username is None or settings.qq_smtp_auth_code is None:
        return UnavailableVerificationMailer()
    return QQVerificationMailer(
        username=settings.qq_smtp_username,
        auth_code=settings.qq_smtp_auth_code.get_secret_value(),
        from_name=settings.qq_smtp_from_name,
    )


def get_account_mailer(
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> AccountMailer:
    if settings.qq_smtp_username is None or settings.qq_smtp_auth_code is None:
        return UnavailableAccountMailer()
    return QQVerificationMailer(
        username=settings.qq_smtp_username,
        auth_code=settings.qq_smtp_auth_code.get_secret_value(),
        from_name=settings.qq_smtp_from_name,
    )


def get_campus_mailer(
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> CampusMailer:
    if settings.qq_smtp_username is None or settings.qq_smtp_auth_code is None:
        return UnavailableCampusMailer()
    return QQVerificationMailer(
        username=settings.qq_smtp_username,
        auth_code=settings.qq_smtp_auth_code.get_secret_value(),
        from_name=settings.qq_smtp_from_name,
    )


def get_auth_service(
    repository: Annotated[IdentityRepository, Depends(get_identity_repository)],
    verification_store: Annotated[VerificationCodeStore, Depends(get_verification_store)],
    mailer: Annotated[VerificationMailer, Depends(get_verification_mailer)],
    password_manager: Annotated[PasswordManager, Depends(get_password_manager)],
    token_manager: Annotated[TokenManager, Depends(get_token_manager)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> AuthService:
    return AuthService(
        repository=repository,
        verification_store=verification_store,
        mailer=mailer,
        password_manager=password_manager,
        token_manager=token_manager,
        settings=settings,
    )


def get_account_service(
    repository: Annotated[AccountRepository, Depends(get_account_repository)],
    request_limiter: Annotated[VerificationCodeStore, Depends(get_verification_store)],
    mailer: Annotated[AccountMailer, Depends(get_account_mailer)],
    password_manager: Annotated[PasswordManager, Depends(get_password_manager)],
    token_manager: Annotated[TokenManager, Depends(get_token_manager)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> AccountService:
    return AccountService(
        repository=repository,
        request_limiter=request_limiter,
        mailer=mailer,
        password_manager=password_manager,
        token_manager=token_manager,
        settings=settings,
    )


def get_campus_service(
    repository: Annotated[CampusRepository, Depends(get_campus_repository)],
    verification_store: Annotated[VerificationCodeStore, Depends(get_verification_store)],
    mailer: Annotated[CampusMailer, Depends(get_campus_mailer)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> CampusService:
    return CampusService(
        repository=repository,
        verification_store=verification_store,
        mailer=mailer,
        storage=PrivateAppealStorage(
            settings.resolved_private_storage_root,
            max_bytes=settings.campus_appeal_max_bytes,
        ),
        settings=settings,
    )


def get_market_service(
    repository: Annotated[MarketRepository, Depends(get_market_repository)],
) -> MarketService:
    return MarketService(repository)


def get_catalog_service(
    repository: Annotated[CatalogRepository, Depends(get_catalog_repository)],
) -> CatalogService:
    return CatalogService(repository, catalog_cache)


def get_realtime_publisher(request: Request) -> RealtimePublisher:
    return cast(RealtimePublisher, request.app.state.realtime_publisher)


def get_realtime_hub(request: Request) -> RealtimeHub:
    return cast(RealtimeHub, request.app.state.realtime_hub)


def get_chat_message_limiter(request: Request) -> ChatMessageLimiter:
    return cast(ChatMessageLimiter, request.app.state.chat_message_limiter)


def get_websocket_ticket_store(request: Request) -> WebSocketTicketStore:
    if request.app.state.redis is None:
        return UnavailableWebSocketTicketStore()
    return RedisWebSocketTicketStore(request.app.state.redis)


def get_chat_service(
    request: Request,
    repository: Annotated[ChatRepository, Depends(get_chat_repository)],
    publisher: Annotated[RealtimePublisher, Depends(get_realtime_publisher)],
    limiter: Annotated[ChatMessageLimiter, Depends(get_chat_message_limiter)],
) -> ChatService:
    delivery = cast(NotificationDeliveryCoordinator | None, request.app.state.notification_delivery)
    return ChatService(repository, publisher, limiter, delivery)


def get_product_image_upload_service(
    repository: Annotated[
        ProductImageUploadRepository, Depends(get_product_image_upload_repository)
    ],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> ProductImageUploadService:
    return ProductImageUploadService(
        repository=repository,
        storage=LocalObjectStorage(settings.resolved_public_product_storage_root),
        processor=ProductImageProcessor(
            max_bytes=settings.product_image_max_bytes,
            max_pixels=settings.product_image_max_pixels,
        ),
        max_uploads=settings.product_image_max_uploads,
        upload_hours=settings.product_image_upload_hours,
    )


def get_seller_product_service(
    repository: Annotated[SellerProductRepository, Depends(get_seller_product_repository)],
    uploads: Annotated[ProductImageUploadRepository, Depends(get_product_image_upload_repository)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> SellerProductService:
    return SellerProductService(
        repository=repository,
        uploads=uploads,
        storage=LocalObjectStorage(settings.resolved_public_product_storage_root),
    )
