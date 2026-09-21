import asyncio
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, WebSocket, WebSocketDisconnect

from app.api.dependencies import get_chat_service, get_websocket_ticket_store
from app.api.v1.routes.auth import get_auth_context
from app.models.identity import CampusVerificationStatus
from app.schemas.chat import (
    BlockedUsersResponse,
    ChatMessageResponse,
    ChatReportCreate,
    ChatReportResponse,
    ConversationCreate,
    ConversationListResponse,
    ConversationSummary,
    MessagePageResponse,
    MessageSend,
    NotificationListResponse,
    NotificationPreferencesResponse,
    NotificationPreferenceUpdate,
    NotificationReadAllResponse,
    NotificationResponse,
    ReadPositionResponse,
    ReadPositionUpdate,
    WebSocketTicketResponse,
)
from app.services.auth import AuthContext
from app.services.chat import ChatService
from app.services.realtime import (
    RealtimeHub,
    RedisWebSocketTicketStore,
    WebSocketTicketStore,
)

router = APIRouter()


def verified(context: AuthContext) -> bool:
    return context.campus_verification_status == CampusVerificationStatus.VERIFIED


@router.post("/ws-tickets", response_model=WebSocketTicketResponse, status_code=201)
async def websocket_ticket(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    store: Annotated[WebSocketTicketStore, Depends(get_websocket_ticket_store)],
) -> WebSocketTicketResponse:
    ticket, expires_in = await store.issue(context.user.id)
    return WebSocketTicketResponse(ticket=ticket, expires_in=expires_in)


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket, ticket: str = Query(min_length=16, max_length=128)
) -> None:
    redis = websocket.app.state.redis
    if redis is None:
        await websocket.accept()
        await websocket.close(code=1013, reason="realtime unavailable")
        return
    try:
        user_id = await RedisWebSocketTicketStore(redis).consume(ticket)
    except Exception:
        await websocket.accept()
        await websocket.close(code=1013, reason="realtime unavailable")
        return
    if user_id is None:
        await websocket.accept()
        await websocket.close(code=4401, reason="invalid ticket")
        return
    hub = cast(RealtimeHub, websocket.app.state.realtime_hub)
    await hub.connect(user_id, websocket)
    await websocket.send_json({"type": "chat.ready", "data": {"user_id": str(user_id)}})
    try:
        while True:
            message = await asyncio.wait_for(websocket.receive_json(), timeout=45)
            if isinstance(message, dict) and message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json({"type": "error", "data": {"code": "unsupported_event"}})
    except TimeoutError:
        await websocket.close(code=4408, reason="heartbeat timeout")
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(user_id, websocket)


@router.get("/notifications", response_model=NotificationListResponse)
async def notifications(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> NotificationListResponse:
    return await service.notifications(context.user.id)


@router.put("/notifications/read-all", response_model=NotificationReadAllResponse)
async def read_all_notifications(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> NotificationReadAllResponse:
    return NotificationReadAllResponse(
        updated_count=await service.mark_all_notifications_read(context.user.id)
    )


@router.put("/notifications/{notification_id}/read", response_model=NotificationResponse)
async def read_notification(
    notification_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> NotificationResponse:
    return await service.mark_notification_read(context.user.id, notification_id)


@router.get("/notification-preferences", response_model=NotificationPreferencesResponse)
async def notification_preferences(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> NotificationPreferencesResponse:
    return await service.preferences(context.user.id)


@router.put("/notification-preferences", response_model=NotificationPreferencesResponse)
async def update_notification_preference(
    payload: NotificationPreferenceUpdate,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> NotificationPreferencesResponse:
    return await service.set_preference(context.user.id, payload.category, payload.enabled)


@router.get("/blocks", response_model=BlockedUsersResponse)
async def blocked_users(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> BlockedUsersResponse:
    return await service.blocked_users(context.user.id)


@router.put("/blocks/{blocked_id}", status_code=204)
async def block_user(
    blocked_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> Response:
    await service.block_user(user_id=context.user.id, blocked_id=blocked_id)
    return Response(status_code=204)


@router.delete("/blocks/{blocked_id}", status_code=204)
async def unblock_user(
    blocked_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> Response:
    await service.unblock_user(user_id=context.user.id, blocked_id=blocked_id)
    return Response(status_code=204)


@router.post(
    "/conversations/{conversation_id}/reports",
    response_model=ChatReportResponse,
    status_code=201,
)
async def report_message(
    conversation_id: UUID,
    payload: ChatReportCreate,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatReportResponse:
    return await service.report_message(
        user_id=context.user.id,
        conversation_id=conversation_id,
        message_id=payload.message_id,
        reason_code=payload.reason_code,
        details=payload.details,
    )


@router.post("/conversations", response_model=ConversationSummary, status_code=201)
async def create_conversation(
    payload: ConversationCreate,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ConversationSummary:
    return await service.create_conversation(
        user_id=context.user.id,
        campus_verified=verified(context),
        product_id=payload.product_id,
    )


@router.get("/conversations", response_model=ConversationListResponse)
async def conversations(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ConversationListResponse:
    return await service.list_conversations(context.user.id)


@router.get("/conversations/{conversation_id}/messages", response_model=MessagePageResponse)
async def messages(
    conversation_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ChatService, Depends(get_chat_service)],
    cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> MessagePageResponse:
    return await service.list_messages(
        user_id=context.user.id,
        conversation_id=conversation_id,
        cursor=cursor,
        page_size=page_size,
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=ChatMessageResponse,
    status_code=201,
)
async def send_message(
    conversation_id: UUID,
    payload: MessageSend,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatMessageResponse:
    return await service.send_message(
        user_id=context.user.id,
        campus_verified=verified(context),
        conversation_id=conversation_id,
        client_message_id=payload.client_message_id,
        body=payload.body,
    )


@router.put("/conversations/{conversation_id}/read-position", response_model=ReadPositionResponse)
async def mark_read(
    conversation_id: UUID,
    payload: ReadPositionUpdate,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ReadPositionResponse:
    return await service.mark_read(
        user_id=context.user.id,
        conversation_id=conversation_id,
        message_id=payload.message_id,
    )
