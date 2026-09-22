from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.api.dependencies import get_moderation_service
from app.api.v1.routes.auth import get_auth_context
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
from app.services.auth import AuthContext
from app.services.moderation import ModerationService

router = APIRouter()


@router.get("/products", response_model=ModerationProductList)
async def moderation_products(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ModerationService, Depends(get_moderation_service)],
    status: ProductStatus = ProductStatus.PENDING_REVIEW,
) -> ModerationProductList:
    return await service.list_products(moderator_id=context.user.id, status=status)


@router.post("/products/{product_id}/decisions", response_model=ModerationProductSummary)
async def decide_product(
    product_id: UUID,
    payload: ProductModerationDecision,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ModerationService, Depends(get_moderation_service)],
) -> ModerationProductSummary:
    return await service.decide_product(
        moderator_id=context.user.id,
        product_id=product_id,
        action=payload.action,
        expected_version=payload.version,
        reason_code=payload.reason_code,
        public_note=payload.public_note,
        request_id=payload.request_id,
    )


@router.get("/reports", response_model=ModerationReportList)
async def moderation_reports(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ModerationService, Depends(get_moderation_service)],
    status: ReportStatus | None = None,
) -> ModerationReportList:
    return await service.list_reports(moderator_id=context.user.id, status=status)


@router.post("/reports/{report_id}/decisions", response_model=ModerationReportSummary)
async def decide_report(
    report_id: UUID,
    payload: ReportModerationDecision,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ModerationService, Depends(get_moderation_service)],
) -> ModerationReportSummary:
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


@router.post("/appeals/{appeal_id}/decisions", response_model=ReportAppealResponse)
async def review_report_appeal(
    appeal_id: UUID,
    payload: AppealReviewDecision,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ModerationService, Depends(get_moderation_service)],
) -> ReportAppealResponse:
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
) -> ReportAppealList:
    return await service.list_appeals(context.user.id)


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
