from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CategoryNodeResponse(BaseModel):
    id: UUID
    code: str
    slug: str
    name: str
    display_order: int = Field(ge=0)
    children: list["CategoryNodeResponse"] = Field(default_factory=list)


class CampusCatalogResponse(BaseModel):
    id: UUID
    code: str
    name: str
    display_order: int = Field(ge=0)


class SchoolCatalogResponse(BaseModel):
    id: UUID
    code: str
    name: str
    campuses: list[CampusCatalogResponse]


class AdminCategoryResponse(BaseModel):
    id: UUID
    parent_id: UUID | None
    code: str
    slug: str
    name: str
    level: int
    display_order: int
    is_active: bool
    deleted_at: datetime | None
    version: int


class AdminCampusResponse(BaseModel):
    id: UUID
    school_id: UUID
    school_name: str
    code: str
    name: str
    display_order: int
    is_active: bool
    deleted_at: datetime | None
    version: int


class CatalogItemUpdate(BaseModel):
    version: int = Field(ge=1)
    display_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
