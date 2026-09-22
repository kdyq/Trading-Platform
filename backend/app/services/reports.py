from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from app.core.exceptions import AppError
from app.models.moderation import ModerationTargetType, Report, ReportStatus
from app.repositories.reports import SqlAlchemyReportRepository
from app.schemas.reports import (
    ReportEventResponse,
    ReportEvidenceResponse,
    ReportListResponse,
    ReportResponse,
)
from app.services.report_storage import PrivateReportStorage


@dataclass(frozen=True)
class EvidenceDownload:
    path: Path
    media_type: str
    filename: str


class ReportService:
    def __init__(
        self,
        repository: SqlAlchemyReportRepository,
        storage: PrivateReportStorage,
        *,
        hourly_limit: int,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.hourly_limit = hourly_limit

    async def create(
        self,
        *,
        reporter_id: UUID,
        target_type: str,
        target_id: UUID,
        reason_code: str,
        details: str,
    ) -> ReportResponse:
        target = ModerationTargetType(target_type)
        subject_user_id = await self.repository.target_subject(
            reporter_id=reporter_id, target_type=target, target_id=target_id
        )
        if subject_user_id is None:
            raise AppError(
                status_code=404, code="report_target_not_found", message="举报对象不存在"
            )
        if await self.repository.recent_count(reporter_id) >= self.hourly_limit:
            existing = await self.repository.find_key(
                reporter_id=reporter_id,
                target_type=target,
                target_id=target_id,
                reason_code=reason_code,
            )
            if existing is not None:
                return await self._response(existing)
            raise AppError(status_code=429, code="report_rate_limited", message="举报提交过于频繁")
        report, _ = await self.repository.create_or_get(
            reporter_id=reporter_id,
            target_type=target,
            target_id=target_id,
            reason_code=reason_code,
            details=details,
            subject_user_id=subject_user_id,
        )
        return await self._response(report)

    async def list_owned(self, reporter_id: UUID) -> ReportListResponse:
        reports = await self.repository.list_owned(reporter_id)
        return ReportListResponse(items=[await self._response(report) for report in reports])

    async def detail(self, reporter_id: UUID, report_id: UUID) -> ReportResponse:
        report = await self.repository.get_owned(report_id, reporter_id)
        if report is None:
            raise AppError(status_code=404, code="report_not_found", message="举报记录不存在")
        return await self._response(report)

    async def withdraw(self, reporter_id: UUID, report_id: UUID) -> ReportResponse:
        report = await self.repository.get_owned(report_id, reporter_id, lock=True)
        if report is None:
            raise AppError(status_code=404, code="report_not_found", message="举报记录不存在")
        if report.status == ReportStatus.WITHDRAWN:
            return await self._response(report)
        if report.status != ReportStatus.OPEN:
            raise AppError(
                status_code=409, code="report_not_withdrawable", message="当前举报不能撤回"
            )
        previous = report.status
        report.status = ReportStatus.WITHDRAWN
        report.withdrawn_at = datetime.now(UTC)
        self.repository.add_event(
            report=report,
            actor_id=reporter_id,
            from_status=previous,
            to_status=ReportStatus.WITHDRAWN,
            public_note="举报人已撤回",
        )
        return await self._response(report)

    async def upload_evidence(
        self,
        *,
        reporter_id: UUID,
        report_id: UUID,
        filename: str | None,
        media_type: str | None,
        content: bytes,
    ) -> ReportEvidenceResponse:
        report = await self.repository.get_owned(report_id, reporter_id, lock=True)
        if report is None:
            raise AppError(status_code=404, code="report_not_found", message="举报记录不存在")
        if report.status in {ReportStatus.RESOLVED, ReportStatus.DISMISSED, ReportStatus.WITHDRAWN}:
            raise AppError(
                status_code=409, code="report_evidence_closed", message="当前举报不能追加证据"
            )
        stored = self.storage.save(
            reporter_id=reporter_id,
            report_id=report_id,
            filename=filename,
            declared_media_type=media_type,
            content=content,
        )
        self.repository.session.info.setdefault("rollback_callbacks", []).append(
            lambda: self.storage.remove(stored.key)
        )
        evidence, created = await self.repository.add_evidence(
            report_id=report.id,
            uploader_id=reporter_id,
            object_key=stored.key,
            original_filename=stored.original_filename,
            media_type=stored.media_type,
            size_bytes=stored.size_bytes,
            sha256=sha256(content).hexdigest(),
        )
        if not created:
            self.storage.remove(stored.key)
        return ReportEvidenceResponse(
            id=evidence.id,
            original_filename=evidence.original_filename,
            media_type=evidence.media_type,
            size_bytes=evidence.size_bytes,
            created_at=evidence.created_at,
        )

    async def download_evidence(
        self, *, reporter_id: UUID, report_id: UUID, evidence_id: UUID
    ) -> EvidenceDownload:
        report = await self.repository.get_owned(report_id, reporter_id)
        evidence = await self.repository.get_evidence(evidence_id)
        if report is None or evidence is None or evidence.report_id != report.id:
            raise AppError(
                status_code=404, code="report_evidence_not_found", message="举报证据不存在"
            )
        path = self.storage.resolve(evidence.object_key)
        if not path.is_file():
            raise AppError(
                status_code=404, code="report_evidence_not_found", message="举报证据不存在"
            )
        return EvidenceDownload(path, evidence.media_type, evidence.original_filename)

    async def _response(self, report: Report) -> ReportResponse:
        evidence = await self.repository.evidence(report.id)
        events = await self.repository.events(report.id)
        return ReportResponse(
            id=report.id,
            target_type=report.target_type.value,
            target_id=report.target_id,
            reason_code=report.reason_code,
            details=report.details,
            status=report.status.value,
            public_result=report.public_result,
            version=report.version,
            evidence=[
                ReportEvidenceResponse(
                    id=item.id,
                    original_filename=item.original_filename,
                    media_type=item.media_type,
                    size_bytes=item.size_bytes,
                    created_at=item.created_at,
                )
                for item in evidence
            ],
            events=[
                ReportEventResponse(
                    id=item.id,
                    from_status=item.from_status.value if item.from_status else None,
                    to_status=item.to_status.value,
                    public_note=item.public_note,
                    created_at=item.created_at,
                )
                for item in events
            ],
            created_at=report.created_at,
            updated_at=report.updated_at,
        )
