from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand
from agent_factory.sqlite_runtime import sqlite_lifecycle_available
from web_frontend.backend.runtime_bridge import RuntimeBridge


def create_runtime_router(runtime_bridge: RuntimeBridge, logger: logging.Logger) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health_check():
        sqlite_available = sqlite_lifecycle_available()
        runtime_active = runtime_bridge.active
        payload = {
            "status": "ok" if sqlite_available and runtime_active else "unavailable",
            "runtime_service_active": runtime_active,
            "sqlite_lifecycle_available": sqlite_available,
        }
        if payload["status"] != "ok":
            return JSONResponse(status_code=503, content=payload)
        return payload

    @router.get("/events")
    async def events_endpoint(request: Request):
        client_id = str(uuid.uuid4())[:8]
        last_event_id = str(request.headers.get("last-event-id") or "").strip() or None
        event_queue = runtime_bridge.subscribe(
            replay_history=last_event_id is not None,
            after_event_id=last_event_id,
        )
        logger.info("SSE client %s connected", client_id)

        async def event_stream():
            try:
                while not await request.is_disconnected():
                    try:
                        event = await asyncio.wait_for(event_queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    message = {"kind": "factory_frontend_event", "event": event}
                    data = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
                    event_id = str(event.get("event_id") or "")
                    yield f"id: {event_id}\nevent: factory_frontend_event\ndata: {data}\n\n"
            finally:
                runtime_bridge.unsubscribe(event_queue)
                logger.info("SSE client %s disconnected", client_id)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.post("/api/commands")
    async def command_endpoint(payload: dict[str, Any]):
        try:
            command = FactoryFrontendCommand.model_validate(payload.get("command", payload))
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        await runtime_bridge.send_frontend_command(command)
        logger.info("HTTP command sent: %s", command.type)
        return {"accepted": True, "command": command.model_dump(mode="json")}

    return router
