from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse

from app.api.dependencies import get_moderation_service, get_settings_from_request
from app.api.v1.routes.admin import get_admin_service
from app.api.v1.routes.auth import get_auth_context
from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.feature_switches import require_publishing
from app.models.catalog import ProductStatus
from app.models.moderation import ReportStatus
from app.schemas.moderation import (
    AppealReviewDecision,
    ModerationProductList,
    ModerationProductSummary,
    ModerationReportList,
    ModerationReportSummary,
    ProductModerationDecision,
    ReportAppealCreate,
    ReportAppealList,
    ReportAppealResponse,
    ReportModerationDecision,
)
from app.schemas.reports import ReportEvidenceResponse
from app.services.admin import AdminService
from app.services.auth import AuthContext
from app.services.moderation import ModerationService
from app.services.product_storage import PublicProductStorage

router = APIRouter()


@router.get("/products", response_model=ModerationProductList)
async def moderation_products(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ModerationService, Depends(get_moderation_service)],
    status: ProductStatus = ProductStatus.PENDING_REVIEW,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> ModerationProductList:
    return await service.list_products(
        moderator_id=context.user.id, status=status, page=page, page_size=page_size
    )


@router.post("/products/{product_id}/decisions", response_model=ModerationProductSummary)
async def decide_product(
    product_id: UUID,
    payload: ProductModerationDecision,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ModerationService, Depends(get_moderation_service)],
    admin: Annotated[AdminService, Depends(get_admin_service)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> ModerationProductSummary:
    if payload.action in {"approve", "restore"}:
        require_publishing(settings)
    if payload.action in {"hide", "restore"}:
        if payload.confirm_target != product_id:
            raise AppError(
                status_code=422, code="confirmation_required", message="请再次确认目标商品"
            )
        await admin.require(context, "moderation:review", high_risk=True)
    return await service.decide_product(
        moderator_id=context.user.id,
        product_id=product_id,
        action=payload.action,
        expected_version=payload.version,
        reason_code=payload.reason_code,
        public_note=payload.public_note,
        request_id=payload.request_id,
    )


@router.get("/products/{product_id}/images/{image_id}/thumbnail", response_class=FileResponse)
async def moderation_product_image_thumbnail(
    product_id: UUID,
    image_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ModerationService, Depends(get_moderation_service)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> FileResponse:
    image = await service.product_image(
        moderator_id=context.user.id, product_id=product_id, image_id=image_id
    )
    stored = PublicProductStorage(settings.resolved_public_product_storage_root).resolve(
        image.thumbnail_object_key
    )
    return FileResponse(
        stored.path,
        media_type=stored.media_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/reports", response_model=ModerationReportList)
async def moderation_reports(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ModerationService, Depends(get_moderation_service)],
    status: ReportStatus | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> ModerationReportList:
    return await service.list_reports(
        moderator_id=context.user.id,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.post("/reports/{report_id}/decisions", response_model=ModerationReportSummary)
async def decide_report(
    report_id: UUID,
    payload: ReportModerationDecision,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ModerationService, Depends(get_moderation_service)],
    admin: Annotated[AdminService, Depends(get_admin_service)],
) -> ModerationReportSummary:
    if payload.action == "violate" and payload.penalty_code == "suspend":
        if payload.confirm_target != report_id:
            raise AppError(
                status_code=422, code="confirmation_required", message="请再次确认目标举报"
            )
        await admin.require(context, "moderation:suspend", high_risk=True)
    return await service.decide_report(
        moderator_id=context.user.id,
        report_id=report_id,
        action=payload.action,
        expected_version=payload.version,
        penalty_code=payload.penalty_code,
        penalty_points=payload.penalty_points,
        public_result=payload.public_result,
        internal_reason=payload.internal_reason,
        evidence_ids=payload.evidence_ids,
        request_id=payload.request_id,
    )


@router.post("/reports/{report_id}/appeals", response_model=ReportAppealResponse, status_code=201)
async def create_report_appeal(
    report_id: UUID,
    payload: ReportAppealCreate,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ModerationService, Depends(get_moderation_service)],
) -> ReportAppealResponse:
    return await service.create_appeal(
        appellant_id=context.user.id, report_id=report_id, details=payload.details
    )


@router.post(
    "/appeals/{appeal_id}/evidence", response_model=ReportEvidenceResponse, status_code=201
)
async def upload_appeal_evidence(
    appeal_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ModerationService, Depends(get_moderation_service)],
    evidence: Annotated[UploadFile, File()],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> ReportEvidenceResponse:
    content = await evidence.read(settings.report_evidence_max_bytes + 1)
    await evidence.close()
    return await service.upload_appeal_evidence(
        appellant_id=context.user.id,
        appeal_id=appeal_id,
        filename=evidence.filename,
        media_type=evidence.content_type,
        content=content,
    )


@router.get("/appeals/{appeal_id}/evidence/{evidence_id}", response_class=FileResponse)
async def download_appeal_evidence(
    appeal_id: UUID,
    evidence_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ModerationService, Depends(get_moderation_service)],
) -> FileResponse:
    item = await service.download_appeal_evidence(
        user_id=context.user.id,
        appeal_id=appeal_id,
        evidence_id=evidence_id,
    )
    return FileResponse(
        item.path,
        media_type=item.media_type,
        filename=item.filename,
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/appeals/{appeal_id}/decisions", response_model=ReportAppealResponse)
async def review_report_appeal(
    appeal_id: UUID,
    payload: AppealReviewDecision,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ModerationService, Depends(get_moderation_service)],
    admin: Annotated[AdminService, Depends(get_admin_service)],
) -> ReportAppealResponse:
    if payload.action == "reverse":
        if payload.confirm_target != appeal_id:
            raise AppError(
                status_code=422, code="confirmation_required", message="请再次确认目标申诉"
            )
        await admin.require(context, "moderation:review", high_risk=True)
    return await service.review_appeal(
        reviewer_id=context.user.id,
        appeal_id=appeal_id,
        action=payload.action,
        reason=payload.reason,
        override_reason=payload.override_reason,
        request_id=payload.request_id,
    )


@router.get("/appeals", response_model=ReportAppealList)
async def moderation_appeals(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ModerationService, Depends(get_moderation_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> ReportAppealList:
    return await service.list_appeals(context.user.id, page=page, page_size=page_size)


@router.get("/reports/{report_id}/evidence/{evidence_id}", response_class=FileResponse)
async def moderation_report_evidence(
    report_id: UUID,
    evidence_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ModerationService, Depends(get_moderation_service)],
) -> FileResponse:
    item = await service.download_report_evidence(
        moderator_id=context.user.id,
        report_id=report_id,
        evidence_id=evidence_id,
    )
    return FileResponse(
        item.path,
        media_type=item.media_type,
        filename=item.filename,
        headers={"Cache-Control": "private, no-store"},
    )
