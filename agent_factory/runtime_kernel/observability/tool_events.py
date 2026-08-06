from __future__ import annotations

from typing import Any

from langgraph.config import get_stream_writer


def emit_runtime_tool_activity(payload: dict[str, Any], *, node_id: str | None = None) -> None:
    events = _frontend_tool_events(payload, node_id=node_id)
    if not events:
        return
    try:
        writer = get_stream_writer()
    except Exception:
        return
    try:
        writer({"type": "tool_activity", "payload": {"events": events}})
    except Exception:
        return


def _frontend_tool_events(payload: dict[str, Any], *, node_id: str | None) -> list[dict[str, Any]]:
    event_type = str(payload.get("event_type") or "")
    if event_type == "tool_proposed":
        return [_event("tool_call_proposed", payload, node_id=node_id)]
    if event_type == "tool_started":
        return [_event("tool_call_started", payload, node_id=node_id)]
    if event_type == "tool_output_delta":
        return [_event("tool_call_output_delta", payload, node_id=node_id)]
    if event_type == "tool_completed":
        completed = _event("tool_call_completed", payload, node_id=node_id)
        observation = _event("tool_observation_available", payload, node_id=node_id)
        return [completed, observation]
    if event_type == "tool_contract_invalid":
        invalid = _event("tool_contract_invalid", payload, node_id=node_id)
        observation = _event("tool_observation_available", payload, node_id=node_id)
        return [invalid, observation]
    if event_type == "tool_failed":
        failed = _event("tool_call_failed", payload, node_id=node_id)
        observation = _event("tool_observation_available", payload, node_id=node_id)
        return [failed, observation]
    return []


def _event(event_type: str, payload: dict[str, Any], *, node_id: str | None) -> dict[str, Any]:
    tool_id = str(payload.get("tool_id") or payload.get("tool_name") or "")
    tool_call_id = str(payload.get("tool_call_id") or tool_id)
    output = payload.get("output")
    result = payload.get("result")
    error = payload.get("error")
    observation = payload.get("observation")
    if observation is None and isinstance(result, dict):
        observation = result
    if observation is None and output is not None:
        observation = {"output": output}
    if observation is None and error:
        observation = {"error": error}
    return {
        "event_type": event_type,
        "tool_call_id": tool_call_id,
        "tool_id": tool_id,
        "tool_name": tool_id,
        "node_id": node_id,
        "arguments": payload.get("arguments") or {},
        "status": payload.get("status") or _status_for_event(event_type),
        "output": output,
        "result": result,
        "error": error,
        "observation": observation,
        "message": payload.get("message") or payload.get("summary") or payload.get("observation_summary") or "",
    }


def _status_for_event(event_type: str) -> str:
    if event_type == "tool_call_started":
        return "running"
    if event_type == "tool_call_output_delta":
        return "running"
    if event_type == "tool_call_completed":
        return "completed"
    if event_type == "tool_contract_invalid":
        return "completed"
    if event_type == "tool_call_failed":
        return "failed"
    if event_type == "tool_observation_available":
        return "observed"
    return "proposed"
