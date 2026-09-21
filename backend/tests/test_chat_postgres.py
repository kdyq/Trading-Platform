import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.url import database_url_for_sqlalchemy, require_project_database
from app.models import Base
from app.models.messaging import Conversation
from app.models.notification import NotificationDeliveryAttempt
from app.repositories.chat import SqlAlchemyChatRepository
from app.services.notifications import NotificationDeliveryCoordinator


class SequencePublisher:
    def __init__(self, outcomes: list[bool]) -> None:
        self.outcomes = outcomes

    async def publish(self, user_ids, payload):  # type: ignore[no-untyped-def]
        return self.outcomes.pop(0)


def test_chat_repository_enforces_unique_conversations_and_message_state() -> None:
    database_url = os.getenv("DATABASE_URL")
    if database_url is None:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    require_project_database(database_url)
    asyncio.run(_exercise_chat_repository(database_url_for_sqlalchemy(database_url)))


async def _exercise_chat_repository(database_url: str) -> None:
    schema = f"test_chat_{uuid4().hex}"
    admin_engine = create_async_engine(database_url)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        database_url,
        connect_args={"server_settings": {"timezone": "UTC", "search_path": schema}},
    )
    seller_id, buyer_id, outsider_id = uuid4(), uuid4(), uuid4()
    school_id, campus_id, category_id, product_id = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.execute(
                text("INSERT INTO schools (id, code, name) VALUES (:id, 'CHAT', '聊天测试学校')"),
                {"id": school_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO campuses (id, school_id, code, name) "
                    "VALUES (:id, :school, 'MAIN', '主校区')"
                ),
                {"id": campus_id, "school": school_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO categories (id, code, slug, name) "
                    "VALUES (:id, 'chat', 'chat', '聊天测试')"
                ),
                {"id": category_id},
            )
            for user_id, email, name in (
                (seller_id, "chat-seller@example.com", "卖家"),
                (buyer_id, "chat-buyer@example.com", "买家"),
                (outsider_id, "chat-outsider@example.com", "路人"),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO users "
                        "(id, login_email, password_hash, display_name, login_email_verified_at, "
                        "user_agreement_version, privacy_policy_version, terms_agreed_at) "
                        "VALUES (:id, :email, 'hash', :name, now(), 'test', 'test', now())"
                    ),
                    {"id": user_id, "email": email, "name": name},
                )
            await connection.execute(
                text(
                    "INSERT INTO products "
                    "(id, seller_id, campus_id, category_id, title, description, price, status, "
                    "published_at) VALUES "
                    "(:id, :seller, :campus, :category, '聊天商品', '用于聊天测试', 9.90, "
                    "'on_sale', now())"
                ),
                {
                    "id": product_id,
                    "seller": seller_id,
                    "campus": campus_id,
                    "category": category_id,
                },
            )

        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def create_conversation() -> Conversation:
            async with factory.begin() as session:
                repository = SqlAlchemyChatRepository(session)
                product = await repository.visible_product_for_chat(product_id)
                assert product is not None
                return await repository.create_or_get_conversation(
                    product=product, buyer_id=buyer_id
                )

        first, second = await asyncio.gather(create_conversation(), create_conversation())
        assert first.id == second.id

        async with factory.begin() as session:
            repository = SqlAlchemyChatRepository(session)
            conversation = await repository.get_member_conversation(buyer_id, first.id)
            assert conversation is not None
            assert await repository.get_member_conversation(outsider_id, first.id) is None
            sent = []
            for index in range(3):
                sent.append(
                    await repository.create_message(
                        conversation_id=first.id,
                        sender_id=seller_id,
                        client_message_id=f"postgres_{index}",
                        body=f"消息 {index}",
                    )
                )
            duplicate = await repository.create_message(
                conversation_id=first.id,
                sender_id=seller_id,
                client_message_id="postgres_0",
                body="消息 0",
            )
            assert duplicate.message.id == sent[0].message.id
            summaries = await repository.list_conversations(buyer_id, 20)
            assert summaries[0].unread_count == 3
            messages = [item.message for item in sent]
            latest_message = max(messages, key=lambda item: (item.created_at, item.id))
            await repository.mark_read(
                conversation_id=first.id, user_id=buyer_id, message=latest_message
            )
            assert (await repository.list_conversations(buyer_id, 20))[0].unread_count == 0
            latest = await repository.list_messages(
                first.id, before_created_at=None, before_id=None, limit=2
            )
            expected = sorted(messages, key=lambda item: (item.created_at, item.id))[-2:]
            assert [item.id for item in latest] == [item.id for item in expected]

            notification = await repository.create_chat_notification(
                recipient_id=buyer_id, message=latest_message
            )
            duplicate_notification = await repository.create_chat_notification(
                recipient_id=buyer_id, message=latest_message
            )
            assert notification is not None and duplicate_notification is not None
            assert notification.id == duplicate_notification.id
            assert latest_message.body not in notification.summary
            attempts = await session.scalar(
                select(func.count(NotificationDeliveryAttempt.id)).where(
                    NotificationDeliveryAttempt.notification_id == notification.id
                )
            )
            assert attempts == 1
            attempt = await session.scalar(
                select(NotificationDeliveryAttempt).where(
                    NotificationDeliveryAttempt.notification_id == notification.id
                )
            )
            assert (
                attempt is not None
                and attempt.status == "pending"
                and attempt.next_retry_at is not None
            )
            other_recipient = await repository.create_notification_event(
                recipient_id=seller_id,
                event_key=f"shared-event:{latest_message.id}",
                category="chat",
                title="共享事件",
                summary="同一事件可按收件人分别投递。",
                target_type="conversation",
                target_id=first.id,
            )
            buyer_recipient = await repository.create_notification_event(
                recipient_id=buyer_id,
                event_key=f"shared-event:{latest_message.id}",
                category="chat",
                title="共享事件",
                summary="同一事件可按收件人分别投递。",
                target_type="conversation",
                target_id=first.id,
            )
            assert other_recipient is not None and buyer_recipient is not None
            assert other_recipient.id != buyer_recipient.id
            await session.execute(
                update(NotificationDeliveryAttempt)
                .where(
                    NotificationDeliveryAttempt.notification_id.in_(
                        (other_recipient.id, buyer_recipient.id)
                    )
                )
                .values(next_retry_at=None)
            )
            assert await repository.unread_notification_count(buyer_id) == 2
            assert await repository.mark_notification_read(buyer_id, notification.id) is not None
            assert await repository.mark_all_notifications_read(buyer_id) == 1
            assert await repository.unread_notification_count(buyer_id) == 0

            report = await repository.report_message(
                reporter_id=buyer_id,
                message_id=latest_message.id,
                reason_code="spam",
                details="重复发送无关信息",
            )
            repeated_report = await repository.report_message(
                reporter_id=buyer_id,
                message_id=latest_message.id,
                reason_code="spam",
                details="不会覆盖已有证据",
            )
            assert report.id == repeated_report.id

            assert await repository.lock_users(buyer_id, seller_id)
            await repository.block_user(buyer_id, seller_id)
            assert await repository.blocked_between(buyer_id, seller_id)
            assert await repository.list_blocked_user_ids(buyer_id) == [seller_id]
            await repository.unblock_user(buyer_id, seller_id)
            assert not await repository.blocked_between(buyer_id, seller_id)

        recovery = NotificationDeliveryCoordinator(
            factory,
            SequencePublisher([True]),
        )
        assert await recovery.retry_due() == 1
        async with factory.begin() as session:
            recovered = await session.scalar(
                select(NotificationDeliveryAttempt).where(
                    NotificationDeliveryAttempt.notification_id == notification.id
                )
            )
            assert recovered is not None and recovered.status == "delivered"
            await session.execute(
                update(NotificationDeliveryAttempt)
                .where(NotificationDeliveryAttempt.notification_id == buyer_recipient.id)
                .values(next_retry_at=func.now())
            )

        delivery = NotificationDeliveryCoordinator(factory, SequencePublisher([False, True]))
        await delivery.deliver(
            buyer_recipient.id,
            buyer_id,
            delivery.payload(buyer_recipient),
        )
        async with factory.begin() as session:
            await session.execute(
                update(NotificationDeliveryAttempt)
                .where(NotificationDeliveryAttempt.notification_id == buyer_recipient.id)
                .values(next_retry_at=func.now())
            )
        assert await delivery.retry_due() == 1
        async with factory.begin() as session:
            delivery_states = list(
                await session.scalars(
                    select(NotificationDeliveryAttempt.status)
                    .where(NotificationDeliveryAttempt.notification_id == buyer_recipient.id)
                    .order_by(NotificationDeliveryAttempt.attempt_no)
                )
            )
            assert delivery_states == ["failed", "delivered"]

        async with factory.begin() as session:
            await session.execute(
                update(NotificationDeliveryAttempt)
                .where(NotificationDeliveryAttempt.notification_id == other_recipient.id)
                .values(status="processing", attempt_no=5, next_retry_at=func.now())
            )
        exhausted = NotificationDeliveryCoordinator(factory, SequencePublisher([]))
        assert await exhausted.retry_due() == 0
        async with factory.begin() as session:
            terminal = await session.scalar(
                select(NotificationDeliveryAttempt).where(
                    NotificationDeliveryAttempt.notification_id == other_recipient.id
                )
            )
            assert (
                terminal is not None
                and terminal.status == "failed"
                and terminal.next_retry_at is None
                and terminal.error_code == "delivery_lease_expired"
            )
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()
