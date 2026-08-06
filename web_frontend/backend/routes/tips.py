from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

from agent_factory.tip_system import TipCreateRequest, TipFollowUpRequest, TipService


def create_tip_router(service: TipService | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/tips")
    tip_service = service or TipService()

    @router.get("")
    async def list_tips(
        scope_type: str = Query(min_length=1),
        scope_id: str = Query(min_length=1),
    ):
        tips = await asyncio.to_thread(tip_service.list_scope, scope_type, scope_id)
        return {"tips": [tip.model_dump(mode="json") for tip in tips]}

    @router.post("")
    async def create_tip(payload: TipCreateRequest):
        try:
            tip = await asyncio.to_thread(tip_service.create_and_answer, payload)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc
        return {"tip": tip.model_dump(mode="json")}

    @router.post("/{tip_id}/messages")
    async def follow_up_tip(tip_id: str, payload: TipFollowUpRequest):
        try:
            tip = await asyncio.to_thread(tip_service.follow_up, tip_id, payload.question)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc
        return {"tip": tip.model_dump(mode="json")}

    @router.delete("/{tip_id}")
    async def delete_tip(tip_id: str):
        return {"deleted": await asyncio.to_thread(tip_service.delete, tip_id)}

    return router
