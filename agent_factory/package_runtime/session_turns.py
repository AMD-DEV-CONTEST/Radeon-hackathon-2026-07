from __future__ import annotations

from typing import Any

from agent_factory.runtime_attachments import normalized_runtime_attachments
from agent_factory.trace_system import runtime_trace_ref


def session_final_answer(state: Any) -> str | None:
    conversation = getattr(state, "conversation", None)
    if conversation is None:
        return None
    return str(
        getattr(conversation, "final_answer", None)
        or getattr(conversation, "assistant_draft", None)
        or ""
    ).strip() or None


def session_reasoning_content(state: Any) -> str | None:
    conversation = getattr(state, "conversation", None)
    if conversation is None:
        return None
    value = getattr(conversation, "reasoning_content", None)
    return str(value or "").strip() or None


def session_trace_ref(compiled: Any, state: Any) -> dict[str, str] | None:
    trace_id = str(getattr(getattr(state, "observability", None), "trace_id", "") or "").strip()
    run_id = str(getattr(getattr(state, "run", None), "run_id", "") or "").strip()
    services = getattr(compiled, "services", None)
    recorder = getattr(services, "trace_recorder", None) if services is not None else None
    return runtime_trace_ref(recorder=recorder, trace_id=trace_id, run_id=run_id)


def resume_user_input(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("message", "response", "value", "text", "user_input"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    approval = payload.get("approval")
    if isinstance(approval, dict):
        decision = str(approval.get("decision") or approval.get("action") or "").strip()
        return decision or None
    return None


def session_user_input_from_state(
    state: Any,
    *,
    fallback_user_input: str | None = None,
) -> str | None:
    value = _current_user_input_from_state(state) or fallback_user_input
    return str(value or "").strip() or None


def session_attachments_from_state(state: Any, *, fallback_attachments: Any = None) -> list[dict[str, Any]]:
    attachments = _runtime_attachments_from_state(state)
    if attachments is None:
        attachments = fallback_attachments
    return normalized_runtime_attachments(attachments)


def _current_user_input_from_state(state: Any) -> str | None:
    conversation = getattr(state, "conversation", None)
    if conversation is None:
        return None
    value = getattr(conversation, "current_user_input", None)
    return str(value).strip() or None if value is not None else None


def _runtime_attachments_from_state(state: Any) -> list[dict[str, Any]] | None:
    runtime_config = getattr(state, "runtime_config", None)
    user_config = getattr(runtime_config, "user_config", None)
    if not isinstance(user_config, dict):
        return None
    attachments = user_config.get("attachments")
    if not isinstance(attachments, list):
        return None
    return normalized_runtime_attachments(attachments)
