from __future__ import annotations

from typing import Any, Callable

from langgraph.config import get_stream_writer


KnowledgeEventSink = Callable[[dict[str, Any]], None]


KNOWLEDGE_EVENT_TYPES = {
    "knowledge_source_prepare_started",
    "knowledge_source_preview_available",
    "knowledge_source_approval_requested",
    "knowledge_source_registered",
    "knowledge_ingestion_queued",
    "knowledge_ingestion_started",
    "knowledge_ingestion_progress",
    "knowledge_ingestion_completed",
    "knowledge_ingestion_failed",
    "knowledge_ingestion_cancelled",
    "knowledge_source_ready",
    "knowledge_source_removed",
    "knowledge_source_reindex_requested",
}


def knowledge_event_payload(
    *,
    event_type: str,
    owner_type: str,
    owner_id: str,
    source_id: str | None = None,
    job_id: str | None = None,
    mode: str | None = None,
    phase: str | None = None,
    status: str | None = None,
    progress: dict[str, Any] | None = None,
    counts: dict[str, Any] | None = None,
    message: str | None = None,
    error: dict[str, Any] | None = None,
    report_path: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "protocol_version": "knowledge.v1",
        "event_type": event_type,
        "owner_type": owner_type,
        "owner_id": owner_id,
        "source_id": source_id,
        "job_id": job_id,
        "mode": mode,
        "phase": phase,
        "status": status,
        "progress": progress or {},
        "counts": counts or {},
        "message": message,
        "error": error,
        "report_path": report_path,
        **(payload or {}),
    }


def emit_knowledge_event(
    *,
    event_sink: KnowledgeEventSink | None = None,
    **payload: Any,
) -> None:
    if event_sink is not None:
        event_sink(payload)
        return
    try:
        writer = get_stream_writer()
    except Exception:
        return
    writer({"type": "knowledge_event", "payload": payload})
