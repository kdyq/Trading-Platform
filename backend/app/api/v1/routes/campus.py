from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from app.api.dependencies import get_campus_service
from app.api.v1.routes.auth import get_auth_context
from app.models.identity import CampusVerificationStatus
from app.schemas.campus import (
    AppealResponse,
    AppealSummary,
    CampusEmailVerificationConfirm,
    CampusEmailVerificationRequest,
    CampusPolicyResponse,
    CampusStatusResponse,
    CampusSummary,
    CampusVerificationRequestResponse,
    CapabilityResponse,
    SchoolSummary,
)
from app.services.auth import AuthContext
from app.services.campus import CampusService, CampusState

router = APIRouter()
Capability = Literal["publish", "message", "order", "review"]


async def require_campus_verified_context(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[CampusService, Depends(get_campus_service)],
) -> AuthContext:
    """Reusable dependency for every campus-only business endpoint."""
    await service.require_verified(context.user.id)
    return context


@router.get("/policy", response_model=CampusPolicyResponse)
async def campus_policy(
    service: Annotated[CampusService, Depends(get_campus_service)],
) -> CampusPolicyResponse:
    return CampusPolicyResponse(
        verification_days=service.verification_days,
        appeal_retention_days=service.appeal_retention_days,
        appeal_max_bytes=service.max_material_bytes,
        appeal_media_types=["application/pdf", "image/png", "image/jpeg"],
    )


def state_response(state: CampusState) -> CampusStatusResponse:
    verification = state.verification
    appeal = state.appeal
    return CampusStatusResponse(
        status=state.status.value,
        verification_id=verification.id if verification else None,
        campus_id=(
            appeal.campus_id if appeal else (verification.campus_id if verification else None)
        ),
        campus_email=verification.campus_email if verification else None,
        verified_at=verification.verified_at if verification else None,
        expires_at=verification.expires_at if verification else None,
        appeal=(
            AppealSummary(
                id=appeal.id,
                status=appeal.status.value,
                original_filename=appeal.original_filename,
                retention_until=appeal.retention_until,
            )
            if appeal
            else None
        ),
    )


@router.get("/schools", response_model=list[SchoolSummary])
async def list_schools(
    service: Annotated[CampusService, Depends(get_campus_service)],
) -> list[SchoolSummary]:
    schools = await service.schools()
    return [
        SchoolSummary(
            id=school.id,
            name=school.name,
            campuses=[
                CampusSummary(id=campus.id, name=campus.name)
                for campus in sorted(school.campuses, key=lambda item: item.name)
                if campus.is_active and campus.deleted_at is None
            ],
            email_domains=[
                f"*.{domain.domain}" if domain.allow_subdomains else domain.domain
                for domain in sorted(school.email_domains, key=lambda item: item.domain)
                if domain.is_active
            ],
        )
        for school in schools
    ]


@router.post(
    "/email-verifications",
    response_model=CampusVerificationRequestResponse,
    status_code=202,
)
async def request_email_verification(
    payload: CampusEmailVerificationRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[CampusService, Depends(get_campus_service)],
) -> CampusVerificationRequestResponse:
    verification = await service.request_email_verification(
        user_id=context.user.id,
        school_id=payload.school_id,
        campus_id=payload.campus_id,
        campus_email=str(payload.campus_email),
        ip_address=request.client.host if request.client else None,
    )
    return CampusVerificationRequestResponse(
        verification_id=verification.id,
        message="校园认证验证码已发送",
    )


@router.post("/email-verifications/confirm", response_model=CampusStatusResponse)
async def confirm_email_verification(
    payload: CampusEmailVerificationConfirm,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[CampusService, Depends(get_campus_service)],
) -> CampusStatusResponse:
    await service.confirm_email_verification(
        user_id=context.user.id,
        verification_id=payload.verification_id,
        code=payload.code,
    )
    return state_response(await service.state(context.user.id))


@router.get("/status", response_model=CampusStatusResponse)
async def campus_status(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[CampusService, Depends(get_campus_service)],
) -> CampusStatusResponse:
    response = state_response(await service.state(context.user.id))
    if context.account_verification_status == CampusVerificationStatus.VERIFIED:
        response.status = CampusVerificationStatus.VERIFIED.value
    return response


@router.post("/appeals", response_model=AppealResponse, status_code=201)
async def submit_appeal(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[CampusService, Depends(get_campus_service)],
    campus_id: Annotated[UUID, Form()],
    reason: Annotated[str, Form(min_length=20, max_length=1000)],
    material: Annotated[UploadFile, File()],
) -> AppealResponse:
    content = await material.read(service.max_material_bytes + 1)
    await material.close()
    appeal = await service.submit_appeal(
        user_id=context.user.id,
        campus_id=campus_id,
        reason=reason,
        filename=material.filename,
        media_type=material.content_type,
        content=content,
    )
    return AppealResponse(
        id=appeal.id,
        status=appeal.status.value,
        original_filename=appeal.original_filename,
        retention_until=appeal.retention_until,
    )


@router.get("/appeals/{appeal_id}/material", response_class=FileResponse)
async def download_appeal_material(
    appeal_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[CampusService, Depends(get_campus_service)],
) -> FileResponse:
    material = await service.appeal_material(context=context, appeal_id=appeal_id)
    return FileResponse(
        material.path,
        media_type=material.media_type,
        filename=material.filename,
    )


@router.get("/capabilities/{capability}", response_model=CapabilityResponse)
async def check_capability(
    capability: Capability,
    _: Annotated[AuthContext, Depends(require_campus_verified_context)],
) -> CapabilityResponse:
    return CapabilityResponse(capability=capability)
