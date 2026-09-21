from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import AppError
from app.models.catalog import ProductStatus
from app.models.identity import CampusVerificationStatus
from app.models.trade import (
    MeetingProposalStatus,
    Order,
    OrderCommand,
    OrderEvent,
    OrderMeetingProposal,
    OrderStatus,
)
from app.schemas.orders import MeetingProposalCreate, OrderCancel, OrderCreate, OrderDispute
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
        self.proposals: dict[UUID, OrderMeetingProposal] = {}
        self.notifications: list[dict[str, object]] = []
        self.reports: list[object] = []

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

    def add_meeting_proposal(self, proposal):  # type: ignore[no-untyped-def]
        self.proposals[proposal.id] = proposal

    async def get_meeting_proposal(self, proposal_id, *, for_update=False):  # type: ignore[no-untyped-def]
        return self.proposals.get(proposal_id)

    async def refresh_meeting_proposal(self, proposal):  # type: ignore[no-untyped-def]
        now = datetime.now(UTC)
        if proposal.created_at is None:
            proposal.created_at = now
        proposal.updated_at = now

    async def supersede_other_proposals(self, order_id, proposal_id):  # type: ignore[no-untyped-def]
        for proposal in self.proposals.values():
            if proposal.order_id == order_id and proposal.id != proposal_id:
                proposal.status = MeetingProposalStatus.SUPERSEDED

    async def withdraw_pending_proposals(self, order_id):  # type: ignore[no-untyped-def]
        for proposal in self.proposals.values():
            if proposal.order_id == order_id and proposal.status == MeetingProposalStatus.PENDING:
                proposal.status = MeetingProposalStatus.WITHDRAWN

    async def claim_expired_pending(self, limit):  # type: ignore[no-untyped-def]
        now = datetime.now(UTC)
        return [
            order
            for order in self.orders.values()
            if order.status == OrderStatus.PENDING_SELLER_CONFIRMATION
            and order.expires_at is not None
            and order.expires_at <= now
        ][:limit]

    def add_dispute_report(self, report):  # type: ignore[no-untyped-def]
        self.reports.append(report)

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


@pytest.mark.anyio
async def test_participants_confirm_meeting_and_cancellation_restores_product() -> None:
    repository = FakeOrderRepository()
    service = OrderService(repository)
    created = await service.create(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        payload=OrderCreate(product_id=repository.product_id, idempotency_key="meeting_create_1"),
    )
    await service.accept(
        user_id=repository.seller_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=created.id,
        client_action_id="meeting_accept_1",
    )
    proposal = await service.propose_meeting(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=created.id,
        payload=MeetingProposalCreate(
            client_action_id="meeting_propose_1",
            proposed_for=datetime.now(UTC) + timedelta(days=1),
            location_text="图书馆东门",
        ),
    )
    confirmed = await service.confirm_meeting(
        user_id=repository.seller_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=created.id,
        proposal_id=proposal.id,
        client_action_id="meeting_confirm_1",
    )
    repeated = await service.confirm_meeting(
        user_id=repository.seller_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=created.id,
        proposal_id=proposal.id,
        client_action_id="meeting_confirm_1",
    )

    assert confirmed.status == MeetingProposalStatus.ACCEPTED.value
    assert repeated.status == MeetingProposalStatus.ACCEPTED.value
    assert repository.orders[created.id].status == OrderStatus.SCHEDULED
    assert confirmed.location_text == "图书馆东门"

    cancelled = await service.cancel(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=created.id,
        payload=OrderCancel(
            client_action_id="meeting_cancel_1",
            reason_code="schedule_failed",
            note="双方无法调整时间",
        ),
    )
    repeated_cancel = await service.cancel(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=created.id,
        payload=OrderCancel(
            client_action_id="meeting_cancel_1",
            reason_code="schedule_failed",
            note="双方无法调整时间",
        ),
    )
    assert cancelled.status == OrderStatus.CANCELLED.value
    assert repeated_cancel.status == OrderStatus.CANCELLED.value
    assert repository.product.status == ProductStatus.ON_SALE
    assert repository.product.reserved_at is None


@pytest.mark.anyio
async def test_meeting_permissions_time_bounds_and_expiration_are_safe_to_retry() -> None:
    repository = FakeOrderRepository()
    service = OrderService(repository)
    created = await service.create(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        payload=OrderCreate(product_id=repository.product_id, idempotency_key="expiry_create_1"),
    )
    repository.orders[created.id].expires_at = datetime.now(UTC) - timedelta(seconds=1)

    assert await service.expire_pending() == 1
    assert await service.expire_pending() == 0
    assert repository.orders[created.id].status == OrderStatus.EXPIRED
    assert repository.product.status == ProductStatus.ON_SALE
    assert (
        len([event for event in repository.events if event.to_status == OrderStatus.EXPIRED]) == 1
    )

    outsider = uuid4()
    with pytest.raises(AppError) as unauthorized:
        await service.cancel(
            user_id=outsider,
            campus_status=CampusVerificationStatus.VERIFIED,
            order_id=created.id,
            payload=OrderCancel(client_action_id="outsider_cancel_1", reason_code="other"),
        )
    assert unauthorized.value.code == "order_not_found"


