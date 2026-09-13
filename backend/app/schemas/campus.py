from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class CampusSummary(BaseModel):
    id: UUID
    name: str


class SchoolSummary(BaseModel):
    id: UUID
    name: str
    campuses: list[CampusSummary]
    email_domains: list[str]


class CampusPolicyResponse(BaseModel):
    verification_days: int
    appeal_retention_days: int
    appeal_max_bytes: int
    appeal_media_types: list[str]


class CampusEmailVerificationRequest(BaseModel):
    school_id: UUID
    campus_id: UUID
    campus_email: EmailStr


class CampusEmailVerificationConfirm(BaseModel):
    verification_id: UUID
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class CampusVerificationRequestResponse(BaseModel):
    verification_id: UUID
    message: str


class AppealSummary(BaseModel):
    id: UUID
    status: str
    original_filename: str
    retention_until: datetime


class CampusStatusResponse(BaseModel):
    status: str
    verification_id: UUID | None
    campus_id: UUID | None
    campus_email: EmailStr | None
    verified_at: datetime | None
    expires_at: datetime | None
    appeal: AppealSummary | None


class AppealResponse(BaseModel):
    id: UUID
    status: str
    original_filename: str
    retention_until: datetime


class CapabilityResponse(BaseModel):
    capability: Literal["publish", "message", "order", "review"]
    allowed: Literal[True] = True
