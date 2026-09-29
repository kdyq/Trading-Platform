import logging
import re
from time import perf_counter
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Settings
from app.core.exceptions import AppError, error_payload
from app.core.logging import request_id_var
from app.core.rate_limits import RequestLimiter

logger = logging.getLogger("app.request")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied_id = request.headers.get("x-request-id", "")
        request_id = (
            supplied_id if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", supplied_id) else str(uuid4())
        )
        token = request_id_var.set(request_id)
        started = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["x-request-id"] = request_id
            return response
        finally:
            logger.info(
                "request_completed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                },
            )
            request_id_var.reset(token)


def write_limit(path: str, method: str) -> tuple[str, int] | None:
    if method == "GET" and path.startswith("/api/v1/chat/"):
        return "chat-read", 120
    if method == "GET" and path.startswith("/api/v1/reports"):
        return "reports-read", 120
    if method == "GET" and path.startswith(
        (
            "/api/v1/admin",
            "/api/v1/catalog/admin",
            "/api/v1/moderation",
        )
    ):
        return "admin-read", 120
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    if path.startswith("/api/v1/auth/") or path.startswith("/api/v1/account/password"):
        return "identity", 20
    if path.startswith("/api/v1/seller/products") or path.startswith("/api/v1/product-images"):
        return "publish", 40
    if path.startswith("/api/v1/chat/"):
        return "chat", 100
    if path.startswith("/api/v1/reports"):
        return "reports", 20
    if path.startswith("/api/v1/orders"):
        return "orders", 60
    if path.startswith(
        (
            "/api/v1/admin",
            "/api/v1/catalog/admin",
            "/api/v1/credit/adjustments",
            "/api/v1/moderation",
        )
    ):
        return "admin", 120
    return "other-write", 120


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        settings: Settings = request.app.state.settings
        limiter: RequestLimiter | None = getattr(request.app.state, "request_limiter", None)
        if path.startswith("/api/v1/") and not path.startswith("/api/v1/health/") and limiter:
            ip = request.client.host if request.client else "unknown"
            bucket = write_limit(path, request.method)
            try:
                await limiter.check(bucket="ip-global", subject=ip, maximum=300, window_seconds=60)
                if bucket:
                    await limiter.check(
                        bucket=bucket[0],
                        subject=ip,
                        maximum=bucket[1],
                        window_seconds=60,
                        fail_closed=(
                            settings.environment == "production" and bucket[0] == "identity"
                        ),
                    )
            except AppError as exc:
                response: Response = JSONResponse(
                    status_code=exc.status_code,
                    content=error_payload(code=exc.code, message=exc.message),
                )
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if path.startswith("/api/v1/") and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        if settings.environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
