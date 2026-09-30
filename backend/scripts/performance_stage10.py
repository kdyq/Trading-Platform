"""Measure isolated single-process API latency against a disposable PostgreSQL schema."""

import argparse
import asyncio
import ctypes
import json
import os
import platform
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import httpx
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.core.security import TokenManager
from app.db.seed import seed_categories, seed_roles_and_permissions
from app.db.url import database_url_for_sqlalchemy, require_project_database
from app.main import create_app
from app.models import Base
from scripts.postgres_gate import asyncpg_url, load_database_url

SECRET = "stage-ten-performance-secret-longer-than-32-characters"


def working_set_bytes() -> int | None:
    if platform.system() != "Windows":
        return None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("page_fault_count", ctypes.c_ulong),
            ("peak_working_set_size", ctypes.c_size_t),
            ("working_set_size", ctypes.c_size_t),
            ("quota_peak_paged_pool_usage", ctypes.c_size_t),
            ("quota_paged_pool_usage", ctypes.c_size_t),
            ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
            ("quota_non_paged_pool_usage", ctypes.c_size_t),
            ("pagefile_usage", ctypes.c_size_t),
            ("peak_pagefile_usage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    current_process = ctypes.windll.kernel32.GetCurrentProcess
    current_process.restype = ctypes.c_void_p
    get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
    get_memory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    get_memory.restype = ctypes.c_int
    if not get_memory(current_process(), ctypes.byref(counters), counters.cb):
        return None
    return int(counters.working_set_size)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 2)


