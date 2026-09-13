from collections.abc import Awaitable
from hashlib import sha256
from hmac import new as hmac_new
from secrets import randbelow
from typing import Protocol, cast

from redis.asyncio import Redis

from app.core.exceptions import AppError

ISSUE_SCRIPT = """
-- issue-verification
if not redis.call('SET', KEYS[1], '1', 'EX', ARGV[2], 'NX') then
  return -1
end
local count = redis.call('INCR', KEYS[2])
if count == 1 then
  redis.call('EXPIRE', KEYS[2], ARGV[3])
end
if count > tonumber(ARGV[4]) then
  return -2
end
redis.call('HSET', KEYS[3], 'digest', ARGV[1], 'attempts', '0')
redis.call('EXPIRE', KEYS[3], ARGV[5])
return 1
"""

LIMIT_SCRIPT = """
-- reserve-verification-limit
if not redis.call('SET', KEYS[1], '1', 'EX', ARGV[1], 'NX') then
  return -1
end
local count = redis.call('INCR', KEYS[2])
if count == 1 then
  redis.call('EXPIRE', KEYS[2], ARGV[2])
end
if count > tonumber(ARGV[3]) then
  return -2
end
return 1
"""

CONSUME_SCRIPT = """
-- consume-verification
if redis.call('EXISTS', KEYS[1]) == 0 then
  return -1
end
if redis.call('HGET', KEYS[1], 'digest') == ARGV[1] then
  redis.call('DEL', KEYS[1])
  return 1
end
local attempts = redis.call('HINCRBY', KEYS[1], 'attempts', 1)
if attempts >= tonumber(ARGV[2]) then
  redis.call('DEL', KEYS[1])
end
return 0
"""


class VerificationCodeStore(Protocol):
    async def limit(self, *, subject: str, scope: str) -> None: ...

    async def issue(self, *, email: str, purpose: str) -> str: ...

    async def consume(self, *, email: str, purpose: str, code: str) -> None: ...

    async def discard(self, *, email: str, purpose: str) -> None: ...


class UnavailableVerificationCodeStore:
    async def limit(self, *, subject: str, scope: str) -> None:
        raise AppError(status_code=503, code="verification_unavailable", message="验证码服务不可用")

    async def issue(self, *, email: str, purpose: str) -> str:
        raise AppError(status_code=503, code="verification_unavailable", message="验证码服务不可用")

    async def consume(self, *, email: str, purpose: str, code: str) -> None:
        raise AppError(status_code=503, code="verification_unavailable", message="验证码服务不可用")

    async def discard(self, *, email: str, purpose: str) -> None:
        return None


class RedisVerificationCodeStore:
    def __init__(self, redis: Redis, secret: str) -> None:
        self._redis = redis
        self._secret = secret.encode()

    def _identifier(self, email: str, purpose: str) -> str:
        return sha256(f"{purpose}:{email}".encode()).hexdigest()

    def _digest(self, identifier: str, code: str) -> str:
        return hmac_new(self._secret, f"{identifier}:{code}".encode(), sha256).hexdigest()

    async def limit(self, *, subject: str, scope: str) -> None:
        identifier = self._identifier(subject, scope)
        result = await cast(
            Awaitable[int],
            self._redis.eval(
                LIMIT_SCRIPT,
                2,
                f"verification:limit:cooldown:{identifier}",
                f"verification:limit:hourly:{identifier}",
                "60",
                "3600",
                "5",
            ),
        )
        if result == -1:
            raise AppError(
                status_code=429, code="verification_too_frequent", message="请求过于频繁"
            )
        if result == -2:
            raise AppError(
                status_code=429, code="verification_rate_limited", message="请求次数过多"
            )

    async def issue(self, *, email: str, purpose: str) -> str:
        identifier = self._identifier(email, purpose)
        cooldown_key = f"verification:cooldown:{identifier}"
        hourly_key = f"verification:hourly:{identifier}"
        code_key = f"verification:code:{identifier}"
        code = f"{randbelow(1_000_000):06d}"
        result = await cast(
            Awaitable[int],
            self._redis.eval(
                ISSUE_SCRIPT,
                3,
                cooldown_key,
                hourly_key,
                code_key,
                self._digest(identifier, code),
                "60",
                "3600",
                "5",
                "600",
            ),
        )
        if result == -1:
            raise AppError(
                status_code=429, code="verification_too_frequent", message="请求过于频繁"
            )
        if result == -2:
            raise AppError(
                status_code=429, code="verification_rate_limited", message="请求次数过多"
            )
        return code

    async def consume(self, *, email: str, purpose: str, code: str) -> None:
        identifier = self._identifier(email, purpose)
        code_key = f"verification:code:{identifier}"
        result = await cast(
            Awaitable[int],
            self._redis.eval(CONSUME_SCRIPT, 1, code_key, self._digest(identifier, code), "5"),
        )
        if result == -1:
            raise AppError(
                status_code=422, code="verification_expired", message="验证码无效或已过期"
            )
        if result == 0:
            raise AppError(
                status_code=422, code="verification_invalid", message="验证码无效或已过期"
            )

    async def discard(self, *, email: str, purpose: str) -> None:
        identifier = self._identifier(email, purpose)
        await self._redis.delete(f"verification:code:{identifier}")
