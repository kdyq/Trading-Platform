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
    Review,
)
from app.schemas.orders import (
    MeetingProposalCreate,
    OrderCancel,
    OrderCreate,
    OrderDispute,
    ReviewCreate,
)
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
        self.report_events: list[object] = []

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
        open_order = next(
            (
                stored
                for stored in self.orders.values()
                if stored.buyer_id == order.buyer_id
                and stored.product_id == order.product_id
                and stored.status
                in {
                    OrderStatus.PENDING_SELLER_CONFIRMATION,
                    OrderStatus.ACCEPTED,
                    OrderStatus.SCHEDULED,
                    OrderStatus.SELLER_DELIVERED,
                    OrderStatus.DISPUTED,
                }
            ),
            None,
        )
        if open_order is not None:
            return open_order, False
        now = datetime.now(UTC)
        order.created_at = now
        order.updated_at = now
        self.orders[order.id] = order
        self.idempotency[key] = order.id
        return order, True

    async def find_order_by_idempotency(self, buyer_id, idempotency_key):  # type: ignore[no-untyped-def]
        order_id = self.idempotency.get((buyer_id, idempotency_key))
        return self.orders.get(order_id) if order_id else None

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

    def add_dispute_report_event(self, event):  # type: ignore[no-untyped-def]
        self.report_events.append(event)

    async def list_orders(  # type: ignore[no-untyped-def]
        self, *, user_id, role, status, before_updated_at, before_id, limit
    ):
        orders = [
            order
            for order in self.orders.values()
            if (order.buyer_id if role == "buying" else order.seller_id) == user_id
            and (status is None or order.status == status)
        ]
        orders.sort(key=lambda order: (order.updated_at, order.id), reverse=True)
        if before_updated_at is not None and before_id is not None:
            orders = [
                order
                for order in orders
                if (order.updated_at, order.id) < (before_updated_at, before_id)
            ]
        return [(order, None) for order in orders[:limit]]

    async def list_order_events(self, order_id):  # type: ignore[no-untyped-def]
        return [event for event in self.events if event.order_id == order_id]

    async def list_meeting_proposals(self, order_id):  # type: ignore[no-untyped-def]
        return [proposal for proposal in self.proposals.values() if proposal.order_id == order_id]

    async def list_reviews(self, order_id):  # type: ignore[no-untyped-def]
        return [
            review
            for review in getattr(self, "reviews", [])
            if review.order_id == order_id and review.is_visible
        ]

    async def get_review(self, order_id, reviewer_id):  # type: ignore[no-untyped-def]
        return next(
            (
                review
                for review in getattr(self, "reviews", [])
                if review.order_id == order_id and review.reviewer_id == reviewer_id
            ),
            None,
        )

    def add_review(self, review):  # type: ignore[no-untyped-def]
        if not hasattr(self, "reviews"):
            self.reviews: list[Review] = []
        self.reviews.append(review)

    async def refresh_review(self, review):  # type: ignore[no-untyped-def]
        now = datetime.now(UTC)
        review.created_at = now
        review.updated_at = now

    async def find_command(self, actor_id, client_action_id):  # type: ignore[no-untyped-def]
        return self.commands.get((actor_id, client_action_id))

    async def lock_command_key(self, actor_id, client_action_id):  # type: ignore[no-untyped-def]
        return None

    def add_event(  # type: ignore[no-untyped-def]
        self, *, order, actor_id, from_status, to_status, note, event_data=None
    ):
        order.updated_at = datetime.now(UTC)
        event = OrderEvent(
            id=uuid4(),
            order_id=order.id,
            actor_id=actor_id,
            from_status=from_status,
            to_status=to_status,
            note=note,
            event_data=event_data or {},
        )
        event.created_at = datetime.now(UTC)
        event.updated_at = event.created_at
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
async def test_create_order_retry_survives_reservation_and_new_key_is_rejected() -> None:
    repository = FakeOrderRepository()
    service = OrderService(repository)
    original = OrderCreate(
        product_id=repository.product_id,
        idempotency_key="create_retry_original",
    )
    created = await service.create(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        payload=original,
    )
    await service.accept(
        user_id=repository.seller_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=created.id,
        client_action_id="create_retry_accept",
    )

    repeated = await service.create(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        payload=original,
    )
    assert repeated.id == created.id

    repository.product.status = ProductStatus.ON_SALE
    with pytest.raises(AppError) as duplicate:
        await service.create(
            user_id=repository.buyer_id,
            campus_status=CampusVerificationStatus.VERIFIED,
            payload=OrderCreate(
                product_id=repository.product_id,
                idempotency_key="create_retry_new_key",
            ),
        )
    assert duplicate.value.code == "order_already_exists"


def test_meeting_location_is_trimmed_before_length_validation() -> None:
    with pytest.raises(ValueError):
        MeetingProposalCreate(
            client_action_id="blank_location_1",
            proposed_for=datetime.now(UTC) + timedelta(days=1),
            location_text="   ",
        )

    payload = MeetingProposalCreate(
        client_action_id="trim_location_1",
        proposed_for=datetime.now(UTC) + timedelta(days=1),
        location_text="  图书馆东门  ",
    )
    assert payload.location_text == "图书馆东门"


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


