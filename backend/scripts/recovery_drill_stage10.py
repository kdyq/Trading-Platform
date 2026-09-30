"""Back up and restore disposable PostgreSQL schema plus one object file."""

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import asyncpg

from app.db.url import require_project_database, require_test_schema
from scripts.postgres_gate import asyncpg_url, load_database_url

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def postgres_command(tool: str, database_url: str, *args: str) -> None:
    parsed = urlsplit(asyncpg_url(database_url))
    executable = shutil.which(tool)
    if executable is None:
        raise RuntimeError(f"{tool} is required")
    environment = os.environ.copy()
    environment["PGPASSWORD"] = unquote(parsed.password or "")
    subprocess.run(
        [
            executable,
            "--host",
            parsed.hostname or "localhost",
            "--port",
            str(parsed.port or 5432),
            "--username",
            unquote(parsed.username or ""),
            "--dbname",
            parsed.path.lstrip("/"),
            *args,
        ],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def migrate(database_url: str, schema: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    environment["DATABASE_SCHEMA"] = schema
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [sys.executable, "-m", "app.db.seed"],
        cwd=BACKEND_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


async def execute(database_url: str, statement: str, *args: object) -> None:
    connection = await asyncpg.connect(asyncpg_url(database_url))
    try:
        await connection.execute(statement, *args)
    finally:
        await connection.close()


async def fixture(database_url: str, schema: str, object_key: str, thumbnail_key: str) -> None:
    connection = await asyncpg.connect(asyncpg_url(database_url))
    school, campus, user, product, image = (uuid4() for _ in range(5))
    try:
        await connection.execute(f'SET search_path TO "{schema}"')
        category = await connection.fetchval("SELECT id FROM categories WHERE code='books'")
        await connection.execute(
            "INSERT INTO schools (id, code, name) VALUES ($1, 'DRILL', '恢复演练学校')",
            school,
        )
        await connection.execute(
            "INSERT INTO campuses (id, school_id, code, name) "
            "VALUES ($1, $2, 'MAIN', '恢复演练校区')",
            campus,
            school,
        )
        await connection.execute(
            "INSERT INTO users (id, login_email, password_hash, display_name, "
            "login_email_verified_at, user_agreement_version, privacy_policy_version, "
            "terms_agreed_at) VALUES ($1, 'drill@example.invalid', 'test-hash', "
            "'演练用户', now(), 'test', 'test', now())",
            user,
        )
        await connection.execute(
            "INSERT INTO products (id, seller_id, campus_id, category_id, title, "
            "description, price, status) VALUES ($1, $2, $3, $4, '演练商品', "
            "'非生产数据', 1.00, 'draft')",
            product,
            user,
            campus,
            category,
        )
        await connection.execute(
            "INSERT INTO product_images (id, product_id, object_key, thumbnail_object_key, "
            "display_order) VALUES ($1, $2, $3, $4, 0)",
            image,
            product,
            object_key,
            thumbnail_key,
        )
    finally:
        await connection.close()


async def snapshot(database_url: str, schema: str) -> dict[str, object]:
    connection = await asyncpg.connect(asyncpg_url(database_url))
    try:
        await connection.execute(f'SET search_path TO "{schema}"')
        return {
            "migration_version": await connection.fetchval(
                "SELECT version_num FROM alembic_version"
            ),
            "users": await connection.fetchval("SELECT count(*) FROM users"),
            "products": await connection.fetchval("SELECT count(*) FROM products"),
            "images": await connection.fetchval("SELECT count(*) FROM product_images"),
            "categories": await connection.fetchval("SELECT count(*) FROM categories"),
            "object_keys": [
                key
                for row in await connection.fetch(
                    "SELECT object_key, thumbnail_object_key FROM product_images ORDER BY id"
                )
                for key in (row["object_key"], row["thumbnail_object_key"])
            ],
        }
    finally:
        await connection.close()


async def run(output: Path) -> None:
    database_url = load_database_url()
    require_project_database(database_url)
    schema = f"test_gate_{uuid4().hex}"
    require_test_schema(schema)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="stage10-recovery-") as temporary:
        root = Path(temporary)
        object_key = "products/recovery-object.bin"
        thumbnail_key = "products/recovery-thumb.bin"
        contents = {
            object_key: b"non-production-stage-10-object",
            thumbnail_key: b"non-production-stage-10-thumbnail",
        }
        digests = {key: hashlib.sha256(content).hexdigest() for key, content in contents.items()}
        for key, content in contents.items():
            path = root / "active" / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        dump = root / "database.dump"
        await execute(database_url, f'CREATE SCHEMA "{schema}"')
        try:
            migrate(database_url, schema)
            await fixture(database_url, schema, object_key, thumbnail_key)
            before = await snapshot(database_url, schema)
            postgres_command(
                "pg_dump", database_url, "--format=custom", "--schema", schema, "--file", str(dump)
            )
            for key in contents:
                backup_path = root / "backup" / key
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / "active" / key, backup_path)
            backup_seconds = round(time.perf_counter() - started, 2)
            await execute(database_url, f'DROP SCHEMA "{schema}" CASCADE')
            for key in contents:
                (root / "active" / key).unlink()
            restore_started = time.perf_counter()
            postgres_command("pg_restore", database_url, "--no-owner", "--no-privileges", str(dump))
            for key in contents:
                restored_path = root / "active" / key
                restored_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / "backup" / key, restored_path)
            after = await snapshot(database_url, schema)
            if before != after:
                raise RuntimeError("Restored database or object file differs from backup")
            for key in after["object_keys"]:
                restored_path = root / "active" / key
                if (
                    not restored_path.exists()
                    or hashlib.sha256(restored_path.read_bytes()).hexdigest() != digests[key]
                ):
                    raise RuntimeError(
                        f"Restored product image reference is missing or changed: {key}"
                    )
            report = {
                "timestamp_utc": datetime.now(UTC).isoformat(),
                "target": "disposable test_gate_* schema and non-production object",
                "backup_seconds": backup_seconds,
                "restore_seconds": round(time.perf_counter() - restore_started, 2),
                "database_dump_bytes": dump.stat().st_size,
                "object_sha256": digests,
                "before": before,
                "after": after,
                "verified": True,
            }
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(json.dumps({"output": str(output), "verified": True}, ensure_ascii=False))
        finally:
            await execute(database_url, f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(parser.parse_args().output))