async def prepare(database_url: str, schema: str) -> dict[str, str | list[str]]:
    engine = create_async_engine(
        database_url_for_sqlalchemy(database_url),
        connect_args={"server_settings": {"timezone": "UTC", "search_path": schema}},
    )
    seller, buyer, admin = uuid4(), uuid4(), uuid4()
    buyer_session, admin_session = uuid4(), uuid4()
    school, campus, conversation = uuid4(), uuid4(), uuid4()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await seed_categories(connection)
            await seed_roles_and_permissions(connection)
            category = await connection.scalar(
                text("SELECT id FROM categories WHERE code = 'books'")
            )
            assert isinstance(category, UUID)
            await connection.execute(
                text("INSERT INTO schools (id, code, name) VALUES (:id, 'PERF', '性能测试学校')"),
                {"id": school},
            )
            await connection.execute(
                text(
                    "INSERT INTO campuses (id, school_id, code, name) "
                    "VALUES (:id, :school, 'MAIN', '性能测试校区')"
                ),
                {"id": campus, "school": school},
            )
            for user_id, name in ((seller, "卖家"), (buyer, "买家"), (admin, "管理员")):
                await connection.execute(
                    text(
                        "INSERT INTO users (id, login_email, password_hash, display_name, "
                        "login_email_verified_at, user_agreement_version, privacy_policy_version, "
                        "terms_agreed_at) VALUES (:id, :email, 'not-a-login-hash', :name, now(), "
                        "'test', 'test', now())"
                    ),
                    {"id": user_id, "email": f"{user_id}@example.invalid", "name": name},
                )
            for user_id in (seller, buyer):
                await connection.execute(
                    text(
                        "INSERT INTO campus_verifications (id, user_id, campus_id, "
                        "campus_email, status, verified_at, expires_at) "
                        "VALUES (:id, :user, :campus, :email, 'verified', now(), :expires)"
                    ),
                    {
                        "id": uuid4(),
                        "user": user_id,
                        "campus": campus,
                        "email": f"{user_id}@campus.invalid",
                        "expires": datetime.now(UTC) + timedelta(days=30),
                    },
                )
            await connection.execute(
                text(
                    "INSERT INTO user_roles (user_id, role_id) "
                    "SELECT :user, id FROM roles WHERE code = 'SUPER_ADMIN'"
                ),
                {"user": admin},
            )
            for user_id, session in ((buyer, buyer_session), (admin, admin_session)):
                await connection.execute(
                    text(
                        "INSERT INTO user_sessions (id, user_id, family_id, refresh_token_digest, "
                        "expires_at, authenticated_at) "
                        "VALUES (:id, :user, :family, :digest, :expires, now())"
                    ),
                    {
                        "id": session,
                        "user": user_id,
                        "family": uuid4(),
                        "digest": uuid4().hex,
                        "expires": datetime.now(UTC) + timedelta(days=1),
                    },
                )
            await connection.execute(
                text(
                    "INSERT INTO products (id, seller_id, campus_id, category_id, title, "
                    "description, price, status, published_at) "
                    "SELECT gen_random_uuid(), :seller, :campus, :category, "
                    "'性能测试教材 ' || n, '仅用于隔离压测', 18.50, 'on_sale', "
                    "now() - n * interval '1 second' FROM generate_series(1, 2000) n "
                    "RETURNING id"
                ),
                {"seller": seller, "campus": campus, "category": category},
            )
            await connection.execute(
                text(
                    "INSERT INTO product_images "
                    "(id, product_id, object_key, thumbnail_object_key, alt_text) "
                    "SELECT gen_random_uuid(), id, 'perf/' || id || '.png', "
                    "'perf/' || id || '.webp', '性能测试商品图片' FROM products"
                )
            )
            await connection.execute(
                text(
                    "UPDATE products SET status='pending_review' WHERE id IN "
                    "(SELECT id FROM products ORDER BY published_at LIMIT 100)"
                )
            )
            product_rows = await connection.execute(
                text(
                    "SELECT id FROM products WHERE status='on_sale' "
                    "ORDER BY published_at DESC LIMIT 24"
                )
            )
            products = [str(row[0]) for row in product_rows]
            await connection.execute(
                text(
                    "INSERT INTO conversations (id, product_id, buyer_id, seller_id, "
                    "product_title_snapshot, product_price_snapshot) "
                    "VALUES (:id, :product, :buyer, :seller, '性能测试教材', 18.50)"
                ),
                {
                    "id": conversation,
                    "product": UUID(products[0]),
                    "buyer": buyer,
                    "seller": seller,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO messages "
                    "(id, conversation_id, sender_id, client_message_id, body) "
                    "SELECT gen_random_uuid(), :conversation, :sender, 'perf-' || n, "
                    "'隔离性能测试消息 ' || n FROM generate_series(1, 500) n"
                ),
                {"conversation": conversation, "sender": seller},
            )
        token_manager = TokenManager(SECRET, access_minutes=15, refresh_days=1)
        buyer_token, _ = token_manager.issue_access_token(
            user_id=buyer, session_id=buyer_session, authenticated_at=datetime.now(UTC)
        )
        admin_token, _ = token_manager.issue_access_token(
            user_id=admin, session_id=admin_session, authenticated_at=datetime.now(UTC)
        )
        return {
            "products": products,
            "conversation": str(conversation),
            "buyer_token": buyer_token,
            "admin_token": admin_token,
        }
    finally:
        await engine.dispose()


async def benchmark(
    client: httpx.AsyncClient,
    *,
    name: str,
    method: str,
    paths: list[str],
    token: str | None = None,
    payloads: list[dict[str, str]] | None = None,
    concurrency: int = 8,
) -> dict[str, object]:
    semaphore = asyncio.Semaphore(concurrency)
    samples: list[float] = []
    errors: list[dict[str, object]] = []

    async def one(index: int, path: str) -> None:
        async with semaphore:
            started = time.perf_counter()
            response = await client.request(
                method,
                path,
                headers={"Authorization": f"Bearer {token}"} if token else None,
                json=payloads[index] if payloads else None,
            )
            samples.append((time.perf_counter() - started) * 1000)
            if response.status_code >= 400:
                errors.append({"status": response.status_code, "code": response.json().get("code")})

    await asyncio.gather(*(one(i, path) for i, path in enumerate(paths)))
    return {
        "scenario": name,
        "requests": len(samples),
        "concurrency": concurrency,
        "p50_ms": percentile(samples, 0.5),
        "p95_ms": percentile(samples, 0.95),
        "max_ms": round(max(samples), 2),
        "error_rate": round(len(errors) / len(samples), 4),
        "errors": errors[:5],
    }


