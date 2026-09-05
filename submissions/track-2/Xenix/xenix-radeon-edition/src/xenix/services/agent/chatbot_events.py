"""Pure Chatbot projection for final Conversation Messages and live signals.

Chatbot events are a presentation projection.  They never read execution rows,
infer Call/Result pairing from adjacency, or persist their own lifecycle.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Mapping
from enum import StrEnum
from typing import Any

from pydantic import model_serializer
from sqlmodel import Field, SQLModel

from ..llm.messages import blocks_from_payload, blocks_to_json
from ..llm.tooling import canonical_tool_result_value
from .skill_catalog import is_agent_skill_tool
from .tool_presentations import ToolPresentation, tool_presentation_for_name


class ChatbotEventKind(StrEnum):
    TEXT = "text"
    TOOL = "tool"
    CONNECTION = "connection"
    ACTIVITY = "activity"
    THINKING = "thinking"
    USAGE = "usage"


class ChatbotEventStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ChatbotEventAuthor(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatbotEvent(SQLModel):
    id: str
    kind: ChatbotEventKind
    sequence_index: int = 0
    author: ChatbotEventAuthor
    status: ChatbotEventStatus = ChatbotEventStatus.COMPLETED
    content_blocks: list[dict[str, Any]] = Field(default_factory=list)
    # Assistant fields are copied from the canonical Message as a projection.
    # Consumers decide whether a value is user-visible; the Harness must not
    # turn an Assistant Message into a second, display-oriented serializer.
    text: str | None = None
    reasoning: str | None = None
    refusal: str | None = None
    source_message_ids: list[str] = Field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None
    # The canonical ToolResult value copied from the Conversation Message.
    # Detail blocks are only its UI envelope, never an alternate raw result.
    tool_result_value: Any = None
    icon_key: str | None = None
    summary: str | None = None
    usage_payload: dict[str, Any] | None = None
    detail_blocks: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def _serialize_without_ui_open_paths(self, handler) -> Any:
        """Redact ephemeral source paths from every Pydantic serialization.

        The live in-process event still carries the path so the desktop bubble
        can open the selected source.  Logs, diagnostic dumps, IPC-like JSON,
        and any future persistence that relies on normal model serialization
        receive only the bounded display metadata.
        """

        return _redact_ui_open_paths(handler(self))


ToolPresentationLookup = Callable[[str], ToolPresentation]
# A source presentation is deliberately a loose read-only boundary.  The
# DatasetService/Harness owns the concrete record; this module only copies the
# bounded fields needed by the Chatbot UI and remains usable without it.
SourceAttachmentLookup = Callable[[str], Mapping[str, Any] | Any | None]


def thinking_chatbot_event_id(pending_message_id: str) -> str:
    return f"{pending_message_id}:thinking"


def activity_chatbot_event_id(pending_message_id: str, sequence_index: int) -> str:
    return f"{pending_message_id}:activity:{sequence_index}"


def build_activity_chatbot_event(
    *, pending_message_id: str, sequence_index: int,
) -> ChatbotEvent:
    return ChatbotEvent(
        id=activity_chatbot_event_id(pending_message_id, sequence_index),
        kind=ChatbotEventKind.ACTIVITY,
        sequence_index=sequence_index,
        author=ChatbotEventAuthor.ASSISTANT,
        status=ChatbotEventStatus.IN_PROGRESS,
        summary="assistant_activity",
    )


def build_thinking_chatbot_event(
    *, pending_message_id: str, status: ChatbotEventStatus,
) -> ChatbotEvent:
    return ChatbotEvent(
        id=thinking_chatbot_event_id(pending_message_id),
        kind=ChatbotEventKind.THINKING,
        author=ChatbotEventAuthor.ASSISTANT,
        status=status,
        content_blocks=[{"type": "thinking", "text": "Thinking..."}]
        if status is ChatbotEventStatus.IN_PROGRESS else [],
        summary="Thinking..." if status is ChatbotEventStatus.IN_PROGRESS else None,
    )


def build_llm_connection_chatbot_event(
    *, sampling_id: str, retry_events: list[dict[str, Any]],
    status: ChatbotEventStatus = ChatbotEventStatus.IN_PROGRESS,
) -> ChatbotEvent:
    return ChatbotEvent(
        id=f"{sampling_id}:connection",
        kind=ChatbotEventKind.CONNECTION,
        author=ChatbotEventAuthor.ASSISTANT,
        status=status,
        icon_key="connection",
        summary="llm_connection_retry",
        detail_blocks=[{"type": "llm_connection_retry", "retry_events": [dict(e) for e in retry_events]},],
    )


def project_chatbot_events(
    snapshot: Any,
    *, tool_presentation_lookup: ToolPresentationLookup | None = None,
) -> list[ChatbotEvent]:
    """Project final typed Messages; provisional sampling is intentionally hidden."""
    messages = sorted(
        (message for message in snapshot.messages
         if _kind_value(getattr(message, "kind", None)) != "pending_llm_sampling"),
        key=lambda message: getattr(message, "sequence_index", 0),
    )
    result_by_call = {
        str(message.tool_call_message_id): message
        for message in messages
        if _kind_value(getattr(message, "kind", None)) == "tool_result"
        and getattr(message, "tool_call_message_id", None)
    }
    events: list[ChatbotEvent] = []
    for message in messages:
        kind = _kind_value(getattr(message, "kind", None))
        if kind == "tool_result":
            continue
        if kind in {"user", "assistant", "client_control"}:
            if kind == "client_control":
                continue
            events.append(project_text_message_event(message))
        elif kind == "tool_call":
            result = result_by_call.get(str(getattr(message, "id", "")))
            tool_name = _tool_name(message)
            if tool_name and (not is_agent_skill_tool(tool_name) or should_project_agent_skill_tools()):
                events.append(project_tool_chatbot_event(
                    message, result_message=result,
                    tool_presentation_lookup=tool_presentation_lookup,
                ))
    return events


def project_text_message_event(
    message: Any,
) -> ChatbotEvent:
    kind = _kind_value(getattr(message, "kind", None))
    author = ChatbotEventAuthor.USER if kind == "user" else ChatbotEventAuthor.ASSISTANT
    blocks = _message_blocks(message)
    return ChatbotEvent(
        id=str(message.id), kind=ChatbotEventKind.TEXT,
        sequence_index=int(getattr(message, "sequence_index", 0)), author=author,
        content_blocks=blocks,
        text=_optional_text(getattr(message, "text", None)) if kind == "assistant" else None,
        reasoning=_optional_text(getattr(message, "reasoning", None)) if kind == "assistant" else None,
        refusal=_optional_text(getattr(message, "refusal", None)) if kind == "assistant" else None,
        source_message_ids=[str(message.id)],
    )


def enrich_chatbot_events_with_source_attachments(
    snapshot: Any,
    events: Iterable[ChatbotEvent],
    source_attachment_lookup: SourceAttachmentLookup,
) -> list[ChatbotEvent]:
    """Add ephemeral source presentations after the pure event projection.

    The callback receives only a canonical ``dataset_id``.  Its return value
    is copied into a UI-only source block and never fed back to the LLM
    message projection.  A missing/stale source is deliberately a soft result
    so reopening a Thread cannot fail because an original file disappeared.
    """

    canonical_user_ids = {
        str(getattr(message, "id", ""))
        for message in getattr(snapshot, "messages", [])
        if _kind_value(getattr(message, "kind", None)) == "user"
    }
    enriched: list[ChatbotEvent] = []
    for event in events:
        if (
            event.kind is not ChatbotEventKind.TEXT
            or event.author is not ChatbotEventAuthor.USER
            or not event.source_message_ids
            or event.source_message_ids[0] not in canonical_user_ids
        ):
            enriched.append(event)
            continue
        blocks = _project_source_attachments(event.content_blocks, source_attachment_lookup)
        if blocks == event.content_blocks:
            enriched.append(event)
            continue
        enriched.append(event.model_copy(update={"content_blocks": blocks}))
    return enriched


def _project_source_attachments(
    blocks: list[dict[str, Any]],
    source_attachment_lookup: SourceAttachmentLookup,
) -> list[dict[str, Any]]:
    """Append ephemeral source presentations for canonical Dataset blocks.

    Dataset blocks stay unchanged as the canonical event payload; the UI
    filters that type from display and renders only this optional projection.
    Resolver failures are intentionally soft so history remains readable when
    source provenance is missing or stale.  Existing canonical source blocks
    are retained for historical messages and deduplicate an enriched result.
    """

    result = [dict(block) for block in blocks if isinstance(block, dict)]
    visible_source_blocks = [
        block
        for block in result
        if str(block.get("type") or "").strip().lower() == "source_attachment"
        and not (
            block.get("chatbot_visible") is False
            or ("chatbot_visible" not in block and block.get("visible") is False)
        )
    ]
    seen_sources = {
        identity
        for block in visible_source_blocks
        if (identity := _source_identity(block)) is not None
    }
    # A legacy source block lacks the DatasetImport identifier.  Its bounded
    # filename is only a compatibility hint against a new projection; it must
    # never make two distinct *new* imports with the same basename collide.
    legacy_file_names = {
        file_name
        for block in visible_source_blocks
        if not block.get("chatbot_source_projection")
        if (file_name := _safe_file_name(block.get("file_name"))) is not None
    }
    projected_sources: set[tuple[str, str]] = set()
    for block in result:
        if str(block.get("type") or "").strip().lower() != "dataset":
            continue
        dataset_id = str(block.get("dataset_id") or "").strip()
        if not dataset_id:
            continue
        try:
            presentation = source_attachment_lookup(dataset_id)
        except Exception:
            continue
        source_block = _source_attachment_block(dataset_id, presentation)
        if source_block is None:
            continue
        identity = _source_identity(source_block)
        if identity is None:
            continue
        if identity in seen_sources or identity in projected_sources:
            continue
        if (
            identity[0] == "source_group_id"
            and _safe_file_name(source_block.get("file_name")) in legacy_file_names
        ):
            # Existing rows that contain a legacy source block and their
            # DatasetBlock should continue showing that historical attachment
            # once rather than gaining a duplicate projection.
            continue
        result.append(source_block)
        projected_sources.add(identity)
    return result


def _source_attachment_block(
    dataset_id: str,
    presentation: Mapping[str, Any] | Any | None,
) -> dict[str, Any] | None:
    if presentation is None:
        return None

    def value(name: str, default: Any = None) -> Any:
        if isinstance(presentation, Mapping):
            return presentation.get(name, default)
        return getattr(presentation, name, default)

    file_name = _safe_file_name(value("file_name"))
    source_group_id = _bounded_ui_text(value("source_group_id", value("source_key")))
    file_path = _bounded_file_path(value("file_path", value("open_path")))
    is_openable = bool(value("is_openable", value("available", bool(file_path)))) and bool(file_path)
    if not file_name:
        return None
    block: dict[str, Any] = {
        "type": "source_attachment",
        "dataset_id": dataset_id,
        "chatbot_source_projection": True,
        "is_openable": is_openable,
        "file_path": file_path,
    }
    if file_name:
        block["file_name"] = file_name
    if source_group_id:
        block["source_group_id"] = source_group_id
    return block


def _source_identity(block: Mapping[str, Any]) -> tuple[str, str] | None:
    """Return one stable source identity, with DatasetImport taking priority."""

    for field in ("source_group_id", "source_key", "artifact_id"):
        value = _bounded_ui_text(block.get(field))
        if value:
            return (field, value)
    file_name = _safe_file_name(block.get("file_name"))
    return ("file_name", file_name) if file_name else None


def _redact_ui_open_paths(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    blocks = payload.get("content_blocks")
    if not isinstance(blocks, list):
        return payload
    redacted = dict(payload)
    redacted_blocks: list[Any] = []
    for block in blocks:
        if not isinstance(block, dict):
            redacted_blocks.append(block)
            continue
        sanitized = dict(block)
        if sanitized.get("chatbot_source_projection"):
            sanitized.pop("file_path", None)
        redacted_blocks.append(sanitized)
    redacted["content_blocks"] = redacted_blocks
    return redacted


def _bounded_ui_text(value: Any, *, limit: int = 512) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] if value else None


def _bounded_file_path(value: Any, *, limit: int = 4096) -> str | None:
    """Keep a UI capability path intact or drop it; never truncate it."""

    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > limit or any(char in value for char in "\r\n"):
        return None
    return value


def _safe_file_name(value: Any) -> str | None:
    value = _bounded_ui_text(value)
    if not value:
        return None
    leaf = value.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return leaf[:512] if leaf and leaf not in {".", ".."} else None




def project_tool_chatbot_event(
    tool_call: Any, *, request_message: Any | None = None,
    result_message: Any | None = None,
    tool_presentation_lookup: ToolPresentationLookup | None = None,
) -> ChatbotEvent:
    tool_name = _tool_name(tool_call)
    result_status = _kind_value(getattr(result_message, "result_status", None)) if result_message else None
    if not result_status and result_message is not None and getattr(result_message, "error_summary", None):
        result_status = "failed"
    status = {
        "failed": ChatbotEventStatus.FAILED,
        "cancelled": ChatbotEventStatus.CANCELLED,
        "succeeded": ChatbotEventStatus.COMPLETED,
    }.get(result_status, ChatbotEventStatus.PENDING)
    presentation = tool_presentation(tool_name, tool_presentation_lookup=tool_presentation_lookup)
    call_id = str(getattr(tool_call, "id", ""))
    source_ids = [call_id]
    if result_message is not None:
        source_ids.append(str(result_message.id))
    result_value = _canonical_result_value(result_message, result_status)
    payload = result_value if isinstance(result_value, dict) else None
    summary = presentation.summary_for(result_status or "pending")
    if status is ChatbotEventStatus.COMPLETED and isinstance(payload, dict):
        summary = _tool_summary_from_payload(tool_name, payload) or summary
    return ChatbotEvent(
        id=call_id, kind=ChatbotEventKind.TOOL,
        sequence_index=int(getattr(tool_call, "sequence_index", 0)),
        author=ChatbotEventAuthor.TOOL, status=status,
        source_message_ids=source_ids, tool_call_id=call_id,
        tool_name=tool_name, icon_key=presentation.icon_key, summary=summary,
        tool_result_value=result_value,
        detail_blocks=_tool_detail_blocks(tool_call, result_value, result_status),
        actions=_tool_actions(tool_name, payload),
    )


def should_project_agent_skill_tools() -> bool:
    return os.environ.get("XENIX_ENV", "").strip().lower() in {"development", "dev"}


def tool_presentation(tool_name: str, *, tool_presentation_lookup: ToolPresentationLookup | None = None) -> ToolPresentation:
    return (tool_presentation_lookup or tool_presentation_for_name)(tool_name)


def _kind_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _message_blocks(message: Any) -> list[dict[str, Any]]:
    payload = getattr(message, "content_payload", None)
    if isinstance(payload, dict):
        blocks = blocks_from_payload(payload)
        if blocks:
            return blocks_to_json(blocks)
        payload_text = payload.get("text")
        if isinstance(payload_text, str) and payload_text:
            return [{"type": "text", "text": payload_text}]
    if _kind_value(getattr(message, "kind", None)) == "assistant":
        # Assistant text/reasoning/refusal are first-class event fields.  Do
        # not manufacture a second block representation from those columns.
        return []
    blocks: list[dict[str, Any]] = []
    text = getattr(message, "text", None)
    reasoning = getattr(message, "reasoning", None)
    refusal = getattr(message, "refusal", None)
    if isinstance(text, str) and text:
        blocks.append({"type": "text", "text": text})
    if isinstance(reasoning, str) and reasoning:
        blocks.append({"type": "reasoning", "text": reasoning})
    if isinstance(refusal, str) and refusal:
        blocks.append({"type": "refusal", "text": refusal})
    return blocks


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value or None


def _tool_name(message: Any) -> str:
    payload = getattr(message, "content_payload", None)
    if isinstance(payload, dict) and isinstance(payload.get("tool_name"), str):
        return payload["tool_name"]
    return str(getattr(message, "tool_id", "") or "")


def _canonical_result_value(message: Any | None, result_status: str | None) -> Any:
    if message is None:
        return None
    return canonical_tool_result_value(
        value=getattr(message, "value_payload", None),
        failed=result_status == "failed",
        legacy_error_summary=getattr(message, "error_summary", None),
    )


def _tool_summary_from_payload(tool_name: str, payload: dict[str, Any]) -> str | None:
    if payload.get("async_state") != "running_background":
        return None
    return {
        "model.hyper_train": "Model tuning running in background",
        "model.train": "Model training running in background",
        "model.apply": "Model apply running in background",
    }.get(tool_name, "ML task running in background")


def _tool_actions(tool_name: str, payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not payload or tool_name == "model.task.query":
        return []
    raw = payload.get("task_ids")
    if not isinstance(raw, list):
        raw = [payload.get("ml_task_id")] if isinstance(payload.get("ml_task_id"), str) else []
    task_ids = [str(value) for value in raw if str(value).strip()]
    return [{"type": "open_tool_call_detail", "task_ids": task_ids}] if task_ids else []


def _tool_detail_blocks(tool_call: Any, result_value: Any, result_status: str | None) -> list[dict[str, Any]]:
    tool_name = _tool_name(tool_call)
    lines = [f"### {tool_name}", "", f"Status: `{result_status or 'pending'}`"]
    arguments = getattr(tool_call, "arguments_payload", None) or {}
    lines.extend(["", "#### Arguments", "```json", _json_dump(arguments), "```"])
    if result_value is not None:
        lines.extend(["", "#### Result"])
        if isinstance(result_value, str):
            # XTT is already the canonical Tool Result text.  Render it
            # directly rather than re-serializing a hidden JSON payload.
            lines.append(result_value)
        else:
            lines.extend(["```json", _json_dump(result_value), "```"])
    return [{"type": "markdown", "text": "\n".join(lines)}]


def _json_dump(value: Any) -> str:
    dumped = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return dumped if len(dumped) <= 12000 else dumped[:12000] + f"\n... <truncated {len(dumped) - 12000} chars>"
