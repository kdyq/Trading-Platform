"""Test-only ASGI entrypoint: real API/DB with a local verification mail sink."""

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from secrets import randbelow

from fastapi import FastAPI

from app.api.dependencies import get_campus_mailer, get_verification_mailer, get_verification_store
from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.rate_limits import RequestLimiter
from app.db.url import require_project_database, require_test_schema
from app.main import create_app

database_url = os.environ.get("DATABASE_URL")
schema = os.environ.get("DATABASE_SCHEMA", "")
mail_file = os.environ.get("STAGE10_MAIL_FILE", "")
if not database_url or not mail_file or os.environ.get("APP_ENV") != "test":
    raise RuntimeError("Stage 10 browser app requires explicit test environment")
require_project_database(database_url)
require_test_schema(schema)


class LocalCodeStore:
    def __init__(self) -> None:
        self.codes: dict[tuple[str, str], str] = {}

    async def limit(self, *, subject: str, scope: str) -> None:
        return None

    async def issue(self, *, email: str, purpose: str) -> str:
        code = f"{randbelow(1_000_000):06d}"
        self.codes[(email, purpose)] = code
        return code

    async def consume(self, *, email: str, purpose: str, code: str) -> None:
        if self.codes.get((email, purpose)) != code:
            raise AppError(status_code=422, code="verification_invalid", message="验证码无效")
        self.codes.pop((email, purpose), None)

    async def discard(self, *, email: str, purpose: str) -> None:
        self.codes.pop((email, purpose), None)


class LocalMailer:
    async def send_verification_code(self, *, recipient: str, code: str) -> None:
        Path(mail_file).write_text(
            json.dumps({"recipient": recipient, "code": code}), encoding="utf-8"
        )

    async def send_campus_verification_code(self, *, recipient: str, code: str) -> None:
        await self.send_verification_code(recipient=recipient, code=code)


code_store = LocalCodeStore()
mailer = LocalMailer()
app = create_app(Settings(environment="test"))
original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def isolated_browser_lifespan(application: FastAPI) -> AsyncIterator[None]:
    async with original_lifespan(application):
        application.state.request_limiter = RequestLimiter(None)
        yield


app.router.lifespan_context = isolated_browser_lifespan
app.dependency_overrides[get_verification_store] = lambda: code_store
app.dependency_overrides[get_verification_mailer] = lambda: mailer
app.dependency_overrides[get_campus_mailer] = lambda: mailer
