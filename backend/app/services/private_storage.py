from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from app.core.exceptions import AppError

MEDIA_EXTENSIONS = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


@dataclass(frozen=True)
class StoredMaterial:
    key: str
    original_filename: str
    media_type: str
    size_bytes: int


class PrivateAppealStorage:
    def __init__(self, root: Path, *, max_bytes: int) -> None:
        self._root = root.resolve()
        self._max_bytes = max_bytes

    def save(
        self,
        *,
        user_id: UUID,
        filename: str | None,
        declared_media_type: str | None,
        content: bytes,
    ) -> StoredMaterial:
        if not content or len(content) > self._max_bytes:
            raise AppError(
                status_code=422,
                code="appeal_material_size_invalid",
                message=f"申诉材料必须小于 {self._max_bytes // (1024 * 1024)} MB",
            )
        detected_media_type = detect_media_type(content)
        if detected_media_type is None or declared_media_type != detected_media_type:
            raise AppError(
                status_code=422,
                code="appeal_material_type_invalid",
                message="申诉材料仅支持 PDF、PNG 或 JPEG",
            )
        candidate = (filename or "material").replace("\\", "/").rsplit("/", 1)[-1]
        safe_filename = "".join(character for character in candidate if ord(character) >= 32)[:255]
        if not safe_filename:
            safe_filename = f"material{MEDIA_EXTENSIONS[detected_media_type]}"
        key = (
            Path("campus-appeals")
            / str(user_id)
            / f"{uuid4().hex}{MEDIA_EXTENSIONS[detected_media_type]}"
        ).as_posix()
        target = self.resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(content)
        return StoredMaterial(
            key=key,
            original_filename=safe_filename,
            media_type=detected_media_type,
            size_bytes=len(content),
        )

    def resolve(self, key: str) -> Path:
        target = (self._root / key).resolve()
        if not target.is_relative_to(self._root):
            raise AppError(
                status_code=404,
                code="appeal_material_not_found",
                message="未找到申诉材料",
            )
        return target

    def remove(self, key: str) -> None:
        self.resolve(key).unlink(missing_ok=True)


def detect_media_type(content: bytes) -> str | None:
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None
