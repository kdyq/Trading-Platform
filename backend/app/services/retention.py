from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Product, ProductImage, ProductImageUpload, ProductImageUploadStatus
from app.models.identity import CampusVerificationAppeal, User, UserSession
from app.services.private_storage import PrivateAppealStorage
from app.services.product_storage import LocalObjectStorage


async def cleanup_expired_campus_appeals(
    session: AsyncSession, storage: PrivateAppealStorage, *, now: datetime | None = None
) -> int:
    reference = now or datetime.now(UTC)
    appeals = (
        await session.scalars(
            select(CampusVerificationAppeal)
            .where(
                CampusVerificationAppeal.retention_until <= reference,
                CampusVerificationAppeal.material_key.not_like("removed/%"),
            )
            .order_by(CampusVerificationAppeal.retention_until, CampusVerificationAppeal.id)
            .limit(50)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for appeal in appeals:
        storage.remove(appeal.material_key)
        appeal.material_key = f"removed/{appeal.id}"
        appeal.original_filename = "removed"
        appeal.reason = ""
    return len(appeals)


async def cleanup_inactive_session_metadata(
    session: AsyncSession, *, now: datetime | None = None
) -> int:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=30)
    sessions = (
        await session.scalars(
            select(UserSession)
            .where(
                or_(UserSession.expires_at <= cutoff, UserSession.revoked_at <= cutoff),
                or_(UserSession.user_agent.is_not(None), UserSession.ip_address.is_not(None)),
            )
            .order_by(UserSession.expires_at, UserSession.id)
            .limit(50)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for row in sessions:
        row.user_agent = None
        row.ip_address = None
    return len(sessions)


async def cleanup_closed_account_images(
    session: AsyncSession, storage: LocalObjectStorage, *, now: datetime | None = None
) -> int:
    reference = now or datetime.now(UTC)
    images = (
        await session.scalars(
            select(ProductImage)
            .join(Product, Product.id == ProductImage.product_id)
            .join(User, User.id == Product.seller_id)
            .where(User.deleted_at.is_not(None), ProductImage.object_key.not_like("removed/%"))
            .limit(50)
            .with_for_update(skip_locked=True)
        )
    ).all()
    uploads = (
        await session.scalars(
            select(ProductImageUpload)
            .join(User, User.id == ProductImageUpload.owner_id)
            .where(
                User.deleted_at.is_not(None), ProductImageUpload.original_key.not_like("removed/%")
            )
            .limit(50)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for image in images:
        storage.delete(image.object_key)
        storage.delete(image.thumbnail_object_key)
        image.object_key = f"removed/{image.id}/original"
        image.thumbnail_object_key = f"removed/{image.id}/thumbnail"
        image.deleted_at = reference
    for upload in uploads:
        storage.delete(upload.original_key)
        storage.delete(upload.thumbnail_key)
        upload.original_key = f"removed/{upload.id}/original"
        upload.thumbnail_key = f"removed/{upload.id}/thumbnail"
        upload.status = ProductImageUploadStatus.DELETED
        upload.deleted_at = reference
    return len(images) + len(uploads)
