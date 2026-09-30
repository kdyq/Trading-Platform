from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from app.core.exceptions import AppError
from app.models.catalog import (
    Product,
    ProductImage,
    ProductImageUpload,
    ProductImageUploadStatus,
    ProductStatus,
)
from app.repositories.product_images import ProductImageUploadRepository
from app.repositories.seller_products import SellerProductRepository
from app.schemas.seller_products import (
    ProductImageReference,
    SellerProductCreate,
    SellerProductImageResponse,
    SellerProductListResponse,
    SellerProductResponse,
    SellerProductUpdate,
)
from app.services.product_storage import ObjectStorage

EDITABLE_STATUSES = {
    ProductStatus.DRAFT,
    ProductStatus.REJECTED,
    ProductStatus.HIDDEN,
    ProductStatus.ON_SALE,
}


class SellerProductService:
    def __init__(
        self,
        *,
        repository: SellerProductRepository,
        uploads: ProductImageUploadRepository,
        storage: ObjectStorage,
    ) -> None:
        self.repository = repository
        self.uploads = uploads
        self.storage = storage

    async def create(self, owner_id: UUID, payload: SellerProductCreate) -> SellerProductResponse:
        campus_id = await self._require_verified_campus(owner_id, payload.campus_id)
        if payload.category_id is None or not await self.repository.is_active_category(
            payload.category_id
        ):
            raise AppError(status_code=422, code="invalid_category", message="请选择有效分类")
        product = Product(
            seller_id=owner_id,
            campus_id=campus_id,
            category_id=payload.category_id,
            title=payload.title.strip(),
            description=payload.description.strip(),
            price=payload.price,
            original_price=payload.original_price,
            condition=payload.condition,
            is_negotiable=payload.is_negotiable,
            delivery_notes=self._clean_optional(payload.delivery_notes),
            status=ProductStatus.DRAFT,
        )
        product.images = []
        await self.repository.create(product)
        return self._response(product)

    async def list_owned(self, owner_id: UUID) -> SellerProductListResponse:
        return SellerProductListResponse(
            items=[self._response(item) for item in await self.repository.list_owned(owner_id)]
        )

    async def get_owned(self, owner_id: UUID, product_id: UUID) -> SellerProductResponse:
        return self._response(await self._owned(owner_id, product_id))

    async def owned_image(self, owner_id: UUID, product_id: UUID, image_id: UUID) -> ProductImage:
        product = await self._owned(owner_id, product_id)
        image = next(
            (item for item in product.images if item.id == image_id and item.deleted_at is None),
            None,
        )
        if image is None:
            raise AppError(
                status_code=404, code="product_image_not_found", message="商品图片不存在"
            )
        return image

    async def update(
        self, owner_id: UUID, product_id: UUID, payload: SellerProductUpdate
    ) -> SellerProductResponse:
        product = await self._owned(owner_id, product_id, for_update=True)
        self._require_version(product, payload.version)
        if product.status not in EDITABLE_STATUSES:
            raise AppError(
                status_code=409,
                code="product_not_editable",
                message="当前状态不能编辑，请先撤回审核",
            )
        fields = payload.model_fields_set - {"version", "images"}
        await self._apply_fields(owner_id, product, payload, fields)
        if payload.images is not None:
            await self._sync_images(owner_id, product, payload.images)
        if fields or payload.images is not None:
            if product.status in {ProductStatus.ON_SALE, ProductStatus.HIDDEN}:
                product.status = ProductStatus.PENDING_REVIEW
                product.published_at = None
            elif product.status == ProductStatus.REJECTED:
                product.status = ProductStatus.DRAFT
            product.updated_at = datetime.now(UTC)
            await self.repository.flush()
        return self._response(product)

    async def submit(self, owner_id: UUID, product_id: UUID, version: int) -> SellerProductResponse:
        product = await self._owned(owner_id, product_id, for_update=True)
        if product.status == ProductStatus.PENDING_REVIEW:
            return self._response(product)
        self._require_version(product, version)
        if product.status not in {
            ProductStatus.DRAFT,
            ProductStatus.REJECTED,
            ProductStatus.HIDDEN,
        }:
            raise self._transition_error()
        await self._validate_complete(owner_id, product)
        product.status = ProductStatus.PENDING_REVIEW
        product.updated_at = datetime.now(UTC)
        await self.repository.flush()
        return self._response(product)

    async def withdraw(
        self, owner_id: UUID, product_id: UUID, version: int
    ) -> SellerProductResponse:
        product = await self._owned(owner_id, product_id, for_update=True)
        if product.status == ProductStatus.DRAFT:
            return self._response(product)
        self._require_version(product, version)
        if product.status != ProductStatus.PENDING_REVIEW:
            raise self._transition_error()
        product.status = ProductStatus.DRAFT
        product.updated_at = datetime.now(UTC)
        await self.repository.flush()
        return self._response(product)

    async def hide(self, owner_id: UUID, product_id: UUID, version: int) -> SellerProductResponse:
        product = await self._owned(owner_id, product_id, for_update=True)
        if product.status == ProductStatus.HIDDEN:
            return self._response(product)
        self._require_version(product, version)
        if product.status not in {ProductStatus.ON_SALE, ProductStatus.RESERVED}:
            raise self._transition_error()
        product.status = ProductStatus.HIDDEN
        product.updated_at = datetime.now(UTC)
        await self.repository.flush()
        return self._response(product)

    async def mark_sold(
        self, owner_id: UUID, product_id: UUID, version: int
    ) -> SellerProductResponse:
        product = await self._owned(owner_id, product_id, for_update=True)
        if product.status == ProductStatus.SOLD:
            return self._response(product)
        self._require_version(product, version)
        if product.status not in {ProductStatus.ON_SALE, ProductStatus.RESERVED}:
            raise self._transition_error()
        product.status = ProductStatus.SOLD
        product.sold_at = datetime.now(UTC)
        product.updated_at = product.sold_at
        await self.repository.flush()
        return self._response(product)

    async def _apply_fields(
        self,
        owner_id: UUID,
        product: Product,
        payload: SellerProductUpdate,
        fields: set[str],
    ) -> None:
        if "title" in fields:
            product.title = (payload.title or "").strip()
        if "description" in fields:
            product.description = (payload.description or "").strip()
        if "price" in fields:
            if payload.price is None:
                raise AppError(status_code=422, code="invalid_price", message="价格不能为空")
            product.price = payload.price
        if "original_price" in fields:
            product.original_price = payload.original_price
        if "condition" in fields and payload.condition is not None:
            product.condition = payload.condition
        if "is_negotiable" in fields and payload.is_negotiable is not None:
            product.is_negotiable = payload.is_negotiable
        if "delivery_notes" in fields:
            product.delivery_notes = self._clean_optional(payload.delivery_notes)
        if "category_id" in fields:
            if payload.category_id is None or not await self.repository.is_active_category(
                payload.category_id
            ):
                raise AppError(status_code=422, code="invalid_category", message="请选择有效分类")
            product.category_id = payload.category_id
        if "campus_id" in fields:
            product.campus_id = await self._require_verified_campus(owner_id, payload.campus_id)

    async def _sync_images(
        self, owner_id: UUID, product: Product, references: list[ProductImageReference]
    ) -> None:
        if len({(item.kind, item.id) for item in references}) != len(references):
            raise AppError(
                status_code=422, code="duplicate_product_image", message="商品图片不能重复"
            )
        active_images = {image.id: image for image in product.images if image.deleted_at is None}
        existing_ids = {item.id for item in references if item.kind == "existing"}
        if not existing_ids.issubset(active_images):
            raise AppError(
                status_code=404, code="product_image_not_found", message="商品图片不存在"
            )
        upload_ids = [item.id for item in references if item.kind == "upload"]
        uploads = {
            item.id: item
            for item in await self.uploads.list_owned_temporary(
                owner_id, upload_ids, for_update=True
            )
        }
        if set(upload_ids) != set(uploads):
            raise AppError(
                status_code=404, code="image_upload_not_found", message="待处理图片不存在"
            )

        now = datetime.now(UTC)
        for image in active_images.values():
            image.display_order += 100
        await self.repository.flush()
        for image_id, image in active_images.items():
            if image_id not in existing_ids:
                image.deleted_at = now
        for position, reference in enumerate(references):
            if reference.kind == "existing":
                active_images[reference.id].display_order = position
                continue
            image = await self._confirm_upload(product, uploads[reference.id], position)
            product.images.append(image)
        product.updated_at = now
        await self.repository.flush()

    async def _confirm_upload(
        self, product: Product, upload: ProductImageUpload, position: int
    ) -> ProductImage:
        if upload.expires_at <= datetime.now(UTC):
            raise AppError(status_code=409, code="image_upload_expired", message="待处理图片已过期")
        image_id = uuid4()
        # The database status is the ownership boundary. Keeping random object keys
        # unchanged makes confirmation atomic with the database commit: a crash before
        # commit leaves a cleanable temporary upload, while a commit makes those same
        # objects durable without a filesystem/object-store consistency gap.
        original_key = upload.original_key
        thumbnail_key = upload.thumbnail_key
        upload.status = ProductImageUploadStatus.CONFIRMED
        upload.confirmed_at = datetime.now(UTC)
        image = ProductImage(
            id=image_id,
            product_id=product.id,
            object_key=original_key,
            thumbnail_object_key=thumbnail_key,
            alt_text=product.title[:255] or None,
            display_order=position,
        )
        await self.repository.add_image(image)
        return image

    async def _validate_complete(self, owner_id: UUID, product: Product) -> None:
        if not 5 <= len(product.title.strip()) <= 120:
            raise AppError(
                status_code=422, code="invalid_product_title", message="标题需为 5-120 个字符"
            )
        if not 20 <= len(product.description.strip()) <= 3000:
            raise AppError(
                status_code=422,
                code="invalid_product_description",
                message="描述需为 20-3000 个字符",
            )
        if product.price <= Decimal("0"):
            raise AppError(status_code=422, code="invalid_price", message="价格必须大于 0")
        if product.original_price is not None and product.original_price < product.price:
            raise AppError(
                status_code=422, code="invalid_original_price", message="原价不能低于售价"
            )
        if not await self.repository.is_active_category(product.category_id):
            raise AppError(status_code=422, code="invalid_category", message="分类已停用")
        await self._require_verified_campus(owner_id, product.campus_id)
        if not 1 <= len([image for image in product.images if image.deleted_at is None]) <= 8:
            raise AppError(
                status_code=422, code="product_image_required", message="请上传 1-8 张图片"
            )

    async def _require_verified_campus(
        self, owner_id: UUID, requested_campus_id: UUID | None
    ) -> UUID:
        verified_campus_id = await self.repository.verified_campus_id(owner_id)
        if verified_campus_id is None:
            raise AppError(
                status_code=403, code="campus_verification_required", message="请先完成校园认证"
            )
        if requested_campus_id is not None and requested_campus_id != verified_campus_id:
            raise AppError(status_code=403, code="campus_mismatch", message="只能发布到已认证校区")
        if not await self.repository.is_active_campus(verified_campus_id):
            raise AppError(
                status_code=409, code="campus_unavailable", message="认证校区当前不可发布"
            )
        return verified_campus_id

    async def _owned(
        self, owner_id: UUID, product_id: UUID, *, for_update: bool = False
    ) -> Product:
        product = await self.repository.get_owned(owner_id, product_id, for_update=for_update)
        if product is None:
            raise AppError(status_code=404, code="product_not_found", message="商品不存在")
        return product

    @staticmethod
    def _require_version(product: Product, version: int) -> None:
        if product.version != version:
            raise AppError(
                status_code=409,
                code="product_version_conflict",
                message="商品已在其他位置更新，请刷新后重试",
            )

    @staticmethod
    def _clean_optional(value: str | None) -> str | None:
        cleaned = value.strip() if value else ""
        return cleaned or None

    @staticmethod
    def _transition_error() -> AppError:
        return AppError(
            status_code=409, code="invalid_product_transition", message="当前商品状态不允许此操作"
        )

    @staticmethod
    def _response(product: Product) -> SellerProductResponse:
        images = sorted(
            (image for image in product.images if image.deleted_at is None),
            key=lambda item: (item.display_order, item.id),
        )
        return SellerProductResponse(
            id=product.id,
            title=product.title,
            description=product.description,
            price=product.price,
            original_price=product.original_price,
            category_id=product.category_id,
            campus_id=product.campus_id,
            condition=product.condition.value,
            is_negotiable=product.is_negotiable,
            delivery_notes=product.delivery_notes,
            status=product.status.value,
            version=product.version,
            updated_at=product.updated_at,
            images=[
                SellerProductImageResponse(
                    id=image.id,
                    url=f"/api/v1/seller/products/{product.id}/images/{image.id}",
                    thumbnail_url=(
                        f"/api/v1/seller/products/{product.id}/images/{image.id}/thumbnail"
                    ),
                    alt_text=image.alt_text,
                    display_order=image.display_order,
                )
                for image in images
            ],
        )
