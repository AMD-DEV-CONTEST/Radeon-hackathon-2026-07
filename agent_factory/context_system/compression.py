from __future__ import annotations

from time import perf_counter
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from agent_factory.context_system.schema import CompressionPolicy, ContextCompressionReport
from agent_factory.context_system.token_counter import TokenCountResult
from agent_factory.context_system.token_estimation import estimate_messages_tokens, estimate_text_tokens
from agent_factory.models import get_compression_model
from agent_factory.runtime_protocol.messages import incomplete_tool_call_ids


CONTEXT_SUMMARY_KIND = "context_summary"


def maybe_compress_messages(
    *,
    messages: list[Any],
    policy: CompressionPolicy,
    node_id: str,
    token_counter: Callable[[list[Any]], TokenCountResult] | None = None,
    trigger_count: TokenCountResult | None = None,
    on_start: Callable[[ContextCompressionReport], None] | None = None,
) -> tuple[list[Any], ContextCompressionReport]:
    started = perf_counter()
    if not policy.enabled:
        return messages, ContextCompressionReport(status="skipped", node_id=node_id)
    count_before = trigger_count or _count_messages(messages, token_counter=token_counter)
    if count_before.token_count is None:
        return (
            messages,
            ContextCompressionReport(
                status="skipped",
                node_id=node_id,
                original_message_count=len(messages),
                compressed_message_count=len(messages),
                token_count_method=count_before.method,
                token_count_error=count_before.error,
                duration_ms=int((perf_counter() - started) * 1000),
            ),
        )
    token_before = count_before.token_count
    if token_before < policy.trigger_token_threshold:
        return (
            messages,
            ContextCompressionReport(
                status="skipped",
                node_id=node_id,
                original_message_count=len(messages),
                compressed_message_count=len(messages),
                token_estimate_before=token_before,
                token_estimate_after=token_before,
                token_count_method=count_before.method,
                duration_ms=int((perf_counter() - started) * 1000),
            ),
        )
    protected, compressible, recent = _partition_messages(
        messages,
        keep_recent=policy.keep_recent_messages,
        minimum_token_reduction=max(token_before - policy.trigger_token_threshold, 1),
    )
    if not compressible:
        return (
            messages,
            ContextCompressionReport(
                status="skipped",
                node_id=node_id,
                original_message_count=len(messages),
                compressed_message_count=len(messages),
                token_estimate_before=token_before,
                token_estimate_after=token_before,
                token_count_method=count_before.method,
                duration_ms=int((perf_counter() - started) * 1000),
            ),
        )
    try:
        if on_start is not None:
            on_start(
                ContextCompressionReport(
                    status="started",
                    node_id=node_id,
                    original_message_count=len(messages),
                    compressed_message_count=len(messages),
                    token_estimate_before=token_before,
                    token_estimate_after=token_before,
                    token_count_method=count_before.method,
                    duration_ms=int((perf_counter() - started) * 1000),
                )
            )
        summary = _summarize_messages(compressible)
        summary_message = SystemMessage(
            content=summary,
            additional_kwargs={
                "kind": CONTEXT_SUMMARY_KIND,
                "source": "runtime_context_compression",
                "compressed_message_count": len(compressible),
            },
            id=f"context-summary-{uuid4().hex}",
        )
        compressed_messages = [*protected, summary_message, *recent]
        missing = incomplete_tool_call_ids(compressed_messages)
        if missing:
            raise RuntimeError("compressed messages contain incomplete tool call history: " + ", ".join(missing))
        count_after = _count_messages(compressed_messages, token_counter=token_counter)
        token_after = count_after.token_count or 0
        return (
            compressed_messages,
            ContextCompressionReport(
                status="completed",
                node_id=node_id,
                original_message_count=len(messages),
                compressed_message_count=len(compressed_messages),
                token_estimate_before=token_before,
                token_estimate_after=token_after,
                token_count_method=count_after.method,
                token_count_error=count_after.error,
                summary_token_estimate=estimate_text_tokens(summary),
                duration_ms=int((perf_counter() - started) * 1000),
            ),
        )
    except Exception as exc:
        return (
            messages,
            ContextCompressionReport(
                status="failed",
                node_id=node_id,
                original_message_count=len(messages),
                compressed_message_count=len(messages),
                token_estimate_before=token_before,
                token_estimate_after=token_before,
                token_count_method=count_before.method,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=int((perf_counter() - started) * 1000),
            ),
        )


def _count_messages(
    messages: list[Any],
    *,
    token_counter: Callable[[list[Any]], TokenCountResult] | None,
) -> TokenCountResult:
    if token_counter is None:
        return TokenCountResult(token_count=estimate_messages_tokens(messages), method="text_estimation")
    return token_counter(messages)


