import base64
import binascii
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.core.exceptions import AppError
from app.models.catalog import ProductStatus
from app.models.identity import CampusVerificationStatus
from app.models.moderation import ModerationTargetType, Report, ReportEvent, ReportStatus
from app.models.trade import (
    CreditEventType,
    MeetingProposalStatus,
    Order,
    OrderCommand,
    OrderMeetingProposal,
    OrderStatus,
    Review,
)
from app.repositories.credit import SqlAlchemyCreditRepository
from app.repositories.orders import OrderRepository
from app.schemas.orders import (
    MeetingProposalCreate,
    MeetingProposalResponse,
    OrderCancel,
    OrderCreate,
    OrderDetailResponse,
    OrderDispute,
    OrderEventResponse,
    OrderListResponse,
    OrderResponse,
    OrderSummary,
    ReviewCreate,
    ReviewResponse,
)


class OrderService:
    REVIEW_TAGS = {
        "good_communication",
        "on_time",
        "item_as_described",
        "friendly",
        "smooth_transaction",
    }

    def __init__(
        self,
        repository: OrderRepository,
        credit_repository: SqlAlchemyCreditRepository | None = None,
    ) -> None:
        self.repository = repository
        self.credit_repository = credit_repository

    async def create(
        self,
        *,
        user_id: UUID,
        campus_status: CampusVerificationStatus,
        payload: OrderCreate,
    ) -> OrderResponse:
        self._require_verified(campus_status)
        existing = await self.repository.find_order_by_idempotency(user_id, payload.idempotency_key)
        if existing is not None:
            self._require_same_create(existing, payload)
            return self._response(existing)
        product = await self.repository.lock_product(payload.product_id)
        if product is None or product.status != ProductStatus.ON_SALE:
            raise AppError(
                status_code=409,
                code="product_not_available",
                message="商品当前不可发起订单",
            )
        if product.seller_id == user_id:
            raise AppError(
                status_code=409, code="cannot_buy_own_product", message="不能购买自己的商品"
            )
        campus_id = await self.repository.verified_campus_id(user_id)
        if campus_id is None or campus_id != product.campus_id:
            raise AppError(
                status_code=403,
                code="order_campus_mismatch",
                message="只能购买当前认证校区的商品",
            )
        buyer = await self.repository.get_user(user_id)
        seller = await self.repository.get_user(product.seller_id)
        campus_name = await self.repository.campus_name(product.campus_id)
        if buyer is None or seller is None or campus_name is None:
            raise AppError(
                status_code=404, code="order_party_not_found", message="订单参与方不存在"
            )
        if payload.conversation_id is not None:
            conversation = await self.repository.member_conversation(
                payload.conversation_id, user_id, product.id
            )
            if (
                conversation is None
                or conversation.buyer_id != user_id
                or conversation.seller_id != product.seller_id
            ):
                raise AppError(
                    status_code=404,
                    code="conversation_not_found",
                    message="关联会话不存在",
                )
        now = datetime.now(UTC)
        proposed = Order(
            id=uuid4(),
            product_id=product.id,
            conversation_id=payload.conversation_id,
            buyer_id=user_id,
            seller_id=product.seller_id,
            idempotency_key=payload.idempotency_key,
            amount=product.price,
            product_title_snapshot=product.title,
            campus_name_snapshot=campus_name,
            buyer_display_name_snapshot=buyer.display_name,
            seller_display_name_snapshot=seller.display_name,
            payment_mode="offline",
            status=OrderStatus.PENDING_SELLER_CONFIRMATION,
            expires_at=now + timedelta(hours=24),
        )
        order, created = await self.repository.create_order(proposed)
        if not created:
            if order.idempotency_key != payload.idempotency_key:
                raise AppError(
                    status_code=409,
                    code="order_already_exists",
                    message="你已对该商品发起未完成订单",
                )
            if order.product_id != product.id or order.conversation_id != payload.conversation_id:
                raise AppError(
                    status_code=409,
                    code="order_idempotency_conflict",
                    message="订单幂等键已用于其他请求",
                )
            return self._response(order)
        self.repository.add_event(
            order=order,
            actor_id=user_id,
            from_status=None,
            to_status=OrderStatus.PENDING_SELLER_CONFIRMATION,
            note="买家发起订单",
        )
        await self.repository.create_notification(
            recipient_id=order.seller_id,
            event_key=f"order.created:{order.id}",
            title="收到新的交易请求",
            summary="有买家发起了校内面交订单，请查看并确认。",
            order_id=order.id,
        )
        return self._response(order)

    async def accept(
        self,
        *,
        user_id: UUID,
        campus_status: CampusVerificationStatus,
        order_id: UUID,
        client_action_id: str,
    ) -> OrderResponse:
        self._require_verified(campus_status)
        snapshot = await self.repository.get_order(order_id)
        if snapshot is None or snapshot.seller_id != user_id:
            raise AppError(status_code=404, code="order_not_found", message="订单不存在")
        product = await self.repository.lock_product(snapshot.product_id)
        order = await self.repository.get_order(order_id, for_update=True)
        if order is None or order.seller_id != user_id:
            raise AppError(status_code=404, code="order_not_found", message="订单不存在")
        payload_hash = self._payload_hash("accept", {})
        existing = await self._find_command(user_id, client_action_id)
        if existing is not None:
            self._require_same_command(existing, order.id, "accept", payload_hash)
            return self._response(order)
        if order.status != OrderStatus.PENDING_SELLER_CONFIRMATION:
            raise AppError(status_code=409, code="invalid_order_state", message="当前订单不能接受")
        if order.expires_at is not None and order.expires_at <= datetime.now(UTC):
            raise AppError(status_code=409, code="order_expired", message="订单已超过确认期限")
        if product is None or product.status != ProductStatus.ON_SALE:
            raise AppError(status_code=409, code="product_not_available", message="商品已不可预留")
        now = datetime.now(UTC)
        previous = order.status
        order.status = OrderStatus.ACCEPTED
        order.expires_at = None
        product.status = ProductStatus.RESERVED
        product.reserved_at = now
        event = self.repository.add_event(
            order=order,
            actor_id=user_id,
            from_status=previous,
            to_status=OrderStatus.ACCEPTED,
            note="卖家接受订单并预留商品",
        )
        self.repository.add_command(
            order_id=order.id,
            actor_id=user_id,
            client_action_id=client_action_id,
            command="accept",
            payload_hash=payload_hash,
            event=event,
        )
        cancelled = await self.repository.cancel_other_pending(
            product_id=order.product_id,
            accepted_order_id=order.id,
            actor_id=user_id,
        )
        for cancelled_order_id, buyer_id in cancelled:
            await self.repository.create_notification(
                recipient_id=buyer_id,
                event_key=f"order.cancelled:{cancelled_order_id}",
                title="交易请求已结束",
                summary="商品已由其他订单预留，本次交易请求已自动取消。",
                order_id=cancelled_order_id,
            )
        await self.repository.create_notification(
            recipient_id=order.buyer_id,
            event_key=f"order.accepted:{order.id}",
            title="卖家已接受订单",
            summary="商品已为本订单预留，请协商校内面交安排。",
            order_id=order.id,
        )
        await self.repository.refresh_order(order)
        return self._response(order)

    async def propose_meeting(
        self,
        *,
        user_id: UUID,
        campus_status: CampusVerificationStatus,
        order_id: UUID,
        payload: MeetingProposalCreate,
    ) -> MeetingProposalResponse:
        self._require_verified(campus_status)
        order = await self.repository.get_order(order_id, for_update=True)
        self._require_participant(order, user_id)
        assert order is not None
        payload_hash = self._payload_hash(
            "propose_meeting",
            {
                "proposed_for": payload.proposed_for.isoformat(),
                "location_text": payload.location_text,
            },
        )
        existing = await self._find_command(user_id, payload.client_action_id)
        if existing is not None:
            self._require_same_command(existing, order.id, "propose_meeting", payload_hash)
            proposal = (
                await self.repository.get_meeting_proposal(existing.result_id)
                if existing.result_id is not None
                else None
            )
            if proposal is None:
                raise AppError(
                    status_code=409,
                    code="order_action_result_missing",
                    message="操作结果不存在",
                )
            return self._proposal_response(proposal)
        if order.status not in (OrderStatus.ACCEPTED, OrderStatus.SCHEDULED):
            raise AppError(
                status_code=409, code="invalid_order_state", message="当前订单不能协商面交"
            )
        now = datetime.now(UTC)
        proposed_for = payload.proposed_for
        if proposed_for.tzinfo is None or proposed_for.utcoffset() is None:
            raise AppError(
                status_code=422, code="meeting_timezone_required", message="面交时间必须包含时区"
            )
        proposed_for = proposed_for.astimezone(UTC)
        if proposed_for < now + timedelta(minutes=30) or proposed_for > now + timedelta(days=30):
            raise AppError(
                status_code=422,
                code="meeting_time_out_of_range",
                message="面交时间须在 30 分钟至 30 天内",
            )
        proposal = OrderMeetingProposal(
            id=uuid4(),
            order_id=order.id,
            proposer_id=user_id,
            proposed_for=proposed_for,
            location_text=payload.location_text.strip(),
            status=MeetingProposalStatus.PENDING,
            buyer_confirmed_at=now if user_id == order.buyer_id else None,
            seller_confirmed_at=now if user_id == order.seller_id else None,
        )
        self.repository.add_meeting_proposal(proposal)
        event = self.repository.add_event(
            order=order,
            actor_id=user_id,
            from_status=order.status,
            to_status=order.status,
            note="提交面交时间候选",
            event_data={"proposal_id": str(proposal.id), "proposed_for": proposed_for.isoformat()},
        )
        self.repository.add_command(
            order_id=order.id,
            actor_id=user_id,
            client_action_id=payload.client_action_id,
            command="propose_meeting",
            payload_hash=payload_hash,
            event=event,
            result_id=proposal.id,
        )
        await self.repository.create_notification(
            recipient_id=self._other_party(order, user_id),
            event_key=f"order.meeting_proposed:{proposal.id}",
            title="收到新的面交提议",
            summary="对方提出了新的校内面交时间和地点，请进入订单查看。",
            order_id=order.id,
        )
        await self.repository.refresh_meeting_proposal(proposal)
        return self._proposal_response(proposal)

    async def confirm_meeting(
        self,
        *,
        user_id: UUID,
        campus_status: CampusVerificationStatus,
        order_id: UUID,
        proposal_id: UUID,
        client_action_id: str,
    ) -> MeetingProposalResponse:
        self._require_verified(campus_status)
        order = await self.repository.get_order(order_id, for_update=True)
        self._require_participant(order, user_id)
        assert order is not None
        payload_hash = self._payload_hash("confirm_meeting", {"proposal_id": str(proposal_id)})
        existing = await self._find_command(user_id, client_action_id)
        if existing is not None:
            self._require_same_command(existing, order.id, "confirm_meeting", payload_hash)
            proposal = await self.repository.get_meeting_proposal(proposal_id)
            if proposal is None or proposal.order_id != order.id:
                raise AppError(
                    status_code=404,
                    code="meeting_proposal_not_found",
                    message="面交提议不存在",
                )
            return self._proposal_response(proposal)
        proposal = await self.repository.get_meeting_proposal(proposal_id, for_update=True)
        if proposal is None or proposal.order_id != order.id:
            raise AppError(
                status_code=404, code="meeting_proposal_not_found", message="面交提议不存在"
            )
        if order.status not in (OrderStatus.ACCEPTED, OrderStatus.SCHEDULED):
            raise AppError(
                status_code=409, code="invalid_order_state", message="当前订单不能确认面交"
            )
        if proposal.status != MeetingProposalStatus.PENDING:
            raise AppError(
                status_code=409, code="meeting_proposal_closed", message="面交提议已失效"
            )
        now = datetime.now(UTC)
        if user_id == order.buyer_id:
            if proposal.buyer_confirmed_at is not None:
                raise AppError(
                    status_code=409,
                    code="meeting_already_confirmed",
                    message="你已确认该面交提议",
                )
            proposal.buyer_confirmed_at = now
        else:
            if proposal.seller_confirmed_at is not None:
                raise AppError(
                    status_code=409,
                    code="meeting_already_confirmed",
                    message="你已确认该面交提议",
                )
            proposal.seller_confirmed_at = now
        previous = order.status
        both_confirmed = (
            proposal.buyer_confirmed_at is not None and proposal.seller_confirmed_at is not None
        )
        if both_confirmed:
            proposal.status = MeetingProposalStatus.ACCEPTED
            order.status = OrderStatus.SCHEDULED
            order.scheduled_for = proposal.proposed_for
            await self.repository.supersede_other_proposals(order.id, proposal.id)
        event = self.repository.add_event(
            order=order,
            actor_id=user_id,
            from_status=previous,
            to_status=order.status,
            note="双方确认面交安排" if both_confirmed else "一方确认面交提议",
            event_data={"proposal_id": str(proposal.id)},
        )
        self.repository.add_command(
            order_id=order.id,
            actor_id=user_id,
            client_action_id=client_action_id,
            command="confirm_meeting",
            payload_hash=payload_hash,
            event=event,
            result_id=proposal.id,
        )
        await self.repository.create_notification(
            recipient_id=self._other_party(order, user_id),
            event_key=f"order.meeting_confirmed:{proposal.id}:{user_id}",
            title="面交安排已确认" if both_confirmed else "对方已确认面交提议",
            summary=(
                "双方已确认校内面交安排，请按约定前往。"
                if both_confirmed
                else "请进入订单确认面交安排。"
            ),
            order_id=order.id,
        )
        await self.repository.refresh_meeting_proposal(proposal)
        return self._proposal_response(proposal)

    async def cancel(
        self,
        *,
        user_id: UUID,
        campus_status: CampusVerificationStatus,
        order_id: UUID,
        payload: OrderCancel,
    ) -> OrderResponse:
        self._require_verified(campus_status)
        snapshot = await self.repository.get_order(order_id)
        self._require_participant(snapshot, user_id)
        assert snapshot is not None
        product = await self.repository.lock_product(snapshot.product_id)
        order = await self.repository.get_order(order_id, for_update=True)
        self._require_participant(order, user_id)
        assert order is not None
        payload_hash = self._payload_hash(
            "cancel", {"reason_code": payload.reason_code, "note": payload.note}
        )
        existing = await self._find_command(user_id, payload.client_action_id)
        if existing is not None:
            self._require_same_command(existing, order.id, "cancel", payload_hash)
            return self._response(order)
        if order.status not in (
            OrderStatus.PENDING_SELLER_CONFIRMATION,
            OrderStatus.ACCEPTED,
            OrderStatus.SCHEDULED,
        ):
            raise AppError(status_code=409, code="invalid_order_state", message="当前订单不能取消")
        if product is None:
            raise AppError(status_code=409, code="product_not_available", message="关联商品不存在")
        previous = order.status
        order.status = OrderStatus.CANCELLED
        order.cancelled_at = datetime.now(UTC)
        order.cancellation_reason_code = payload.reason_code
        order.cancellation_note = payload.note
        order.expires_at = None
        if product.status == ProductStatus.RESERVED:
            product.status = ProductStatus.ON_SALE
            product.reserved_at = None
        await self.repository.withdraw_pending_proposals(order.id)
        event = self.repository.add_event(
            order=order,
            actor_id=user_id,
            from_status=previous,
            to_status=OrderStatus.CANCELLED,
            note="订单已取消",
            event_data={"reason_code": payload.reason_code},
        )
        self.repository.add_command(
            order_id=order.id,
            actor_id=user_id,
            client_action_id=payload.client_action_id,
            command="cancel",
            payload_hash=payload_hash,
            event=event,
        )
        await self.repository.create_notification(
            recipient_id=self._other_party(order, user_id),
            event_key=f"order.cancelled:{order.id}",
            title="订单已取消",
            summary="对方已取消本次校内面交订单，商品已按规则恢复在售。",
            order_id=order.id,
        )
        await self.repository.refresh_order(order)
        return self._response(order)

    async def expire_pending(self, *, limit: int = 50) -> int:
        orders = await self.repository.claim_expired_pending(limit)
        for order in orders:
            previous = order.status
            order.status = OrderStatus.EXPIRED
            self.repository.add_event(
                order=order,
                actor_id=None,
                from_status=previous,
                to_status=OrderStatus.EXPIRED,
                note="卖家未在确认期限内响应，订单自动过期",
            )
            await self.repository.create_notification(
                recipient_id=order.buyer_id,
                event_key=f"order.expired:{order.id}",
                title="交易请求已过期",
                summary="卖家未在确认期限内响应，商品保持在售。",
                order_id=order.id,
            )
        return len(orders)

    async def mark_delivered(
        self,
        *,
        user_id: UUID,
        campus_status: CampusVerificationStatus,
        order_id: UUID,
        client_action_id: str,
    ) -> OrderResponse:
        self._require_verified(campus_status)
        order = await self.repository.get_order(order_id, for_update=True)
        if order is None or order.seller_id != user_id:
            raise AppError(status_code=404, code="order_not_found", message="订单不存在")
        payload_hash = self._payload_hash("mark_delivered", {})
        existing = await self._find_command(user_id, client_action_id)
        if existing is not None:
            self._require_same_command(existing, order.id, "mark_delivered", payload_hash)
            return self._response(order)
        if order.status not in (OrderStatus.ACCEPTED, OrderStatus.SCHEDULED):
            raise AppError(
                status_code=409, code="invalid_order_state", message="当前订单不能确认交付"
            )
        previous = order.status
        order.status = OrderStatus.SELLER_DELIVERED
        order.seller_delivered_at = datetime.now(UTC)
        event = self.repository.add_event(
            order=order,
            actor_id=user_id,
            from_status=previous,
            to_status=OrderStatus.SELLER_DELIVERED,
            note="卖家确认已当面交付商品",
        )
        self.repository.add_command(
            order_id=order.id,
            actor_id=user_id,
            client_action_id=client_action_id,
            command="mark_delivered",
            payload_hash=payload_hash,
            event=event,
        )
        await self.repository.create_notification(
            recipient_id=order.buyer_id,
            event_key=f"order.delivered:{order.id}",
            title="卖家已确认交付",
            summary="请在核对商品后确认完成；如有异常可从订单发起争议。",
            order_id=order.id,
        )
        await self.repository.refresh_order(order)
        return self._response(order)

    async def complete(
        self,
        *,
        user_id: UUID,
        campus_status: CampusVerificationStatus,
        order_id: UUID,
        client_action_id: str,
    ) -> OrderResponse:
        self._require_verified(campus_status)
        snapshot = await self.repository.get_order(order_id)
        if snapshot is None or snapshot.buyer_id != user_id:
            raise AppError(status_code=404, code="order_not_found", message="订单不存在")
        product = await self.repository.lock_product(snapshot.product_id)
        order = await self.repository.get_order(order_id, for_update=True)
        if order is None or order.buyer_id != user_id:
            raise AppError(status_code=404, code="order_not_found", message="订单不存在")
        payload_hash = self._payload_hash("complete", {})
        existing = await self._find_command(user_id, client_action_id)
        if existing is not None:
            self._require_same_command(existing, order.id, "complete", payload_hash)
            return self._response(order)
        if order.status != OrderStatus.SELLER_DELIVERED:
            raise AppError(
                status_code=409, code="invalid_order_state", message="卖家确认交付后才能完成"
            )
        if product is None or product.status != ProductStatus.RESERVED:
            raise AppError(status_code=409, code="product_not_reserved", message="商品预留状态异常")
        now = datetime.now(UTC)
        previous = order.status
        order.status = OrderStatus.COMPLETED
        order.completed_at = now
        product.status = ProductStatus.SOLD
        product.sold_at = now
        product.reserved_at = None
        event = self.repository.add_event(
            order=order,
            actor_id=user_id,
            from_status=previous,
            to_status=OrderStatus.COMPLETED,
            note="买家确认收货，订单完成",
        )
        self.repository.add_command(
            order_id=order.id,
            actor_id=user_id,
            client_action_id=client_action_id,
            command="complete",
            payload_hash=payload_hash,
            event=event,
        )
        await self.repository.create_notification(
            recipient_id=order.seller_id,
            event_key=f"order.completed:{order.id}",
            title="订单已完成",
            summary="买家已确认收货，本次校内面交已完成。",
            order_id=order.id,
        )
        if self.credit_repository is not None:
            for participant_id in (order.buyer_id, order.seller_id):
                await self.credit_repository.append(
                    user_id=participant_id,
                    event_type=CreditEventType.ORDER_COMPLETED,
                    source_type="order",
                    reference_id=order.id,
                    delta=2,
                    reason="完成校内交易",
                )
        await self.repository.refresh_order(order)
        return self._response(order)

    async def dispute(
        self,
        *,
        user_id: UUID,
        campus_status: CampusVerificationStatus,
        order_id: UUID,
        payload: OrderDispute,
    ) -> OrderResponse:
        self._require_verified(campus_status)
        order = await self.repository.get_order(order_id, for_update=True)
        self._require_participant(order, user_id)
        assert order is not None
        payload_hash = self._payload_hash(
            "dispute", {"reason_code": payload.reason_code, "details": payload.details}
        )
        existing = await self._find_command(user_id, payload.client_action_id)
        if existing is not None:
            self._require_same_command(existing, order.id, "dispute", payload_hash)
            return self._response(order)
        if order.status not in (
            OrderStatus.ACCEPTED,
            OrderStatus.SCHEDULED,
            OrderStatus.SELLER_DELIVERED,
        ):
            raise AppError(
                status_code=409, code="invalid_order_state", message="当前订单不能发起争议"
            )
        now = datetime.now(UTC)
        previous = order.status
        order.status = OrderStatus.DISPUTED
        order.disputed_at = now
        order.dispute_reason_code = payload.reason_code
        order.dispute_details = payload.details
        report = Report(
            id=uuid4(),
            reporter_id=user_id,
            target_type=ModerationTargetType.ORDER,
            target_id=order.id,
            reason_code=payload.reason_code,
            details=payload.details,
            subject_user_id=self._other_party(order, user_id),
            status=ReportStatus.OPEN,
        )
        self.repository.add_dispute_report(report)
        self.repository.add_dispute_report_event(
            ReportEvent(
                id=uuid4(),
                report_id=report.id,
                actor_id=user_id,
                from_status=None,
                to_status=ReportStatus.OPEN,
                public_note="订单争议举报已提交",
                event_data={"order_id": str(order.id)},
            )
        )
        event = self.repository.add_event(
            order=order,
            actor_id=user_id,
            from_status=previous,
            to_status=OrderStatus.DISPUTED,
            note="订单已进入争议处理",
            event_data={"report_id": str(report.id), "reason_code": payload.reason_code},
        )
        self.repository.add_command(
            order_id=order.id,
            actor_id=user_id,
            client_action_id=payload.client_action_id,
            command="dispute",
            payload_hash=payload_hash,
            event=event,
            result_id=report.id,
        )
        await self.repository.create_notification(
            recipient_id=self._other_party(order, user_id),
            event_key=f"order.disputed:{order.id}",
            title="订单已进入争议处理",
            summary="对方已提交订单争议，订单状态已冻结，等待授权人员处理。",
            order_id=order.id,
        )
        await self.repository.refresh_order(order)
        return self._response(order)

    async def list_orders(
        self,
        *,
        user_id: UUID,
        role: str,
        status: OrderStatus | None,
        cursor: str | None,
        limit: int,
    ) -> OrderListResponse:
        before_updated_at, before_id = self._decode_cursor(cursor) if cursor else (None, None)
        records = list(
            await self.repository.list_orders(
                user_id=user_id,
                role=role,
                status=status,
                before_updated_at=before_updated_at,
                before_id=before_id,
                limit=limit + 1,
            )
        )
        has_more = len(records) > limit
        page = records[:limit]
        items = [
            OrderSummary(
                id=order.id,
                product_id=order.product_id,
                amount=order.amount,
                status=order.status.value,
                role=role,
                product_title=order.product_title_snapshot,
                campus_name=order.campus_name_snapshot,
                counterparty_name=(
                    order.seller_display_name_snapshot
                    if role == "buying"
                    else order.buyer_display_name_snapshot
                ),
                payment_mode=order.payment_mode,
                image_url=(
                    f"/api/v1/market/product-image-thumbnails/{image_id}"
                    if image_id is not None
                    else None
                ),
                scheduled_for=order.scheduled_for,
                created_at=order.created_at,
                updated_at=order.updated_at,
            )
            for order, image_id in page
        ]
        return OrderListResponse(
            items=items,
            next_cursor=self._encode_cursor(page[-1][0]) if has_more and page else None,
        )

    async def detail(self, *, user_id: UUID, order_id: UUID) -> OrderDetailResponse:
        order = await self.repository.get_order(order_id)
        self._require_participant(order, user_id)
        assert order is not None
        events = await self.repository.list_order_events(order.id)
        proposals = await self.repository.list_meeting_proposals(order.id)
        reviews = await self.repository.list_reviews(order.id)
        own_review = await self.repository.get_review(order.id, user_id)
        deadline = (
            order.completed_at + timedelta(days=30) if order.completed_at is not None else None
        )
        base = self._response(order)
        return OrderDetailResponse(
            **base.model_dump(),
            cancellation_reason_code=order.cancellation_reason_code,
            cancellation_note=order.cancellation_note,
            dispute_reason_code=order.dispute_reason_code,
            dispute_details=order.dispute_details,
            seller_delivered_at=order.seller_delivered_at,
            events=[
                OrderEventResponse(
                    id=event.id,
                    actor_id=event.actor_id,
                    from_status=event.from_status.value if event.from_status else None,
                    to_status=event.to_status.value,
                    note=event.note,
                    created_at=event.created_at,
                )
                for event in events
            ],
            meeting_proposals=[self._proposal_response(proposal) for proposal in proposals],
            reviews=[self._review_response(order, review) for review in reviews],
            can_review=(
                order.status == OrderStatus.COMPLETED
                and deadline is not None
                and datetime.now(UTC) <= deadline
                and own_review is None
            ),
            review_deadline=deadline,
        )

    async def create_review(
        self,
        *,
        user_id: UUID,
        campus_status: CampusVerificationStatus,
        order_id: UUID,
        payload: ReviewCreate,
    ) -> ReviewResponse:
        self._require_verified(campus_status)
        order = await self.repository.get_order(order_id, for_update=True)
        self._require_participant(order, user_id)
        assert order is not None
        if order.status != OrderStatus.COMPLETED or order.completed_at is None:
            raise AppError(
                status_code=409, code="order_not_reviewable", message="订单完成后才能评价"
            )
        if datetime.now(UTC) > order.completed_at + timedelta(days=30):
            raise AppError(status_code=409, code="review_window_closed", message="评价期限已结束")
        if await self.repository.get_review(order.id, user_id) is not None:
            raise AppError(status_code=409, code="review_already_exists", message="你已评价该订单")
        tags = list(dict.fromkeys(payload.tags))
        if any(tag not in self.REVIEW_TAGS for tag in tags):
            raise AppError(status_code=422, code="invalid_review_tag", message="评价标签无效")
        content = payload.content.strip() if payload.content else None
        review = Review(
            id=uuid4(),
            order_id=order.id,
            reviewer_id=user_id,
            reviewee_id=self._other_party(order, user_id),
            rating=payload.rating,
            tags=tags,
            content=content or None,
            is_visible=True,
        )
        self.repository.add_review(review)
        review_delta = 1 if payload.rating >= 4 else (-1 if payload.rating <= 2 else 0)
        if self.credit_repository is not None and review_delta:
            await self.credit_repository.append(
                user_id=review.reviewee_id,
                event_type=CreditEventType.REVIEW_RECEIVED,
                source_type="review",
                reference_id=review.id,
                delta=review_delta,
                reason="收到有效交易评价",
            )
        await self.repository.create_notification(
            recipient_id=review.reviewee_id,
            event_key=f"order.reviewed:{order.id}:{user_id}",
            title="收到新的交易评价",
            summary="对方已对本次完成的校内交易作出评价。",
            order_id=order.id,
        )
        await self.repository.refresh_review(review)
        return self._review_response(order, review)

    @staticmethod
    def _review_response(order: Order, review: Review) -> ReviewResponse:
        reviewer_name = (
            order.buyer_display_name_snapshot
            if review.reviewer_id == order.buyer_id
            else order.seller_display_name_snapshot
        )
        return ReviewResponse(
            id=review.id,
            reviewer_id=review.reviewer_id,
            reviewer_name=reviewer_name,
            reviewee_id=review.reviewee_id,
            rating=review.rating,
            tags=review.tags,
            content=review.content,
            created_at=review.created_at,
        )

    @staticmethod
    def _encode_cursor(order: Order) -> str:
        value = json.dumps({"updated_at": order.updated_at.isoformat(), "id": str(order.id)})
        return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(value: str) -> tuple[datetime, UUID]:
        try:
            padded = value + "=" * (-len(value) % 4)
            data = json.loads(base64.urlsafe_b64decode(padded).decode())
            if not isinstance(data, dict):
                raise ValueError
            return datetime.fromisoformat(data["updated_at"]), UUID(data["id"])
        except (binascii.Error, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AppError(status_code=422, code="invalid_cursor", message="分页游标无效") from exc

    @staticmethod
    def _proposal_response(proposal: OrderMeetingProposal) -> MeetingProposalResponse:
        return MeetingProposalResponse(
            id=proposal.id,
            order_id=proposal.order_id,
            proposer_id=proposal.proposer_id,
            proposed_for=proposal.proposed_for,
            location_text=proposal.location_text,
            status=proposal.status.value,
            buyer_confirmed_at=proposal.buyer_confirmed_at,
            seller_confirmed_at=proposal.seller_confirmed_at,
            created_at=proposal.created_at,
        )

    @staticmethod
    def _require_participant(order: Order | None, user_id: UUID) -> None:
        if order is None or user_id not in (order.buyer_id, order.seller_id):
            raise AppError(status_code=404, code="order_not_found", message="订单不存在")

    async def _find_command(self, actor_id: UUID, client_action_id: str) -> OrderCommand | None:
        await self.repository.lock_command_key(actor_id, client_action_id)
        return await self.repository.find_command(actor_id, client_action_id)

    @staticmethod
    def _require_same_create(order: Order, payload: OrderCreate) -> None:
        if (
            order.product_id != payload.product_id
            or order.conversation_id != payload.conversation_id
        ):
            raise AppError(
                status_code=409,
                code="order_idempotency_conflict",
                message="订单幂等键已用于其他请求",
            )

    @staticmethod
    def _other_party(order: Order, user_id: UUID) -> UUID:
        return order.seller_id if user_id == order.buyer_id else order.buyer_id

    @staticmethod
    def _response(order: Order) -> OrderResponse:
        return OrderResponse(
            id=order.id,
            product_id=order.product_id,
            conversation_id=order.conversation_id,
            buyer_id=order.buyer_id,
            seller_id=order.seller_id,
            amount=order.amount,
            status=order.status.value,
            product_title=order.product_title_snapshot,
            campus_name=order.campus_name_snapshot,
            buyer_display_name=order.buyer_display_name_snapshot,
            seller_display_name=order.seller_display_name_snapshot,
            payment_mode=order.payment_mode,
            expires_at=order.expires_at,
            scheduled_for=order.scheduled_for,
            completed_at=order.completed_at,
            created_at=order.created_at,
            updated_at=order.updated_at,
        )

    @staticmethod
    def _require_verified(status: CampusVerificationStatus) -> None:
        if status != CampusVerificationStatus.VERIFIED:
            raise AppError(
                status_code=403,
                code="campus_verification_required",
                message="请先完成校园认证",
            )

    @staticmethod
    def _payload_hash(command: str, payload: dict[str, object]) -> str:
        encoded = json.dumps(
            {"command": command, "payload": payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _require_same_command(
        existing: OrderCommand,
        order_id: UUID,
        command: str,
        payload_hash: str,
    ) -> None:
        if not all(
            (
                existing.order_id == order_id,
                existing.command == command,
                existing.payload_hash == payload_hash,
            )
        ):
            raise AppError(
                status_code=409,
                code="order_action_idempotency_conflict",
                message="操作幂等键已用于其他请求",
            )