async def benchmark_mixed(
    client: httpx.AsyncClient, fixture: dict[str, str | list[str]]
) -> dict[str, object]:
    products = fixture["products"]
    assert isinstance(products, list)
    buyer_token = fixture["buyer_token"]
    admin_token = fixture["admin_token"]
    conversation = fixture["conversation"]
    assert isinstance(buyer_token, str)
    assert isinstance(admin_token, str)
    assert isinstance(conversation, str)
    requests: list[tuple[str, str, str | None, dict[str, str] | None]] = []
    for index in range(8):
        requests.extend(
            [
                ("GET", "/api/v1/market/summary", None, None),
                ("GET", "/api/v1/market/products?keyword=性能测试&page_size=12", None, None),
                ("GET", f"/api/v1/market/products/{products[index]}", None, None),
                ("GET", f"/api/v1/chat/conversations/{conversation}/messages", buyer_token, None),
                (
                    "GET",
                    "/api/v1/moderation/products?status=pending_review&page_size=20",
                    admin_token,
                    None,
                ),
            ]
        )
    for index, product in enumerate(products[13:17]):
        requests.append(
            (
                "POST",
                "/api/v1/orders",
                buyer_token,
                {"product_id": product, "idempotency_key": f"perf-mixed-order-{index}"},
            )
        )
    semaphore = asyncio.Semaphore(8)
    samples: list[float] = []
    errors: list[dict[str, object]] = []

    async def one(
        method: str, path: str, token: str | None, payload: dict[str, str] | None
    ) -> None:
        async with semaphore:
            started = time.perf_counter()
            response = await client.request(
                method,
                path,
                headers={"Authorization": f"Bearer {token}"} if token else None,
                json=payload,
            )
            samples.append((time.perf_counter() - started) * 1000)
            if response.status_code >= 400:
                errors.append({"path": path, "status": response.status_code})

    await asyncio.gather(*(one(*item) for item in requests))
    return {
        "scenario": "mixed",
        "request_mix": "8 each home/search/detail/chat/moderation + 4 order create",
        "requests": len(samples),
        "concurrency": 8,
        "p50_ms": percentile(samples, 0.5),
        "p95_ms": percentile(samples, 0.95),
        "max_ms": round(max(samples), 2),
        "error_rate": round(len(errors) / len(samples), 4),
        "errors": errors[:5],
    }


