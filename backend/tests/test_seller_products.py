from collections.abc import Callable
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from PIL import Image

from app.core.exceptions import AppError
from app.models.catalog import ProductImageUploadStatus, ProductStatus
from app.schemas.seller_products import (
    ProductImageReference,
    SellerProductCreate,
    SellerProductUpdate,
)
from app.services.product_images import ProductImageProcessor, ProductImageUploadService
from app.services.product_storage import LocalObjectStorage
from app.services.seller_products import SellerProductService


class FakeProductRepository:
    def __init__(self, owner_id: UUID) -> None:
        self.owner_id = owner_id
        self.campus_id = uuid4()
        self.category_id = uuid4()
        self.products: dict[UUID, Any] = {}
        self.rollback_callbacks: list[Callable[[], None]] = []

    async def verified_campus_id(self, user_id):  # type: ignore[no-untyped-def]
        return self.campus_id if user_id == self.owner_id else None

    async def is_active_category(self, category_id):  # type: ignore[no-untyped-def]
        return category_id == self.category_id

    async def is_active_campus(self, campus_id):  # type: ignore[no-untyped-def]
        return campus_id == self.campus_id

    async def create(self, product):  # type: ignore[no-untyped-def]
        product.id = uuid4()
        product.version = 1
        product.updated_at = datetime.now(UTC)
        self.products[product.id] = product
        return product

    async def list_owned(self, owner_id):  # type: ignore[no-untyped-def]
        return [item for item in self.products.values() if item.seller_id == owner_id]

    async def get_owned(self, owner_id, product_id, *, for_update=False):  # type: ignore[no-untyped-def]
        item = self.products.get(product_id)
        return item if item and item.seller_id == owner_id else None

    async def add_image(self, image):  # type: ignore[no-untyped-def]
        return None

    async def flush(self) -> None:
        return None

    def add_rollback_callback(self, callback):  # type: ignore[no-untyped-def]
        self.rollback_callbacks.append(callback)


class FakeUploadRepository:
    def __init__(self) -> None:
        self.uploads: dict[UUID, Any] = {}
        self.rollback_callbacks: list[Callable[[], None]] = []

    async def count_temporary(self, owner_id):  # type: ignore[no-untyped-def]
        return 0

    async def create(self, **values):  # type: ignore[no-untyped-def]
        item = SimpleNamespace(
            id=values.pop("upload_id"),
            status=ProductImageUploadStatus.TEMPORARY,
            confirmed_at=None,
            deleted_at=None,
            **values,
        )
        self.uploads[item.id] = item
        return item

    async def get_owned_temporary(  # type: ignore[no-untyped-def]
        self, owner_id, upload_id, *, for_update=False
    ):
        item = self.uploads.get(upload_id)
        return item if item and item.owner_id == owner_id else None

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
        return []

    async def mark_deleted(self, upload):  # type: ignore[no-untyped-def]
        upload.status = ProductImageUploadStatus.DELETED

    def add_rollback_callback(self, callback):  # type: ignore[no-untyped-def]
        self.rollback_callbacks.append(callback)


def jpeg() -> bytes:
    output = BytesIO()
    Image.new("RGB", (80, 60), "orange").save(output, format="JPEG")
    return output.getvalue()


@pytest.mark.anyio
async def test_verified_owner_can_save_images_and_submit_complete_draft(tmp_path) -> None:  # type: ignore[no-untyped-def]
    owner_id = uuid4()
    products = FakeProductRepository(owner_id)
    uploads = FakeUploadRepository()
    storage = LocalObjectStorage(tmp_path)
    upload_service = ProductImageUploadService(
        repository=uploads,
        storage=storage,
        processor=ProductImageProcessor(max_bytes=1_000_000, max_pixels=1_000_000),
        max_uploads=8,
        upload_hours=24,
    )
    image_upload = await upload_service.upload(
        owner_id=owner_id,
        filename="book.jpg",
        claimed_media_type="image/jpeg",
        content=jpeg(),
    )
    service = SellerProductService(repository=products, uploads=uploads, storage=storage)
    draft = await service.create(
        owner_id,
        SellerProductCreate(
            title="高等数学教材",
            description="有少量课堂笔记，页面完整，没有缺页和明显污损。",
            price="18.50",
            original_price="49.00",
            category_id=products.category_id,
            campus_id=products.campus_id,
            delivery_notes="东门自提",
        ),
    )
    saved = await service.update(
        owner_id,
        draft.id,
        SellerProductUpdate(
            version=draft.version,
            images=[ProductImageReference(kind="upload", id=image_upload.id)],
        ),
    )
    assert saved.images[0].display_order == 0
    assert image_upload.status == ProductImageUploadStatus.CONFIRMED
    assert storage.path_for(image_upload.original_key).is_file()
    assert saved.images[0].url.endswith(f"/{saved.images[0].id}")
    assert products.rollback_callbacks == []

    submitted = await service.submit(owner_id, draft.id, saved.version)
    assert submitted.status == "pending_review"
    assert (await service.submit(owner_id, draft.id, 1)).status == "pending_review"


@pytest.mark.anyio
async def test_incomplete_draft_cannot_submit_and_pending_draft_must_be_withdrawn(
    tmp_path: Path,
) -> None:
    owner_id = uuid4()
    products = FakeProductRepository(owner_id)
    service = SellerProductService(
        repository=products,
        uploads=FakeUploadRepository(),
        storage=LocalObjectStorage(tmp_path),
    )
    draft = await service.create(
        owner_id,
        SellerProductCreate(category_id=products.category_id, campus_id=products.campus_id),
    )
    with pytest.raises(AppError) as incomplete:
        await service.submit(owner_id, draft.id, draft.version)
    assert incomplete.value.code == "invalid_product_title"

    product = products.products[draft.id]
    product.status = ProductStatus.PENDING_REVIEW
    with pytest.raises(AppError) as editing:
        await service.update(
            owner_id,
            draft.id,
            SellerProductUpdate(version=draft.version, title="不能直接修改"),
        )
    assert editing.value.code == "product_not_editable"
    withdrawn = await service.withdraw(owner_id, draft.id, draft.version)
    assert withdrawn.status == "draft"


@pytest.mark.anyio
async def test_owner_and_version_are_enforced(tmp_path) -> None:  # type: ignore[no-untyped-def]
    owner_id = uuid4()
    products = FakeProductRepository(owner_id)
    service = SellerProductService(
        repository=products,
        uploads=FakeUploadRepository(),
        storage=LocalObjectStorage(tmp_path),
    )
    draft = await service.create(
        owner_id,
        SellerProductCreate(category_id=products.category_id, campus_id=products.campus_id),
    )
    with pytest.raises(AppError) as hidden:
        await service.get_owned(uuid4(), draft.id)
    assert hidden.value.status_code == 404
    products.products[draft.id].version = 2
    with pytest.raises(AppError) as conflict:
        await service.update(
            owner_id,
            draft.id,
            SellerProductUpdate(version=1, title="版本冲突商品"),
        )
    assert conflict.value.code == "product_version_conflict"
