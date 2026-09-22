from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse

from app.api.dependencies import get_report_service
from app.api.v1.routes.auth import get_auth_context
from app.schemas.reports import (
    ReportCreate,
    ReportEvidenceResponse,
    ReportListResponse,
    ReportResponse,
)
from app.services.auth import AuthContext
from app.services.reports import ReportService

router = APIRouter()


@router.post("", response_model=ReportResponse, status_code=201)
async def create_report(
    payload: ReportCreate,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ReportService, Depends(get_report_service)],
) -> ReportResponse:
    return await service.create(
        reporter_id=context.user.id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        reason_code=payload.reason_code,
        details=payload.details,
    )


@router.get("", response_model=ReportListResponse)
async def list_my_reports(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ReportService, Depends(get_report_service)],
) -> ReportListResponse:
    return await service.list_owned(context.user.id)


@router.get("/{report_id}", response_model=ReportResponse)
async def report_detail(
    report_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ReportService, Depends(get_report_service)],
) -> ReportResponse:
    return await service.detail(context.user.id, report_id)


@router.post("/{report_id}/withdraw", response_model=ReportResponse)
async def withdraw_report(
    report_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ReportService, Depends(get_report_service)],
) -> ReportResponse:
    return await service.withdraw(context.user.id, report_id)


@router.post("/{report_id}/evidence", response_model=ReportEvidenceResponse, status_code=201)
async def upload_report_evidence(
    report_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ReportService, Depends(get_report_service)],
    evidence: Annotated[UploadFile, File()],
) -> ReportEvidenceResponse:
    content = await evidence.read(service.storage.max_bytes + 1)
    await evidence.close()
    return await service.upload_evidence(
        reporter_id=context.user.id,
        report_id=report_id,
        filename=evidence.filename,
        media_type=evidence.content_type,
        content=content,
    )


@router.get("/{report_id}/evidence/{evidence_id}", response_class=FileResponse)
async def download_report_evidence(
    report_id: UUID,
    evidence_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ReportService, Depends(get_report_service)],
) -> FileResponse:
    item = await service.download_evidence(
        reporter_id=context.user.id, report_id=report_id, evidence_id=evidence_id
    )
    return FileResponse(
        item.path,
        media_type=item.media_type,
        filename=item.filename,
        headers={"Cache-Control": "private, no-store"},
    )
