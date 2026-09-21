import asyncio
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings
from app.core.exceptions import AppError
from app.main import create_app
from app.services.realtime import (
    InMemoryChatMessageLimiter,
    RedisChatMessageLimiter,
    RedisWebSocketTicketStore,
)


class MemoryTicketRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, **options: Any) -> bool:
        if options.get("nx") and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script: str, key_count: int, key: str) -> str | None:
        assert key_count == 1
        return self.values.pop(key, None)

    async def aclose(self) -> None:
        return None


class FailingTicketRedis(MemoryTicketRedis):
    async def set(self, key: str, value: str, **options: Any) -> bool:
        raise ConnectionError("redis unavailable")

    async def eval(self, script: str, key_count: int, key: str) -> str | None:
        raise ConnectionError("redis unavailable")


def ticket_store() -> tuple[RedisWebSocketTicketStore, MemoryTicketRedis]:
    redis = MemoryTicketRedis()
    return RedisWebSocketTicketStore(cast(Redis, redis)), redis


@pytest.mark.anyio
async def test_websocket_ticket_is_short_lived_opaque_and_single_use() -> None:
    store, redis = ticket_store()
    user_id = uuid4()

    ticket, expires_in = await store.issue(user_id)

    assert expires_in == 60
    assert str(user_id) not in ticket
    assert all(ticket not in key for key in redis.values)
    assert await store.consume(ticket) == user_id
    assert await store.consume(ticket) is None


@pytest.mark.anyio
async def test_ticket_issue_maps_redis_failure_to_stable_service_unavailable() -> None:
    store = RedisWebSocketTicketStore(cast(Redis, FailingTicketRedis()))

    with pytest.raises(AppError) as unavailable:
        await store.issue(uuid4())

    assert unavailable.value.status_code == 503
    assert unavailable.value.code == "realtime_unavailable"


@pytest.mark.anyio
async def test_local_message_limiter_rejects_burst_per_member_and_conversation() -> None:
    limiter = InMemoryChatMessageLimiter(maximum=2, window_seconds=60)
    user_id, conversation_id = uuid4(), uuid4()

    await limiter.check(user_id, conversation_id)
    await limiter.check(user_id, conversation_id)
    with pytest.raises(AppError) as limited:
        await limiter.check(user_id, conversation_id)
    assert limited.value.code == "chat_rate_limited"


@pytest.mark.anyio
async def test_configured_redis_limiter_preserves_rest_writes_with_local_fallback() -> None:
    limiter = RedisChatMessageLimiter(
        cast(Redis, FailingTicketRedis()),
        InMemoryChatMessageLimiter(maximum=1, window_seconds=60),
    )
    user_id, conversation_id = uuid4(), uuid4()

    await limiter.check(user_id, conversation_id)
    with pytest.raises(AppError) as limited:
        await limiter.check(user_id, conversation_id)

    assert limited.value.status_code == 429
    assert limited.value.code == "chat_rate_limited"


def test_websocket_requires_single_use_ticket_and_answers_heartbeat() -> None:
    app = create_app(Settings(database_url=None, redis_url=None))
    store, redis = ticket_store()
    user_id = uuid4()
    ticket, _ = asyncio.run(store.issue(user_id))

    with TestClient(app) as client:
        app.state.redis = cast(Redis, redis)
        with client.websocket_connect(f"/api/v1/chat/ws?ticket={ticket}") as websocket:
            assert websocket.receive_json() == {
                "type": "chat.ready",
                "data": {"user_id": str(user_id)},
            }
            websocket.send_json({"type": "ping"})
            assert websocket.receive_json() == {"type": "pong"}

        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect(f"/api/v1/chat/ws?ticket={ticket}") as replay:
                replay.receive_json()
        assert rejected.value.code == 4401
