from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import Category, Product, ProductImage
from app.models.identity import Campus, CampusVerification, CampusVerificationStatus, School


class SellerProductRepository(Protocol):
    async def verified_campus_id(self, user_id: UUID) -> UUID | None: ...

    async def is_active_category(self, category_id: UUID) -> bool: ...

    async def is_active_campus(self, campus_id: UUID) -> bool: ...

    async def create(self, product: Product) -> Product: ...

    async def list_owned(self, owner_id: UUID) -> Sequence[Product]: ...

    async def get_owned(
        self, owner_id: UUID, product_id: UUID, *, for_update: bool = False
    ) -> Product | None: ...

    async def add_image(self, image: ProductImage) -> None: ...

    async def flush(self) -> None: ...

    def add_rollback_callback(self, callback: Callable[[], None]) -> None: ...


class SqlAlchemySellerProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def verified_campus_id(self, user_id: UUID) -> UUID | None:
        now = datetime.now(UTC)
        return cast(
            UUID | None,
            await self.session.scalar(
                select(CampusVerification.campus_id)
                .where(
                    CampusVerification.user_id == user_id,
                    CampusVerification.deleted_at.is_(None),
                    CampusVerification.status == CampusVerificationStatus.VERIFIED,
                    CampusVerification.expires_at > now,
                )
                .order_by(CampusVerification.verified_at.desc().nulls_last())
                .limit(1)
            ),
        )

    async def is_active_category(self, category_id: UUID) -> bool:
        found = await self.session.scalar(
            select(Category.id).where(
                Category.id == category_id,
                Category.deleted_at.is_(None),
                Category.is_active.is_(True),
            )
        )
        return found is not None

    async def is_active_campus(self, campus_id: UUID) -> bool:
        found = await self.session.scalar(
            select(Campus.id)
            .join(School, School.id == Campus.school_id)
            .where(
                Campus.id == campus_id,
                Campus.deleted_at.is_(None),
                Campus.is_active.is_(True),
                School.deleted_at.is_(None),
                School.is_active.is_(True),
            )
        )
        return found is not None

    async def create(self, product: Product) -> Product:
        self.session.add(product)
        await self.session.flush()
        return product

    async def list_owned(self, owner_id: UUID) -> Sequence[Product]:
        result = await self.session.scalars(
            select(Product)
            .options(selectinload(Product.images))
            .where(Product.seller_id == owner_id, Product.deleted_at.is_(None))
            .order_by(Product.updated_at.desc(), Product.id)
        )
        return result.unique().all()

    async def get_owned(
        self, owner_id: UUID, product_id: UUID, *, for_update: bool = False
    ) -> Product | None:
        query = (
            select(Product)
            .options(selectinload(Product.images))
            .where(
                Product.id == product_id,
                Product.seller_id == owner_id,
                Product.deleted_at.is_(None),
            )
        )
        if for_update:
            query = query.with_for_update()
        return cast(Product | None, await self.session.scalar(query))

    async def add_image(self, image: ProductImage) -> None:
        self.session.add(image)
        await self.session.flush()

    async def flush(self) -> None:
        await self.session.flush()

    def add_rollback_callback(self, callback: Callable[[], None]) -> None:
        callbacks = cast(
            list[Callable[[], None]], self.session.info.setdefault("rollback_callbacks", [])
        )
        callbacks.append(callback)
