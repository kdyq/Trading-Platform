import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.core.exceptions import AppError
from app.models.catalog import ProductStatus
from app.models.identity import CampusVerificationStatus
from app.models.trade import Order, OrderCommand, OrderStatus
from app.repositories.orders import OrderRepository
from app.schemas.orders import OrderCreate, OrderResponse


class OrderService:
    def __init__(self, repository: OrderRepository) -> None:
        self.repository = repository

    async def create(
        self,
        *,
        user_id: UUID,
        campus_status: CampusVerificationStatus,
        payload: OrderCreate,
    ) -> OrderResponse:
        self._require_verified(campus_status)
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
        existing = await self.repository.find_command(user_id, client_action_id)
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
