from __future__ import annotations

from typing import Any
from uuid import uuid4

from agent_factory.runtime_attachments import transcript_attachment_views


def build_chat_turn_messages(
    *,
    index: int | str,
    created_at: str,
    updated_at: str,
    user_input: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    reasoning_content: str | None = None,
    final_answer: str | None = None,
    tool_activities: list[dict[str, Any]] | None = None,
    message_metadata: dict[str, Any] | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    turn_id = str(index)
    messages: list[dict[str, Any]] = []
    user_text = str(user_input or "").strip()
    if user_text:
        messages.append(
            _chat_message(
                message_id=f"turn-{turn_id}-user",
                role="user",
                timestamp=created_at,
                status="completed",
                metadata=message_metadata,
                parts=[
                    _text_part(
                        part_id=f"turn-{turn_id}-user:text",
                        text=user_text,
                        timestamp=created_at,
                        fmt="plain",
                    ),
                    *[
                        _attachment_part(
                            part_id=f"turn-{turn_id}-user:attachment:{item_index}",
                            attachment=attachment,
                            timestamp=created_at,
                        )
                        for item_index, attachment in enumerate(attachments or [])
                        if isinstance(attachment, dict)
                    ],
                ],
            )
        )

    for activity_index, activity in enumerate(tool_activities or []):
        if not isinstance(activity, dict):
            continue
        activity_key = _tool_activity_key(activity, fallback=str(activity_index))
        activity_timestamp = str(activity.get("createdAt") or activity.get("timestamp") or updated_at)
        messages.append(
            _chat_message(
                message_id=f"turn-{turn_id}-tool-{activity_key}",
                role="assistant",
                timestamp=activity_timestamp,
                status=_tool_message_status(activity),
                parts=_tool_parts(turn_id=turn_id, updated_at=updated_at, activity=activity),
                metadata={
                    "tool_activity": True,
                    "tool_call_id": activity.get("toolCallId") or activity.get("tool_call_id"),
                    "tool_name": activity.get("toolName") or activity.get("tool_name") or activity.get("name"),
                },
            )
        )

    assistant_parts: list[dict[str, Any]] = []
    reasoning_text = str(reasoning_content or "").strip()
    if reasoning_text:
        assistant_parts.append(
            _reasoning_part(
                part_id=f"turn-{turn_id}-assistant:reasoning",
                text=reasoning_text,
                timestamp=updated_at,
            )
        )
    answer_text = str(final_answer or "").strip()
    if answer_text:
        assistant_parts.append(
            _text_part(
                part_id=f"turn-{turn_id}-assistant:text",
                text=answer_text,
                timestamp=updated_at,
                fmt="markdown",
                status=_part_status(status),
            )
        )
    if assistant_parts:
        messages.append(
            _chat_message(
                message_id=f"turn-{turn_id}-assistant",
                role="assistant",
                timestamp=updated_at,
                status=_message_status(status),
                parts=assistant_parts,
            )
        )
    return messages


def _chat_message(
    *,
    message_id: str,
    role: str,
    timestamp: str,
    status: str,
    parts: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "id": message_id,
        "role": role,
        "status": status,
        "timestamp": timestamp,
        "parts": parts,
    }
    if metadata:
        payload["metadata"] = metadata
    return payload


def _text_part(*, part_id: str, text: str, timestamp: str, fmt: str, status: str = "completed") -> dict[str, Any]:
    return {
        "id": part_id,
        "type": "text",
        "format": fmt,
        "text": text,
        "status": status,
        "createdAt": timestamp,
        "updatedAt": timestamp,
    }


def _reasoning_part(*, part_id: str, text: str, timestamp: str) -> dict[str, Any]:
    return {
        "id": part_id,
        "type": "reasoning",
        "text": text,
        "status": "completed",
        "createdAt": timestamp,
        "updatedAt": timestamp,
    }


def _attachment_part(*, part_id: str, attachment: dict[str, Any], timestamp: str) -> dict[str, Any]:
    projected = transcript_attachment_views([attachment])
    attachment_view = projected[0] if projected else {
        "kind": attachment.get("kind") or "file",
        "name": attachment.get("name") or attachment.get("display_name") or attachment.get("attachment_id") or "",
    }
    return {
        "id": part_id,
        "type": "attachment",
        "attachment": attachment_view,
        "status": "completed",
        "createdAt": timestamp,
        "updatedAt": timestamp,
    }


def _tool_parts(*, turn_id: str, updated_at: str, activity: dict[str, Any]) -> list[dict[str, Any]]:
    activity_key = _tool_activity_key(activity, fallback=uuid4().hex)
    tool_name = str(activity.get("toolName") or activity.get("tool_name") or activity.get("name") or "tool_call")
    call_id = activity.get("toolCallId") or activity.get("tool_call_id")
    payload = activity.get("payload") if isinstance(activity.get("payload"), dict) else activity
    status = str(activity.get("status") or "completed")
    parts = [
        {
            "id": f"turn-{turn_id}-tool-{activity_key}:call",
            "type": "tool_call",
            "toolName": tool_name,
            "callId": str(call_id) if call_id else None,
            "arguments": payload.get("arguments") or payload.get("args") or {},
            "liveOutput": payload.get("output"),
            "status": _tool_part_status(status),
            "createdAt": activity.get("createdAt") or updated_at,
            "updatedAt": activity.get("timestamp") or updated_at,
        }
    ]
    if status in {"completed", "failed", "observed"}:
        output = payload.get("output") or payload.get("result") or payload.get("observation") or payload.get("content")
        parts.append(
            {
                "id": f"turn-{turn_id}-tool-{activity_key}:result",
                "type": "tool_result",
                "toolName": tool_name,
                "callId": str(call_id) if call_id else None,
                "output": output,
                "error": payload.get("error"),
                "status": "failed" if status == "failed" else "completed",
                "createdAt": activity.get("createdAt") or updated_at,
                "updatedAt": activity.get("timestamp") or updated_at,
            }
        )
        if status != "failed":
            parts.extend(
                _artifact_parts(
                    activity_key=activity_key,
                    output=output,
                    timestamp=activity.get("timestamp") or updated_at,
                )
            )
    return parts


def _tool_activity_key(activity: dict[str, Any], *, fallback: str) -> str:
    return str(
        activity.get("activityKey")
        or activity.get("tool_call_id")
        or activity.get("toolCallId")
        or fallback
    )


def _tool_message_status(activity: dict[str, Any]) -> str:
    status = str(activity.get("status") or "")
    if status == "failed":
        return "failed"
    if status in {"proposed", "approval", "started", "running", "streaming"}:
        return "streaming"
    return "completed"


def _artifact_parts(*, activity_key: str, output: Any, timestamp: str) -> list[dict[str, Any]]:
    return [
        {
            "id": f"tool-{activity_key}:artifact:{index}",
            "type": "artifact",
            "name": _artifact_name(record),
            "path": record.get("relative_path") or record.get("path"),
            "mimeType": record.get("mime_type") or record.get("mimeType"),
            "sizeBytes": record.get("size_bytes") or record.get("sizeBytes"),
            "status": "completed",
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }
        for index, record in enumerate(_artifact_records(output))
    ]


def _artifact_records(value: Any) -> list[dict[str, Any]]:
    current = value
    for _depth in range(3):
        if not isinstance(current, dict):
            return []
        records = current.get("artifacts") if isinstance(current.get("artifacts"), list) else current.get("assets")
        if isinstance(records, list):
            return [dict(item) for item in records if isinstance(item, dict)]
        current = current.get("output")
    return []


def _artifact_name(record: dict[str, Any]) -> str:
    explicit = str(record.get("name") or "").strip()
    if explicit:
        return explicit
    path = str(record.get("relative_path") or record.get("path") or "artifact").replace("\\", "/")
    return path.rsplit("/", 1)[-1] or "artifact"


def _tool_part_status(status: str) -> str:
    if status == "approval":
        return "awaiting_approval"
    if status in {"proposed", "started"}:
        return "running"
    if status == "failed":
        return "failed"
    return "completed"


def _message_status(status: str | None) -> str:
    if status in {"failed", "stopped"}:
        return status
    if status in {"running", "interrupted"}:
        return "streaming"
    return "completed"


def _part_status(status: str | None) -> str:
    return "streaming" if status in {"running", "interrupted"} else _message_status(status)
