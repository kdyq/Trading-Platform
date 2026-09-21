import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import transaction_scope
from app.repositories.orders import SqlAlchemyOrderRepository
from app.services.orders import OrderService

logger = logging.getLogger(__name__)


class OrderExpirationCoordinator:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def expire_due(self, *, limit: int = 50) -> int:
        async with transaction_scope(self.session_factory) as session:
            service = OrderService(SqlAlchemyOrderRepository(session))
            return await service.expire_pending(limit=limit)

    async def run(self, *, interval_seconds: float = 30) -> None:
        while True:
            try:
                await self.expire_due()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Order expiration sweep failed")
            await asyncio.sleep(interval_seconds)
