from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import ProductImageUpload, ProductImageUploadStatus


class ProductImageUploadRepository(Protocol):
    async def count_temporary(self, owner_id: UUID) -> int: ...

    async def create(
        self,
        *,
        upload_id: UUID,
        owner_id: UUID,
        original_key: str,
        thumbnail_key: str,
        original_filename: str,
        media_type: str,
        size_bytes: int,
        width: int,
        height: int,
        expires_at: datetime,
    ) -> ProductImageUpload: ...

    async def get_owned_temporary(
        self, owner_id: UUID, upload_id: UUID, *, for_update: bool = False
    ) -> ProductImageUpload | None: ...

    async def list_owned_temporary(
        self, owner_id: UUID, upload_ids: Sequence[UUID], *, for_update: bool = False
    ) -> Sequence[ProductImageUpload]: ...

    async def list_expired_temporary(self, now: datetime) -> Sequence[ProductImageUpload]: ...

    async def mark_deleted(self, upload: ProductImageUpload) -> None: ...

    def add_rollback_callback(self, callback: Callable[[], None]) -> None: ...


class SqlAlchemyProductImageUploadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def count_temporary(self, owner_id: UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count(ProductImageUpload.id)).where(
                    ProductImageUpload.owner_id == owner_id,
                    ProductImageUpload.status == ProductImageUploadStatus.TEMPORARY,
                )
            )
            or 0
        )

    async def create(
        self,
        *,
        upload_id: UUID,
        owner_id: UUID,
        original_key: str,
        thumbnail_key: str,
        original_filename: str,
        media_type: str,
        size_bytes: int,
        width: int,
        height: int,
        expires_at: datetime,
    ) -> ProductImageUpload:
        upload = ProductImageUpload(
            id=upload_id,
            owner_id=owner_id,
            original_key=original_key,
            thumbnail_key=thumbnail_key,
            original_filename=original_filename,
            media_type=media_type,
            size_bytes=size_bytes,
            width=width,
            height=height,
            expires_at=expires_at,
        )
        self.session.add(upload)
        await self.session.flush()
        return upload

    async def get_owned_temporary(
        self, owner_id: UUID, upload_id: UUID, *, for_update: bool = False
    ) -> ProductImageUpload | None:
        query = select(ProductImageUpload).where(
            ProductImageUpload.id == upload_id,
            ProductImageUpload.owner_id == owner_id,
            ProductImageUpload.status == ProductImageUploadStatus.TEMPORARY,
        )
        if for_update:
            query = query.with_for_update()
        return cast(ProductImageUpload | None, await self.session.scalar(query))

    async def list_owned_temporary(
        self, owner_id: UUID, upload_ids: Sequence[UUID], *, for_update: bool = False
    ) -> Sequence[ProductImageUpload]:
        if not upload_ids:
            return []
        query = select(ProductImageUpload).where(
            ProductImageUpload.id.in_(upload_ids),
            ProductImageUpload.owner_id == owner_id,
            ProductImageUpload.status == ProductImageUploadStatus.TEMPORARY,
        )
        if for_update:
            query = query.with_for_update()
        result = await self.session.scalars(query)
        return result.all()

    async def list_expired_temporary(self, now: datetime) -> Sequence[ProductImageUpload]:
        result = await self.session.scalars(
            select(ProductImageUpload)
            .where(
                ProductImageUpload.status == ProductImageUploadStatus.TEMPORARY,
                ProductImageUpload.expires_at < now,
            )
            .with_for_update(skip_locked=True)
        )
        return result.all()

    async def mark_deleted(self, upload: ProductImageUpload) -> None:
        upload.status = ProductImageUploadStatus.DELETED
        upload.deleted_at = datetime.now(UTC)
        await self.session.flush()

    def add_rollback_callback(self, callback: Callable[[], None]) -> None:
        callbacks = cast(
            list[Callable[[], None]],
            self.session.info.setdefault("rollback_callbacks", []),
        )
        callbacks.append(callback)
