from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import AppError

IMAGE_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".avif": "image/avif",
}


@dataclass(frozen=True)
class PublicProductFile:
    path: Path
    media_type: str


class PublicProductStorage:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def resolve(self, key: str) -> PublicProductFile:
        target = (self._root / key).resolve()
        media_type = IMAGE_MEDIA_TYPES.get(target.suffix.lower())
        if not target.is_relative_to(self._root) or media_type is None or not target.is_file():
            raise AppError(
                status_code=404,
                code="product_image_not_found",
                message="商品图片不存在",
            )
        return PublicProductFile(path=target, media_type=media_type)
