from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from PIL import Image

from app.core.exceptions import AppError
from app.models.catalog import ProductImageUploadStatus
from app.services.product_images import ProductImageProcessor, ProductImageUploadService
from app.services.product_storage import LocalObjectStorage, S3CompatibleObjectStorage


def image_bytes(image_format: str = "JPEG", *, size: tuple[int, int] = (64, 48)) -> bytes:
    buffer = BytesIO()
    image = Image.new("RGB", size, (242, 108, 61))
    image.getexif()[0x010E] = "private metadata"
    image.save(buffer, format=image_format, exif=image.getexif())
    return buffer.getvalue()


class FakeUploadRepository:
    def __init__(self) -> None:
        self.uploads: dict[UUID, SimpleNamespace] = {}
        self.rollback_callbacks: list[Callable[[], None]] = []

    async def count_temporary(self, owner_id):  # type: ignore[no-untyped-def]
        return sum(
            item.owner_id == owner_id and item.status == ProductImageUploadStatus.TEMPORARY
            for item in self.uploads.values()
        )

    async def create(self, **values):  # type: ignore[no-untyped-def]
        item = SimpleNamespace(
            id=values.pop("upload_id"),
            status=ProductImageUploadStatus.TEMPORARY,
            deleted_at=None,
            **values,
        )
        self.uploads[item.id] = item
        return item

    async def get_owned_temporary(  # type: ignore[no-untyped-def]
        self, owner_id, upload_id, *, for_update=False
    ):
        item = self.uploads.get(upload_id)
        return (
            item
            if item
            and item.owner_id == owner_id
            and item.status == ProductImageUploadStatus.TEMPORARY
            else None
        )

    async def list_owned_temporary(  # type: ignore[no-untyped-def]
        self, owner_id, upload_ids, *, for_update=False
    ):
        return [
            item
            for upload_id in upload_ids
            if (item := self.uploads.get(upload_id))
            and item.owner_id == owner_id
            and item.status == ProductImageUploadStatus.TEMPORARY
        ]

    async def list_expired_temporary(self, now):  # type: ignore[no-untyped-def]
        return [
            item
            for item in self.uploads.values()
            if item.status == ProductImageUploadStatus.TEMPORARY and item.expires_at < now
        ]

    async def mark_deleted(self, upload):  # type: ignore[no-untyped-def]
        upload.status = ProductImageUploadStatus.DELETED
        upload.deleted_at = datetime.now(UTC)

    def add_rollback_callback(self, callback):  # type: ignore[no-untyped-def]
        self.rollback_callbacks.append(callback)


def test_processor_reencodes_image_and_removes_exif() -> None:
    processor = ProductImageProcessor(max_bytes=1_000_000, max_pixels=1_000_000)
    result = processor.process(
        image_bytes(), filename="market.jpg", claimed_media_type="image/jpeg"
    )
    with Image.open(BytesIO(result.original)) as normalized:
        assert normalized.size == (64, 48)
        assert not normalized.getexif()
    with Image.open(BytesIO(result.thumbnail)) as thumbnail:
        assert thumbnail.format == "WEBP"


@pytest.mark.parametrize(
    ("content", "filename", "media_type", "code"),
    [
        (b"<svg><script>alert(1)</script></svg>", "photo.svg", "image/svg+xml", "invalid_image"),
        (image_bytes(), "photo.png", "image/jpeg", "image_extension_mismatch"),
        (image_bytes(), "photo.jpg", "image/png", "image_media_type_mismatch"),
    ],
)
def test_processor_rejects_unsafe_or_disguised_files(
    content: bytes, filename: str, media_type: str, code: str
) -> None:
    processor = ProductImageProcessor(max_bytes=1_000_000, max_pixels=1_000_000)
    with pytest.raises(AppError) as error:
        processor.process(content, filename=filename, claimed_media_type=media_type)
    assert error.value.code == code


@pytest.mark.anyio
async def test_upload_uses_temporary_random_keys_and_cleanup_window(tmp_path) -> None:  # type: ignore[no-untyped-def]
    repository = FakeUploadRepository()
    storage = LocalObjectStorage(tmp_path)
    service = ProductImageUploadService(
        repository=repository,
        storage=storage,
        processor=ProductImageProcessor(max_bytes=1_000_000, max_pixels=1_000_000),
        max_uploads=4,
        upload_hours=24,
    )
    owner_id = uuid4()
    upload = await service.upload(
        owner_id=owner_id,
        filename="book.jpg",
        claimed_media_type="image/jpeg",
        content=image_bytes(),
    )
    assert upload.original_key.startswith(f"temporary/{owner_id}/{upload.id}/")
    assert storage.path_for(upload.original_key).is_file()
    assert storage.path_for(upload.thumbnail_key).is_file()
    assert len(repository.rollback_callbacks) == 1

    upload.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert await service.cleanup_expired() == 1
    assert not storage.path_for(upload.original_key).exists()
    assert upload.status == ProductImageUploadStatus.DELETED


def test_storage_adapters_reject_traversal_and_s3_move_is_copy_then_delete(tmp_path) -> None:  # type: ignore[no-untyped-def]
    local = LocalObjectStorage(tmp_path)
    with pytest.raises(AppError):
        local.put("../escape.jpg", b"data", media_type="image/jpeg")

    class Client:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def put_object(self, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(("put", kwargs))

        def copy_object(self, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(("copy", kwargs))

        def delete_object(self, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(("delete", kwargs))

    client = Client()
    s3 = S3CompatibleObjectStorage(client, "products")
    s3.move("temporary/a.jpg", "products/a.jpg")
    assert [call[0] for call in client.calls] == ["copy", "delete"]
    with pytest.raises(AppError):
        s3.delete("../escape.jpg")
