import asyncio
import json
import logging
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from hashlib import sha256
from secrets import token_urlsafe
from time import monotonic
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from fastapi import WebSocket
from redis.asyncio import Redis

from app.core.exceptions import AppError

logger = logging.getLogger(__name__)
CHANNEL = "shiguang:chat:events"
CONSUME_TICKET_SCRIPT = """
local value = redis.call('GET', KEYS[1])
if value then redis.call('DEL', KEYS[1]) end
return value
"""
MESSAGE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return count
"""


class WebSocketTicketStore(Protocol):
    async def issue(self, user_id: UUID) -> tuple[str, int]: ...

    async def consume(self, ticket: str) -> UUID | None: ...


class UnavailableWebSocketTicketStore:
    async def issue(self, user_id: UUID) -> tuple[str, int]:
        raise AppError(status_code=503, code="realtime_unavailable", message="实时通信暂不可用")

    async def consume(self, ticket: str) -> UUID | None:
        return None


class RedisWebSocketTicketStore:
    def __init__(self, redis: Redis, *, ttl_seconds: int = 60) -> None:
        self._redis = redis
        self._ttl_seconds = ttl_seconds

    @staticmethod
    def _key(ticket: str) -> str:
        return f"chat:ws-ticket:{sha256(ticket.encode()).hexdigest()}"

    async def issue(self, user_id: UUID) -> tuple[str, int]:
        ticket = token_urlsafe(32)
        try:
            created = await self._redis.set(
                self._key(ticket), str(user_id), ex=self._ttl_seconds, nx=True
            )
        except Exception as exc:
            raise AppError(
                status_code=503,
                code="realtime_unavailable",
                message="实时通信暂不可用",
            ) from exc
        if not created:
            raise AppError(status_code=503, code="realtime_unavailable", message="实时通信暂不可用")
        return ticket, self._ttl_seconds

    async def consume(self, ticket: str) -> UUID | None:
        if len(ticket) > 128:
            return None
        value = await cast(
            Awaitable[str | None], self._redis.eval(CONSUME_TICKET_SCRIPT, 1, self._key(ticket))
        )
        if value is None:
            return None
        try:
            return UUID(value)
        except ValueError:
            return None


class ChatMessageLimiter(Protocol):
    async def check(self, user_id: UUID, conversation_id: UUID) -> None: ...


class NullChatMessageLimiter:
    async def check(self, user_id: UUID, conversation_id: UUID) -> None:
        return None


class InMemoryChatMessageLimiter:
    def __init__(self, *, maximum: int = 20, window_seconds: int = 10) -> None:
        self.maximum = maximum
        self.window_seconds = window_seconds
        self._events: dict[tuple[UUID, UUID], deque[float]] = {}
        self._lock = asyncio.Lock()

    async def check(self, user_id: UUID, conversation_id: UUID) -> None:
        now = monotonic()
        key = (user_id, conversation_id)
        async with self._lock:
            if len(self._events) >= 10_000 and key not in self._events:
                self._events.pop(next(iter(self._events)))
            events = self._events.setdefault(key, deque())
            while events and events[0] <= now - self.window_seconds:
                events.popleft()
            if len(events) >= self.maximum:
                raise AppError(
                    status_code=429, code="chat_rate_limited", message="消息发送过于频繁"
                )
            events.append(now)


class RedisChatMessageLimiter:
    def __init__(
        self,
        redis: Redis | None,
        fallback: ChatMessageLimiter,
        *,
        maximum: int = 20,
        window_seconds: int = 10,
    ) -> None:
        self.redis = redis
        self.fallback = fallback
        self.maximum = maximum
        self.window_seconds = window_seconds

    async def check(self, user_id: UUID, conversation_id: UUID) -> None:
        if self.redis is None:
            await self.fallback.check(user_id, conversation_id)
            return
        try:
            count = await cast(
                Awaitable[int],
                self.redis.eval(
                    MESSAGE_LIMIT_SCRIPT,
                    1,
                    f"chat:send-limit:{user_id}:{conversation_id}",
                    str(self.window_seconds),
                ),
            )
        except Exception:
            logger.warning("Redis chat rate limit failed; using local fallback", exc_info=True)
            await self.fallback.check(user_id, conversation_id)
            return
        if count > self.maximum:
            raise AppError(status_code=429, code="chat_rate_limited", message="消息发送过于频繁")


class RealtimeHub:
    def __init__(self) -> None:
        self._connections: dict[UUID, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, user_id: UUID, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[user_id].add(websocket)

    async def disconnect(self, user_id: UUID, websocket: WebSocket) -> None:
        async with self._lock:
            sockets = self._connections.get(user_id)
            if sockets is None:
                return
            sockets.discard(websocket)
            if not sockets:
                self._connections.pop(user_id, None)

    async def send_user(self, user_id: UUID, payload: dict[str, Any]) -> bool:
        async with self._lock:
            sockets = tuple(self._connections.get(user_id, ()))
        failed: list[WebSocket] = []
        for websocket in sockets:
            try:
                await websocket.send_json(payload)
            except Exception:
                failed.append(websocket)
        for websocket in failed:
            await self.disconnect(user_id, websocket)
        return bool(sockets) and len(failed) < len(sockets)


class RealtimePublisher(Protocol):
    async def publish(self, user_ids: tuple[UUID, ...], payload: dict[str, Any]) -> bool: ...


class NullRealtimePublisher:
    async def publish(self, user_ids: tuple[UUID, ...], payload: dict[str, Any]) -> bool:
        return False


class RedisRealtimePublisher:
    def __init__(self, hub: RealtimeHub, redis: Redis | None) -> None:
        self.hub = hub
        self.redis = redis
        self.instance_id = str(uuid4())

    async def publish(self, user_ids: tuple[UUID, ...], payload: dict[str, Any]) -> bool:
        delivered_locally = False
        for user_id in set(user_ids):
            delivered_locally = await self.hub.send_user(user_id, payload) or delivered_locally
        if self.redis is None:
            return delivered_locally
        envelope = {
            "origin": self.instance_id,
            "user_ids": [str(user_id) for user_id in set(user_ids)],
            "payload": payload,
        }
        try:
            subscriber_count = await cast(
                Awaitable[int],
                self.redis.publish(CHANNEL, json.dumps(envelope, ensure_ascii=False)),
            )
        except Exception:
            logger.warning("Redis realtime publish failed", exc_info=True)
            return delivered_locally
        return delivered_locally or subscriber_count > 0

    async def listen(self) -> None:
        if self.redis is None:
            return
        while True:
            pubsub = self.redis.pubsub()
            try:
                await pubsub.subscribe(CHANNEL)
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    try:
                        envelope = json.loads(message["data"])
                        if envelope.get("origin") == self.instance_id:
                            continue
                        for value in envelope["user_ids"]:
                            await self.hub.send_user(UUID(value), envelope["payload"])
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                        logger.warning("Discarded invalid realtime event", exc_info=True)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Redis realtime listener reconnecting", exc_info=True)
                await asyncio.sleep(1)
            finally:
                close_pubsub = cast(Callable[[], Awaitable[None]], pubsub.aclose)
                await close_pubsub()
