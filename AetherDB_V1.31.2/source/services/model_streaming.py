"""Server-owned stream events and duplicate-safe accumulation."""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from services.model_reliability import (
    FallbackRequired,
    ModelErrorCode,
    ModelExecutionError,
    normalize_model_error,
)
from services.model_recovery import create_recovery_ticket, safe_model_candidates
from services.model_routing import ModelRouteError, RouteStatus


StreamEventName = Literal[
    "task_started",
    "routing_resolved",
    "context_request",
    "context_candidates_ready",
    "context_approved",
    "thinking_start",
    "thinking_delta",
    "thinking_end",
    "final_start",
    "final_delta",
    "final_end",
    "usage_update",
    "retry_start",
    "fallback_required",
    "stream_error",
    "task_done",
    "task_cancelled",
]

TERMINAL_EVENTS = {"stream_error", "task_done", "task_cancelled"}


class StreamEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal["1.0"] = "1.0"
    task_id: str
    sequence: int = Field(ge=0)
    event: StreamEventName
    timestamp: str
    payload: dict[str, Any] = Field(default_factory=dict)


class StreamSession:
    def __init__(self, task_id: str, max_output_chars: int = 1_000_000, max_event_bytes: int = 64_000):
        self.task_id = task_id
        self.max_output_chars = max_output_chars
        self.max_event_bytes = max_event_bytes
        self.sequence = 0
        self.thinking_content = ""
        self.final_content = ""
        self.thinking_started = False
        self.final_started = False
        self.terminal = False

    def emit(self, event: StreamEventName, payload: dict[str, Any] | None = None) -> StreamEvent:
        if self.terminal:
            raise RuntimeError("Stream session is already terminal")
        payload = payload or {}
        if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > self.max_event_bytes:
            raise ModelExecutionError(ModelErrorCode.STREAM_INTERRUPTED, "Stream event exceeds limit")
        item = StreamEvent(
            task_id=self.task_id,
            sequence=self.sequence,
            event=event,
            timestamp=datetime.now(timezone.utc).isoformat(),
            payload=payload,
        )
        self.sequence += 1
        if event in TERMINAL_EVENTS:
            self.terminal = True
        return item

    def append_delta(self, phase: Literal["thinking", "final"], delta: str) -> list[StreamEvent]:
        if not isinstance(delta, str):
            raise ModelExecutionError(ModelErrorCode.INVALID_INPUT_FORMAT)
        events = []
        if phase == "thinking":
            if self.final_started:
                raise ModelExecutionError(
                    ModelErrorCode.STREAM_INTERRUPTED,
                    "Thinking content cannot follow final content",
                )
            if not self.thinking_started:
                self.thinking_started = True
                events.append(self.emit("thinking_start"))
            if len(self.thinking_content) + len(delta) > self.max_output_chars:
                raise ModelExecutionError(ModelErrorCode.STREAM_INTERRUPTED, "Output limit exceeded")
            self.thinking_content += delta
            events.append(self.emit("thinking_delta", {"delta": delta}))
            return events

        if not self.final_started:
            if self.thinking_started:
                events.append(self.emit("thinking_end"))
            self.final_started = True
            events.append(self.emit("final_start"))
        if len(self.final_content) + len(delta) > self.max_output_chars:
            raise ModelExecutionError(ModelErrorCode.STREAM_INTERRUPTED, "Output limit exceeded")
        self.final_content += delta
        events.append(self.emit("final_delta", {"delta": delta}))
        return events

    def partial_final(self, keep: bool = True) -> str:
        content = self.final_content
        if not keep:
            self.final_content = ""
        return content if keep else ""


class StreamAccumulator:
    """Duplicate-safe state reducer reusable by later UI clients."""

    def __init__(self):
        self.last_sequence = -1
        self.thinking_content = ""
        self.final_content = ""
        self.terminal = False

    def apply(self, event: StreamEvent) -> bool:
        if event.sequence <= self.last_sequence or self.terminal:
            return False
        self.last_sequence = event.sequence
        if event.event == "thinking_delta":
            self.thinking_content += str(event.payload.get("delta", ""))
        elif event.event == "final_delta":
            self.final_content += str(event.payload.get("delta", ""))
        if event.event in TERMINAL_EVENTS:
            self.terminal = True
        return True

    def resolve_partial_final(self, keep: bool) -> str:
        if keep:
            return self.final_content
        self.final_content = ""
        return ""


