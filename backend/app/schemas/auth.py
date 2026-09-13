from datetime import datetime
from typing import Literal
from unicodedata import category
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class EmailVerificationRequest(BaseModel):
    email: EmailStr
    purpose: Literal["registration"] = "registration"


class RegisterRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    display_name: str = Field(min_length=2, max_length=30)
    password: str = Field(min_length=8, max_length=128)
    accept_user_agreement: bool
    accept_privacy_policy: bool

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        return validate_display_name_value(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserSummary(BaseModel):
    id: UUID
    login_email: EmailStr
    display_name: str
    status: str
    campus_verification_status: str


class AuthResponse(BaseModel):
    access_token: str
    access_token_expires_at: datetime
    token_type: Literal["bearer"] = "bearer"
    user: UserSummary


class MessageResponse(BaseModel):
    message: str


def validate_display_name_value(value: str) -> str:
    normalized = value.strip()
    reserved_names = ("拾光集市", "官方", "管理员", "客服", "系统通知")
    if not 2 <= len(normalized) <= 30 or any(
        category(character).startswith("C") for character in normalized
    ):
        raise ValueError("公开昵称格式不正确")
    if any(name.casefold() in normalized.casefold() for name in reserved_names):
        raise ValueError("公开昵称不能冒充平台官方身份")
    return normalized
