"""Process queued audit exports outside request workers: python -m app.workers.audit_export."""

import argparse
import asyncio
import csv
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.session import create_database_engine, create_session_factory, transaction_scope
from app.db.url import require_project_database
from app.models.admin import AuditExportJob
from app.models.moderation import AuditLog
from app.services.admin_insights import redacted_data


async def claim(factory: async_sessionmaker[AsyncSession]) -> UUID | None:
    async with transaction_scope(factory) as session:
        now = datetime.now(UTC)
        job = await session.scalar(
            select(AuditExportJob)
            .where(
                AuditExportJob.revoked.is_(False),
                AuditExportJob.expires_at > now,
                AuditExportJob.status == "queued",
            )
            .order_by(AuditExportJob.created_at, AuditExportJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        job.status = "processing"
        job.failure_code = None
        await session.flush()
        return job.id


async def process_job(
    factory: async_sessionmaker[AsyncSession], job_id: UUID, private_root: Path
) -> None:
    export_directory = private_root / "exports"
    export_directory.mkdir(parents=True, exist_ok=True)
    key = f"{job_id.hex}.csv"
    path = export_directory / key
    temp_path = export_directory / f"{job_id.hex}.partial"
    try:
        async with transaction_scope(factory) as session:
            job = await session.get(AuditExportJob, job_id)
            if job is None or job.revoked or job.expires_at <= datetime.now(UTC):
                return
            start = datetime.fromisoformat(str(job.filters["starts_at"]))
            end = datetime.fromisoformat(str(job.filters["ends_at"]))
            action_value = job.filters.get("action")
            action = str(action_value) if action_value else None
            watermark_time = datetime.now(UTC).isoformat()
            cursor: tuple[datetime, UUID] | None = None
            cancelled = False
            with temp_path.open("w", encoding="utf-8-sig", newline="") as output:
                writer = csv.writer(output)
                writer.writerow(
                    [
                        "exported_by",
                        "exported_at",
                        "audit_id",
                        "created_at",
                        "actor_id",
                        "action",
                        "target_type",
                        "target_id",
                        "audit_data",
                    ]
                )
                while True:
                    query = select(AuditLog).where(
                        AuditLog.created_at >= start, AuditLog.created_at < end
                    )
                    if action:
                        query = query.where(AuditLog.action == action)
                    if cursor:
                        query = query.where(
                            or_(
                                AuditLog.created_at < cursor[0],
                                and_(AuditLog.created_at == cursor[0], AuditLog.id < cursor[1]),
                            )
                        )
                    rows = (
                        await session.scalars(
                            query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(
                                200
                            )
                        )
                    ).all()
                    if not rows:
                        break
                    for row in rows:
                        writer.writerow(
                            [
                                str(job.actor_id),
                                watermark_time,
                                str(row.id),
                                row.created_at.isoformat(),
                                str(row.actor_id or ""),
                                row.action,
                                row.target_type,
                                str(row.target_id or ""),
                                json.dumps(redacted_data(row.audit_data), ensure_ascii=False),
                            ]
                        )
                    cursor = (rows[-1].created_at, rows[-1].id)
                    async with transaction_scope(factory) as heartbeat_session:
                        active = await heartbeat_session.scalar(
                            select(AuditExportJob)
                            .where(AuditExportJob.id == job_id)
                            .with_for_update()
                        )
                        if active is None or active.status != "processing" or active.revoked:
                            cancelled = True
                            break
                        active.updated_at = datetime.now(UTC)
            if cancelled:
                temp_path.unlink(missing_ok=True)
                return
            async with transaction_scope(factory) as update_session:
                current = await update_session.scalar(
                    select(AuditExportJob).where(AuditExportJob.id == job_id).with_for_update()
                )
                if (
                    current is None
                    or current.status != "processing"
                    or current.revoked
                    or current.expires_at <= datetime.now(UTC)
                ):
                    temp_path.unlink(missing_ok=True)
                    return
                os.replace(temp_path, path)
                current.object_key = key
                current.status = "ready"
                current.completed_at = datetime.now(UTC)
                await update_session.flush()
    except Exception:
        temp_path.unlink(missing_ok=True)
        async with transaction_scope(factory) as session:
            job = await session.scalar(
                select(AuditExportJob).where(AuditExportJob.id == job_id).with_for_update()
            )
            if job is not None:
                job.status = "failed"
                job.failure_code = "export_failed"
        raise


async def run_once() -> int:
    settings = get_settings()
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL is required")
    require_project_database(settings.database_url)
    engine = create_database_engine(settings.database_url, schema=os.getenv("DATABASE_SCHEMA"))
    factory = create_session_factory(engine)
    completed = 0
    try:
        await prune_unavailable_files(factory, settings.resolved_private_storage_root)
        while job_id := await claim(factory):
            await process_job(factory, job_id, settings.resolved_private_storage_root)
            completed += 1
    finally:
        await engine.dispose()
    return completed


async def run_forever(interval_seconds: int) -> None:
    while True:
        try:
            await run_once()
        except Exception:
            # Keep the worker alive without leaking connection details into logs.
            print("Audit export cycle failed; will retry")
        await asyncio.sleep(interval_seconds)


async def prune_unavailable_files(
    factory: async_sessionmaker[AsyncSession], private_root: Path
) -> None:
    async with transaction_scope(factory) as session:
        now = datetime.now(UTC)
        stale_processing = (
            await session.scalars(
                select(AuditExportJob)
                .where(
                    AuditExportJob.status == "processing",
                    or_(
                        AuditExportJob.expires_at <= now,
                        AuditExportJob.updated_at < now - timedelta(minutes=10),
                    ),
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
        for job in stale_processing:
            job.status = "failed"
            job.failure_code = "export_expired" if job.expires_at <= now else "export_worker_lost"
        rows = (
            await session.scalars(
                select(AuditExportJob).where(
                    AuditExportJob.object_key.is_not(None),
                    or_(
                        AuditExportJob.revoked.is_(True),
                        AuditExportJob.expires_at <= now,
                    ),
                )
            )
        ).all()
        for job in rows:
            key = f"{job.id.hex}.csv"
            if job.object_key == key:
                (private_root / "exports" / key).unlink(missing_ok=True)
                job.object_key = None


def main() -> None:
    parser = argparse.ArgumentParser(description="Process queued audit exports")
    parser.add_argument("--once", action="store_true", help="process current queue then exit")
    parser.add_argument("--interval", type=int, default=5, help="poll interval in seconds")
    args = parser.parse_args()
    if args.interval < 1:
        parser.error("--interval must be positive")
    if args.once:
        print(f"Processed {asyncio.run(run_once())} audit export job(s)")
    else:
        asyncio.run(run_forever(args.interval))


if __name__ == "__main__":
    main()