@pytest.mark.anyio
async def test_meeting_proposal_rejects_unauthorized_and_out_of_range_times() -> None:
    repository = FakeOrderRepository()
    service = OrderService(repository)
    created = await service.create(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        payload=OrderCreate(product_id=repository.product_id, idempotency_key="bounds_create_1"),
    )
    await service.accept(
        user_id=repository.seller_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=created.id,
        client_action_id="bounds_accept_1",
    )
    with pytest.raises(AppError) as too_soon:
        await service.propose_meeting(
            user_id=repository.buyer_id,
            campus_status=CampusVerificationStatus.VERIFIED,
            order_id=created.id,
            payload=MeetingProposalCreate(
                client_action_id="bounds_propose_1",
                proposed_for=datetime.now(UTC) + timedelta(minutes=5),
                location_text="教学楼门口",
            ),
        )
    assert too_soon.value.code == "meeting_time_out_of_range"

    with pytest.raises(AppError) as outsider:
        await service.propose_meeting(
            user_id=uuid4(),
            campus_status=CampusVerificationStatus.VERIFIED,
            order_id=created.id,
            payload=MeetingProposalCreate(
                client_action_id="bounds_propose_2",
                proposed_for=datetime.now(UTC) + timedelta(days=1),
                location_text="教学楼门口",
            ),
        )
    assert outsider.value.code == "order_not_found"


@pytest.mark.anyio
async def test_seller_delivery_and_buyer_completion_are_idempotent_and_atomic() -> None:
    repository = FakeOrderRepository()
    service = OrderService(repository)
    created = await service.create(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        payload=OrderCreate(product_id=repository.product_id, idempotency_key="complete_create_1"),
    )
    await service.accept(
        user_id=repository.seller_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=created.id,
        client_action_id="complete_accept_1",
    )
    delivered = await service.mark_delivered(
        user_id=repository.seller_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=created.id,
        client_action_id="complete_deliver_1",
    )
    repeated_delivery = await service.mark_delivered(
        user_id=repository.seller_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=created.id,
        client_action_id="complete_deliver_1",
    )
    assert delivered.status == OrderStatus.SELLER_DELIVERED.value
    assert repeated_delivery.status == OrderStatus.SELLER_DELIVERED.value

    completed = await service.complete(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=created.id,
        client_action_id="complete_confirm_1",
    )
    repeated_completion = await service.complete(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=created.id,
        client_action_id="complete_confirm_1",
    )
    assert completed.status == OrderStatus.COMPLETED.value
    assert repeated_completion.status == OrderStatus.COMPLETED.value
    assert repository.product.status == ProductStatus.SOLD
    assert repository.product.sold_at is not None

    with pytest.raises(AppError) as seller_cannot_complete:
        await service.complete(
            user_id=repository.seller_id,
            campus_status=CampusVerificationStatus.VERIFIED,
            order_id=created.id,
            client_action_id="complete_confirm_2",
        )
    assert seller_cannot_complete.value.code == "order_not_found"


@pytest.mark.anyio
async def test_dispute_freezes_order_and_creates_one_moderation_entry() -> None:
    repository = FakeOrderRepository()
    service = OrderService(repository)
    created = await service.create(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        payload=OrderCreate(product_id=repository.product_id, idempotency_key="dispute_create_1"),
    )
    await service.accept(
        user_id=repository.seller_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=created.id,
        client_action_id="dispute_accept_1",
    )
    payload = OrderDispute(
        client_action_id="dispute_open_1",
        reason_code="item_not_as_described",
        details="现场商品与描述存在明显差异",
    )
    disputed = await service.dispute(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=created.id,
        payload=payload,
    )
    repeated = await service.dispute(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=created.id,
        payload=payload,
    )
    assert disputed.status == OrderStatus.DISPUTED.value
    assert repeated.status == OrderStatus.DISPUTED.value
    assert len(repository.reports) == 1
    assert repository.product.status == ProductStatus.RESERVED

    with pytest.raises(AppError) as cannot_complete:
        await service.complete(
            user_id=repository.buyer_id,
            campus_status=CampusVerificationStatus.VERIFIED,
            order_id=created.id,
            client_action_id="dispute_complete_1",
        )
    assert cannot_complete.value.code == "invalid_order_state"
