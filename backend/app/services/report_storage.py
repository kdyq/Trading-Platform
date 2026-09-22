from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from app.core.exceptions import AppError
from app.services.private_storage import MEDIA_EXTENSIONS, detect_media_type


@dataclass(frozen=True)
class StoredReportEvidence:
    key: str
    original_filename: str
    media_type: str
    size_bytes: int


class PrivateReportStorage:
    def __init__(self, root: Path, *, max_bytes: int) -> None:
        self.root = root.resolve()
        self.max_bytes = max_bytes

    def save(
        self,
        *,
        reporter_id: UUID,
        report_id: UUID,
        filename: str | None,
        declared_media_type: str | None,
        content: bytes,
    ) -> StoredReportEvidence:
        if not content or len(content) > self.max_bytes:
            raise AppError(
                status_code=413,
                code="report_evidence_size_invalid",
                message=f"举报证据必须小于 {self.max_bytes // (1024 * 1024)} MB",
            )
        media_type = detect_media_type(content)
        if media_type is None or media_type != declared_media_type:
            raise AppError(
                status_code=422,
                code="report_evidence_type_invalid",
                message="举报证据仅支持 PDF、PNG 或 JPEG",
            )
        candidate = (filename or "evidence").replace("\\", "/").rsplit("/", 1)[-1]
        safe_filename = "".join(character for character in candidate if ord(character) >= 32)[:255]
        if not safe_filename:
            safe_filename = f"evidence{MEDIA_EXTENSIONS[media_type]}"
        key = (
            Path("report-evidence")
            / str(reporter_id)
            / str(report_id)
            / f"{uuid4().hex}{MEDIA_EXTENSIONS[media_type]}"
        ).as_posix()
        target = self.resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(content)
        return StoredReportEvidence(key, safe_filename, media_type, len(content))

    def resolve(self, key: str) -> Path:
        target = (self.root / key).resolve()
        if not target.is_relative_to(self.root):
            raise AppError(
                status_code=404, code="report_evidence_not_found", message="举报证据不存在"
            )
        return target

    def remove(self, key: str) -> None:
        self.resolve(key).unlink(missing_ok=True)
