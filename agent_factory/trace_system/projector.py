from __future__ import annotations

from datetime import datetime
from typing import Any

from agent_factory.trace_system.reader import TraceReader
from agent_factory.trace_system.schema import (
    TraceErrorItem,
    TraceFactRecord,
    TraceProjection,
    TraceReferenceIndexItem,
    TraceSpanNode,
    TraceTimelineItem,
)


class TraceProjector:
    """Build WebUI-friendly views from raw trace facts."""

    def __init__(self, reader: TraceReader) -> None:
        self.reader = reader

    def project(self, trace_id: str) -> TraceProjection:
        manifest = self.reader.get_manifest(trace_id)
        facts = self.reader.read_facts(trace_id)
        return TraceProjection(
            manifest=manifest,
            timeline=self.timeline_from_facts(facts),
            span_tree=self.span_tree_from_facts(facts),
            errors=self.error_index_from_facts(facts),
            references=self.reader.read_refs(trace_id),
        )

    def timeline(self, trace_id: str) -> list[TraceTimelineItem]:
        return self.timeline_from_facts(self.reader.read_facts(trace_id))

    def span_tree(self, trace_id: str) -> list[TraceSpanNode]:
        return self.span_tree_from_facts(self.reader.read_facts(trace_id))

    def error_index(self, trace_id: str) -> list[TraceErrorItem]:
        return self.error_index_from_facts(self.reader.read_facts(trace_id))

    def reference_index(self, trace_id: str) -> list[TraceReferenceIndexItem]:
        return self.reader.read_refs(trace_id)

    def timeline_from_facts(self, facts: list[TraceFactRecord]) -> list[TraceTimelineItem]:
        return [
            TraceTimelineItem(
                record_id=record.record_id,
                timestamp=record.created_at,
                item_type=record.record_type,
                event_type=record.event_type,
                node_id=record.node_id,
                span_id=record.span_id,
                parent_span_id=record.parent_span_id,
                span_kind=record.span_kind,
                status=record.status,
                message=record.message,
                summary=_summary_for_record(record),
                payload=record.payload,
            )
            for record in sorted(facts, key=lambda item: item.created_at)
        ]

    def span_tree_from_facts(self, facts: list[TraceFactRecord]) -> list[TraceSpanNode]:
        spans: dict[str, TraceSpanNode] = {}
        for record in sorted(facts, key=lambda item: item.created_at):
            if not record.span_id:
                continue
            if record.record_type == "span_started":
                spans[record.span_id] = TraceSpanNode(
                    span_id=record.span_id,
                    parent_span_id=record.parent_span_id,
                    span_kind=record.span_kind,
                    name=record.message,
                    node_id=record.node_id,
                    status=record.status or "started",
                    started_at=record.created_at,
                    start_payload=record.payload,
                )
            elif record.record_type == "span_finished":
                span = spans.get(record.span_id)
                if span is None:
                    span = TraceSpanNode(
                        span_id=record.span_id,
                        parent_span_id=record.parent_span_id,
                        span_kind=record.span_kind,
                        name=record.message,
                        node_id=record.node_id,
                    )
                    spans[record.span_id] = span
                span.status = record.status or span.status
                span.finished_at = record.created_at
                span.finish_payload = record.payload
                if span.started_at:
                    span.duration_ms = _duration_ms(span.started_at, record.created_at)
        roots: list[TraceSpanNode] = []
        for span in spans.values():
            if span.parent_span_id and span.parent_span_id in spans:
                spans[span.parent_span_id].children.append(span)
            else:
                roots.append(span)
        for span in spans.values():
            _sort_span_children(span)
        return sorted(roots, key=lambda item: item.started_at or "")

    def error_index_from_facts(self, facts: list[TraceFactRecord]) -> list[TraceErrorItem]:
        errors: list[TraceErrorItem] = []
        for record in sorted(facts, key=lambda item: item.created_at):
            if not _is_error_record(record):
                continue
            errors.append(
                TraceErrorItem(
                    record_id=record.record_id,
                    timestamp=record.created_at,
                    event_type=record.event_type,
                    node_id=record.node_id,
                    span_id=record.span_id,
                    span_kind=record.span_kind,
                    status=record.status,
                    message=record.message,
                    error_summary=_error_summary(record),
                    payload=record.payload,
                )
            )
        return errors


def _summary_for_record(record: TraceFactRecord) -> str | None:
    for key in ("summary", "observation_summary", "error", "where", "status"):
        value = record.payload.get(key)
        if value:
            return str(value)
    return record.message


def _is_error_record(record: TraceFactRecord) -> bool:
    status = str(record.status or "").lower()
    event_type = record.event_type.lower()
    if status in {"failed", "error", "invalid_arguments", "invalid_output", "execution_failed"}:
        return True
    return event_type.endswith("failed") or "error" in event_type


def _error_summary(record: TraceFactRecord) -> str | None:
    for key in ("error", "error_summary", "message", "where"):
        value = record.payload.get(key)
        if value:
            return str(value)
    return record.message or record.status


def _duration_ms(started_at: str, finished_at: str) -> int | None:
    try:
        start = _parse_datetime(started_at)
        finish = _parse_datetime(finished_at)
    except ValueError:
        return None
    return max(0, int((finish - start).total_seconds() * 1000))


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _sort_span_children(span: TraceSpanNode) -> None:
    span.children.sort(key=lambda item: item.started_at or "")
    for child in span.children:
        _sort_span_children(child)
