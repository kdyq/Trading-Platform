from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import ColumnElement, Select, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Category, Product, ProductCondition, ProductImage, ProductStatus
from app.models.identity import (
    Campus,
    CampusVerification,
    CampusVerificationStatus,
    School,
    User,
    UserStatus,
)
from app.models.trade import Order, OrderStatus, Review


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
    category_id: UUID
    category_code: str
    category_name: str
    condition: str
    is_negotiable: bool
    view_count: int


@dataclass(frozen=True)
class PublicProductDetailRecord(PublicProductRecord):
    description: str
    seller_review_count: int
    seller_average_rating: Decimal | None
    seller_completed_orders: int


@dataclass(frozen=True)
class PublicProductImageRecord:
    id: UUID
    object_key: str
    thumbnail_object_key: str
    alt_text: str | None


@dataclass(frozen=True)
class PublicProductFilters:
    keyword: str | None = None
    category: str | None = None
    campus_id: UUID | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    condition: ProductCondition | None = None
    negotiable: bool | None = None
    status: ProductStatus | None = None
    sort: str = "newest"


@dataclass(frozen=True)
class PublicMarketCounts:
    available_products: int
    active_campuses: int
    verified_sellers: int


class MarketRepository(Protocol):
    async def list_categories(self) -> Sequence[Category]: ...

    async def list_latest_products(self, *, limit: int) -> Sequence[PublicProductRecord]: ...

    async def list_campuses(self) -> Sequence[tuple[UUID, str, str]]: ...

    async def search_products(
        self, *, filters: PublicProductFilters, offset: int, limit: int
    ) -> tuple[Sequence[PublicProductRecord], int]: ...

    async def get_product(self, product_id: UUID) -> PublicProductDetailRecord | None: ...

    async def list_similar_products(
        self, *, product_id: UUID, category_id: UUID, limit: int
    ) -> Sequence[PublicProductRecord]: ...

    async def list_product_images(self, product_id: UUID) -> Sequence[PublicProductImageRecord]: ...

    async def get_product_image(self, image_id: UUID) -> PublicProductImageRecord | None: ...

    async def count_latest_products(self) -> int: ...

    async def get_summary(self) -> PublicMarketCounts: ...


