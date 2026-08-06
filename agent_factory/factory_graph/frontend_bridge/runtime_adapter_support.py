from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand, FactoryFrontendEvent


@dataclass(slots=True)
class VisibleAssistantOutputAccumulator:
    content: str | None = None
    reasoning_content: str | None = None
    tool_activities: list[dict[str, Any]] = field(default_factory=list)

    def accept(self, item: FactoryFrontendEvent) -> None:
        upsert_tool_activity(self.tool_activities, item)
        if item.event_type == "message_part_completed" and item.payload.get("part_type") == "reasoning":
            content = visible_message_part_content(item)
            if content:
                self.reasoning_content = content
            return
        if item.event_type != "message_part_completed" or item.payload.get("part_type") != "text":
            return
        content = visible_message_part_content(item)
        if content:
            self.content = content


def interrupt_accepts_message(pending: Any) -> bool:
    payload = getattr(pending, "interrupt_payload", None)
    return isinstance(payload, dict) and str(payload.get("resume_kind") or "").strip() == "answer"


def message_resume_command(
    command: FactoryFrontendCommand,
    message: str,
) -> FactoryFrontendCommand:
    return command.model_copy(
        update={
            "type": "resume_interrupt",
            "message": None,
            "payload": {
                **dict(command.payload or {}),
                "action": "answer",
                "input_text": message,
                "answer": message,
                "message": message,
            },
        }
    )


TOOL_ACTIVITY_EVENT_STATUS = {
    "tool_call_proposed": "proposed",
    "tool_approval_requested": "approval",
    "tool_approval_resolved": "approval",
    "tool_call_started": "started",
    "tool_call_output_delta": "started",
    "tool_call_completed": "completed",
    "tool_call_failed": "failed",
    "tool_contract_invalid": "failed",
    "tool_observation_available": "observed",
}


def upsert_tool_activity(activities: list[dict[str, Any]], item: FactoryFrontendEvent) -> None:
    status = TOOL_ACTIVITY_EVENT_STATUS.get(item.event_type)
    if status is None:
        return
    for payload in _tool_activity_payloads(item):
        _upsert_projected_tool_activity(activities, item=item, payload=payload, status=status)


def _tool_activity_payloads(item: FactoryFrontendEvent) -> list[dict[str, Any]]:
    payload = item.payload if isinstance(item.payload, dict) else {}
    if item.event_type == "tool_approval_requested":
        requests = payload.get("requests") if isinstance(payload.get("requests"), list) else []
        common = {key: value for key, value in payload.items() if key != "requests"}
        return [
            {**common, **request}
            for request in requests
            if isinstance(request, dict)
        ]
    if item.event_type == "tool_approval_resolved":
        return [{**payload, "tool_call_id": call_id} for call_id in _approval_tool_call_ids(payload)]
    return [payload]


def _approval_tool_call_ids(payload: dict[str, Any]) -> list[str]:
    requests = payload.get("requests") if isinstance(payload.get("requests"), list) else []
    candidates = [
        payload.get("tool_call_id"),
        payload.get("toolCallId"),
        *(payload.get("tool_call_ids") if isinstance(payload.get("tool_call_ids"), list) else []),
        *(payload.get("toolCallIds") if isinstance(payload.get("toolCallIds"), list) else []),
        *(
            request.get("tool_call_id") or request.get("toolCallId")
            for request in requests
            if isinstance(request, dict)
        ),
    ]
    return list(dict.fromkeys(str(value or "").strip() for value in candidates if str(value or "").strip()))


def _upsert_projected_tool_activity(
    activities: list[dict[str, Any]],
    *,
    item: FactoryFrontendEvent,
    payload: dict[str, Any],
    status: str,
) -> None:
    tool_call_id = _first_payload_text(payload, "tool_call_id", "toolCallId")
    activity_key = tool_call_id or str(item.span_id or item.event_id)
    existing_index = next(
        (
            index
            for index, activity in enumerate(activities)
            if activity.get("activityKey") == activity_key
            or (tool_call_id and activity.get("toolCallId") == tool_call_id)
        ),
        -1,
    )
    existing = activities[existing_index] if existing_index >= 0 else {}
    existing_payload = existing.get("payload") if isinstance(existing.get("payload"), dict) else {}
    tool_name = _first_payload_text(payload, "tool_name", "tool_id", "name") or existing.get("toolName") or "tool_call"
    merged_payload = {**existing_payload, **payload}
    merged_payload["arguments"] = {
        **_payload_arguments(existing_payload),
        **_payload_arguments(payload),
    }
    activity = {
        "activityKey": str(existing.get("activityKey") or activity_key),
        "requestId": item.request_id or existing.get("requestId"),
        "eventType": item.event_type,
        "timestamp": item.timestamp,
        "createdAt": existing.get("createdAt") or item.timestamp,
        "stageId": item.stage_id or existing.get("stageId"),
        "nodeId": item.node_id or existing.get("nodeId"),
        "toolCallId": tool_call_id or existing.get("toolCallId"),
        "toolName": tool_name,
        "status": status,
        "approvalState": _approval_state(item, existing.get("approvalState")),
        "payload": merged_payload,
    }
    if existing_index >= 0:
        activities[existing_index] = activity
    else:
        activities.append(activity)


