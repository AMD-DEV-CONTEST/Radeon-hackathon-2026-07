"""Pure view models for rendering heterogeneous agent results in chat."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChatResultView:
    content: str
    status: str
    session_id: str | None = None
    task_id: str | None = None
    plan: Any = None
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    visual_evidence: list[dict[str, Any]] = field(default_factory=list)
    risks: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    report_paths: list[tuple[str, str]] = field(default_factory=list)
    pending_confirmation: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _errors(result: dict[str, Any]) -> list[str]:
    errors = [str(item) for item in result.get("errors", []) if item]
    for failure in _dict_list(result.get("failures")):
        source = failure.get("source_path")
        detail = failure.get("error") or failure.get("reason")
        if detail:
            errors.append(f"{source}: {detail}" if source else str(detail))
    if result.get("status") in {"failed", "safe_failure"} and not errors:
        response = result.get("final_response")
        if response:
            errors.append(str(response))
    return errors


def _citations(result: dict[str, Any]) -> list[dict[str, Any]]:
    direct = _dict_list(result.get("citations"))
    if direct:
        return direct
    citations: list[dict[str, Any]] = []
    chunks = _dict_list(result.get("retrieved_chunks"))
    if not chunks:
        chunks = _dict_list(result.get("retrieved_evidence"))
    for chunk in chunks:
        citations.append(
            {
                "chunk_id": chunk.get("chunk_id"),
                "source": chunk.get("source_path") or chunk.get("source"),
                "article": chunk.get("article"),
                "page": chunk.get("page"),
                "content": chunk.get("content"),
            }
        )
    return citations


def _report_paths(result: dict[str, Any]) -> list[tuple[str, str]]:
    paths: list[tuple[str, str]] = []
    for key, label in (("report_path", "Markdown"), ("html_path", "HTML")):
        value = result.get(key)
        if value:
            paths.append((label, str(value)))
    pdf = result.get("pdf")
    if isinstance(pdf, dict) and pdf.get("available") and pdf.get("path"):
        paths.append(("PDF", str(pdf["path"])))
    return paths


def normalize_agent_result(result: dict[str, Any]) -> ChatResultView:
    """Map both graph-agent and deterministic MVP results to one UI shape."""
    pending = result.get("pending_confirmation")
    return ChatResultView(
        content=str(result.get("final_response") or "任务已完成，但没有文本回复。"),
        status=str(result.get("status") or "completed"),
        session_id=(str(result["session_id"]) if result.get("session_id") else None),
        task_id=(str(result["task_id"]) if result.get("task_id") else None),
        plan=result.get("plan"),
        tool_results=_dict_list(result.get("tool_results")),
        visual_evidence=_dict_list(result.get("visual_evidence")),
        risks=(
            _dict_list(result.get("risks"))
            or _dict_list(result.get("risk_results"))
        ),
        citations=_citations(result),
        errors=_errors(result),
        report_paths=_report_paths(result),
        pending_confirmation=(dict(pending) if isinstance(pending, dict) else None),
        raw=dict(result),
    )


def normalize_message(message: dict[str, Any]) -> dict[str, Any]:
    """Normalize a persisted message without trusting optional metadata fields."""
    role = str(message.get("role") or "assistant")
    if role not in {"user", "assistant"}:
        role = "assistant"
    metadata = message.get("metadata")
    return {
        "id": str(message.get("id") or ""),
        "role": role,
        "content": str(message.get("content") or ""),
        "metadata": dict(metadata) if isinstance(metadata, dict) else {},
        "created_at": str(message.get("created_at") or ""),
    }


def risk_summary(risks: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for risk in risks:
        severity = str(risk.get("severity") or "unknown").lower()
        summary[severity] = summary.get(severity, 0) + 1
    return summary
