from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from web_frontend.backend.conversation_storage import ConversationStorageService
from web_frontend.backend.runtime_bridge import RuntimeBridge


class ConversationClearRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: bool


def create_storage_router(runtime_bridge: RuntimeBridge) -> APIRouter:
    router = APIRouter(prefix="/api/storage")
    service = ConversationStorageService(runtime_bridge)

    @router.get("/conversations")
    def conversation_usage():
        try:
            return service.usage()
        except Exception as exc:
            raise HTTPException(status_code=500, detail="读取聊天记录占用失败。") from exc

    @router.post("/conversations/clear")
    async def clear_conversations(payload: ConversationClearRequest):
        if not payload.confirmed:
            raise HTTPException(status_code=422, detail="清理聊天记录需要明确确认。")
        try:
            return await service.clear()
        except TimeoutError as exc:
            raise HTTPException(status_code=409, detail="仍有会话正在停止，请稍后重试。") from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="清理聊天记录失败。") from exc

    return router
