from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies import get_catalog_service
from app.api.v1.routes.auth import get_auth_context
from app.schemas.catalog import (
    AdminCampusResponse,
    AdminCategoryResponse,
    CatalogItemUpdate,
    CategoryNodeResponse,
    SchoolCatalogResponse,
)
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
) -> list[AdminCategoryResponse]:
    return await service.admin_categories(context.user.id)


@router.get("/admin/campuses", response_model=list[AdminCampusResponse])
async def admin_campuses(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> list[AdminCampusResponse]:
    return await service.admin_campuses(context.user.id)


@router.patch("/admin/categories/{category_id}", response_model=AdminCategoryResponse)
async def update_category(
    category_id: UUID,
    payload: CatalogItemUpdate,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> AdminCategoryResponse:
    return await service.update_category(context.user.id, category_id, payload)


@router.patch("/admin/campuses/{campus_id}", response_model=AdminCampusResponse)
async def update_campus(
    campus_id: UUID,
    payload: CatalogItemUpdate,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> AdminCampusResponse:
    return await service.update_campus(context.user.id, campus_id, payload)
