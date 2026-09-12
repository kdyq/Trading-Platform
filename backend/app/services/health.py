from typing import TypedDict

from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class DependencyState(TypedDict):
    status: str
    reason: str | None


class ReadinessState(TypedDict):
    status: str
    dependencies: dict[str, DependencyState]


async def _database_state(engine: AsyncEngine | None) -> DependencyState:
    if engine is None:
        return {"status": "unavailable", "reason": "not_configured"}
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return {"status": "ready", "reason": None}
    except Exception:
        return {"status": "unavailable", "reason": "connection_failed"}


async def _redis_state(client: Redis | None) -> DependencyState:
    if client is None:
        return {"status": "unavailable", "reason": "not_configured"}
    try:
        await client.ping()
        return {"status": "ready", "reason": None}
    except Exception:
        return {"status": "unavailable", "reason": "connection_failed"}


async def readiness_status(app: FastAPI) -> ReadinessState:
    database = await _database_state(app.state.database_engine)
    redis = await _redis_state(app.state.redis)
    dependencies = {"database": database, "redis": redis}
    return {
        "status": "ready"
        if all(state["status"] == "ready" for state in dependencies.values())
        else "not_ready",
        "dependencies": dependencies,
    }
