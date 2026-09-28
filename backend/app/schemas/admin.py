from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.catalog import ProductStatus
from app.models.identity import UserStatus
from app.schemas.catalog import AdminCampusResponse, AdminCategoryResponse


class ReasonModel(BaseModel):
    @field_validator("reason", mode="before", check_fields=False)
    @classmethod
    def trim_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class AdminCapabilities(BaseModel):
    roles: list[str]
    permissions: list[str]
    must_change_password: bool


class StaffSummary(BaseModel):
    id: UUID
    username: str | None
    email: str | None
    display_name: str
    status: UserStatus
    roles: list[str]
    created_at: datetime


class StaffList(BaseModel):
    items: list[StaffSummary]
    total: int
    page: int
    page_size: int


class StaffInvitation(ReasonModel):
    email: EmailStr
    role: str
    reason: str = Field(min_length=5, max_length=500)
    confirm_email: EmailStr


class StaffRolesUpdate(ReasonModel):
    roles: list[str] = Field(min_length=1, max_length=4)
    reason: str = Field(min_length=5, max_length=500)
    confirm_target: UUID


class StatusUpdate(ReasonModel):
    status: UserStatus
    reason: str = Field(min_length=5, max_length=500)
    confirm_target: UUID


class UserSummaryAdmin(BaseModel):
    id: UUID
    username: str | None
    email: str | None
    display_name: str
    status: UserStatus
    campus_status: str
    created_at: datetime


class UserListAdmin(BaseModel):
    items: list[UserSummaryAdmin]
    total: int
    page: int
    page_size: int


class ProductSummaryAdmin(BaseModel):
    id: UUID
    title: str
    seller_id: UUID
    seller_name: str
    status: ProductStatus
    report_penalty_active: bool
    price: str
    version: int
    created_at: datetime


class ProductListAdmin(BaseModel):
    items: list[ProductSummaryAdmin]
    total: int
    page: int
    page_size: int


class CampusAppealSummaryAdmin(BaseModel):
    id: UUID
    user_id: UUID
    campus_id: UUID
    status: str
    reason: str
    original_filename: str
    created_at: datetime
    reviewed_at: datetime | None
    review_reason: str | None


class CampusAppealListAdmin(BaseModel):
    items: list[CampusAppealSummaryAdmin]
    total: int
    page: int
    page_size: int


class CampusAppealDecisionAdmin(ReasonModel):
    action: str = Field(pattern="^(approve|reject)$")
    reason: str = Field(min_length=5, max_length=500)
    confirm_target: UUID


class CatalogUpdateAdmin(ReasonModel):
    version: int = Field(ge=1)
    display_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
    reason: str = Field(min_length=5, max_length=500)
    confirm_target: UUID


class CategoryListAdmin(BaseModel):
    items: list[AdminCategoryResponse]
    total: int
    page: int
    page_size: int


class CampusListAdmin(BaseModel):
    items: list[AdminCampusResponse]
    total: int
    page: int
    page_size: int


class DashboardMetricsAdmin(BaseModel):
    starts_at: datetime
    ends_at: datetime
    registered_users: int
    verified_campus: int
    published_products: int
    completed_orders: int
    submitted_reports: int
    pending_products_now: int
    active_sessions_now: int


class AuditEntryAdmin(BaseModel):
    id: UUID
    actor_id: UUID | None
    action: str
    target_type: str
    target_id: UUID | None
    audit_data: dict[str, object]
    created_at: datetime


class AuditListAdmin(BaseModel):
    items: list[AuditEntryAdmin]
    total: int
    page: int
    page_size: int


class AuditExportCreate(ReasonModel):
    starts_at: datetime
    ends_at: datetime
    action: str | None = Field(default=None, max_length=96)
    reason: str = Field(min_length=5, max_length=500)


class AuditExportSummary(BaseModel):
    id: UUID
    status: str
    created_at: datetime
    expires_at: datetime
    revoked: bool
    failure_code: str | None


class AuditExportList(BaseModel):
    items: list[AuditExportSummary]
    total: int
    page: int
    page_size: int
