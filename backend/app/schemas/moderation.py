from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ModerationReasonModel(BaseModel):
    @field_validator(
        "reason_code",
        "public_note",
        "public_result",
        "internal_reason",
        "reason",
        "override_reason",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def trim_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ModerationProductSummary(BaseModel):
    id: UUID
    seller_id: UUID
    seller_name: str
    title: str
    description: str
    price: Decimal
    status: str
    version: int
    image_urls: list[str]
    moderation_reason_code: str | None
    moderation_public_note: str | None
    created_at: datetime
    updated_at: datetime


class ModerationProductList(BaseModel):
    items: list[ModerationProductSummary]
    page: int
    page_size: int
    total: int


class ProductModerationDecision(ModerationReasonModel):
    action: Literal["approve", "reject", "hide", "restore"]
    version: int = Field(ge=1)
    reason_code: str = Field(min_length=3, max_length=64)
    public_note: str = Field(min_length=5, max_length=500)
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    confirm_target: UUID | None = None


class ModerationReportSummary(BaseModel):
    id: UUID
    reporter_id: UUID
    subject_user_id: UUID | None
    target_type: str
    target_id: UUID
    reason_code: str
    details: str | None
    status: str
    public_result: str | None
    version: int
    evidence_ids: list[UUID]
    created_at: datetime
    updated_at: datetime


class ModerationReportList(BaseModel):
    items: list[ModerationReportSummary]
    page: int
    page_size: int
    total: int


class ReportModerationDecision(ModerationReasonModel):
    action: Literal["review", "dismiss", "violate"]
    version: int = Field(ge=1)
    penalty_code: Literal["none", "warn", "hide", "suspend"] = "none"
    penalty_points: int = Field(default=0, ge=0, le=20)
    public_result: str = Field(min_length=5, max_length=500)
    internal_reason: str = Field(min_length=5, max_length=1000)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=20)
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    confirm_target: UUID | None = None


class ReportAppealCreate(BaseModel):
    details: str = Field(min_length=10, max_length=1000)


class ReportAppealResponse(BaseModel):
    id: UUID
    report_id: UUID
    status: str
    details: str
    review_reason: str | None
    evidence_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ReportAppealList(BaseModel):
    items: list[ReportAppealResponse]
    page: int
    page_size: int
    total: int


class AppealReviewDecision(ModerationReasonModel):
    action: Literal["uphold", "reverse"]
    reason: str = Field(min_length=5, max_length=1000)
    override_reason: str | None = Field(default=None, min_length=5, max_length=500)
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    confirm_target: UUID | None = None