@pytest.mark.anyio
async def test_order_list_detail_and_bidirectional_reviews_respect_rules() -> None:
    repository = FakeOrderRepository()
    service = OrderService(repository)
    created = await service.create(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        payload=OrderCreate(product_id=repository.product_id, idempotency_key="review_create_1"),
    )
    await service.accept(
        user_id=repository.seller_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=created.id,
        client_action_id="review_accept_1",
    )
    await service.mark_delivered(
        user_id=repository.seller_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=created.id,
        client_action_id="review_deliver_1",
    )
    await service.complete(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=created.id,
        client_action_id="review_complete_1",
    )

    buying = await service.list_orders(
        user_id=repository.buyer_id,
        role="buying",
        status=OrderStatus.COMPLETED,
        cursor=None,
        limit=20,
    )
    assert len(buying.items) == 1
    assert buying.items[0].counterparty_name == "卖家"
    assert not hasattr(buying.items[0], "location_text")

    detail_before = await service.detail(user_id=repository.buyer_id, order_id=created.id)
    assert detail_before.can_review
    buyer_review = await service.create_review(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=created.id,
        payload=ReviewCreate(
            rating=5,
            tags=["item_as_described", "on_time"],
            content="商品与描述一致，面交顺利",
        ),
    )
    seller_review = await service.create_review(
        user_id=repository.seller_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        order_id=created.id,
        payload=ReviewCreate(rating=5, tags=["good_communication"]),
    )
    assert buyer_review.reviewee_id == repository.seller_id
    assert seller_review.reviewee_id == repository.buyer_id

    with pytest.raises(AppError) as duplicate:
        await service.create_review(
            user_id=repository.buyer_id,
            campus_status=CampusVerificationStatus.VERIFIED,
            order_id=created.id,
            payload=ReviewCreate(rating=4),
        )
    assert duplicate.value.code == "review_already_exists"
    detail_after = await service.detail(user_id=repository.buyer_id, order_id=created.id)
    assert not detail_after.can_review
    assert len(detail_after.reviews) == 2


@pytest.mark.anyio
async def test_order_list_uses_updated_at_for_stable_cursor_ordering() -> None:
    repository = FakeOrderRepository()
    service = OrderService(repository)
    created = await service.create(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        payload=OrderCreate(product_id=repository.product_id, idempotency_key="sorting_create_1"),
    )
    first = repository.orders[created.id]
    now = datetime.now(UTC)
    first.created_at = now - timedelta(days=2)
    first.updated_at = now
    second = Order(
        id=uuid4(),
        product_id=uuid4(),
        conversation_id=None,
        buyer_id=repository.buyer_id,
        seller_id=repository.seller_id,
        idempotency_key="sorting_create_2",
        amount=Decimal("20.00"),
        product_title_snapshot="较晚创建但较早更新的商品",
        campus_name_snapshot="东校区",
        buyer_display_name_snapshot="买家",
        seller_display_name_snapshot="卖家",
        payment_mode="offline",
        status=OrderStatus.PENDING_SELLER_CONFIRMATION,
        expires_at=now + timedelta(hours=12),
    )
    second.created_at = now - timedelta(days=1)
    second.updated_at = now - timedelta(hours=1)
    repository.orders[second.id] = second

    page_one = await service.list_orders(
        user_id=repository.buyer_id,
        role="buying",
        status=None,
        cursor=None,
        limit=1,
    )
    assert [item.id for item in page_one.items] == [first.id]
    assert page_one.items[0].updated_at == first.updated_at
    assert page_one.next_cursor is not None

    page_two = await service.list_orders(
        user_id=repository.buyer_id,
        role="buying",
        status=None,
        cursor=page_one.next_cursor,
        limit=1,
    )
    assert [item.id for item in page_two.items] == [second.id]


@pytest.mark.anyio
async def test_reviews_reject_unfinished_expired_and_invalid_tags() -> None:
    repository = FakeOrderRepository()
    service = OrderService(repository)
    created = await service.create(
        user_id=repository.buyer_id,
        campus_status=CampusVerificationStatus.VERIFIED,
        payload=OrderCreate(product_id=repository.product_id, idempotency_key="review_rules_1"),
    )
    with pytest.raises(AppError) as unfinished:
        await service.create_review(
            user_id=repository.buyer_id,
            campus_status=CampusVerificationStatus.VERIFIED,
            order_id=created.id,
            payload=ReviewCreate(rating=5),
        )
    assert unfinished.value.code == "order_not_reviewable"

    order = repository.orders[created.id]
    order.status = OrderStatus.COMPLETED
    order.completed_at = datetime.now(UTC) - timedelta(days=31)
    with pytest.raises(AppError) as expired:
        await service.create_review(
            user_id=repository.buyer_id,
            campus_status=CampusVerificationStatus.VERIFIED,
            order_id=created.id,
            payload=ReviewCreate(rating=5),
        )
    assert expired.value.code == "review_window_closed"

    order.completed_at = datetime.now(UTC)
    with pytest.raises(AppError) as invalid_tag:
        await service.create_review(
            user_id=repository.buyer_id,
            campus_status=CampusVerificationStatus.VERIFIED,
            order_id=created.id,
            payload=ReviewCreate(rating=5, tags=["private_location"]),
        )
    assert invalid_tag.value.code == "invalid_review_tag"
