from __future__ import annotations

from collections import defaultdict
import json
from threading import RLock
from typing import Any
from uuid import uuid4

from agent_factory.event_persistence import is_durable_event
from agent_factory.trace_system.schema import TraceFactRecord, TraceReferenceRecord
from agent_factory.trace_system.runtime_log import RuntimeLogStore
from agent_factory.trace_system.store import JSONLTraceStore


class TraceRecorder:
    """Append-only trace writer used by RuntimeKernel and SystemPackage runtimes."""

    def __init__(
        self,
        *,
        store: JSONLTraceStore,
        package_id: str | None = None,
        producer_type: str = "agent_runtime",
        max_inline_payload_chars: int = 12000,
        runtime_log_store: RuntimeLogStore | None = None,
    ) -> None:
        self.store = store
        self.package_id = package_id
        self.producer_type = producer_type
        self.max_inline_payload_chars = max_inline_payload_chars
        self.runtime_log_store = runtime_log_store
        self._active_spans_by_run: dict[str, list[str]] = defaultdict(list)
        self._suppressed_traces: set[str] = set()
        self._trace_context: dict[str, dict[str, str]] = {}
        self._transient_event_stats: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._state_lock = RLock()
        self.last_error: str | None = None

    def ensure_trace(
        self,
        *,
        trace_id: str,
        run_id: str,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        if trace_id in self._suppressed_traces:
            return
        incoming_context = {
            key: value
            for key, value in {
                "run_id": run_id,
                "agent_id": agent_id,
                "session_id": session_id,
            }.items()
            if value
        }
        with self._state_lock:
            current_context = self._trace_context.get(trace_id, {})
            should_ensure = trace_id not in self._trace_context or any(
                key not in current_context for key in incoming_context
            )
            if not should_ensure:
                return
        ensured = self._safe(
            self.store.ensure_trace,
            trace_id=trace_id,
            run_id=run_id,
            agent_id=agent_id,
            session_id=session_id,
            package_id=self.package_id,
            producer_type=self.producer_type,
        )
        if ensured:
            with self._state_lock:
                self._trace_context[trace_id] = {**current_context, **incoming_context}

    def record_event(
        self,
        *,
        trace_id: str,
        run_id: str,
        event_type: str,
        node_id: str | None = None,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
        status: str | None = None,
    ) -> None:
        if trace_id in self._suppressed_traces:
            return
        if not is_durable_event(event_type):
            self._record_transient_event(
                trace_id=trace_id,
                run_id=run_id,
                event_type=event_type,
                payload=payload or {},
            )
            return
        self.ensure_trace(trace_id=trace_id, run_id=run_id)
        self._safe(
            self.store.append_fact,
            TraceFactRecord(
                trace_id=trace_id,
                run_id=run_id,
                record_type="event",
                event_type=event_type,
                span_id=self.current_span_id(run_id),
                node_id=node_id,
                message=self._clip_text(message),
                payload=self._clip_payload(payload or {}),
                status=status,
            ),
        )

    def start_span(
        self,
        *,
        trace_id: str,
        run_id: str,
        span_kind: str,
        name: str,
        node_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        if trace_id in self._suppressed_traces:
            return ""
        self.ensure_trace(trace_id=trace_id, run_id=run_id)
        span_id = uuid4().hex
        parent_span_id = self.current_span_id(run_id)
        self._active_spans_by_run[run_id].append(span_id)
        self._safe(
            self.store.append_fact,
            TraceFactRecord(
                trace_id=trace_id,
                run_id=run_id,
                record_type="span_started",
                event_type=f"{span_kind}.started",
                span_id=span_id,
                parent_span_id=parent_span_id,
                span_kind=span_kind,
                node_id=node_id,
                message=name,
                payload=self._clip_payload(payload or {}),
                status="started",
            ),
        )
        return span_id

    def finish_span(
        self,
        *,
        trace_id: str,
        run_id: str,
        span_id: str,
        span_kind: str,
        name: str,
        status: str,
        node_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if trace_id in self._suppressed_traces or not span_id:
            return
        stack = self._active_spans_by_run.get(run_id)
        parent_span_id = None
        if stack:
            if span_id in stack:
                index = stack.index(span_id)
                parent_span_id = stack[index - 1] if index > 0 else None
                del stack[index:]
            else:
                parent_span_id = stack[-1]
        self._safe(
            self.store.append_fact,
            TraceFactRecord(
                trace_id=trace_id,
                run_id=run_id,
                record_type="span_finished",
                event_type=f"{span_kind}.finished",
                span_id=span_id,
                parent_span_id=parent_span_id,
                span_kind=span_kind,
                node_id=node_id,
                message=name,
                payload=self._clip_payload(payload or {}),
                status=status,
            ),
        )

    def record_reference(
        self,
        *,
        trace_id: str,
        run_id: str,
        reference_type: str,
        uri: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if trace_id in self._suppressed_traces:
            return
        self._safe(
            self.store.append_reference,
            TraceReferenceRecord(
                trace_id=trace_id,
                run_id=run_id,
                span_id=self.current_span_id(run_id),
                reference_type=reference_type,
                uri=uri,
                metadata=self._clip_payload(metadata or {}),
            ),
        )

    def finish_trace(self, *, trace_id: str, status: str) -> None:
        if trace_id in self._suppressed_traces:
            return
        self._flush_transient_event_summary(trace_id)
        self._safe(self.store.finish_trace, trace_id=trace_id, status=status)
        with self._state_lock:
            context = self._trace_context.pop(trace_id, {})
            run_id = context.get("run_id")
            if run_id:
                self._active_spans_by_run.pop(run_id, None)

    def suppress_trace(
        self,
        *,
        trace_id: str,
        run_id: str,
        reason: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._suppressed_traces.add(trace_id)
        self._active_spans_by_run.pop(run_id, None)
        with self._state_lock:
            self._trace_context.pop(trace_id, None)
            self._transient_event_stats = {
                key: value
                for key, value in self._transient_event_stats.items()
                if key[0] != trace_id
            }
        self._safe(self.store.delete_trace, trace_id)
        self.record_runtime_issue(
            event_type="agent_trace_suppressed",
            payload={
                "trace_id": trace_id,
                "run_id": run_id,
                "reason": reason,
                "package_id": self.package_id,
                "producer_type": self.producer_type,
                **(payload or {}),
            },
        )

    def record_runtime_issue(self, *, event_type: str, payload: dict[str, Any]) -> None:
        if self.runtime_log_store is None:
            return
        self._safe(
            self.runtime_log_store.append,
            event_type=event_type,
            payload=self._clip_payload(payload),
        )

    def manifest_for(self, trace_id: str) -> dict[str, Any] | None:
        manifest = self.store.manifest_for(trace_id)
        return manifest.model_dump(mode="json") if manifest is not None else None

    def current_span_id(self, run_id: str) -> str | None:
        stack = self._active_spans_by_run.get(run_id)
        return stack[-1] if stack else None

    def _record_transient_event(
        self,
        *,
        trace_id: str,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        delta = payload.get("delta")
        content_chars = len(delta) if isinstance(delta, str) else 0
        stream_id = str(payload.get("stream_id") or payload.get("part_id") or "").strip()
        key = (trace_id, run_id, event_type)
        with self._state_lock:
            stats = self._transient_event_stats.setdefault(
                key,
                {
                    "event_count": 0,
                    "content_chars": 0,
                    "payload_chars": 0,
                    "stream_ids": set(),
                },
            )
            stats["event_count"] += 1
            stats["content_chars"] += content_chars
            stats["payload_chars"] += len(serialized)
            if stream_id:
                stats["stream_ids"].add(stream_id)

    def _flush_transient_event_summary(self, trace_id: str) -> None:
        with self._state_lock:
            matching = [
                (key, value)
                for key, value in self._transient_event_stats.items()
                if key[0] == trace_id
            ]
            for key, _value in matching:
                self._transient_event_stats.pop(key, None)
        summaries_by_run: dict[str, dict[str, dict[str, int]]] = defaultdict(dict)
        for (_trace_id, run_id, event_type), stats in matching:
            summaries_by_run[run_id][event_type] = {
                "event_count": int(stats["event_count"]),
                "content_chars": int(stats["content_chars"]),
                "payload_chars": int(stats["payload_chars"]),
                "stream_count": len(stats["stream_ids"]),
            }
        for run_id, event_stats in summaries_by_run.items():
            self.ensure_trace(trace_id=trace_id, run_id=run_id)
            self._safe(
                self.store.append_fact,
                TraceFactRecord(
                    trace_id=trace_id,
                    run_id=run_id,
                    record_type="diagnostic",
                    event_type="transient_event_summary",
                    span_id=self.current_span_id(run_id),
                    payload={"events": event_stats},
                    status="completed",
                ),
            )

    def _clip_payload(self, value: dict[str, Any]) -> dict[str, Any]:
        text = str(value)
        if len(text) <= self.max_inline_payload_chars:
            return value
        return {
            "truncated": True,
            "preview": text[: self.max_inline_payload_chars],
            "original_chars": len(text),
        }

    def _clip_text(self, value: str | None) -> str | None:
        if value is None or len(value) <= self.max_inline_payload_chars:
            return value
        return value[: self.max_inline_payload_chars]

    def _safe(self, fn, *args, **kwargs) -> bool:
        try:
            fn(*args, **kwargs)
            self.last_error = None
            return True
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False
