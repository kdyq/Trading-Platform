from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ProductImageUploadResponse(BaseModel):
    id: UUID
    original_filename: str
    media_type: str
    size_bytes: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    expires_at: datetime
    preview_url: str


class ProductImageCleanupResponse(BaseModel):
    deleted: int = Field(ge=0)
