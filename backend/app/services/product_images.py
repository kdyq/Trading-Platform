from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.exceptions import AppError
from app.models.catalog import ProductImageUpload
from app.models.identity import UserStatus
from app.repositories.product_images import ProductImageUploadRepository
from app.services.product_storage import ObjectStorage

FORMAT_RULES = {
    "JPEG": ("image/jpeg", ".jpg", {".jpg", ".jpeg"}),
    "PNG": ("image/png", ".png", {".png"}),
    "WEBP": ("image/webp", ".webp", {".webp"}),
}


@dataclass(frozen=True)
class ProcessedImage:
    original: bytes
    thumbnail: bytes
    media_type: str
    extension: str
    width: int
    height: int


class ProductImageProcessor:
    def __init__(self, *, max_bytes: int, max_pixels: int) -> None:
        self.max_bytes = max_bytes
        self.max_pixels = max_pixels

    def process(
        self, content: bytes, *, filename: str, claimed_media_type: str | None
    ) -> ProcessedImage:
        if not content:
            raise AppError(status_code=422, code="empty_image", message="图片内容为空")
        if len(content) > self.max_bytes:
            raise AppError(status_code=413, code="image_too_large", message="图片文件过大")
        try:
            with Image.open(BytesIO(content)) as probe:
                detected_format = probe.format
                width, height = probe.size
                probe.verify()
            if detected_format not in FORMAT_RULES:
                raise AppError(
                    status_code=422, code="unsupported_image", message="仅支持 JPEG、PNG 和 WebP"
                )
            media_type, extension, allowed_extensions = FORMAT_RULES[detected_format]
            if Path(filename).suffix.lower() not in allowed_extensions:
                raise AppError(
                    status_code=422,
                    code="image_extension_mismatch",
                    message="图片扩展名与内容不一致",
                )
            if claimed_media_type and claimed_media_type != media_type:
                raise AppError(
                    status_code=422,
                    code="image_media_type_mismatch",
                    message="图片类型与内容不一致",
                )
            if width * height > self.max_pixels:
                raise AppError(
                    status_code=422, code="image_dimensions_too_large", message="图片像素尺寸过大"
                )
            with Image.open(BytesIO(content)) as opened:
                normalized = ImageOps.exif_transpose(opened)
                normalized.load()
                original = self._encode(normalized, detected_format)
                thumbnail_image = normalized.copy()
                thumbnail_image.thumbnail((640, 640), Image.Resampling.LANCZOS)
                thumbnail = self._encode(thumbnail_image, "WEBP")
                width, height = normalized.size
        except AppError:
            raise
        except (Image.DecompressionBombError, OSError, UnidentifiedImageError, ValueError) as exc:
            raise AppError(
                status_code=422, code="invalid_image", message="图片已损坏或无法解析"
            ) from exc
        return ProcessedImage(
            original=original,
            thumbnail=thumbnail,
            media_type=media_type,
            extension=extension,
            width=width,
            height=height,
        )

    @staticmethod
    def _encode(image: Image.Image, image_format: str) -> bytes:
        output = BytesIO()
        if image_format == "JPEG":
            image.convert("RGB").save(output, format="JPEG", quality=88, optimize=True)
        elif image_format == "PNG":
            image.save(output, format="PNG", optimize=True)
        else:
            image.save(output, format="WEBP", quality=84, method=4)
        return output.getvalue()


class ProductImageUploadService:
    def __init__(
        self,
        *,
        repository: ProductImageUploadRepository,
        storage: ObjectStorage,
        processor: ProductImageProcessor,
        max_uploads: int,
        upload_hours: int,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.processor = processor
        self.max_uploads = max_uploads
        self.upload_hours = upload_hours

    async def upload(
        self,
        *,
        owner_id: UUID,
        filename: str,
        claimed_media_type: str | None,
        content: bytes,
    ) -> ProductImageUpload:
        owner = await self.repository.lock_owner(owner_id)
        if owner is None or owner.deleted_at is not None or owner.status != UserStatus.ACTIVE:
            raise AppError(
                status_code=403, code="account_unavailable", message="账户当前不可上传图片"
            )
        if await self.repository.count_temporary(owner_id) >= self.max_uploads:
            raise AppError(
                status_code=409, code="too_many_image_uploads", message="待处理图片数量已达上限"
            )
        processed = self.processor.process(
            content,
            filename=filename,
            claimed_media_type=claimed_media_type,
        )
        upload_id = uuid4()
        prefix = f"temporary/{owner_id}/{upload_id}"
        original_key = f"{prefix}/original{processed.extension}"
        thumbnail_key = f"{prefix}/thumbnail.webp"
        self.storage.put(original_key, processed.original, media_type=processed.media_type)
        try:
            self.storage.put(thumbnail_key, processed.thumbnail, media_type="image/webp")
        except BaseException:
            self.storage.delete(original_key)
            raise
        self.repository.add_rollback_callback(
            lambda: self._delete_objects(original_key, thumbnail_key)
        )
        return await self.repository.create(
            upload_id=upload_id,
            owner_id=owner_id,
            original_key=original_key,
            thumbnail_key=thumbnail_key,
            original_filename=Path(filename).name[:255],
            media_type=processed.media_type,
            size_bytes=len(processed.original),
            width=processed.width,
            height=processed.height,
            expires_at=datetime.now(UTC) + timedelta(hours=self.upload_hours),
        )

    async def discard(self, owner_id: UUID, upload_id: UUID) -> None:
        upload = await self.repository.get_owned_temporary(owner_id, upload_id, for_update=True)
        if upload is None:
            return
        self._delete_objects(upload.original_key, upload.thumbnail_key)
        await self.repository.mark_deleted(upload)

    async def cleanup_expired(self, *, now: datetime | None = None) -> int:
        uploads = await self.repository.list_expired_temporary(now or datetime.now(UTC))
        for upload in uploads:
            self._delete_objects(upload.original_key, upload.thumbnail_key)
            await self.repository.mark_deleted(upload)
        return len(uploads)

    def _delete_objects(self, original_key: str, thumbnail_key: str) -> None:
        self.storage.delete(original_key)
        self.storage.delete(thumbnail_key)