def _first_payload_text(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return None


def _payload_arguments(payload: dict[str, Any]) -> dict[str, Any]:
    arguments = payload.get("arguments")
    if isinstance(arguments, dict):
        return dict(arguments)
    args = payload.get("args")
    if isinstance(args, dict):
        return dict(args)
    return {}


def _approval_state(item: FactoryFrontendEvent, existing: Any) -> str | None:
    if item.event_type == "tool_approval_requested":
        return "pending"
    if item.event_type != "tool_approval_resolved":
        return str(existing) if existing else None
    payload = item.payload if isinstance(item.payload, dict) else {}
    approved = payload.get("approved")
    action = str(payload.get("action") or payload.get("decision") or "").strip().lower()
    if approved is True or action == "approve":
        return "approved"
    if approved is False or action in {"deny", "reject", "rejected"}:
        return "denied"
    return str(existing) if existing else None


def visible_message_part_content(item: FactoryFrontendEvent) -> str | None:
    if not isinstance(item.payload, dict):
        return None
    content = str(item.payload.get("content") or item.payload.get("text") or "").strip()
    return content or None


def session_payload(record: Any | None, *, snapshot_mode: str | None = None) -> dict[str, Any]:
    if record is None:
        return {}
    payload = record.model_dump(mode="json")
    first_user_input = payload.get("first_user_input")
    payload["first_user_input"] = first_user_input
    payload["display_title"] = payload.get("display_title") or display_title(first_user_input)
    mode = snapshot_mode or payload.get("current_mode")
    turns = _turns_for_mode(payload, mode)
    messages = _messages_from_session_turns(turns)
    payload["mode_titles"] = {
        "create_agent": display_title(_first_turn_input(payload.get("create_agent_turns"))),
        "evolve_agent": display_title(_first_turn_input(payload.get("evolve_agent_turns"))),
    }
    payload["mode_turn_counts"] = {
        "create_agent": int(payload.get("create_agent_turn_count") or 0),
        "evolve_agent": int(payload.get("evolve_agent_turn_count") or 0),
    }
    payload["snapshot"] = {
        "mode": mode,
        "turns": turns if isinstance(turns, list) else [],
        "messages": messages,
        "pending_interrupt": None,
        "recent_tool_activities": [],
    }
    return payload


def _messages_from_session_turns(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    messages: list[dict[str, Any]] = []
    for index, turn in enumerate(value, start=1):
        if not isinstance(turn, dict):
            continue
        turn_messages = turn.get("messages")
        if isinstance(turn_messages, list):
            messages.extend(item for item in turn_messages if isinstance(item, dict))
    return messages


def _turns_for_mode(payload: dict[str, Any], mode: str | None) -> Any:
    if mode == "create_agent":
        return payload.get("create_agent_turns")
    if mode == "evolve_agent":
        return payload.get("evolve_agent_turns")
    return payload.get("turns")


def _first_turn_input(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    for turn in value:
        if not isinstance(turn, dict):
            continue
        text = str(turn.get("user_input") or "").strip()
        if text:
            return text
    return None


def display_title(value: str | None, *, limit: int = 42) -> str | None:
    if not value:
        return None
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit - 1]}…"


def bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def extract_interrupt_payload(chunk: Any) -> Any | None:
    if not isinstance(chunk, dict):
        return None
    interrupts = chunk.get("__interrupt__")
    if not interrupts:
        return None
    first = interrupts[0]
    return interrupt_payload(first)


def interrupt_payload(interrupt: Any) -> Any:
    value = getattr(interrupt, "value", interrupt)
    interrupt_id = str(getattr(interrupt, "id", "") or "").strip()
    if not interrupt_id:
        return value
    if isinstance(value, dict):
        return {**value, "interrupt_id": interrupt_id}
    return {"value": value, "interrupt_id": interrupt_id}
