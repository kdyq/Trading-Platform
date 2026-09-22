from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ReportCreate(BaseModel):
    target_type: Literal["product", "user", "message", "order"]
    target_id: UUID
    reason_code: str = Field(
        pattern=r"^(fraud|harassment|spam|prohibited|unsafe|counterfeit|no_show|other)$"
    )
    details: str = Field(min_length=5, max_length=1000)

    @field_validator("details", mode="before")
    @classmethod
    def strip_details(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ReportEvidenceResponse(BaseModel):
    id: UUID
    original_filename: str
    media_type: str
    size_bytes: int
    created_at: datetime


class ReportEventResponse(BaseModel):
    id: UUID
    from_status: str | None
    to_status: str
    public_note: str | None
    created_at: datetime


class ReportResponse(BaseModel):
    id: UUID
    target_type: str
    target_id: UUID
    reason_code: str
    details: str | None
    status: str
    public_result: str | None
    version: int
    evidence: list[ReportEvidenceResponse] = Field(default_factory=list)
    events: list[ReportEventResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ReportListResponse(BaseModel):
    items: list[ReportResponse]
