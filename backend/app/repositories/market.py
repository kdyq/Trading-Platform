from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import ColumnElement, Select, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Category, Product, ProductStatus
from app.models.identity import Campus, CampusVerification, CampusVerificationStatus, School, User


@dataclass(frozen=True)
class PublicProductRecord:
    id: UUID
    seller_id: UUID
    title: str
    price: Decimal
    status: str
    published_at: datetime | None
    campus_name: str
    school_name: str
    seller_name: str
    seller_verified: bool
    category_code: str
    category_name: str


@dataclass(frozen=True)
class PublicMarketCounts:
    available_products: int
    active_campuses: int
    verified_sellers: int


class MarketRepository(Protocol):
    async def list_categories(self) -> Sequence[Category]: ...

    async def list_latest_products(self, *, limit: int) -> Sequence[PublicProductRecord]: ...

    async def count_latest_products(self) -> int: ...

    async def get_summary(self) -> PublicMarketCounts: ...


class SqlAlchemyMarketRepository:
    PUBLIC_STATUSES = (ProductStatus.ON_SALE, ProductStatus.RESERVED)

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _verified_seller(self) -> ColumnElement[bool]:
        now = datetime.now(UTC)
        return select(
            exists().where(
                CampusVerification.user_id == Product.seller_id,
                CampusVerification.deleted_at.is_(None),
                CampusVerification.status == CampusVerificationStatus.VERIFIED,
                CampusVerification.expires_at > now,
            )
        ).scalar_subquery()

    def _public_product_query(self) -> Select[tuple[object, ...]]:
        return (
            select(
                Product.id,
                Product.seller_id,
                Product.title,
                Product.price,
                Product.status,
                Product.published_at,
                Campus.name.label("campus_name"),
                School.name.label("school_name"),
                User.display_name.label("seller_name"),
                self._verified_seller().label("seller_verified"),
                Category.code.label("category_code"),
                Category.name.label("category_name"),
            )
            .join(Campus, Campus.id == Product.campus_id)
            .join(School, School.id == Campus.school_id)
            .join(User, User.id == Product.seller_id)
            .join(Category, Category.id == Product.category_id)
            .where(
                Product.deleted_at.is_(None),
                Product.status.in_(self.PUBLIC_STATUSES),
                Campus.deleted_at.is_(None),
                School.deleted_at.is_(None),
                User.deleted_at.is_(None),
                Category.deleted_at.is_(None),
                Category.is_active.is_(True),
            )
        )

    async def list_categories(self) -> Sequence[Category]:
        result = await self.session.scalars(
            select(Category)
            .where(Category.deleted_at.is_(None), Category.is_active.is_(True))
            .order_by(Category.display_order, Category.name)
        )
        return result.all()

    async def list_latest_products(self, *, limit: int) -> Sequence[PublicProductRecord]:
        result = await self.session.execute(
            self._public_product_query()
            .order_by(
                Product.published_at.desc().nulls_last(), Product.created_at.desc(), Product.id
            )
            .limit(limit)
        )
        return [PublicProductRecord(**dict(row._mapping)) for row in result]

    async def count_latest_products(self) -> int:
        return int(
            await self.session.scalar(
                select(func.count(Product.id)).where(
                    Product.deleted_at.is_(None), Product.status.in_(self.PUBLIC_STATUSES)
                )
            )
            or 0
        )

    async def get_summary(self) -> PublicMarketCounts:
        base = self._public_product_query().subquery()
        row = (
            await self.session.execute(
                select(
                    func.count(base.c.id),
                    func.count(func.distinct(base.c.campus_name)),
                    func.count(func.distinct(base.c.seller_id)).filter(
                        base.c.seller_verified.is_(True)
                    ),
                )
            )
        ).one()
        return PublicMarketCounts(
            available_products=int(row[0] or 0),
            active_campuses=int(row[1] or 0),
            verified_sellers=int(row[2] or 0),
        )
