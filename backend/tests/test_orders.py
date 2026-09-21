from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import AppError
from app.models.catalog import ProductStatus
from app.models.identity import CampusVerificationStatus
from app.models.trade import Order, OrderCommand, OrderEvent, OrderStatus
from app.schemas.orders import OrderCreate
from app.services.orders import OrderService


class FakeOrderRepository:
    def __init__(self) -> None:
        self.buyer_id = uuid4()
        self.seller_id = uuid4()
        self.campus_id = uuid4()
        self.product_id = uuid4()
        self.product = SimpleNamespace(
            id=self.product_id,
            seller_id=self.seller_id,
            campus_id=self.campus_id,
            title="高等数学教材",
            price=Decimal("18.50"),
            status=ProductStatus.ON_SALE,
            reserved_at=None,
        )
        self.users = {
            self.buyer_id: SimpleNamespace(id=self.buyer_id, display_name="买家"),
            self.seller_id: SimpleNamespace(id=self.seller_id, display_name="卖家"),
        }
        self.orders: dict[UUID, Order] = {}
        self.idempotency: dict[tuple[UUID, str], UUID] = {}
        self.commands: dict[tuple[UUID, str], OrderCommand] = {}
        self.events: list[OrderEvent] = []
        self.notifications: list[dict[str, object]] = []

    async def verified_campus_id(self, user_id):  # type: ignore[no-untyped-def]
        return self.campus_id if user_id == self.buyer_id else None

    async def get_user(self, user_id):  # type: ignore[no-untyped-def]
        return self.users.get(user_id)

    async def lock_product(self, product_id):  # type: ignore[no-untyped-def]
        return self.product if product_id == self.product_id else None

    async def campus_name(self, campus_id):  # type: ignore[no-untyped-def]
        return "东校区" if campus_id == self.campus_id else None

    async def member_conversation(self, conversation_id, user_id, product_id):  # type: ignore[no-untyped-def]
        return None

    async def create_order(self, order):  # type: ignore[no-untyped-def]
        key = (order.buyer_id, order.idempotency_key)
        if key in self.idempotency:
            return self.orders[self.idempotency[key]], False
        now = datetime.now(UTC)
        order.created_at = now
        order.updated_at = now
        self.orders[order.id] = order
        self.idempotency[key] = order.id
        return order, True

    async def get_order(self, order_id, *, for_update=False):  # type: ignore[no-untyped-def]
        return self.orders.get(order_id)

    async def refresh_order(self, order):  # type: ignore[no-untyped-def]
        order.updated_at = datetime.now(UTC)

    async def find_command(self, actor_id, client_action_id):  # type: ignore[no-untyped-def]
        return self.commands.get((actor_id, client_action_id))

    def add_event(  # type: ignore[no-untyped-def]
        self, *, order, actor_id, from_status, to_status, note, event_data=None
    ):
        event = OrderEvent(
            id=uuid4(),
            order_id=order.id,
            actor_id=actor_id,
            from_status=from_status,
            to_status=to_status,
            note=note,
            event_data=event_data or {},
        )
        self.events.append(event)
        return event

    def add_command(self, **values):  # type: ignore[no-untyped-def]
        command = OrderCommand(id=uuid4(), **values)
        self.commands[(command.actor_id, command.client_action_id)] = command

    async def cancel_other_pending(self, **values):  # type: ignore[no-untyped-def]
        return []

    async def create_notification(self, **values):  # type: ignore[no-untyped-def]
        self.notifications.append(values)
        return None


@pytest.mark.anyio
async def test_create_order_uses_server_snapshots_and_is_idempotent() -> None:
    repository = FakeOrderRepository()
    service = OrderService(repository)
    payload = OrderCreate(product_id=repository.product_id, idempotency_key="order_create_001")

    created = await service.create(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        payload=payload,
    )
    repeated = await service.create(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        payload=payload,
    )

    assert repeated.id == created.id
    assert created.amount == Decimal("18.50")
    assert created.product_title == "高等数学教材"
    assert created.campus_name == "东校区"
    assert created.payment_mode == "offline"
    assert len(repository.events) == 1
    assert repository.notifications[0]["recipient_id"] == repository.seller_id


@pytest.mark.anyio
async def test_order_creation_rejects_owner_unverified_and_wrong_campus() -> None:
    repository = FakeOrderRepository()
    service = OrderService(repository)
    payload = OrderCreate(product_id=repository.product_id, idempotency_key="order_create_002")

    with pytest.raises(AppError) as owner:
        await service.create(
            user_id=repository.seller_id,
            campus_status=CampusVerificationStatus.VERIFIED,
            payload=payload,
        )
    assert owner.value.code == "cannot_buy_own_product"

    with pytest.raises(AppError) as unverified:
        await service.create(
            user_id=repository.buyer_id,
            campus_status=CampusVerificationStatus.PENDING,
            payload=payload,
        )
    assert unverified.value.code == "campus_verification_required"

    repository.campus_id = uuid4()
    with pytest.raises(AppError) as campus:
        await service.create(
            user_id=repository.buyer_id,
            campus_status=CampusVerificationStatus.VERIFIED,
            payload=payload,
        )
    assert campus.value.code == "order_campus_mismatch"


@pytest.mark.anyio
async def test_seller_accepts_once_and_product_is_reserved() -> None:
    repository = FakeOrderRepository()
    service = OrderService(repository)
    order = await service.create(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        payload=OrderCreate(
            product_id=repository.product_id,
            idempotency_key="order_create_003",
        ),
    )

    accepted = await service.accept(
        user_id=repository.seller_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=order.id,
        client_action_id="order_accept_001",
    )
    repeated = await service.accept(
        user_id=repository.seller_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=order.id,
        client_action_id="order_accept_001",
    )

    assert accepted.status == OrderStatus.ACCEPTED.value
    assert repeated.status == OrderStatus.ACCEPTED.value
    assert repository.product.status == ProductStatus.RESERVED
    assert len(repository.events) == 2

    with pytest.raises(AppError) as buyer_cannot_accept:
        await service.accept(
            user_id=repository.buyer_id,
            campus_status=CampusVerificationStatus.VERIFIED,
            order_id=order.id,
            client_action_id="order_accept_002",
        )
    assert buyer_cannot_accept.value.code == "order_not_found"
