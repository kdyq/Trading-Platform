import asyncio
import logging
from collections import deque
from hashlib import sha256
from time import monotonic
from typing import Any, cast

from redis.asyncio import Redis

from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

INCREMENT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return count
"""


class RequestLimiter:
    def __init__(self, redis: Redis | None) -> None:
        self.redis = redis
        self._events: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def check(
        self,
        *,
        bucket: str,
        subject: str,
        maximum: int,
        window_seconds: int,
        fail_closed: bool = False,
    ) -> None:
        digest = sha256(subject.encode()).hexdigest()
        key = f"request-limit:{bucket}:{digest}"
        if self.redis is not None:
            try:
                count = await cast(
                    Any,
                    self.redis.eval(INCREMENT_SCRIPT, 1, key, str(window_seconds)),
                )
                if int(count) > maximum:
                    raise AppError(
                        status_code=429, code="request_rate_limited", message="请求过于频繁"
                    )
                return
            except AppError:
                raise
            except Exception:
                logger.warning("request_rate_limit_redis_unavailable")
        if fail_closed:
            raise AppError(status_code=503, code="rate_limit_unavailable", message="服务暂不可用")
        now = monotonic()
        async with self._lock:
            if len(self._events) >= 10_000 and key not in self._events:
                self._events.pop(next(iter(self._events)))
            events = self._events.setdefault(key, deque())
            while events and events[0] <= now - window_seconds:
                events.popleft()
            if len(events) >= maximum:
                raise AppError(status_code=429, code="request_rate_limited", message="请求过于频繁")
            events.append(now)