async def run(state: dict[str, object]) -> None:
    database_url = load_database_url()
    require_project_database(database_url)
    schema = f"test_gate_{uuid4().hex}"
    admin_engine = create_async_engine(database_url_for_sqlalchemy(database_url))
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    previous_schema = os.environ.get("DATABASE_SCHEMA")
    os.environ["DATABASE_SCHEMA"] = schema
    started = time.perf_counter()
    cpu_started = time.process_time()
    memory_started = working_set_bytes()
    try:
        fixture = await prepare(database_url, schema)
        state["stage"] = "measurement"
        async with admin_engine.begin() as connection:
            for table in (
                "products",
                "messages",
                "users",
                "categories",
                "schools",
                "campuses",
                "product_images",
                "orders",
                "reviews",
            ):
                await connection.execute(text(f'ANALYZE "{schema}".{table}'))
        settings = Settings(
            database_url=database_url,
            redis_url=None,
            auth_secret_key=SECRET,
            log_level="ERROR",
            environment="test",
        )
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            engine = app.state.database_engine
            active_scenario = ""
            captured: dict[str, list[tuple[str, tuple[object, ...]]]] = {}
            order_sql_ms: dict[str, list[float]] = {}

            def capture_query(
                _connection: object,
                _cursor: object,
                statement: str,
                parameters: tuple[object, ...],
                _context: object,
                _executemany: bool,
            ) -> None:
                if active_scenario == "order-create":
                    _context._stage10_started = time.perf_counter()  # type: ignore[attr-defined]
                if active_scenario and statement.lstrip().upper().startswith("SELECT"):
                    entries = captured.setdefault(active_scenario, [])
                    if len(entries) < 30 and all(sql != statement for sql, _ in entries):
                        entries.append((statement, tuple(parameters)))

            def capture_order_duration(
                _connection: object,
                _cursor: object,
                statement: str,
                _parameters: object,
                context: object,
                _executemany: bool,
            ) -> None:
                started_at = getattr(context, "_stage10_started", None)
                if started_at is None:
                    return
                normalized = statement.upper()
                if normalized.lstrip().startswith("INSERT INTO ORDERS"):
                    kind = "order_insert"
                elif "FROM ORDERS" in normalized:
                    kind = "order_lookup"
                elif "FROM PRODUCTS" in normalized and "FOR UPDATE" in normalized:
                    kind = "product_lock"
                else:
                    return
                order_sql_ms.setdefault(kind, []).append(
                    round((time.perf_counter() - started_at) * 1000, 3)
                )

            event.listen(engine.sync_engine, "before_cursor_execute", capture_query)
            event.listen(engine.sync_engine, "after_cursor_execute", capture_order_duration)
            peak_checked_out = 0
            peak_memory = memory_started or 0
            sampler_stop = asyncio.Event()

            async def sample_resources() -> None:
                nonlocal peak_checked_out, peak_memory
                while not sampler_stop.is_set():
                    peak_checked_out = max(peak_checked_out, engine.sync_engine.pool.checkedout())
                    peak_memory = max(peak_memory, working_set_bytes() or 0)
                    await asyncio.sleep(0.01)

            sampler = asyncio.create_task(sample_resources())
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://stage10.test", timeout=30
            ) as client:
                products = fixture["products"]
                assert isinstance(products, list)
                buyer_token = fixture["buyer_token"]
                admin_token = fixture["admin_token"]
                conversation = fixture["conversation"]
                assert isinstance(buyer_token, str)
                assert isinstance(admin_token, str)
                assert isinstance(conversation, str)

                async def measure(
                    measured_client: httpx.AsyncClient, **kwargs: object
                ) -> dict[str, object]:
                    nonlocal active_scenario
                    active_scenario = str(kwargs["name"])
                    return await benchmark(measured_client, **kwargs)  # type: ignore[arg-type]

                scenarios = [
                    await measure(
                        client, name="home", method="GET", paths=["/api/v1/market/summary"] * 20
                    ),
                    await measure(
                        client,
                        name="search",
                        method="GET",
                        paths=["/api/v1/market/products?keyword=性能测试&page_size=12"] * 20,
                    ),
                    await measure(
                        client,
                        name="detail",
                        method="GET",
                        paths=[f"/api/v1/market/products/{products[0]}"] * 20,
                    ),
                    await measure(
                        client,
                        name="chat-history",
                        method="GET",
                        paths=[f"/api/v1/chat/conversations/{conversation}/messages"] * 20,
                        token=buyer_token,
                    ),
                    await measure(
                        client,
                        name="order-create",
                        method="POST",
                        paths=["/api/v1/orders"] * 12,
                        token=buyer_token,
                        payloads=[
                            {"product_id": item, "idempotency_key": f"perf-order-{index}"}
                            for index, item in enumerate(products[1:13])
                        ],
                        concurrency=4,
                    ),
                    await measure(
                        client,
                        name="admin-queue",
                        method="GET",
                        paths=["/api/v1/moderation/products?status=pending_review&page_size=20"]
                        * 20,
                        token=admin_token,
                    ),
                ]
                active_scenario = "mixed"
                scenarios.append(await benchmark_mixed(client, fixture))
                active_scenario = ""
                sampler_stop.set()
                await sampler
                pool_status = engine.sync_engine.pool.status()
                async with engine.connect() as connection:
                    postgres_version = await connection.scalar(text("SHOW server_version"))
                    connections = await connection.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE datname = current_database()"
                        )
                    )
                plan_targets = {
                    "home": ("home", "FROM products", None),
                    "search_count": ("search", "ILIKE", False),
                    "search_list": ("search", "ILIKE", True),
                    "detail": ("detail", "FROM products", None),
                    "chat-history": ("chat-history", "FROM messages", None),
                    "admin_count": ("admin-queue", "FROM products", False),
                    "admin_list": ("admin-queue", "FROM products", True),
                    "order_product_lock": ("order-create", "FROM products", None),
                    "order_idempotency_lookup": ("order-create", "FROM orders", None),
                }
                plans: dict[str, list[str]] = {}
                state["stage"] = "query-plans"
                explain_connection = await asyncpg.connect(asyncpg_url(database_url))
                try:
                    await explain_connection.execute(f'SET search_path TO "{schema}"')
                    for name, (scenario_name, marker, ordered) in plan_targets.items():
                        query = next(
                            (
                                (sql, params)
                                for sql, params in captured[scenario_name]
                                if marker in sql
                                and (
                                    ordered is None
                                    or (not sql.lstrip().upper().startswith("SELECT COUNT("))
                                    == ordered
                                )
                            ),
                            None,
                        )
                        if query is None:
                            raise RuntimeError(f"No captured SQL for {name}: {marker}")
                        rows = await explain_connection.fetch(
                            "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) " + query[0], *query[1]
                        )
                        plans[name] = [row[0] for row in rows]
                finally:
                    await explain_connection.close()
        report = {
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "machine": platform.platform(),
            "python": platform.python_version(),
            "postgresql": postgres_version,
            "database_schema": "disposable test_gate_*",
            "sample": {
                "products": 2000,
                "pending_products": 100,
                "product_image_rows": 2000,
                "messages": 500,
                "buyers": 1,
                "sellers": 1,
            },
            "process": "single ASGI process, in-process HTTP transport",
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "process_cpu_seconds": round(time.process_time() - cpu_started, 2),
            "process_working_set_start_bytes": memory_started,
            "process_working_set_end_bytes": working_set_bytes(),
            "process_working_set_peak_bytes": peak_memory,
            "database_connections_at_end": connections,
            "sqlalchemy_pool_peak_checked_out": peak_checked_out,
            "sqlalchemy_pool_at_end": pool_status,
            "order_sql_ms": {
                kind: {
                    "count": len(samples),
                    "p50_ms": percentile(samples, 0.5),
                    "p95_ms": percentile(samples, 0.95),
                    "max_ms": round(max(samples), 3),
                }
                for kind, samples in order_sql_ms.items()
            },
            "scenarios": scenarios,
            "explain_actual_endpoint_queries": plans,
        }
        state.update(report)
        state["stage"] = "cleanup"
    finally:
        if previous_schema is None:
            os.environ.pop("DATABASE_SCHEMA", None)
        else:
            os.environ["DATABASE_SCHEMA"] = previous_schema
        try:
            async with admin_engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            await admin_engine.dispose()


def write_result(output: Path, state: dict[str, object]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)


async def tracked_run(output: Path) -> None:
    state: dict[str, object] = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "status": "running",
        "stage": "preflight",
    }
    write_result(output, state)
    try:
        await run(state)
    except BaseException as exc:
        state.update(status="failed", error=f"{type(exc).__name__}: {exc}", exit_code=1)
        write_result(output, state)
        raise
    state.update(status="passed", stage="complete", exit_code=0)
    state["completed_at_utc"] = datetime.now(UTC).isoformat()
    write_result(output, state)
    print(json.dumps({"output": str(output), "scenarios": state["scenarios"]}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(tracked_run(parser.parse_args().output))
