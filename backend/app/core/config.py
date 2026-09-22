from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="APP_",
        extra="ignore",
        populate_by_name=True,
    )

    environment: Literal["development", "test", "production"] = Field(
        default="development", validation_alias="APP_ENV"
    )
    log_level: str = Field(default="INFO", validation_alias="APP_LOG_LEVEL")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"],
        validation_alias="APP_CORS_ORIGINS",
    )
    database_url: str | None = Field(default=None, validation_alias="DATABASE_URL")
    redis_url: str | None = Field(default=None, validation_alias="REDIS_URL")
    auth_secret_key: SecretStr | None = Field(default=None, validation_alias="AUTH_SECRET_KEY")
    auth_verification_secret: SecretStr | None = Field(
        default=None, validation_alias="AUTH_VERIFICATION_SECRET"
    )
    registration_enabled: bool = Field(default=True, validation_alias="AUTH_REGISTRATION_ENABLED")
    user_agreement_version: str = Field(
        default="development-placeholder", validation_alias="AUTH_USER_AGREEMENT_VERSION"
    )
    privacy_policy_version: str = Field(
        default="development-placeholder", validation_alias="AUTH_PRIVACY_POLICY_VERSION"
    )
    access_token_minutes: int = Field(default=15, ge=5, le=60)
    refresh_token_days: int = Field(default=30, ge=1, le=90)
    recent_auth_minutes: int = Field(default=15, ge=5, le=60)
    password_reset_minutes: int = Field(default=30, ge=10, le=60)
    frontend_public_url: str = Field(
        default="http://127.0.0.1:5173", validation_alias="FRONTEND_PUBLIC_URL"
    )
    campus_verification_days: int = Field(default=365, ge=30, le=730)
    campus_appeal_retention_days: int = Field(default=180, ge=30, le=730)
    campus_appeal_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=25 * 1024 * 1024)
    report_evidence_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=25 * 1024 * 1024)
    report_hourly_limit: int = Field(default=10, ge=1, le=100)
    private_storage_root: Path = Field(default=BACKEND_ROOT / "var" / "private")
    public_product_storage_root: Path = Field(default=BACKEND_ROOT / "var" / "public-products")
    product_image_max_bytes: int = Field(default=8 * 1024 * 1024, ge=1024, le=20 * 1024 * 1024)
    product_image_max_pixels: int = Field(default=20_000_000, ge=1_000_000, le=50_000_000)
    product_image_max_uploads: int = Field(default=12, ge=1, le=30)
    product_image_upload_hours: int = Field(default=24, ge=1, le=168)
    qq_smtp_username: str | None = Field(default=None, validation_alias="QQ_SMTP_USERNAME")
    qq_smtp_auth_code: SecretStr | None = Field(default=None, validation_alias="QQ_SMTP_AUTH_CODE")
    qq_smtp_from_name: str = Field(default="拾光集市", validation_alias="QQ_SMTP_FROM_NAME")

    @property
    def resolved_private_storage_root(self) -> Path:
        if self.private_storage_root.is_absolute():
            return self.private_storage_root.resolve()
        return (BACKEND_ROOT / self.private_storage_root).resolve()

    @property
    def resolved_public_product_storage_root(self) -> Path:
        if self.public_product_storage_root.is_absolute():
            return self.public_product_storage_root.resolve()
        return (BACKEND_ROOT / self.public_product_storage_root).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
