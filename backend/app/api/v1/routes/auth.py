from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.dependencies import get_auth_service, get_settings_from_request
from app.core.config import Settings
from app.core.exceptions import AppError, error_payload
from app.models.identity import User
from app.schemas.auth import (
    AuthResponse,
    EmailVerificationRequest,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    UserSummary,
)
from app.services.auth import AuthContext, AuthResult, AuthService

router = APIRouter()
bearer = HTTPBearer(auto_error=False)
REFRESH_COOKIE = "shiguang_refresh"


def user_summary(user: User) -> UserSummary:
    return UserSummary(
        id=user.id,
        login_email=user.login_email,
        display_name=user.display_name,
        status=user.status.value,
        campus_verification_status="unapplied",
    )


def set_refresh_cookie(response: Response, result: AuthResult, *, settings: Settings) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=result.refresh_token,
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        path="/api/v1/auth",
    )


def require_trusted_origin(request: Request, settings: Settings) -> None:
    origin = request.headers.get("origin")
    trusted_origins = {value.rstrip("/") for value in settings.cors_origins}
    if origin is not None and origin.rstrip("/") not in trusted_origins:
        raise AppError(status_code=403, code="untrusted_origin", message="请求来源不受信任")


def auth_response(result: AuthResult) -> AuthResponse:
    return AuthResponse(
        access_token=result.access_token,
        access_token_expires_at=result.access_token_expires_at,
        user=user_summary(result.user),
    )


async def get_auth_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(status_code=401, code="authentication_required", message="请先登录")
    return await service.authenticate(credentials.credentials)


@router.post("/email-verifications", response_model=MessageResponse, status_code=202)
async def request_email_verification(
    payload: EmailVerificationRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    await service.request_registration_code(str(payload.email))
    return MessageResponse(message="如果该邮箱可以注册，验证码邮件将很快送达")


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> AuthResponse:
    result = await service.register(
        email=str(payload.email),
        code=payload.code,
        display_name=payload.display_name,
        password=payload.password,
        accept_user_agreement=payload.accept_user_agreement,
        accept_privacy_policy=payload.accept_privacy_policy,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    set_refresh_cookie(response, result, settings=settings)
    return auth_response(result)


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> AuthResponse:
    result = await service.login(
        email=str(payload.email),
        password=payload.password,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    set_refresh_cookie(response, result, settings=settings)
    return auth_response(result)


@router.post("/refresh", response_model=AuthResponse)
async def refresh(
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> AuthResponse | Response:
    if refresh_token is None:
        raise AppError(
            status_code=401, code="invalid_refresh_token", message="登录状态无效或已过期"
        )
    require_trusted_origin(request, settings)
    try:
        result = await service.refresh(refresh_token)
    except AppError as exc:
        # Returning the handled error lets the request transaction persist family revocation
        # when a replayed refresh token is detected.
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(code=exc.code, message=exc.message),
        )
    set_refresh_cookie(response, result, settings=settings)
    return auth_response(result)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> MessageResponse:
    require_trusted_origin(request, settings)
    if refresh_token is not None:
        await service.logout(refresh_token)
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    return MessageResponse(message="已退出当前设备")


@router.post("/logout-all", response_model=MessageResponse)
async def logout_all(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AuthService, Depends(get_auth_service)],
    response: Response,
) -> MessageResponse:
    await service.logout_all(context.user.id)
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    return MessageResponse(message="已退出全部设备")


@router.get("/me", response_model=UserSummary)
async def me(context: Annotated[AuthContext, Depends(get_auth_context)]) -> UserSummary:
    return user_summary(context.user)