def _partition_messages(
    messages: list[Any],
    *,
    keep_recent: int,
    minimum_token_reduction: int,
) -> tuple[list[Any], list[Any], list[Any]]:
    normalized = list(messages)
    protected: list[Any] = []
    cursor = 0
    while cursor < len(normalized) and _is_protected_message(normalized[cursor]):
        protected.append(normalized[cursor])
        cursor += 1
    history_count = len(normalized) - cursor
    if history_count <= 2:
        return protected, [], normalized[cursor:]

    maximum_recent_count = min(keep_recent, history_count - 1)
    first_boundary = len(normalized) - maximum_recent_count
    last_boundary = len(normalized) - 2
    selected_boundary: int | None = None
    for boundary in range(first_boundary, last_boundary + 1):
        if boundary < len(normalized) and _is_tool_message(normalized[boundary]):
            continue
        candidate = normalized[cursor:boundary]
        if not candidate or incomplete_tool_call_ids(candidate):
            continue
        selected_boundary = boundary
        if estimate_messages_tokens(candidate) >= minimum_token_reduction:
            break
    if selected_boundary is None:
        return protected, [], normalized[cursor:]

    compressible = normalized[cursor:selected_boundary]
    recent = normalized[selected_boundary:]
    return protected, compressible, recent


def _is_protected_message(message: Any) -> bool:
    if not isinstance(message, SystemMessage):
        return False
    metadata = dict(getattr(message, "additional_kwargs", {}) or {})
    return metadata.get("kind") != CONTEXT_SUMMARY_KIND


def is_context_summary_message(message: Any) -> bool:
    if not isinstance(message, SystemMessage):
        return False
    metadata = dict(getattr(message, "additional_kwargs", {}) or {})
    return metadata.get("kind") == CONTEXT_SUMMARY_KIND


def _is_tool_message(message: Any) -> bool:
    return isinstance(message, ToolMessage)


def _summarize_messages(messages: list[Any]) -> str:
    model = get_compression_model()
    if model is None:
        raise RuntimeError("compression model is not configured")
    configured = model
    prompt = [
        SystemMessage(
            content=(
                "You are compacting the current conversation into an internal session snapshot for a future agent turn. "
                "The snapshot is private runtime state, not a user-facing reply. "
                "Your job is to preserve enough information for the next agent call to continue work without reading the removed messages.\n\n"
                "Write the output as one tagged internal snapshot using exactly this shape:\n"
                "<session_snapshot>\n"
                "  <user_intent>...</user_intent>\n"
                "  <key_facts>...</key_facts>\n"
                "  <completed_actions>...</completed_actions>\n"
                "  <active_state>...</active_state>\n"
                "  <tool_and_knowledge_results>...</tool_and_knowledge_results>\n"
                "  <continuation_instructions>...</continuation_instructions>\n"
                "</session_snapshot>\n\n"
                "Section rules:\n"
                "- user_intent: the user's goals, questions, preferences, and constraints from this segment.\n"
                "- key_facts: concrete facts needed for continuity, including exact names, numbers, URLs, paths, IDs, and answers when they matter.\n"
                "- completed_actions: actions already completed and their outcomes.\n"
                "- active_state: unfinished tasks, pending confirmations, blockers, or the exact point where work stopped.\n"
                "- tool_and_knowledge_results: concise summaries of important tool outputs or knowledge retrieval results; do not paste large raw outputs.\n"
                "- continuation_instructions: short guidance for the next turn, including what not to repeat or expose.\n\n"
                "Preserve concrete details that affect future turns. Remove greetings, jokes, repeated phrasing, and details with no future value. "
                "Do not replace specifics with vague phrases like 'goal achieved', 'task completed', or 'information found'. "
                "If a section has no useful content, write 'None'. Do not invent facts. Return only the tagged snapshot."
            )
        ),
        HumanMessage(content=_conversation_text(messages)),
    ]
    response = configured.invoke(prompt)
    content = getattr(response, "content", response)
    text = content if isinstance(content, str) else str(content)
    text = text.strip()
    if not text:
        raise RuntimeError("compression model returned empty summary")
    return text


def _conversation_text(messages: list[Any]) -> str:
    lines: list[str] = []
    for message in messages:
        role = _message_role(message)
        content = _message_text(message)
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _message_role(message: Any) -> str:
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, AIMessage):
        return "assistant"
    if isinstance(message, ToolMessage):
        return "tool"
    if isinstance(message, SystemMessage):
        return "system"
    return str(getattr(message, "type", "message"))


def _message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    return str(content)
