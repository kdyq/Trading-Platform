import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

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


class ObjectStorage(Protocol):
    def put(self, key: str, content: bytes, *, media_type: str) -> None: ...

    def move(self, source_key: str, destination_key: str) -> None: ...

    def delete(self, key: str) -> None: ...


class S3Client(Protocol):
    def put_object(self, **kwargs: object) -> object: ...

    def copy_object(self, **kwargs: object) -> object: ...

    def delete_object(self, **kwargs: object) -> object: ...


class LocalObjectStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def path_for(self, key: str) -> Path:
        target = (self.root / key).resolve()
        if not target.is_relative_to(self.root) or Path(key).is_absolute():
            raise AppError(status_code=422, code="invalid_object_key", message="图片对象键无效")
        return target

    def put(self, key: str, content: bytes, *, media_type: str) -> None:
        del media_type
        target = self.path_for(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.upload")
        temporary.write_bytes(content)
        os.replace(temporary, target)

    def move(self, source_key: str, destination_key: str) -> None:
        source = self.path_for(source_key)
        destination = self.path_for(destination_key)
        if not source.is_file():
            raise AppError(status_code=409, code="image_source_missing", message="待确认图片不存在")
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)

    def delete(self, key: str) -> None:
        self.path_for(key).unlink(missing_ok=True)


class S3CompatibleObjectStorage:
    def __init__(self, client: S3Client, bucket: str) -> None:
        if not bucket.strip():
            raise ValueError("bucket is required")
        self.client = client
        self.bucket = bucket

    def put(self, key: str, content: bytes, *, media_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._safe_key(key),
            Body=content,
            ContentType=media_type,
        )

    def move(self, source_key: str, destination_key: str) -> None:
        source = self._safe_key(source_key)
        destination = self._safe_key(destination_key)
        self.client.copy_object(
            Bucket=self.bucket,
            Key=destination,
            CopySource={"Bucket": self.bucket, "Key": source},
        )
        self.client.delete_object(Bucket=self.bucket, Key=source)

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._safe_key(key))

    @staticmethod
    def _safe_key(key: str) -> str:
        path = Path(key)
        if path.is_absolute() or ".." in path.parts or not key.strip():
            raise AppError(status_code=422, code="invalid_object_key", message="图片对象键无效")
        return path.as_posix()


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
