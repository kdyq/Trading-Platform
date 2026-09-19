from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse, Response

from app.api.dependencies import (
    get_product_image_upload_repository,
    get_product_image_upload_service,
    get_settings_from_request,
)
from app.api.v1.routes.auth import get_auth_context
from app.core.config import Settings
from app.core.exceptions import AppError
from app.models.identity import CampusVerificationStatus
from app.repositories.product_images import ProductImageUploadRepository
from app.schemas.product_images import ProductImageUploadResponse
from app.services.auth import AuthContext
from app.services.product_images import ProductImageUploadService
from app.services.product_storage import LocalObjectStorage

router = APIRouter()


def require_verified(context: AuthContext) -> None:
    if context.campus_verification_status != CampusVerificationStatus.VERIFIED:
        raise AppError(
            status_code=403, code="campus_verification_required", message="请先完成校园认证"
        )


@router.post("/uploads", response_model=ProductImageUploadResponse, status_code=201)
async def upload_product_image(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ProductImageUploadService, Depends(get_product_image_upload_service)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
    image: Annotated[UploadFile, File()],
) -> ProductImageUploadResponse:
    require_verified(context)
    content = await image.read(settings.product_image_max_bytes + 1)
    upload = await service.upload(
        owner_id=context.user.id,
        filename=image.filename or "upload",
        claimed_media_type=image.content_type,
        content=content,
    )
    return ProductImageUploadResponse(
        id=upload.id,
        original_filename=upload.original_filename,
        media_type=upload.media_type,
        size_bytes=upload.size_bytes,
        width=upload.width,
        height=upload.height,
        expires_at=upload.expires_at,
        preview_url=f"/api/v1/product-images/uploads/{upload.id}/preview",
    )


@router.get("/uploads/{upload_id}/preview", response_class=FileResponse)
async def preview_product_image(
    upload_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    repository: Annotated[
        ProductImageUploadRepository, Depends(get_product_image_upload_repository)
    ],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> FileResponse:
    upload = await repository.get_owned_temporary(context.user.id, upload_id)
    if upload is None:
        raise AppError(status_code=404, code="image_upload_not_found", message="待处理图片不存在")
    path = LocalObjectStorage(settings.resolved_public_product_storage_root).path_for(
        upload.thumbnail_key
    )
    if not path.is_file():
        raise AppError(status_code=404, code="image_upload_not_found", message="待处理图片不存在")
    return FileResponse(
        path, media_type="image/webp", headers={"Cache-Control": "private, no-store"}
    )


@router.delete("/uploads/{upload_id}", status_code=204)
async def discard_product_image(
    upload_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ProductImageUploadService, Depends(get_product_image_upload_service)],
) -> Response:
    await service.discard(context.user.id, upload_id)
    return Response(status_code=204)
