from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import AppServices, get_services
from app.schemas import AgentResponse, ChatRequest

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=AgentResponse)
def run_agentflow(payload: ChatRequest, services: AppServices = Depends(get_services)) -> AgentResponse:
    return services.orchestrator.run(
        conversation_id=payload.conversation_id,
        user_message=payload.message,
        document_ids=payload.document_ids,
        requested_model=payload.model,
    )
