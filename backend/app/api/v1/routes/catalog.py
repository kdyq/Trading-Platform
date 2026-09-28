from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies import get_catalog_service
from app.api.v1.routes.admin import get_admin_service
from app.api.v1.routes.auth import get_auth_context
from app.core.exceptions import AppError
from app.schemas.admin import CatalogUpdateAdmin
from app.schemas.catalog import (
    AdminCampusResponse,
    AdminCategoryResponse,
    CatalogItemUpdate,
    CategoryNodeResponse,
    SchoolCatalogResponse,
)
from app.services.admin import AdminService
from app.services.auth import AuthContext
from app.services.catalog import CatalogService

router = APIRouter()


@router.get("/categories", response_model=list[CategoryNodeResponse])
async def categories(
    service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> list[CategoryNodeResponse]:
    return await service.public_categories()


@router.get("/schools", response_model=list[SchoolCatalogResponse])
async def schools(
    service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> list[SchoolCatalogResponse]:
    return await service.public_schools()


@router.get("/admin/categories", response_model=list[AdminCategoryResponse])
async def admin_categories(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[CatalogService, Depends(get_catalog_service)],
    admin: Annotated[AdminService, Depends(get_admin_service)],
) -> list[AdminCategoryResponse]:
    await admin.require(context, "catalog:read")
    return await service.admin_categories(context.user.id)


@router.get("/admin/campuses", response_model=list[AdminCampusResponse])
async def admin_campuses(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[CatalogService, Depends(get_catalog_service)],
    admin: Annotated[AdminService, Depends(get_admin_service)],
) -> list[AdminCampusResponse]:
    await admin.require(context, "catalog:read")
    return await service.admin_campuses(context.user.id)


@router.patch("/admin/categories/{category_id}", response_model=AdminCategoryResponse)
async def update_category(
    category_id: UUID,
    payload: CatalogUpdateAdmin,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[CatalogService, Depends(get_catalog_service)],
    admin: Annotated[AdminService, Depends(get_admin_service)],
) -> AdminCategoryResponse:
    if payload.confirm_target != category_id:
        raise AppError(status_code=422, code="confirmation_mismatch", message="确认对象不一致")
    await admin.require(context, "catalog:write", high_risk=True)
    result = await service.update_category(
        context.user.id,
        category_id,
        CatalogItemUpdate(
            version=payload.version,
            display_order=payload.display_order,
            is_active=payload.is_active,
        ),
    )
    await admin._audit(
        context.user.id,
        "catalog.category.update",
        "category",
        category_id,
        {
            "version_before": payload.version,
            "after_order": result.display_order,
            "after_active": result.is_active,
            "reason": payload.reason.strip(),
        },
    )
    return result


@router.patch("/admin/campuses/{campus_id}", response_model=AdminCampusResponse)
async def update_campus(
    campus_id: UUID,
    payload: CatalogUpdateAdmin,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[CatalogService, Depends(get_catalog_service)],
    admin: Annotated[AdminService, Depends(get_admin_service)],
) -> AdminCampusResponse:
    if payload.confirm_target != campus_id:
        raise AppError(status_code=422, code="confirmation_mismatch", message="确认对象不一致")
    await admin.require(context, "catalog:write", high_risk=True)
    result = await service.update_campus(
        context.user.id,
        campus_id,
        CatalogItemUpdate(
            version=payload.version,
            display_order=payload.display_order,
            is_active=payload.is_active,
        ),
    )
    await admin._audit(
        context.user.id,
        "catalog.campus.update",
        "campus",
        campus_id,
        {
            "version_before": payload.version,
            "after_order": result.display_order,
            "after_active": result.is_active,
            "reason": payload.reason.strip(),
        },
    )
    return result
