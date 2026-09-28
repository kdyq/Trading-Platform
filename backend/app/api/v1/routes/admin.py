from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_settings_from_request
from app.api.v1.routes.auth import get_auth_context
from app.core.config import Settings
from app.core.exceptions import AppError
from app.db.session import get_database_session
from app.models.catalog import ProductStatus
from app.models.identity import CampusAppealStatus, UserStatus
from app.schemas.admin import (
    AdminCapabilities,
    AuditExportCreate,
    AuditExportList,
    AuditExportSummary,
    AuditListAdmin,
    CampusAppealDecisionAdmin,
    CampusAppealListAdmin,
    CampusAppealSummaryAdmin,
    CampusListAdmin,
    CategoryListAdmin,
    DashboardMetricsAdmin,
    ProductListAdmin,
    StaffInvitation,
    StaffList,
    StaffRolesUpdate,
    StaffSummary,
    StatusUpdate,
    UserListAdmin,
    UserSummaryAdmin,
)
from app.services.admin import AdminService
from app.services.admin_insights import AdminInsightsService
from app.services.auth import AuthContext

router = APIRouter()


def get_admin_service(
    session: Annotated[AsyncSession, Depends(get_database_session)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> AdminService:
    return AdminService(session, settings)


def get_admin_insights_service(
    session: Annotated[AsyncSession, Depends(get_database_session)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> AdminInsightsService:
    return AdminInsightsService(session, settings)


@router.get("/me", response_model=AdminCapabilities)
async def capabilities(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AdminService, Depends(get_admin_service)],
) -> AdminCapabilities:
    return await service.capabilities(context)


@router.get("/staff", response_model=StaffList)
async def staff(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AdminService, Depends(get_admin_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> StaffList:
    return await service.staff(context, page=page, page_size=page_size)


@router.post("/staff/invitations", response_model=StaffSummary, status_code=201)
async def invite_staff(
    payload: StaffInvitation,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AdminService, Depends(get_admin_service)],
) -> StaffSummary:
    if payload.email != payload.confirm_email:
        raise AppError(status_code=422, code="confirmation_mismatch", message="确认邮箱不一致")
    return await service.invite_existing(
        context,
        email=str(payload.email),
        role_code=payload.role,
        reason=payload.reason.strip(),
    )


@router.put("/staff/{target_id}/roles", response_model=StaffSummary)
async def update_staff_roles(
    target_id: UUID,
    payload: StaffRolesUpdate,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AdminService, Depends(get_admin_service)],
) -> StaffSummary:
    if payload.confirm_target != target_id:
        raise AppError(status_code=422, code="confirmation_mismatch", message="确认对象不一致")
    return await service.set_staff_roles(
        context, target_id, roles=payload.roles, reason=payload.reason.strip()
    )


@router.patch("/staff/{target_id}/status", response_model=StaffSummary)
async def update_staff_status(
    target_id: UUID,
    payload: StatusUpdate,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AdminService, Depends(get_admin_service)],
) -> StaffSummary:
    if payload.confirm_target != target_id:
        raise AppError(status_code=422, code="confirmation_mismatch", message="确认对象不一致")
    result = await service.set_status(
        context, target_id, status=payload.status, reason=payload.reason.strip(), staff_only=True
    )
    if not isinstance(result, StaffSummary):
        raise RuntimeError("Expected staff summary")
    return result


@router.get("/users", response_model=UserListAdmin)
async def users(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AdminService, Depends(get_admin_service)],
    query: Annotated[str | None, Query(max_length=100)] = None,
    status: UserStatus | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> UserListAdmin:
    return await service.users(context, query=query, status=status, page=page, page_size=page_size)


@router.patch("/users/{target_id}/status", response_model=UserSummaryAdmin)
async def update_user_status(
    target_id: UUID,
    payload: StatusUpdate,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AdminService, Depends(get_admin_service)],
) -> UserSummaryAdmin:
    if payload.confirm_target != target_id:
        raise AppError(status_code=422, code="confirmation_mismatch", message="确认对象不一致")
    result = await service.set_status(
        context, target_id, status=payload.status, reason=payload.reason.strip(), staff_only=False
    )
    if not isinstance(result, UserSummaryAdmin):
        raise RuntimeError("Expected user summary")
    return result


@router.get("/products", response_model=ProductListAdmin)
async def products(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AdminService, Depends(get_admin_service)],
    query: Annotated[str | None, Query(max_length=100)] = None,
    status: ProductStatus | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> ProductListAdmin:
    return await service.products(
        context, query=query, status=status, page=page, page_size=page_size
    )


@router.get("/categories", response_model=CategoryListAdmin)
async def categories(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AdminService, Depends(get_admin_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> CategoryListAdmin:
    return await service.categories(context, page=page, page_size=page_size)


@router.get("/campuses", response_model=CampusListAdmin)
async def campuses(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AdminService, Depends(get_admin_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> CampusListAdmin:
    return await service.campuses(context, page=page, page_size=page_size)


@router.get("/campus-appeals", response_model=CampusAppealListAdmin)
async def campus_appeals(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AdminService, Depends(get_admin_service)],
    status: CampusAppealStatus | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> CampusAppealListAdmin:
    return await service.campus_appeals(context, status=status, page=page, page_size=page_size)


@router.post("/campus-appeals/{appeal_id}/decisions", response_model=CampusAppealSummaryAdmin)
async def decide_campus_appeal(
    appeal_id: UUID,
    payload: CampusAppealDecisionAdmin,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AdminService, Depends(get_admin_service)],
) -> CampusAppealSummaryAdmin:
    if payload.confirm_target != appeal_id:
        raise AppError(status_code=422, code="confirmation_mismatch", message="确认对象不一致")
    return await service.decide_campus_appeal(
        context, appeal_id, action=payload.action, reason=payload.reason.strip()
    )


@router.get("/dashboard", response_model=DashboardMetricsAdmin)
async def dashboard(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AdminInsightsService, Depends(get_admin_insights_service)],
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> DashboardMetricsAdmin:
    end = ends_at or datetime.now(UTC)
    start = starts_at or end - timedelta(days=7)
    return await service.dashboard(context, start, end)


@router.get("/audit", response_model=AuditListAdmin)
async def audit_entries(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AdminInsightsService, Depends(get_admin_insights_service)],
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    action: Annotated[str | None, Query(max_length=96)] = None,
    actor_id: UUID | None = None,
    target_type: Annotated[str | None, Query(max_length=64)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> AuditListAdmin:
    end = ends_at or datetime.now(UTC)
    start = starts_at or end - timedelta(days=7)
    return await service.audit(
        context,
        starts_at=start,
        ends_at=end,
        action=action,
        actor_id=actor_id,
        target_type=target_type,
        page=page,
        page_size=page_size,
    )


@router.post("/audit-exports", response_model=AuditExportSummary, status_code=202)
async def create_audit_export(
    payload: AuditExportCreate,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AdminInsightsService, Depends(get_admin_insights_service)],
) -> AuditExportSummary:
    return await service.create_export(
        context,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        action=payload.action,
        reason=payload.reason.strip(),
    )


@router.get("/audit-exports", response_model=AuditExportList)
async def list_audit_exports(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AdminInsightsService, Depends(get_admin_insights_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> AuditExportList:
    return await service.list_exports(context, page=page, page_size=page_size)


@router.get("/audit-exports/{job_id}", response_model=AuditExportSummary)
async def audit_export_status(
    job_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AdminInsightsService, Depends(get_admin_insights_service)],
) -> AuditExportSummary:
    return await service.get_export(context, job_id)


@router.get("/audit-exports/{job_id}/download", response_class=FileResponse)
async def download_audit_export(
    job_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AdminInsightsService, Depends(get_admin_insights_service)],
) -> FileResponse:
    path = await service.download_export(context, job_id)
    return FileResponse(
        path,
        media_type="text/csv; charset=utf-8",
        filename=f"audit-{job_id}.csv",
        headers={"Cache-Control": "private, no-store"},
    )


@router.delete("/audit-exports/{job_id}", response_model=AuditExportSummary)
async def revoke_audit_export(
    job_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[AdminInsightsService, Depends(get_admin_insights_service)],
) -> AuditExportSummary:
    return await service.revoke_export(context, job_id)
