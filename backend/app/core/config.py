from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="APP_",
        extra="ignore",
    )

    environment: str = Field(default="development", validation_alias="APP_ENV")
    log_level: str = Field(default="INFO", validation_alias="APP_LOG_LEVEL")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"],
        validation_alias="APP_CORS_ORIGINS",
    )
    database_url: str | None = Field(default=None, validation_alias="DATABASE_URL")
    redis_url: str | None = Field(default=None, validation_alias="REDIS_URL")


@lru_cache
def get_settings() -> Settings:
    return Settings()