class SqlAlchemyMarketRepository:
    PUBLIC_STATUSES = (ProductStatus.ON_SALE, ProductStatus.RESERVED)
    ALL_PUBLIC_STATUSES = (*PUBLIC_STATUSES, ProductStatus.SOLD)

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _verified_seller(self) -> ColumnElement[bool]:
        now = datetime.now(UTC)
        return select(
            exists()
            .where(
                CampusVerification.user_id == Product.seller_id,
                CampusVerification.deleted_at.is_(None),
                CampusVerification.status == CampusVerificationStatus.VERIFIED,
                CampusVerification.expires_at > now,
            )
            .correlate(Product)
        ).scalar_subquery()

    def _public_product_query(
        self, statuses: tuple[ProductStatus, ...] | None = None
    ) -> Select[tuple[object, ...]]:
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
                Category.id.label("category_id"),
                Category.code.label("category_code"),
                Category.name.label("category_name"),
                Product.condition,
                Product.is_negotiable,
                Product.view_count,
            )
            .join(Campus, Campus.id == Product.campus_id)
            .join(School, School.id == Campus.school_id)
            .join(User, User.id == Product.seller_id)
            .join(Category, Category.id == Product.category_id)
            .where(
                Product.deleted_at.is_(None),
                Product.status.in_(statuses or self.PUBLIC_STATUSES),
                Campus.deleted_at.is_(None),
                School.deleted_at.is_(None),
                User.deleted_at.is_(None),
                User.status == UserStatus.ACTIVE,
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

    async def list_campuses(self) -> Sequence[tuple[UUID, str, str]]:
        result = await self.session.execute(
            select(Campus.id, Campus.name, School.name)
            .join(School, School.id == Campus.school_id)
            .where(
                Campus.deleted_at.is_(None),
                School.deleted_at.is_(None),
                Campus.is_active.is_(True),
                School.is_active.is_(True),
            )
            .order_by(School.name, Campus.name)
        )
        return [(row[0], row[1], row[2]) for row in result]

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
        base = self._public_product_query().subquery()
        return int(await self.session.scalar(select(func.count(base.c.id))) or 0)

    async def search_products(
        self, *, filters: PublicProductFilters, offset: int, limit: int
    ) -> tuple[Sequence[PublicProductRecord], int]:
        query = self._public_product_query(self.ALL_PUBLIC_STATUSES)
        if filters.status is None:
            query = query.where(Product.status.in_(self.PUBLIC_STATUSES))
        else:
            query = query.where(Product.status == filters.status)
        if filters.keyword:
            query = query.where(Product.title.contains(filters.keyword, autoescape=True))
        if filters.category:
            query = query.where(Category.code == filters.category)
        if filters.campus_id:
            query = query.where(Product.campus_id == filters.campus_id)
        if filters.min_price is not None:
            query = query.where(Product.price >= filters.min_price)
        if filters.max_price is not None:
            query = query.where(Product.price <= filters.max_price)
        if filters.condition:
            query = query.where(Product.condition == filters.condition)
        if filters.negotiable is not None:
            query = query.where(Product.is_negotiable.is_(filters.negotiable))

        count = int(
            await self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        )
        ordering = {
            "price_asc": (Product.price.asc(), Product.id),
            "price_desc": (Product.price.desc(), Product.id),
            "newest": (
                Product.published_at.desc().nulls_last(),
                Product.created_at.desc(),
                Product.id,
            ),
        }[filters.sort]
        result = await self.session.execute(query.order_by(*ordering).offset(offset).limit(limit))
        return [PublicProductRecord(**dict(row._mapping)) for row in result], count

    async def get_product(self, product_id: UUID) -> PublicProductDetailRecord | None:
        review_count = (
            select(func.count(Review.id))
            .join(Order, Order.id == Review.order_id)
            .where(
                Order.status == OrderStatus.COMPLETED,
                Order.seller_id == Product.seller_id,
                Review.reviewee_id == Order.seller_id,
                Review.reviewer_id == Order.buyer_id,
            )
            .correlate(Product)
            .scalar_subquery()
        )
        average_rating = (
            select(func.avg(Review.rating))
            .join(Order, Order.id == Review.order_id)
            .where(
                Order.status == OrderStatus.COMPLETED,
                Order.seller_id == Product.seller_id,
                Review.reviewee_id == Order.seller_id,
                Review.reviewer_id == Order.buyer_id,
            )
            .correlate(Product)
            .scalar_subquery()
        )
        completed_orders = (
            select(func.count(Order.id))
            .where(
                Order.seller_id == Product.seller_id,
                Order.status == OrderStatus.COMPLETED,
            )
            .correlate(Product)
            .scalar_subquery()
        )
        result = await self.session.execute(
            self._public_product_query(self.ALL_PUBLIC_STATUSES)
            .add_columns(
                Product.description,
                review_count.label("seller_review_count"),
                average_rating.label("seller_average_rating"),
                completed_orders.label("seller_completed_orders"),
            )
            .where(Product.id == product_id)
        )
        row = result.one_or_none()
        return PublicProductDetailRecord(**dict(row._mapping)) if row else None

    async def list_similar_products(
        self, *, product_id: UUID, category_id: UUID, limit: int
    ) -> Sequence[PublicProductRecord]:
        result = await self.session.execute(
            self._public_product_query()
            .where(Product.id != product_id, Product.category_id == category_id)
            .order_by(
                Product.published_at.desc().nulls_last(), Product.created_at.desc(), Product.id
            )
            .limit(limit)
        )
        return [PublicProductRecord(**dict(row._mapping)) for row in result]

    def _public_image_query(self) -> Select[tuple[UUID, str, str, str | None]]:
        return (
            select(
                ProductImage.id,
                ProductImage.object_key,
                ProductImage.thumbnail_object_key,
                ProductImage.alt_text,
            )
            .join(Product, Product.id == ProductImage.product_id)
            .join(Campus, Campus.id == Product.campus_id)
            .join(School, School.id == Campus.school_id)
            .join(User, User.id == Product.seller_id)
            .join(Category, Category.id == Product.category_id)
            .where(
                ProductImage.deleted_at.is_(None),
                Product.deleted_at.is_(None),
                Product.status.in_(self.ALL_PUBLIC_STATUSES),
                Campus.deleted_at.is_(None),
                Campus.is_active.is_(True),
                School.deleted_at.is_(None),
                School.is_active.is_(True),
                User.deleted_at.is_(None),
                User.status == UserStatus.ACTIVE,
                Category.deleted_at.is_(None),
                Category.is_active.is_(True),
            )
        )

    async def list_product_images(self, product_id: UUID) -> Sequence[PublicProductImageRecord]:
        result = await self.session.execute(
            self._public_image_query()
            .where(ProductImage.product_id == product_id)
            .order_by(ProductImage.display_order, ProductImage.id)
        )
        return [PublicProductImageRecord(**dict(row._mapping)) for row in result]

    async def get_product_image(self, image_id: UUID) -> PublicProductImageRecord | None:
        result = await self.session.execute(
            self._public_image_query().where(ProductImage.id == image_id)
        )
        row = result.one_or_none()
        return PublicProductImageRecord(**dict(row._mapping)) if row else None

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
