import asyncio
import os

from app.core.config import get_settings
from app.db.session import create_database_engine, create_session_factory, transaction_scope
from app.db.url import require_project_database
from app.repositories.product_images import SqlAlchemyProductImageUploadRepository
from app.services.product_images import ProductImageProcessor, ProductImageUploadService
from app.services.product_storage import LocalObjectStorage


async def main() -> None:
    settings = get_settings()
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL is required for cleanup")
    require_project_database(settings.database_url)
    engine = create_database_engine(settings.database_url, schema=os.getenv("DATABASE_SCHEMA"))
    factory = create_session_factory(engine)
    try:
        async with transaction_scope(factory) as session:
            service = ProductImageUploadService(
                repository=SqlAlchemyProductImageUploadRepository(session),
                storage=LocalObjectStorage(settings.resolved_public_product_storage_root),
                processor=ProductImageProcessor(
                    max_bytes=settings.product_image_max_bytes,
                    max_pixels=settings.product_image_max_pixels,
                ),
                max_uploads=settings.product_image_max_uploads,
                upload_hours=settings.product_image_upload_hours,
            )
            deleted = await service.cleanup_expired()
            print(f"deleted_expired_product_images={deleted}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
