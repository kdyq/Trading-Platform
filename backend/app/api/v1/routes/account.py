import logging
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, Request, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dependencies import get_account_service
from app.api.v1.routes.auth import REFRESH_COOKIE, get_auth_context
from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.security import PasswordManager, TokenManager
from app.db.session import transaction_scope
from app.repositories.identity import SqlAlchemyIdentityRepository
from app.schemas.account import (
    PasswordChangeRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    ProfileResponse,
    ProfileUpdateRequest,
    SessionResponse,
)
from app.schemas.auth import MessageResponse
from app.services.account import AccountService
from app.services.auth import AuthContext
from app.services.email_verification import RedisVerificationCodeStore
from app.services.mailer import QQVerificationMailer

router = APIRouter()
logger = logging.getLogger(__name__)


async def deliver_password_reset_with_service(
    service: AccountService, email: str, ip_address: str | None
) -> None:
    try:
        await service.request_password_reset(email, ip_address=ip_address)
    except AppError as exc:
        logger.warning("password_reset_request_rejected", extra={"error_code": exc.code})


async def deliver_password_reset(app: FastAPI, email: str, ip_address: str | None) -> None:
    settings = cast(Settings, app.state.settings)
    session_factory = cast(async_sessionmaker[AsyncSession] | None, app.state.session_factory)
    redis = cast(Redis | None, app.state.redis)
    if (
        session_factory is None
        or redis is None
        or settings.auth_secret_key is None
        or settings.auth_verification_secret is None
        or settings.qq_smtp_username is None
        or settings.qq_smtp_auth_code is None
    ):
        logger.warning("password_reset_delivery_unavailable")
        return
    try:
        async with transaction_scope(session_factory) as session:
            service = AccountService(
                repository=SqlAlchemyIdentityRepository(session),
                request_limiter=RedisVerificationCodeStore(
                    redis, settings.auth_verification_secret.get_secret_value()
                ),
                mailer=QQVerificationMailer(
                    username=settings.qq_smtp_username,
                    auth_code=settings.qq_smtp_auth_code.get_secret_value(),
                    from_name=settings.qq_smtp_from_name,
                ),
                password_manager=PasswordManager(),
                token_manager=TokenManager(
                    settings.auth_secret_key.get_secret_value(),
                    access_minutes=settings.access_token_minutes,
                    refresh_days=settings.refresh_token_days,
                ),
                settings=settings,
            )
            await service.request_password_reset(email, ip_address=ip_address)
    except AppError as exc:
        logger.warning("password_reset_request_rejected", extra={"error_code": exc.code})
    except Exception:
        logger.exception("password_reset_background_failure")


async def profile_response(context: AuthContext, service: AccountService) -> ProfileResponse:
    active_products, favorites, orders, credit_events = await service.profile_counts(
        context.user.id
    )
    return ProfileResponse(
        id=context.user.id,
        login_email=context.user.login_email,
        display_name=context.user.display_name,
        has_avatar=context.user.avatar_key is not None,
        campus_verification_status=(
            context.account_verification_status or context.campus_verification_status
        ).value,
        credit_status="recorded" if credit_events else "no_record",
        active_products=active_products,
        favorites=favorites,
        orders=orders,
    )


@router.post("/password-reset-requests", response_model=MessageResponse, status_code=202)
async def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    service: Annotated[AccountService, Depends(get_account_service)],
) -> MessageResponse:
    ip_address = request.client.host if request.client else None
    if request.app.state.session_factory is None:
        # Dependency-overridden tests do not own a database session factory.
        background_tasks.add_task(
            deliver_password_reset_with_service, service, str(payload.email), ip_address
        )
    else:
        background_tasks.add_task(
            deliver_password_reset, request.app, str(payload.email), ip_address
        )
    return MessageResponse(message="如果该账户存在，重置邮件将很快送达")


@router.post("/password-resets", response_model=MessageResponse)
async def reset_password(
    payload: PasswordResetConfirm,
    service: Annotated[AccountService, Depends(get_account_service)],
) -> MessageResponse:
    await service.reset_password(token=payload.token, new_password=payload.new_password)
    return MessageResponse(message="密码已重置，请重新登录")


@router.post("/password-change", response_model=MessageResponse)
async def change_password(
    payload: PasswordChangeRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AccountService, Depends(get_account_service)],
) -> MessageResponse:
    await service.change_password(
        context=context,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    return MessageResponse(message="密码已更新，其他设备已退出")


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AccountService, Depends(get_account_service)],
) -> ProfileResponse:
    return await profile_response(context, service)


@router.patch("/profile", response_model=ProfileResponse)
async def update_profile(
    payload: ProfileUpdateRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AccountService, Depends(get_account_service)],
) -> ProfileResponse:
    await service.update_profile(user=context.user, display_name=payload.display_name)
    return await profile_response(context, service)


@router.delete("/profile", response_model=MessageResponse)
async def close_profile(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AccountService, Depends(get_account_service)],
    response: Response,
) -> MessageResponse:
    await service.close_account(context)
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    return MessageResponse(message="账号已注销")


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AccountService, Depends(get_account_service)],
) -> list[SessionResponse]:
    sessions = await service.sessions(context.user.id)
    return [
        SessionResponse(
            id=session.id,
            user_agent=session.user_agent,
            ip_address=session.ip_address,
            created_at=session.created_at,
            last_used_at=session.last_used_at,
            expires_at=session.expires_at,
            is_current=session.id == context.session.id,
        )
        for session in sessions
    ]


@router.delete("/sessions/{session_id}", response_model=MessageResponse)
async def revoke_session(
    session_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AccountService, Depends(get_account_service)],
) -> MessageResponse:
    await service.revoke_session(context=context, session_id=session_id)
    return MessageResponse(message="该设备已退出")
