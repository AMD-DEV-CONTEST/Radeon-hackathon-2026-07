from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import AppServices, get_services
from app.schemas import ConversationDetail, ConversationSummary

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationSummary])
def list_conversations(services: AppServices = Depends(get_services)) -> list[ConversationSummary]:
    return [ConversationSummary(**row) for row in services.storage.list_conversations()]


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str, services: AppServices = Depends(get_services)) -> ConversationDetail:
    record = services.storage.get_conversation(conversation_id)
    if not record:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationDetail(**record)
