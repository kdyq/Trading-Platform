from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_chat_service
from app.api.v1.routes.auth import get_auth_context
from app.models.identity import CampusVerificationStatus
from app.schemas.chat import (
    ChatMessageResponse,
    ConversationCreate,
    ConversationListResponse,
    ConversationSummary,
    MessagePageResponse,
    MessageSend,
    ReadPositionResponse,
    ReadPositionUpdate,
)
from app.services.auth import AuthContext
from app.services.chat import ChatService

router = APIRouter()


def verified(context: AuthContext) -> bool:
    return context.campus_verification_status == CampusVerificationStatus.VERIFIED


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
