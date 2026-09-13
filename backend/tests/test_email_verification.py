from asyncio import gather, run
from collections.abc import Mapping
from typing import Any, cast

import pytest
from redis.asyncio import Redis

from app.core.exceptions import AppError
from app.services.email_verification import RedisVerificationCodeStore


class MemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.ttls: dict[str, int] = {}

    async def eval(self, script: str, numkeys: int, *arguments: object) -> int:
        keys = [str(value) for value in arguments[:numkeys]]
        args = [str(value) for value in arguments[numkeys:]]
        if "issue-verification" in script:
            cooldown_key, hourly_key, code_key = keys
            if cooldown_key in self.values:
                return -1
            self.values[cooldown_key] = "1"
            self.ttls[cooldown_key] = int(args[1])
            hourly_count = int(self.values.get(hourly_key, "0")) + 1
            self.values[hourly_key] = str(hourly_count)
            if hourly_count == 1:
                self.ttls[hourly_key] = int(args[2])
            if hourly_count > int(args[3]):
                return -2
            self.hashes[code_key] = {"digest": args[0], "attempts": "0"}
            self.ttls[code_key] = int(args[4])
            return 1
        if "consume-verification" in script:
            code_key = keys[0]
            if code_key not in self.hashes:
                return -1
            if self.hashes[code_key]["digest"] == args[0]:
                await self.delete(code_key)
                return 1
            attempts = int(self.hashes[code_key]["attempts"]) + 1
            self.hashes[code_key]["attempts"] = str(attempts)
            if attempts >= int(args[1]):
                await self.delete(code_key)
            return 0
        raise AssertionError("unexpected script")

    async def set(self, key: str, value: str, **options: Any) -> bool:
        if options.get("nx") and key in self.values:
            return False
        self.values[key] = value
        return True

    async def incr(self, key: str) -> int:
        value = int(self.values.get(key, "0")) + 1
        self.values[key] = str(value)
        return value

    async def expire(self, key: str, _seconds: int) -> bool:
        return key in self.values or key in self.hashes

    async def hset(self, key: str, mapping: Mapping[str, object]) -> int:
        self.hashes[key] = {name: str(value) for name, value in mapping.items()}
        return len(mapping)

    async def hgetall(self, key: str) -> dict[str, str]:
        return self.hashes.get(key, {}).copy()

    async def hincrby(self, key: str, field: str, amount: int) -> int:
        value = int(self.hashes[key][field]) + amount
        self.hashes[key][field] = str(value)
        return value

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            removed += int(self.values.pop(key, None) is not None)
            removed += int(self.hashes.pop(key, None) is not None)
            self.ttls.pop(key, None)
        return removed


def store_with_memory_redis() -> tuple[RedisVerificationCodeStore, MemoryRedis]:
    redis = MemoryRedis()
    store = RedisVerificationCodeStore(cast(Redis, redis), "verification-test-secret")
    return store, redis


async def check_code_is_single_use_and_cooldown_is_enforced() -> None:
    store, redis = store_with_memory_redis()
    code = await store.issue(email="student@example.com", purpose="registration")
    assert 600 in redis.ttls.values()

    with pytest.raises(AppError, match="请求过于频繁"):
        await store.issue(email="student@example.com", purpose="registration")

    await store.consume(email="student@example.com", purpose="registration", code=code)
    with pytest.raises(AppError) as replay:
        await store.consume(email="student@example.com", purpose="registration", code=code)
    assert replay.value.code == "verification_expired"


def test_code_is_single_use_and_cooldown_is_enforced() -> None:
    run(check_code_is_single_use_and_cooldown_is_enforced())


async def check_five_invalid_attempts_exhaust_the_code() -> None:
    store, _ = store_with_memory_redis()
    await store.issue(email="student@example.com", purpose="registration")

    for _ in range(5):
        with pytest.raises(AppError) as invalid:
            await store.consume(
                email="student@example.com", purpose="registration", code="not-the-code"
            )
        assert invalid.value.code == "verification_invalid"

    with pytest.raises(AppError) as exhausted:
        await store.consume(email="student@example.com", purpose="registration", code="000000")
    assert exhausted.value.code == "verification_expired"


def test_five_invalid_attempts_exhaust_the_code() -> None:
    run(check_five_invalid_attempts_exhaust_the_code())


async def check_concurrent_consumption_has_one_winner() -> None:
    store, _ = store_with_memory_redis()
    code = await store.issue(email="parallel@example.com", purpose="registration")
    results = await gather(
        store.consume(email="parallel@example.com", purpose="registration", code=code),
        store.consume(email="parallel@example.com", purpose="registration", code=code),
        return_exceptions=True,
    )
    assert sum(result is None for result in results) == 1
    failures = [result for result in results if isinstance(result, AppError)]
    assert len(failures) == 1
    assert failures[0].code == "verification_expired"


def test_concurrent_consumption_has_one_winner() -> None:
    run(check_concurrent_consumption_has_one_winner())
