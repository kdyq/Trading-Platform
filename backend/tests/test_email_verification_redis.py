import asyncio
from hashlib import sha256
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.exceptions import AppError
from app.services.email_verification import RedisVerificationCodeStore


def test_real_redis_code_is_atomic_and_has_ttl() -> None:
    redis_url = Settings().redis_url
    if redis_url is None:
        pytest.skip("REDIS_URL is required for Redis integration test")
    asyncio.run(_exercise_real_redis(redis_url))


async def _exercise_real_redis(redis_url: str) -> None:
    redis = Redis.from_url(redis_url, decode_responses=True)
    email = f"redis-{uuid4()}@example.com"
    purpose = "registration"
    identifier = sha256(f"{purpose}:{email}".encode()).hexdigest()
    keys = [
        f"verification:cooldown:{identifier}",
        f"verification:hourly:{identifier}",
        f"verification:code:{identifier}",
    ]
    try:
        store = RedisVerificationCodeStore(redis, "redis-integration-secret")
        code = await store.issue(email=email, purpose=purpose)
        ttl = await redis.ttl(keys[2])
        assert 0 < ttl <= 600

        results = await asyncio.gather(
            store.consume(email=email, purpose=purpose, code=code),
            store.consume(email=email, purpose=purpose, code=code),
            return_exceptions=True,
        )
        assert sum(result is None for result in results) == 1
        failures = [result for result in results if isinstance(result, AppError)]
        assert len(failures) == 1
        assert failures[0].code == "verification_expired"
    finally:
        await redis.delete(*keys)
        await redis.aclose()
