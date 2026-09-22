from datetime import UTC, datetime
from uuid import UUID

from app.core.exceptions import AppError
from app.models.catalog import Product, ProductStatus
from app.models.moderation import ModerationAction
from app.repositories.moderation import SqlAlchemyModerationRepository
from app.schemas.moderation import ModerationProductList, ModerationProductSummary


class ModerationService:
    REVIEW_ROLES = {"REVIEWER", "ADMIN", "SUPER_ADMIN"}

    def __init__(self, repository: SqlAlchemyModerationRepository) -> None:
        self.repository = repository

    async def require_reviewer(self, user_id: UUID) -> None:
        if not await self.repository.has_role(user_id, self.REVIEW_ROLES):
            raise AppError(status_code=403, code="moderation_forbidden", message="无审核权限")

    async def list_products(
        self, *, moderator_id: UUID, status: ProductStatus
    ) -> ModerationProductList:
        await self.require_reviewer(moderator_id)
        rows = await self.repository.list_products(status)
        return ModerationProductList(
            items=[self._product(product, seller_name) for product, seller_name in rows]
        )

    async def decide_product(
        self,
        *,
        moderator_id: UUID,
        product_id: UUID,
        action: str,
        expected_version: int,
        reason_code: str,
        public_note: str,
        request_id: str,
    ) -> ModerationProductSummary:
        await self.require_reviewer(moderator_id)
        product = await self.repository.get_product(product_id, lock=True)
        if product is None:
            raise AppError(
                status_code=404, code="moderation_product_not_found", message="商品不存在"
            )
        if product.version != expected_version:
            raise AppError(
                status_code=409, code="product_version_conflict", message="商品已被其他审核员处理"
            )
        before = product.status
        now = datetime.now(UTC)
        if action == "approve":
            self._require_status(product, {ProductStatus.PENDING_REVIEW})
            product.status = ProductStatus.ON_SALE
            product.published_at = product.published_at or now
            record_action = ModerationAction.APPROVE
            title = "商品审核通过"
        elif action == "reject":
            self._require_status(product, {ProductStatus.PENDING_REVIEW})
            product.status = ProductStatus.REJECTED
            record_action = ModerationAction.REJECT
            title = "商品审核未通过"
        elif action == "hide":
            self._require_status(
                product, {ProductStatus.ON_SALE, ProductStatus.RESERVED, ProductStatus.SOLD}
            )
            product.hidden_from_status = product.status.value
            product.status = ProductStatus.HIDDEN
            record_action = ModerationAction.HIDE
            title = "商品已暂时隐藏"
        elif action == "restore":
            self._require_status(product, {ProductStatus.HIDDEN})
            try:
                restored = ProductStatus(product.hidden_from_status or "")
            except ValueError:
                restored = ProductStatus.PENDING_REVIEW
            if restored not in {ProductStatus.ON_SALE, ProductStatus.RESERVED, ProductStatus.SOLD}:
                restored = ProductStatus.PENDING_REVIEW
            product.status = restored
            product.hidden_from_status = None
            record_action = ModerationAction.RESTORE
            title = "商品已恢复"
        else:
            raise AppError(
                status_code=422, code="moderation_action_invalid", message="审核动作无效"
            )
        product.moderation_reason_code = reason_code
        product.moderation_public_note = public_note.strip()
        self.repository.record_decision(
            product=product,
            moderator_id=moderator_id,
            action=record_action,
            reason=public_note.strip(),
            request_id=request_id,
            before_status=before,
        )
        await self.repository.notify_seller(
            product=product,
            action=action,
            title=title,
            summary=public_note.strip(),
        )
        seller_name = await self.repository.seller_name(product.seller_id)
        await self.repository.session.flush()
        await self.repository.session.refresh(product, attribute_names=["version", "updated_at"])
        return self._product(product, seller_name)

    @staticmethod
    def _require_status(product: Product, allowed: set[ProductStatus]) -> None:
        if product.status not in allowed:
            raise AppError(
                status_code=409, code="invalid_product_state", message="当前商品状态不能执行该操作"
            )

    @staticmethod
    def _product(product: Product, seller_name: str) -> ModerationProductSummary:
        return ModerationProductSummary(
            id=product.id,
            seller_id=product.seller_id,
            seller_name=seller_name,
            title=product.title,
            description=product.description,
            price=product.price,
            status=product.status.value,
            version=product.version,
            image_urls=[
                f"/api/v1/market/images/{image.id}/thumbnail"
                for image in sorted(product.images, key=lambda item: item.display_order)
                if image.deleted_at is None
            ],
            moderation_reason_code=product.moderation_reason_code,
            moderation_public_note=product.moderation_public_note,
            created_at=product.created_at,
            updated_at=product.updated_at,
        )
