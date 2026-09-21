import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import transaction_scope
from app.models.notification import Notification, NotificationDeliveryAttempt
from app.services.realtime import RealtimePublisher

logger = logging.getLogger(__name__)


class NotificationDeliveryCoordinator:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        publisher: RealtimePublisher,
        *,
        maximum_attempts: int = 5,
        lease_seconds: int = 30,
    ) -> None:
        self.session_factory = session_factory
        self.publisher = publisher
        self.maximum_attempts = maximum_attempts
        self.lease_seconds = lease_seconds

    @staticmethod
    def payload(notification: Notification) -> dict[str, Any]:
        return {
            "type": "notification.created",
            "data": {
                "id": str(notification.id),
                "category": notification.category,
                "title": notification.title,
                "summary": notification.summary,
                "target_type": notification.target_type,
                "target_id": str(notification.target_id) if notification.target_id else None,
                "read_at": notification.read_at.isoformat() if notification.read_at else None,
                "created_at": notification.created_at.isoformat(),
            },
        }

    async def deliver(
        self,
        notification_id: UUID,
        recipient_id: UUID,
        payload: dict[str, Any],
        *,
        attempt_no: int = 1,
    ) -> None:
        now = datetime.now(UTC)
        async with transaction_scope(self.session_factory) as session:
            attempt = await session.scalar(
                select(NotificationDeliveryAttempt)
                .where(
                    NotificationDeliveryAttempt.notification_id == notification_id,
                    NotificationDeliveryAttempt.attempt_no == attempt_no,
                    NotificationDeliveryAttempt.status == "pending",
                    NotificationDeliveryAttempt.next_retry_at.is_not(None),
                    NotificationDeliveryAttempt.next_retry_at <= now,
                )
                .with_for_update()
            )
            if attempt is None:
                return
            attempt.next_retry_at = now + timedelta(seconds=self.lease_seconds)
        await self._publish_claimed(notification_id, recipient_id, payload, attempt_no)

    async def _publish_claimed(
        self,
        notification_id: UUID,
        recipient_id: UUID,
        payload: dict[str, Any],
        attempt_no: int,
    ) -> None:
        delivered = False
        try:
            delivered = await self.publisher.publish((recipient_id,), payload)
        except Exception:
            logger.warning("Notification realtime delivery failed", exc_info=True)
        now = datetime.now(UTC)
        async with transaction_scope(self.session_factory) as session:
            attempt = await session.scalar(
                select(NotificationDeliveryAttempt)
                .where(
                    NotificationDeliveryAttempt.notification_id == notification_id,
                    NotificationDeliveryAttempt.attempt_no == attempt_no,
                    NotificationDeliveryAttempt.status == "pending",
                )
                .with_for_update()
            )
            if attempt is None:
                return
            if delivered:
                attempt.status = "delivered"
                attempt.delivered_at = now
                attempt.error_code = None
                attempt.detail = None
                attempt.next_retry_at = None
            else:
                attempt.status = "failed"
                attempt.error_code = "realtime_unavailable"
                attempt.detail = "Realtime delivery was not accepted."
                attempt.next_retry_at = (
                    now + timedelta(seconds=min(2**attempt_no, 60))
                    if attempt_no < self.maximum_attempts
                    else None
                )

    async def retry_due(self, *, limit: int = 50) -> int:
        now = datetime.now(UTC)
        queued: list[tuple[UUID, UUID, dict[str, Any], int]] = []
        async with transaction_scope(self.session_factory) as session:
            rows = await session.execute(
                select(NotificationDeliveryAttempt, Notification)
                .join(Notification, Notification.id == NotificationDeliveryAttempt.notification_id)
                .where(
                    NotificationDeliveryAttempt.status.in_(("pending", "failed")),
                    NotificationDeliveryAttempt.next_retry_at.is_not(None),
                    NotificationDeliveryAttempt.next_retry_at <= now,
                    (
                        (NotificationDeliveryAttempt.status == "pending")
                        | (NotificationDeliveryAttempt.attempt_no < self.maximum_attempts)
                    ),
                )
                .order_by(NotificationDeliveryAttempt.next_retry_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            for previous, notification in rows:
                if previous.status == "failed":
                    attempt_no = previous.attempt_no + 1
                    session.add(
                        NotificationDeliveryAttempt(
                            id=uuid4(),
                            notification_id=notification.id,
                            attempt_no=attempt_no,
                            status="pending",
                            next_retry_at=now + timedelta(seconds=self.lease_seconds),
                        )
                    )
                    previous.next_retry_at = None
                else:
                    attempt_no = previous.attempt_no
                    previous.next_retry_at = now + timedelta(seconds=self.lease_seconds)
                queued.append(
                    (
                        notification.id,
                        notification.user_id,
                        self.payload(notification),
                        attempt_no,
                    )
                )
        for notification_id, recipient_id, payload, attempt_no in queued:
            await self._publish_claimed(notification_id, recipient_id, payload, attempt_no)
        return len(queued)

    async def run(self, *, interval_seconds: float = 5) -> None:
        while True:
            try:
                await self.retry_due()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Notification delivery retry failed")
            await asyncio.sleep(interval_seconds)
