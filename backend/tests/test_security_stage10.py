from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.middleware import write_limit
from app.core.rate_limits import RequestLimiter
from app.main import create_app


class CountingRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def eval(self, _script: str, _keys: int, key: str, _ttl: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


class BrokenRedis:
    async def eval(self, *_args: Any) -> int:
        raise ConnectionError("down")


def test_write_routes_use_their_intended_rate_buckets() -> None:
    assert write_limit("/api/v1/seller/products", "POST") == ("publish", 40)
    assert write_limit("/api/v1/product-images/uploads", "POST") == ("publish", 40)
    assert write_limit("/api/v1/catalog/admin/categories", "POST") == ("admin", 120)
    assert write_limit("/api/v1/credit/adjustments", "POST") == ("admin", 120)
    assert write_limit("/api/v1/moderation/reports/one", "POST") == ("admin", 120)
    assert write_limit("/api/v1/admin/users", "GET") == ("admin-read", 120)
    assert write_limit("/api/v1/admin/audit", "GET") == ("admin-read", 120)
    assert write_limit("/api/v1/chat/conversations/one/messages", "GET") == ("chat-read", 120)
    assert write_limit("/api/v1/reports", "GET") == ("reports-read", 120)


@pytest.mark.anyio
async def test_redis_limiter_enforces_subject_and_bucket_budgets() -> None:
    limiter = RequestLimiter(cast(Redis, CountingRedis()))
    await limiter.check(bucket="login", subject="alice@example.test", maximum=2, window_seconds=60)
    await limiter.check(bucket="login", subject="alice@example.test", maximum=2, window_seconds=60)
    await limiter.check(bucket="login", subject="bob@example.test", maximum=2, window_seconds=60)
    with pytest.raises(AppError) as limited:
        await limiter.check(
            bucket="login", subject="alice@example.test", maximum=2, window_seconds=60
        )
    assert limited.value.code == "request_rate_limited"


@pytest.mark.anyio
async def test_critical_limiter_fails_closed_when_redis_is_unavailable() -> None:
    for redis in (None, cast(Redis, BrokenRedis())):
        limiter = RequestLimiter(redis)
        with pytest.raises(AppError) as unavailable:
            await limiter.check(
                bucket="login",
                subject="alice@example.test",
                maximum=2,
                window_seconds=60,
                fail_closed=True,
            )
        assert unavailable.value.code == "rate_limit_unavailable"


@pytest.mark.anyio
async def test_noncritical_limiter_has_bounded_local_fallback() -> None:
    limiter = RequestLimiter(cast(Redis, BrokenRedis()))
    await limiter.check(bucket="browse", subject="127.0.0.1", maximum=1, window_seconds=60)
    with pytest.raises(AppError) as limited:
        await limiter.check(bucket="browse", subject="127.0.0.1", maximum=1, window_seconds=60)
    assert limited.value.status_code == 429


def test_security_headers_and_untrusted_websocket_origin() -> None:
    app = create_app(Settings(database_url=None, redis_url=None, environment="test"))
    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect(
                "/api/v1/chat/ws?ticket=abcdefghijklmnop",
                headers={"origin": "https://hostile.example"},
            ):
                pass
        assert rejected.value.code == 4403