def _route_error_code(error: ModelRouteError) -> ModelErrorCode:
    if error.result.status is RouteStatus.BLOCKED:
        return ModelErrorCode.PRIVACY_BLOCKED
    if error.result.status is RouteStatus.UNAVAILABLE:
        return ModelErrorCode.MODEL_DISABLED
    return ModelErrorCode.MODEL_UNSUPPORTED_TASK


async def stream_model_task(
    gateway,
    request,
    *,
    recovery_owner: str | None = None,
    recovery_kind: str | None = None,
):
    session = StreamSession(request.task_id)
    yield session.emit(
        "task_started",
        {
            "task_type": request.canonical_task_type,
            "legacy_task_type": request.legacy_task_type,
        },
    )
    try:
        if hasattr(gateway, "resolve") and hasattr(gateway, "execute_resolved"):
            route = gateway.resolve(request)
            route_payload = {
                "status": route.status.value,
                "model_profile_id": route.selected_model_profile_id,
                "reason": route.reason,
                "requires_user_confirmation": route.requires_user_confirmation,
            }
            if route.status is RouteStatus.AMBIGUOUS:
                candidate_ids = [item.model_profile_id for item in route.candidates]
                route_payload["candidates"] = safe_model_candidates(candidate_ids)
                if recovery_owner:
                    ticket = create_recovery_ticket(
                        "ambiguous_selection",
                        request,
                        candidate_ids,
                        recovery_owner,
                    )
                    route_payload["recovery_ticket"] = ticket["id"]
                    route_payload["recovery_expires_at"] = ticket["expires_at"]
            if recovery_kind:
                route_payload["recovery_kind"] = recovery_kind
            yield session.emit(
                "routing_resolved",
                route_payload,
            )
            if route.status is not RouteStatus.RESOLVED:
                raise ModelRouteError(route)
            if recovery_kind == "fallback_confirmation":
                result = await gateway.execute_fallback(
                    request,
                    route.selected_model_profile_id,
                    confirmed=True,
                )
            else:
                result = await gateway.execute_resolved(request, route)
        else:
            result = await gateway.execute(request)
            yield session.emit(
                "routing_resolved",
                {
                    "status": "resolved",
                    "model_profile_id": result.model_profile_id,
                    "reason": "legacy_compatibility",
                },
            )

        if result.thinking_content:
            for event in session.append_delta("thinking", result.thinking_content):
                yield event
        for event in session.append_delta("final", result.content):
            yield event
        yield session.emit("final_end", {
            "provider_id": result.provider_id,
            "model_profile_id": result.model_profile_id,
            "provider_model_name": result.provider_model_name,
            "finish_reason": result.finish_reason,
            "warnings": list(result.warnings),
            "truncated": "OUTPUT_TRUNCATED" in result.warnings,
            "task_type": request.canonical_task_type,
            "legacy_task_type": request.legacy_task_type,
        })
        yield session.emit("usage_update", {"usage": dict(result.usage)})
        yield session.emit("task_done", {"result": result.to_read_model(request.task_type)})
    except asyncio.CancelledError:
        yield session.emit("task_cancelled", {"partial_final_available": bool(session.final_content)})
    except FallbackRequired as exc:
        candidates = safe_model_candidates(exc.candidate_model_ids)
        payload = {
            "error_code": exc.code.value,
            "candidate_model_ids": list(exc.candidate_model_ids),
            "candidates": candidates,
            "partial_final_available": bool(session.final_content),
        }
        if recovery_owner:
            ticket = create_recovery_ticket(
                "fallback_confirmation",
                request,
                exc.candidate_model_ids,
                recovery_owner,
                source_model_profile_id=exc.source_model_profile_id,
                error_code=exc.code.value,
            )
            payload["recovery_ticket"] = ticket["id"]
            payload["recovery_expires_at"] = ticket["expires_at"]
        yield session.emit(
            "fallback_required",
            payload,
        )
        yield session.emit(
            "stream_error",
            {"error_code": exc.code.value, "partial_final_available": bool(session.final_content)},
        )
    except ModelRouteError as exc:
        code = _route_error_code(exc)
        yield session.emit(
            "stream_error",
            {
                "error_code": code.value,
                "route_status": exc.result.status.value,
                "partial_final_available": bool(session.final_content),
            },
        )
    except ModelExecutionError as exc:
        yield session.emit(
            "stream_error",
            {"error_code": exc.code.value, "partial_final_available": bool(session.final_content)},
        )
    except Exception as exc:
        error = normalize_model_error(exc)
        yield session.emit(
            "stream_error",
            {"error_code": error.code.value, "partial_final_available": bool(session.final_content)},
        )
