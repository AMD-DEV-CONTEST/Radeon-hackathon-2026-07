from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from typing import Any, Callable
import uuid

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage

from agent_factory.create_agent.output_safety import looks_like_internal_observation_payload
from agent_factory.factory_graph.frontend_bridge.protocol import (
    FactoryFrontendEvent,
    FactoryFrontendEventType,
    FactoryMode,
    event,
)
from agent_factory.models.content import content_to_text, strip_internal_snapshot_blocks
from agent_factory.models.reasoning import reasoning_content_from_message
from agent_factory.runtime_render.schema import default_model_message_visible_to_user, default_node_visible_to_user


FACTORY_TOOLS_NODE = "factory_tools"
RUNTIME_TOOL_EXECUTION_NODES = {FACTORY_TOOLS_NODE, "tool_exec"}
INTERNAL_MODEL_MESSAGE_NODES = {"intent_gate"}
NODE_EVENT_TYPES: set[str] = {
    "model_cache_metrics",
    "model_call_started",
    "model_reasoning_delta",
    "model_reasoning_completed",
    "model_stream_delta",
    "model_message_completed",
}
TOOL_EVENT_INLINE_JSON_LIMIT = 6000
TOOL_EVENT_PREVIEW_CHARS = 1200
TOOL_OBSERVATION_TEXT_KEYS = frozenset(
    {
        "arguments",
        "chunk_count",
        "compressed_output",
        "content",
        "contract_status",
        "document_id",
        "errors",
        "evidence",
        "execution_status",
        "message",
        "output",
        "output_ref",
        "output_summary",
        "output_truncated",
        "results",
        "retryable",
        "status",
        "tool_call_id",
        "tool_id",
        "type",
    }
)


Emit = Callable[[FactoryFrontendEvent], None]


@dataclass(slots=True)
class ModelStreamState:
    stream_id: str
    node_id: str
    span_id: str
    parent_span_id: str | None
    content: str = ""
    reasoning_content: str = ""
    completed: bool = False


@dataclass(slots=True)
class VisibleAssistantMessage:
    content: str | None = None
    reasoning_content: str | None = None
    stream_id: str | None = None
    node_id: str | None = None


@dataclass(slots=True)
class RuntimeEventNormalizer:
    emit: Emit
    request_id: str | None
    session_id: str | None
    mode: FactoryMode
    graph_id: str
    producer_type: str = "factory_runtime"
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    sequence: int = 0
    run_span_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    stage_spans: dict[str, str] = field(default_factory=dict)
    node_spans: dict[str, str] = field(default_factory=dict)
    started_nodes: set[str] = field(default_factory=set)
    completed_nodes: set[str] = field(default_factory=set)
    model_streams: dict[str, ModelStreamState] = field(default_factory=dict)
    node_visibility: dict[str, bool] = field(default_factory=dict)
    current_stage_id: str | None = None
    pending_tool_call_ids_by_name: dict[str, list[str]] = field(default_factory=dict)
    proposed_tool_call_ids: set[str] = field(default_factory=set)
    last_plan_fingerprint: str | None = None
    default_payload: dict[str, Any] = field(default_factory=dict)
    runtime_pattern_id: str | None = None
    visible_assistant_output: VisibleAssistantMessage = field(default_factory=VisibleAssistantMessage)

    def runtime_event(
        self,
        event_type: FactoryFrontendEventType,
        *,
        node_id: str | None = None,
        node_label: str | None = None,
        node_kind: str | None = None,
        stage_id: str | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None,
        protocol_version: str | None = None,
        producer_type: str | None = None,
        thread_id: str | None = None,
        severity: str | None = None,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> FactoryFrontendEvent:
        self.sequence += 1
        event_payload = {**self.default_payload, **(payload or {})}
        item = event(
            event_type,
            request_id=self.request_id,
            protocol_version=protocol_version,
            producer_type=producer_type or self.producer_type,
            run_id=self.run_id,
            session_id=self.session_id,
            thread_id=thread_id,
            mode=self.mode,
            graph_id=self.graph_id,
            node_id=node_id,
            node_label=node_label,
            node_kind=node_kind,
            stage_id=stage_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            sequence=self.sequence,
            timestamp=datetime.now(UTC).isoformat(),
            severity=severity,
            message=message,
            payload=event_payload,
        )
        self.emit(item)
        return item

    def emit_run_started(self, payload: dict[str, Any]) -> None:
        self.runtime_event(
            "run_started",
            span_id=self.run_span_id,
            payload={"run_id": self.run_id, **payload},
        )

    def emit_run_completed(self, payload: dict[str, Any]) -> None:
        self.complete_open_model_streams(reason="run_completed")
        self.runtime_event("run_completed", span_id=self.run_span_id, payload=payload)

    def emit_run_cancelled(self, reason: str = "user_cancelled", extra_payload: dict[str, Any] | None = None) -> None:
        payload = {"status": "cancelled", "reason": reason}
        if extra_payload:
            payload.update(extra_payload)
        self.complete_open_model_streams(reason="run_cancelled")
        self.runtime_event(
            "run_cancelled",
            span_id=self.run_span_id,
            message="Runtime request was cancelled.",
            payload=payload,
        )

    def emit_run_failed(self, exc: Exception, extra_payload: dict[str, Any] | None = None) -> None:
        payload = {"where": "runtime_stream", "error_type": type(exc).__name__, "message": str(exc)}
        if extra_payload:
            payload.update(extra_payload)
        self.complete_open_model_streams(reason="run_failed")
        self.runtime_event("run_failed", span_id=self.run_span_id, message=f"{type(exc).__name__}: {exc}", payload=payload)

    def emit_update(self, node_id: str, patch: dict[str, Any]) -> None:
        stage_id = _stage_id_from_patch(patch) or self.current_stage_id
        node_span_id = self._node_span(node_id, stage_id)
        if stage_id:
            self._ensure_stage_started(stage_id)
        self.emit_plan_updates_from_chunk({node_id: patch})
        self.runtime_event(
            "debug_patch",
            node_id=node_id,
            stage_id=stage_id,
            span_id=node_span_id,
            parent_span_id=self._stage_span_or_run(stage_id),
            payload={"patch": _frontend_debug_patch(patch)},
        )
        self.emit_model_activity_from_patch(node_id, stage_id, patch)
        self._emit_tool_proposals(node_id, stage_id, node_span_id, patch)
        self._emit_tool_observations(node_id, stage_id, node_span_id, patch)
        if _patch_has_ai_message(patch) and node_id != FACTORY_TOOLS_NODE:
            if _patch_ai_message_requests_tool(patch):
                self._discard_model_stream_for_node(node_id or "model", reason="tool_call_requested")
            else:
                self._complete_model_stream_for_node(node_id or "model", reason="node_completed")

    def emit_debug_event(self, chunk: Any) -> None:
        if not isinstance(chunk, dict):
            return
        self.runtime_event(
            "debug_patch",
            span_id=self.run_span_id,
            payload={"debug": json_safe(chunk)},
        )

    def emit_custom_event(self, chunk: Any) -> None:
        if not isinstance(chunk, dict):
            return
        if chunk.get("type") == "runtime_render_event":
            self._emit_runtime_render_event(chunk.get("payload") or {})
            return
        if chunk.get("type") == "tool_activity":
            self._emit_custom_tool_activity(chunk.get("payload") or {})
            return
        if chunk.get("type") == "memory_event":
            self._emit_memory_event(chunk.get("payload") or {})
            return
        if chunk.get("type") == "scheduler_event":
            self._emit_scheduler_event(chunk.get("payload") or {})
            return
        if chunk.get("type") == "context_event":
            self._emit_context_event(chunk.get("payload") or {})
            return
        if chunk.get("type") == "knowledge_event":
            self._emit_knowledge_event(chunk.get("payload") or {})
            return
        if chunk.get("type") == "node_event":
            self._emit_node_event(chunk.get("payload") or {})
            return
        if chunk.get("type") != "model_activity":
            self.runtime_event(
                "debug_patch",
                span_id=self.run_span_id,
                payload={"custom": json_safe(chunk)},
            )
            return
        payload = chunk.get("payload")
        if not isinstance(payload, dict):
            return
        event_type = str(payload.get("event_type") or "")
        if event_type not in {"model_call_started", "model_call_completed", "model_call_failed"}:
            return
        span_id = str(payload.get("span_id") or uuid.uuid4().hex)
        self.runtime_event(
            event_type,  # type: ignore[arg-type]
            stage_id=self.current_stage_id,
            span_id=span_id,
            parent_span_id=self.run_span_id,
            payload={key: value for key, value in json_safe(payload).items() if key not in {"event_type", "span_id"}},
        )

    def emit_stream_item(self, stream_mode: str, chunk: Any, *, updates_payload_key: str) -> bool:
        if stream_mode == "messages":
            self.emit_model_message_stream_item(chunk)
            return True
        if stream_mode == "debug":
            self.emit_debug_event(json_safe(chunk))
            return True
        if stream_mode == "custom":
            self.emit_custom_event(json_safe(chunk))
            return True
        if stream_mode == "updates":
            self.emit_plan_updates_from_chunk(chunk)
            self.runtime_event(
                "debug_patch",
                span_id=self.run_span_id,
                payload={updates_payload_key: json_safe(chunk)},
            )
            return True
        return False

    def _emit_subsystem_event(
        self,
        payload: Any,
        allowed_event_types: set[str],
        include_node_id: bool = False,
        auto_severity: bool = True,
    ) -> None:
        """通用的子系统事件发射器，统一处理 memory/context/scheduler/knowledge 等事件"""
        if not isinstance(payload, dict):
            return
        event_type = str(payload.get("event_type") or "")
        if event_type not in allowed_event_types:
            return

        kwargs: dict[str, Any] = {
            "stage_id": self.current_stage_id,
            "span_id": uuid.uuid4().hex,
            "parent_span_id": self.run_span_id,
            "payload": {key: value for key, value in json_safe(payload).items() if key != "event_type"},
        }

        if include_node_id:
            kwargs["node_id"] = _optional_str(payload.get("node_id"))

        if auto_severity and event_type.endswith("failed"):
            kwargs["severity"] = "error"

        self.runtime_event(event_type, **kwargs)  # type: ignore[arg-type]

    def _emit_memory_event(self, payload: Any) -> None:
        self._emit_subsystem_event(
            payload,
            allowed_event_types={
                "memory_write_queued",
                "memory_write_queued_failed",
                "memory_segment_prepared",
                "memory_extraction_completed",
                "memory_write_completed",
                "memory_write_failed",
                "memory_retrieval_completed",
                "memory_injection_completed",
            },
        )

    def _emit_context_event(self, payload: Any) -> None:
        self._emit_subsystem_event(
            payload,
            allowed_event_types={
                "context_prepare_started",
                "context_prepare_completed",
                "context_prepare_failed",
                "context_compression_started",
                "context_compression_completed",
                "context_compression_failed",
                "context_compression_skipped",
                "context_window_updated",
                "context_retrieval_completed",
                "context_assembly_completed",
                "context_injection_completed",
            },
            include_node_id=True,
        )

    def _emit_scheduler_event(self, payload: Any) -> None:
        self._emit_subsystem_event(
            payload,
            allowed_event_types={
                "scheduler_job_created",
                "scheduler_job_updated",
                "scheduler_job_deleted",
                "scheduler_job_auto_paused",
                "scheduler_jobs_listed",
                "scheduler_options_listed",
                "scheduler_job_described",
                "scheduler_runs_listed",
                "scheduler_run_scheduled",
                "scheduler_run_started",
                "scheduler_run_completed",
                "scheduler_run_failed",
                "scheduler_run_skipped",
                "scheduler_run_cancelled",
                "scheduler_feedback_completed",
                "scheduler_feedback_failed",
                "scheduler_seed_detected",
                "scheduler_seed_applied",
                "scheduler_seed_unchanged",
                "scheduler_seed_failed",
            },
        )

    def _emit_knowledge_event(self, payload: Any) -> None:
        self._emit_subsystem_event(
            payload,
            allowed_event_types={
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
                "knowledge_sources_listed",
                "knowledge_documents_listed",
                "knowledge_search_completed",
                "knowledge_document_read",
            },
        )

    def _emit_node_event(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        event_type = str(payload.get("event_type") or "")
        if event_type not in NODE_EVENT_TYPES:
            return
        event_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        node_id = _optional_str(payload.get("node_id"))
        frontend_payload = {key: value for key, value in json_safe(event_payload).items() if key != "event_type"}
        if event_type in {
            "model_call_started",
            "model_reasoning_delta",
            "model_reasoning_completed",
            "model_stream_delta",
            "model_message_completed",
        }:
            frontend_payload.setdefault("visible_to_user", self._model_message_visible_to_user(node_id))
            frontend_payload = _with_model_message_part_payload(event_type, frontend_payload)
            self._record_model_stream_event(event_type, node_id=node_id, payload=frontend_payload)
        self.runtime_event(
            event_type,  # type: ignore[arg-type]
            node_id=node_id,
            stage_id=self.current_stage_id,
            span_id=uuid.uuid4().hex,
            parent_span_id=self._stage_span_or_run(self.current_stage_id),
            severity="error" if event_type.endswith("failed") else None,
            message=_optional_str(payload.get("message")),
            payload=frontend_payload,
        )
        if event_type in {
            "model_reasoning_delta",
            "model_reasoning_completed",
            "model_stream_delta",
            "model_message_completed",
        }:
            stream_id = str(frontend_payload.get("stream_id") or "").strip()
            stream = self.model_streams.get(stream_id)
            if stream is not None:
                self._emit_message_event_from_model_event(event_type, stream=stream, payload=frontend_payload)

    def _emit_runtime_render_event(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        event_type = str(payload.get("event_type") or "")
        if event_type not in {"node_started", "node_progress", "node_completed", "node_failed"}:
            return
        node_id = str(payload.get("node_id") or "")
        if not node_id:
            return
        stage_id = str(payload.get("stage_id") or "") or self.current_stage_id
        span_id = self._node_span(node_id, stage_id)
        if stage_id:
            self._ensure_stage_started(stage_id)
        if event_type == "node_started":
            self.started_nodes.add(node_id)
        if event_type in {"node_completed", "node_failed"}:
            self.started_nodes.add(node_id)
            self.completed_nodes.add(node_id)
        source_graph_id = _optional_str(payload.get("graph_id"))
        if source_graph_id:
            self.runtime_pattern_id = source_graph_id
        source_protocol_version = _optional_str(payload.get("protocol_version"))
        render_payload = dict(payload.get("payload") or {})
        if "visible_to_user" in render_payload:
            visible_to_user = bool(render_payload.get("visible_to_user"))
            self.node_visibility[node_id] = visible_to_user
            if not visible_to_user and not self._model_message_visible_to_user(node_id):
                self._discard_model_stream_for_node(node_id, reason="node_hidden")
        if source_protocol_version:
            render_payload["source_protocol_version"] = source_protocol_version
        self.runtime_event(
            event_type,  # type: ignore[arg-type]
            node_id=node_id,
            node_label=_optional_str(payload.get("node_label")),
            node_kind=_optional_str(payload.get("node_kind")),
            stage_id=stage_id or None,
            span_id=span_id,
            parent_span_id=self._stage_span_or_run(stage_id or None),
            producer_type=_optional_str(payload.get("producer_type")),
            thread_id=_optional_str(payload.get("thread_id")),
            severity=_optional_str(payload.get("severity")),
            message=_optional_str(payload.get("message")),
            payload=render_payload,
        )
        if stage_id and event_type == "node_completed":
            self.runtime_event(
                "stage_completed",
                node_id=node_id,
                stage_id=stage_id,
                span_id=self._stage_span_or_run(stage_id),
                parent_span_id=self.run_span_id,
                payload={"stage_id": stage_id, "node_id": node_id, **render_payload},
            )
        elif stage_id and event_type == "node_failed":
            self.runtime_event(
                "stage_failed",
                node_id=node_id,
                stage_id=stage_id,
                span_id=self._stage_span_or_run(stage_id),
                parent_span_id=self.run_span_id,
                payload={"stage_id": stage_id, "node_id": node_id, **render_payload},
            )

    def _emit_custom_tool_activity(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        events = payload.get("events") or []
        if not isinstance(events, list):
            return
        for item in events:
            if not isinstance(item, dict):
                continue
            event_type = _canonical_tool_event_type(str(item.get("event_type") or ""))
            if event_type not in {
                "tool_call_proposed",
                "tool_call_started",
                "tool_call_output_delta",
                "tool_call_completed",
                "tool_contract_invalid",
                "tool_call_failed",
                "tool_observation_available",
            }:
                continue
            item_payload = _compact_tool_activity_payload(
                {key: value for key, value in json_safe(item).items() if key != "event_type"}
            )
            if event_type == "tool_call_proposed" and not self._remember_tool_proposal(item_payload):
                continue
            tool_span_id = uuid.uuid4().hex
            self.runtime_event(
                event_type,  # type: ignore[arg-type]
                node_id=str(item.get("node_id") or self.current_stage_id or ""),
                stage_id=self.current_stage_id,
                span_id=tool_span_id,
                parent_span_id=self._stage_span_or_run(self.current_stage_id),
                payload=item_payload,
            )

    def emit_model_activity_from_patch(self, node_id: str, stage_id: str | None, patch: dict[str, Any]) -> None:
        for item in patch.get("model_activity", []) or []:
            if not isinstance(item, dict):
                continue
            event_type = str(item.get("event_type") or "")
            if event_type not in {"model_call_started", "model_call_completed", "model_call_failed"}:
                continue
            span_id = str(item.get("span_id") or uuid.uuid4().hex)
            payload = {key: value for key, value in item.items() if key not in {"event_type", "span_id"}}
            self.runtime_event(
                event_type,  # type: ignore[arg-type]
                node_id=node_id,
                stage_id=stage_id,
                span_id=span_id,
                parent_span_id=self._node_span(node_id, stage_id),
                payload=payload,
            )

    def emit_plan_updates_from_chunk(self, chunk: Any) -> None:
        for node_id, patch in _iter_update_patches(chunk):
            plan = _plan_from_update_patch(patch)
            if plan is None:
                continue
            if _plan_is_empty(plan):
                continue
            fingerprint = _json_text(plan)
            if fingerprint == self.last_plan_fingerprint:
                continue
            self.last_plan_fingerprint = fingerprint
            stage_id = _stage_id_from_patch(patch) or self.current_stage_id
            if stage_id:
                self._ensure_stage_started(stage_id)
            source_node_id = node_id or _source_node_id_from_patch(patch) or "runtime_plan"
            node_span_id = self._node_span(source_node_id, stage_id)
            payload = dict(plan)
            payload["source_node_id"] = source_node_id
            self.runtime_event(
                "plan_updated",
                node_id=source_node_id,
                stage_id=stage_id,
                span_id=node_span_id,
                parent_span_id=self._stage_span_or_run(stage_id),
                payload=payload,
            )

    def emit_interrupt(self, payload: Any) -> None:
        self.complete_open_model_streams(reason="runtime_paused")
        safe_payload = payload if isinstance(payload, dict) else {"value": payload}
        interrupt_type = safe_payload.get("type") if isinstance(safe_payload, dict) else None
        interrupt_span_id = uuid.uuid4().hex
        if interrupt_type == "tool_approval":
            requests = safe_payload.get("requests", []) or []
            normalized_requests = [self._normalize_approval_request(request) for request in requests]
            safe_payload = {**safe_payload, "requests": normalized_requests}
            for request in normalized_requests:
                if not self._remember_tool_proposal(request):
                    continue
                tool_span_id = uuid.uuid4().hex
                self.runtime_event(
                    "tool_call_proposed",
                    span_id=tool_span_id,
                    parent_span_id=self.run_span_id,
                    payload=request,
                )
            self.runtime_event(
                "runtime_paused",
                span_id=self.run_span_id,
                payload={"reason": "tool_approval"},
            )
            self.runtime_event(
                "tool_approval_requested",
                span_id=interrupt_span_id,
                parent_span_id=self.run_span_id,
                payload=safe_payload,
            )
            return
        self.runtime_event(
            "interrupt_requested",
            span_id=interrupt_span_id,
            parent_span_id=self.run_span_id,
            payload=safe_payload,
        )
        self.runtime_event(
            "runtime_paused",
            span_id=self.run_span_id,
            payload={"reason": interrupt_type or "interrupt"},
        )

    def emit_runtime_resumed(self, payload: dict[str, Any]) -> None:
        if _is_tool_approval_resume_payload(payload):
            self.runtime_event("tool_approval_resolved", span_id=self.run_span_id, payload=payload)
        self.runtime_event("runtime_resumed", span_id=self.run_span_id, payload=payload)

    def emit_model_message_stream_item(self, chunk: Any) -> None:
        message, metadata = _message_stream_parts(chunk)
        if not isinstance(message, (AIMessage, AIMessageChunk)):
            return
        node_id = _message_stream_node_id(metadata)
        stream_id = _message_stream_id(
            message=message,
            metadata=metadata,
            node_id=node_id,
            request_id=self.request_id,
        )
        stream = self._ensure_model_stream_started(stream_id=stream_id, node_id=node_id)
        reasoning_content = reasoning_content_from_message(message)
        if reasoning_content and isinstance(message, AIMessageChunk):
            self._emit_recorded_model_event(
                "model_reasoning_delta",
                stream=stream,
                payload={
                    **_message_part_payload(stream.stream_id, "reasoning", status="streaming"),
                    "delta": reasoning_content,
                    "content_mode": "delta",
                },
            )
        content = strip_internal_snapshot_blocks(content_to_text(getattr(message, "content", "")))
        if _looks_like_tool_observation_text(content):
            content = ""
        if isinstance(message, AIMessageChunk):
            if content:
                self._emit_recorded_model_event(
                    "model_stream_delta",
                    stream=stream,
                    payload={
                        **_message_part_payload(stream.stream_id, "text", status="streaming"),
                        "delta": content,
                        "content_mode": "delta",
                    },
                )
            return
        self._emit_recorded_model_event(
            "model_message_completed",
            stream=stream,
            payload={
                **_message_part_payload(stream.stream_id, "text", status="completed"),
                "content": content,
                "content_mode": "snapshot",
                "completion_reason": "message_stream_completed",
                **({"reasoning_content": reasoning_content} if reasoning_content else {}),
            },
        )

    def complete_open_model_streams(self, *, reason: str) -> None:
        for stream in list(self.model_streams.values()):
            self._complete_model_stream(stream, reason=reason)

    def complete_visible_assistant_output_from_state(self, final_state: Any, *, reason: str) -> VisibleAssistantMessage:
        self.complete_open_model_streams(reason=reason)
        self._fill_visible_assistant_output_from_state(final_state, reason=reason)
        return self.visible_assistant_output

    def complete_visible_assistant_output_from_text(
        self,
        text: str,
        *,
        node_id: str,
        reason: str,
    ) -> VisibleAssistantMessage:
        self.complete_open_model_streams(reason=reason)
        self._fill_visible_assistant_output_from_text(text, node_id=node_id, reason=reason)
        return self.visible_assistant_output

    def _fill_visible_assistant_output_from_state(self, final_state: Any, *, reason: str) -> None:
        conversation = getattr(final_state, "conversation", None)
        text = str(
            getattr(conversation, "final_answer", None)
            or getattr(conversation, "assistant_draft", None)
            or ""
        ).strip()
        node_id = _optional_str(getattr(getattr(final_state, "execution", None), "current_node", None)) or "final_answer"
        self._fill_visible_assistant_output_from_text(text, node_id=node_id, reason=reason)

    def _fill_visible_assistant_output_from_text(self, text: str, *, node_id: str, reason: str) -> None:
        text = strip_internal_snapshot_blocks(text)
        if not text:
            return
        if _looks_like_tool_observation_text(text):
            return
        if self.visible_assistant_output.content:
            return
        stream_id = uuid.uuid4().hex
        payload = {
            **_message_part_payload(stream_id, "text", status="completed"),
            "stream_id": stream_id,
            "content": text,
            "content_mode": "snapshot",
            "completion_reason": reason,
            "completion_inferred": True,
            "visible_to_user": self._model_message_visible_to_user(node_id),
        }
        if payload["visible_to_user"]:
            self.runtime_event(
                "message_started",
                node_id=node_id,
                stage_id=self.current_stage_id,
                span_id=uuid.uuid4().hex,
                parent_span_id=self._node_span(node_id, self.current_stage_id),
                payload={
                    "message_id": stream_id,
                    "stream_id": stream_id,
                    "role": "assistant",
                    "status": "streaming",
                },
            )
        self._record_model_stream_event("model_message_completed", node_id=node_id, payload=payload)
        self.runtime_event(
            "model_message_completed",
            node_id=node_id,
            stage_id=self.current_stage_id,
            span_id=uuid.uuid4().hex,
            parent_span_id=self._node_span(node_id, self.current_stage_id),
            payload=payload,
        )
        self._emit_message_event_from_model_event(
            "model_message_completed",
            stream=self.model_streams[stream_id],
            payload=payload,
        )

    def _complete_model_stream_for_node(self, node_id: str, *, reason: str) -> None:
        for stream in list(self.model_streams.values()):
            if stream.node_id == node_id:
                self._complete_model_stream(stream, reason=reason)

    def _discard_model_stream_for_node(self, node_id: str, *, reason: str) -> None:
        for stream in list(self.model_streams.values()):
            if stream.node_id != node_id or stream.completed:
                continue
            stream.completed = True
            stream.content = ""
            stream.reasoning_content = ""
            self._forget_visible_assistant_output_for_stream(stream)
            self.runtime_event(
                "model_message_completed",
                node_id=stream.node_id,
                stage_id=self.current_stage_id,
                span_id=stream.span_id,
                parent_span_id=stream.parent_span_id,
                payload={
                    "stream_id": stream.stream_id,
                    "content": "",
                    "content_mode": "discard",
                    "completion_reason": reason,
                    "completion_inferred": True,
                    "discard": True,
                    "visible_to_user": False,
                },
            )

    def _ensure_model_stream_started(self, *, stream_id: str, node_id: str) -> ModelStreamState:
        stream = self.model_streams.get(stream_id)
        if stream is not None:
            return stream
        stream = ModelStreamState(
            stream_id=stream_id,
            node_id=node_id,
            span_id=uuid.uuid4().hex,
            parent_span_id=self._node_span(node_id, self.current_stage_id),
        )
        self.model_streams[stream_id] = stream
        self.runtime_event(
            "model_call_started",
            node_id=node_id,
            stage_id=self.current_stage_id,
            span_id=stream.span_id,
            parent_span_id=stream.parent_span_id,
            payload={
                "stream_id": stream.stream_id,
                "operation": "langgraph_message_stream",
                "visible_to_user": self._model_message_visible_to_user(node_id),
            },
        )
        if self._model_message_visible_to_user(node_id):
            self.runtime_event(
                "message_started",
                node_id=node_id,
                stage_id=self.current_stage_id,
                span_id=stream.span_id,
                parent_span_id=stream.parent_span_id,
                payload={
                    "message_id": stream.stream_id,
                    "stream_id": stream.stream_id,
                    "role": "assistant",
                    "status": "streaming",
                },
            )
        return stream

    def _emit_recorded_model_event(
        self,
        event_type: FactoryFrontendEventType,
        *,
        stream: ModelStreamState,
        payload: dict[str, Any],
    ) -> None:
        event_payload = {
            "stream_id": stream.stream_id,
            "visible_to_user": self._model_message_visible_to_user(stream.node_id),
            **payload,
        }
        self._record_model_stream_event(event_type, node_id=stream.node_id, payload=event_payload)
        self.runtime_event(
            event_type,
            node_id=stream.node_id,
            stage_id=self.current_stage_id,
            span_id=stream.span_id,
            parent_span_id=stream.parent_span_id,
            payload=event_payload,
        )
        self._emit_message_event_from_model_event(event_type, stream=stream, payload=event_payload)

    def _emit_message_event_from_model_event(
        self,
        event_type: str,
        *,
        stream: ModelStreamState,
        payload: dict[str, Any],
    ) -> None:
        if payload.get("visible_to_user") is False:
            return
        if not self._model_message_visible_to_user(stream.node_id):
            return
        part_type = str(payload.get("part_type") or "")
        part_id = str(payload.get("part_id") or "")
        message_id = str(payload.get("message_id") or stream.stream_id)
        if not part_type or not part_id or not message_id:
            return
        if event_type in {"model_reasoning_delta", "model_stream_delta"}:
            self.runtime_event(
                "message_part_delta",
                node_id=stream.node_id,
                stage_id=self.current_stage_id,
                span_id=stream.span_id,
                parent_span_id=stream.parent_span_id,
                payload={
                    "message_id": message_id,
                    "stream_id": stream.stream_id,
                    "part_id": part_id,
                    "part_type": part_type,
                    "part_status": "streaming",
                    "format": "markdown",
                    "delta": str(payload.get("delta") or ""),
                },
            )
            return
        if event_type == "model_reasoning_completed":
            content = str(payload.get("content") or payload.get("reasoning_content") or "")
            self.runtime_event(
                "message_part_completed",
                node_id=stream.node_id,
                stage_id=self.current_stage_id,
                span_id=stream.span_id,
                parent_span_id=stream.parent_span_id,
                payload={
                    "message_id": message_id,
                    "stream_id": stream.stream_id,
                    "part_id": part_id,
                    "part_type": "reasoning",
                    "part_status": "completed",
                    "content": content,
                },
            )
            return
        if event_type == "model_message_completed":
            content = str(payload.get("content") or "")
            reasoning_content = str(payload.get("reasoning_content") or stream.reasoning_content or "")
            if not content and not reasoning_content.strip():
                return
            if reasoning_content.strip():
                reasoning_part = _message_part_payload(stream.stream_id, "reasoning", status="completed")
                self.runtime_event(
                    "message_part_completed",
                    node_id=stream.node_id,
                    stage_id=self.current_stage_id,
                    span_id=stream.span_id,
                    parent_span_id=stream.parent_span_id,
                    payload={
                        "message_id": message_id,
                        "stream_id": stream.stream_id,
                        "part_id": reasoning_part["part_id"],
                        "part_type": "reasoning",
                        "part_status": "completed",
                        "content": reasoning_content,
                    },
                )
            if content:
                self.runtime_event(
                    "message_part_completed",
                    node_id=stream.node_id,
                    stage_id=self.current_stage_id,
                    span_id=stream.span_id,
                    parent_span_id=stream.parent_span_id,
                    payload={
                        "message_id": message_id,
                        "stream_id": stream.stream_id,
                        "part_id": part_id,
                        "part_type": "text",
                        "part_status": "completed",
                        "format": "markdown",
                        "content": content,
                    },
                )
            self.runtime_event(
                "message_completed",
                node_id=stream.node_id,
                stage_id=self.current_stage_id,
                span_id=stream.span_id,
                parent_span_id=stream.parent_span_id,
                payload={
                    "message_id": message_id,
                    "stream_id": stream.stream_id,
                    "status": "completed",
                    "completion_reason": payload.get("completion_reason"),
                },
            )

    def _complete_model_stream(self, stream: ModelStreamState, *, reason: str) -> None:
        if stream.completed:
            return
        if stream.node_id in RUNTIME_TOOL_EXECUTION_NODES or _looks_like_tool_observation_text(stream.content):
            stream.completed = True
            return
        stream.completed = True
        if stream.reasoning_content.strip():
            reasoning_payload = {
                **_message_part_payload(stream.stream_id, "reasoning", status="completed"),
                "stream_id": stream.stream_id,
                "content": stream.reasoning_content,
                "content_mode": "snapshot",
                "completion_reason": reason,
                "completion_inferred": True,
                "visible_to_user": self._model_message_visible_to_user(stream.node_id),
            }
            self._record_model_stream_event(
                "model_reasoning_completed",
                node_id=stream.node_id,
                payload=reasoning_payload,
            )
            self.runtime_event(
                "model_reasoning_completed",
                node_id=stream.node_id,
                stage_id=self.current_stage_id,
                span_id=stream.span_id,
                parent_span_id=stream.parent_span_id,
                payload=reasoning_payload,
            )
            self._emit_message_event_from_model_event(
                "model_reasoning_completed",
                stream=stream,
                payload=reasoning_payload,
            )
        message_payload = {
            **_message_part_payload(stream.stream_id, "text", status="completed"),
            "stream_id": stream.stream_id,
            "content": stream.content,
            "content_mode": "snapshot",
            "completion_reason": reason,
            "completion_inferred": True,
            "visible_to_user": self._model_message_visible_to_user(stream.node_id),
            **({"reasoning_content": stream.reasoning_content} if stream.reasoning_content.strip() else {}),
        }
        self._record_model_stream_event("model_message_completed", node_id=stream.node_id, payload=message_payload)
        self.runtime_event(
            "model_message_completed",
            node_id=stream.node_id,
            stage_id=self.current_stage_id,
            span_id=stream.span_id,
            parent_span_id=stream.parent_span_id,
            payload=message_payload,
        )
        self._emit_message_event_from_model_event(
            "model_message_completed",
            stream=stream,
            payload=message_payload,
        )

    def _node_visible_to_user(self, node_id: str | None) -> bool:
        if not node_id:
            return True
        if node_id in INTERNAL_MODEL_MESSAGE_NODES:
            return False
        if node_id in self.node_visibility:
            return self.node_visibility[node_id]
        if self.runtime_pattern_id:
            return default_node_visible_to_user(pattern_id=self.runtime_pattern_id, node_id=node_id)
        return True

    def _model_message_visible_to_user(self, node_id: str | None) -> bool:
        if not node_id:
            return True
        if node_id in INTERNAL_MODEL_MESSAGE_NODES or node_id in RUNTIME_TOOL_EXECUTION_NODES:
            return False
        if self.runtime_pattern_id:
            return default_model_message_visible_to_user(pattern_id=self.runtime_pattern_id, node_id=node_id)
        return True

    def _record_model_stream_event(self, event_type: str, *, node_id: str | None, payload: dict[str, Any]) -> None:
        stream_id = str(payload.get("stream_id") or "").strip()
        if not stream_id:
            return
        stream = self.model_streams.get(stream_id)
        if stream is None:
            stream = ModelStreamState(
                stream_id=stream_id,
                node_id=node_id or "model",
                span_id=uuid.uuid4().hex,
                parent_span_id=self._node_span(node_id or "model", self.current_stage_id),
            )
            self.model_streams[stream_id] = stream
        if event_type == "model_reasoning_delta":
            stream.reasoning_content += str(payload.get("delta") or "")
        elif event_type == "model_reasoning_completed":
            content = payload.get("content")
            if isinstance(content, str):
                stream.reasoning_content = content
        elif event_type == "model_stream_delta":
            stream.content += str(payload.get("delta") or "")
        elif event_type == "model_message_completed":
            content = payload.get("content")
            if isinstance(content, str):
                stream.content = content
            reasoning_content = payload.get("reasoning_content")
            if isinstance(reasoning_content, str):
                stream.reasoning_content = reasoning_content
            stream.completed = True
        if payload.get("discard") or payload.get("visible_to_user") is False:
            self._forget_visible_assistant_output_for_stream(stream)
        self._remember_visible_assistant_output(event_type, node_id=node_id, payload=payload, stream=stream)

    def _forget_visible_assistant_output_for_stream(self, stream: ModelStreamState) -> None:
        if self.visible_assistant_output.stream_id != stream.stream_id:
            return
        self.visible_assistant_output = VisibleAssistantMessage()

    def _remember_visible_assistant_output(
        self,
        event_type: str,
        *,
        node_id: str | None,
        payload: dict[str, Any],
        stream: ModelStreamState,
    ) -> None:
        if payload.get("visible_to_user") is False:
            return
        if not self._model_message_visible_to_user(node_id or stream.node_id):
            return
        if event_type == "model_reasoning_completed":
            content = str(payload.get("content") or payload.get("reasoning_content") or "").strip()
            if content:
                self.visible_assistant_output.reasoning_content = content
                self.visible_assistant_output.stream_id = stream.stream_id
                self.visible_assistant_output.node_id = node_id or stream.node_id
            return
        if event_type != "model_message_completed":
            return
        content = str(payload.get("content") or "").strip()
        if not content:
            return
        self.visible_assistant_output.content = content
        reasoning_content = str(payload.get("reasoning_content") or stream.reasoning_content or "").strip()
        self.visible_assistant_output.reasoning_content = reasoning_content or None
        self.visible_assistant_output.stream_id = stream.stream_id
        self.visible_assistant_output.node_id = node_id or stream.node_id

    def _normalize_approval_request(self, request: Any) -> dict[str, Any]:
        if not isinstance(request, dict):
            return {"summary": str(request)}
        normalized = dict(request)
        if normalized.get("tool_call_id"):
            return normalized
        tool_name = str(normalized.get("tool_name") or normalized.get("tool_id") or normalized.get("name") or "").strip()
        tool_call_id = self._pop_pending_tool_call_id(tool_name)
        if tool_call_id:
            normalized["tool_call_id"] = tool_call_id
        return normalized

    def _pop_pending_tool_call_id(self, tool_name: str) -> str | None:
        if not tool_name:
            return None
        pending = self.pending_tool_call_ids_by_name.get(tool_name) or []
        if not pending:
            return None
        tool_call_id = pending.pop(0)
        if pending:
            self.pending_tool_call_ids_by_name[tool_name] = pending
        else:
            self.pending_tool_call_ids_by_name.pop(tool_name, None)
        return tool_call_id

    def _remember_tool_proposal(self, payload: dict[str, Any]) -> bool:
        tool_call_id = str(payload.get("tool_call_id") or "").strip()
        tool_name = str(payload.get("tool_name") or payload.get("tool_id") or payload.get("name") or "").strip()
        if tool_call_id:
            if tool_call_id in self.proposed_tool_call_ids:
                return False
            self.proposed_tool_call_ids.add(tool_call_id)
        if tool_call_id and tool_name:
            pending = self.pending_tool_call_ids_by_name.setdefault(tool_name, [])
            if tool_call_id not in pending:
                pending.append(tool_call_id)
        return True

    def _ensure_stage_started(self, stage_id: str) -> str:
        self.current_stage_id = stage_id
        if stage_id not in self.stage_spans:
            span_id = uuid.uuid4().hex
            self.stage_spans[stage_id] = span_id
            self.runtime_event(
                "stage_started",
                stage_id=stage_id,
                span_id=span_id,
                parent_span_id=self.run_span_id,
                payload={"stage_id": stage_id},
            )
        return self.stage_spans[stage_id]

    def _node_span(self, node_id: str, stage_id: str | None) -> str:
        key = node_id
        if key not in self.node_spans:
            self.node_spans[key] = uuid.uuid4().hex
        return self.node_spans[key]

    def _emit_node_started(self, node_id: str, stage_id: str | None, payload: dict[str, Any]) -> None:
        if node_id in self.started_nodes:
            return
        self.started_nodes.add(node_id)
        self.runtime_event(
            "node_started",
            node_id=node_id,
            stage_id=stage_id,
            span_id=self._node_span(node_id, stage_id),
            parent_span_id=self._stage_span_or_run(stage_id),
            payload=payload,
        )

    def _emit_node_completed(self, node_id: str, stage_id: str | None, payload: dict[str, Any]) -> None:
        if node_id in self.completed_nodes:
            return
        self.completed_nodes.add(node_id)
        self.runtime_event(
            "node_completed",
            node_id=node_id,
            stage_id=stage_id,
            span_id=self._node_span(node_id, stage_id),
            parent_span_id=self._stage_span_or_run(stage_id),
            payload=payload,
        )

    def _emit_node_failed(self, node_id: str, stage_id: str | None, payload: dict[str, Any]) -> None:
        if node_id in self.completed_nodes:
            return
        self.started_nodes.add(node_id)
        self.completed_nodes.add(node_id)
        self.runtime_event(
            "node_failed",
            node_id=node_id,
            stage_id=stage_id,
            span_id=self._node_span(node_id, stage_id),
            parent_span_id=self._stage_span_or_run(stage_id),
            payload=payload,
        )

    def _stage_span_or_run(self, stage_id: str | None) -> str:
        if not stage_id:
            return self.run_span_id
        return self.stage_spans.get(stage_id) or self._ensure_stage_started(stage_id)

    def _emit_tool_observations(self, node_id: str, stage_id: str | None, parent_span_id: str, patch: dict[str, Any]) -> None:
        for message in patch.get("messages", []) or []:
            if message.get("type") != "ToolMessage":
                continue
            tool_span_id = uuid.uuid4().hex
            event_type = _tool_message_event_type(message)
            payload = _frontend_tool_message_event_payload(message)
            self.runtime_event(
                event_type,
                node_id=node_id,
                stage_id=stage_id,
                span_id=tool_span_id,
                parent_span_id=parent_span_id,
                payload=payload,
            )
            self.runtime_event(
                "tool_observation_available",
                node_id=node_id,
                stage_id=stage_id,
                span_id=tool_span_id,
                parent_span_id=parent_span_id,
                payload=payload,
            )
        resource_plan = patch.get("resource_condition_plan") or {}
        for item in resource_plan.get("check_results", []) or []:
            tool_span_id = uuid.uuid4().hex
            payload = {"resource_check": item}
            self.runtime_event(
                "tool_call_completed",
                node_id=node_id,
                stage_id=stage_id,
                span_id=tool_span_id,
                parent_span_id=parent_span_id,
                payload=payload,
            )

    def _emit_tool_proposals(self, node_id: str, stage_id: str | None, parent_span_id: str, patch: dict[str, Any]) -> None:
        for message in patch.get("messages", []) or []:
            if message.get("type") != "AIMessage":
                continue
            for tool_call in message.get("tool_calls", []) or []:
                if not isinstance(tool_call, dict):
                    continue
                tool_span_id = uuid.uuid4().hex
                payload = {
                    "tool_call_id": tool_call.get("id"),
                    "tool_name": tool_call.get("name"),
                    "arguments": tool_call.get("args") or {},
                    "source": "ai_tool_call",
                }
                if not self._remember_tool_proposal(payload):
                    continue
                self.runtime_event(
                    "tool_call_proposed",
                    node_id=node_id,
                    stage_id=stage_id,
                    span_id=tool_span_id,
                    parent_span_id=parent_span_id,
                    payload=payload,
                )


def _stage_id_from_patch(patch: dict[str, Any]) -> str | None:
    return None


def _iter_update_patches(chunk: Any) -> list[tuple[str, dict[str, Any]]]:
    safe_chunk = json_safe(chunk)
    if not isinstance(safe_chunk, dict):
        return []
    if _plan_from_update_patch(safe_chunk) is not None:
        return [(_source_node_id_from_patch(safe_chunk) or "", safe_chunk)]
    patches: list[tuple[str, dict[str, Any]]] = []
    for node_id, patch in safe_chunk.items():
        if not isinstance(patch, dict):
            continue
        patches.append((str(node_id), patch))
    return patches


def _plan_from_update_patch(patch: dict[str, Any]) -> dict[str, Any] | None:
    plan = patch.get("plan")
    if isinstance(plan, dict):
        return plan
    runtime = patch.get("runtime")
    if not isinstance(runtime, dict):
        return None
    runtime_plan = runtime.get("plan")
    if isinstance(runtime_plan, dict):
        return runtime_plan
    return None


def _plan_is_empty(plan: dict[str, Any]) -> bool:
    return str(plan.get("status") or "empty") == "empty" and not plan.get("steps")


def _source_node_id_from_patch(patch: dict[str, Any]) -> str | None:
    runtime = patch.get("runtime")
    if not isinstance(runtime, dict):
        return None
    execution = runtime.get("execution")
    if not isinstance(execution, dict):
        return None
    return _optional_str(execution.get("current_node"))


def _canonical_tool_event_type(event_type: str) -> str:
    return {
        "tool_proposed": "tool_call_proposed",
        "tool_started": "tool_call_started",
        "tool_output_delta": "tool_call_output_delta",
        "tool_completed": "tool_call_completed",
        "tool_contract_invalid": "tool_contract_invalid",
        "tool_failed": "tool_call_failed",
    }.get(event_type, event_type)


def _tool_message_event_type(message: dict[str, Any]) -> FactoryFrontendEventType:
    content = message.get("content")
    if isinstance(content, str):
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            payload = {}
        if (
            isinstance(payload, dict)
            and payload.get("execution_status") == "completed"
            and payload.get("contract_status") == "invalid"
        ):
            return "tool_contract_invalid"
    if str(message.get("status") or "") == "error":
        return "tool_call_failed"
    return "tool_call_completed"


def _frontend_debug_patch(patch: dict[str, Any]) -> dict[str, Any]:
    compacted = json_safe(patch)
    if not isinstance(compacted, dict):
        return {"value": compacted}
    messages = compacted.get("messages")
    if isinstance(messages, list):
        compacted["messages"] = [
            _frontend_tool_message(item) if isinstance(item, dict) and item.get("type") == "ToolMessage" else item
            for item in messages
        ]
    return compacted


def _frontend_tool_message(message: dict[str, Any]) -> dict[str, Any]:
    content = message.get("content")
    if not isinstance(content, str):
        return message
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return message
    if not isinstance(payload, dict):
        return message
    compacted = (
        _compact_skill_observation(payload)
        if str(message.get("name") or "") == "skill"
        else _compact_tool_observation(payload)
    )
    updated = dict(message)
    updated["content"] = json.dumps(compacted, ensure_ascii=False, sort_keys=True)
    updated["content_omitted"] = compacted is not payload
    return updated


def _frontend_tool_message_event_payload(message: dict[str, Any]) -> dict[str, Any]:
    frontend_message = _frontend_tool_message(message)
    content_payload = _tool_message_content_payload(frontend_message)
    tool_call_id = (
        _optional_str(frontend_message.get("tool_call_id"))
        or _optional_str(content_payload.get("tool_call_id"))
    )
    tool_name = (
        _optional_str(frontend_message.get("name"))
        or _optional_str(content_payload.get("tool_id"))
        or _optional_str(content_payload.get("tool_name"))
    )
    payload: dict[str, Any] = {
        "message": frontend_message,
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "tool_id": tool_name,
        "status": content_payload.get("status") or frontend_message.get("status"),
    }
    arguments = content_payload.get("arguments")
    if isinstance(arguments, dict):
        payload["arguments"] = _compact_value(arguments)
    for key in ("output_summary", "output_ref", "output_truncated", "content_omitted", "omission_reason"):
        if key in content_payload:
            payload[key] = content_payload[key]
    return {key: value for key, value in payload.items() if value is not None}


def _tool_message_content_payload(message: dict[str, Any]) -> dict[str, Any]:
    content = message.get("content")
    if not isinstance(content, str):
        return {}
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _compact_tool_activity_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compacted = dict(payload)
    for key in ("observation", "result"):
        value = compacted.get(key)
        if isinstance(value, dict):
            compacted[key] = _compact_tool_observation(value)
    output = compacted.get("output")
    if isinstance(output, dict):
        compacted["output"] = _compact_tool_output(output, parent=compacted)
    return compacted


def _compact_tool_observation(payload: dict[str, Any]) -> dict[str, Any]:
    if len(_json_text(payload)) <= TOOL_EVENT_INLINE_JSON_LIMIT:
        return payload
    compacted: dict[str, Any] = {
        key: value
        for key, value in payload.items()
        if key
        in {
            "type",
            "status",
            "tool_id",
            "tool_call_id",
            "message",
            "retryable",
            "execution_status",
            "contract_status",
            "output_summary",
            "output_ref",
            "output_truncated",
            "errors",
            "user_instruction",
        }
    }
    if isinstance(payload.get("arguments"), dict):
        compacted["arguments"] = _compact_value(payload["arguments"])
    if isinstance(payload.get("evidence"), dict):
        compacted["evidence"] = _compact_value(payload["evidence"])
    if isinstance(payload.get("output"), dict):
        compacted["output"] = _compact_tool_output(payload["output"], parent=payload)
    compacted["content_omitted"] = True
    compacted["omission_reason"] = "tool_observation_exceeded_frontend_inline_limit"
    compacted["original_chars"] = len(_json_text(payload))
    return compacted


def _compact_tool_output(output: dict[str, Any], *, parent: dict[str, Any]) -> dict[str, Any]:
    if len(_json_text(output)) <= TOOL_EVENT_INLINE_JSON_LIMIT:
        return output
    compact: dict[str, Any] = {}
    output_ref = parent.get("output_ref")
    if isinstance(output_ref, dict):
        compact["output_ref"] = output_ref
    tool_output_compacted = output.get("_tool_output_compacted")
    if isinstance(tool_output_compacted, dict):
        compact["_tool_output_compacted"] = tool_output_compacted
    compressed = output.get("compressed_output")
    if isinstance(compressed, str) and compressed.strip():
        compact["compressed_output"] = _preview_text(compressed, TOOL_EVENT_PREVIEW_CHARS)
    else:
        compact["preview"] = _preview_text(_json_text(output), TOOL_EVENT_PREVIEW_CHARS)
    compact["content_omitted"] = True
    compact["omission_reason"] = "tool_output_exceeded_frontend_inline_limit"
    compact["original_chars"] = len(_json_text(output))
    return compact


def _compact_value(value: Any) -> Any:
    if len(_json_text(value)) <= TOOL_EVENT_PREVIEW_CHARS:
        return value
    return {
        "preview": _preview_text(_json_text(value), TOOL_EVENT_PREVIEW_CHARS),
        "content_omitted": True,
        "original_chars": len(_json_text(value)),
    }


def _compact_skill_observation(payload: dict[str, Any]) -> dict[str, Any]:
    output = payload.get("output")
    if not isinstance(output, dict):
        return payload
    resource = output.get("resource")
    if not isinstance(resource, dict):
        return payload
    compact_resource = _compact_skill_resource(resource)
    if isinstance(resource.get("resources"), list):
        compact_resource["resources"] = [
            _compact_skill_resource(item) if isinstance(item, dict) else item
            for item in resource.get("resources", [])
        ]
    compact_output = dict(output)
    compact_output["resource"] = compact_resource
    compacted = dict(payload)
    compacted["output"] = compact_output
    compacted["message"] = _skill_resource_summary_message(compact_resource)
    return compacted


def _compact_skill_resource(resource: dict[str, Any]) -> dict[str, Any]:
    compact = {
        key: value
        for key, value in resource.items()
        if key
        in {
            "name",
            "path",
            "kind",
            "purpose",
            "media_type",
            "size_bytes",
            "readable",
            "mode",
            "pointer",
            "already_read",
            "digest",
            "content_ref",
            "schema_read_level",
            "task_model_summary",
            "outline",
            "read_record",
            "message",
            "content_omitted",
            "omission_reason",
        }
    }
    if "fragment" in resource:
        compact["fragment"] = resource["fragment"]
    if resource.get("content") and not resource.get("task_model_summary"):
        text = str(resource.get("content") or "")
        compact["task_model_summary"] = {"preview": " ".join(text.split())[:500], "chars": len(text)}
    compact["content"] = ""
    compact["content_omitted"] = True
    return compact


def _skill_resource_summary_message(resource: dict[str, Any]) -> str:
    path = str(resource.get("path") or "resource")
    purpose = str(resource.get("purpose") or "resource")
    digest = str(resource.get("digest") or "")[:12]
    return f"Skill resource summarized: {path} ({purpose}, digest={digest})"


def _message_stream_parts(chunk: Any) -> tuple[Any | None, dict[str, Any]]:
    if isinstance(chunk, (list, tuple)) and chunk:
        message = chunk[0]
        metadata = chunk[1] if len(chunk) >= 2 and isinstance(chunk[1], dict) else {}
        return message, metadata
    return None, {}


def _message_stream_node_id(metadata: dict[str, Any]) -> str:
    node_id = (
        metadata.get("langgraph_node")
        or metadata.get("node_id")
        or metadata.get("name")
        or "model"
    )
    return str(node_id or "model")


def _message_stream_id(
    *,
    message: Any,
    metadata: dict[str, Any],
    node_id: str,
    request_id: str | None,
) -> str:
    checkpoint_ns = str(
        metadata.get("langgraph_checkpoint_ns")
        or metadata.get("checkpoint_ns")
        or ""
    ).strip()
    if checkpoint_ns:
        return f"message:{node_id}:{checkpoint_ns}"
    step = str(metadata.get("langgraph_step") or "").strip()
    if step:
        return f"message:{node_id}:{request_id or 'request'}:{step}"
    message_id = str(getattr(message, "id", "") or "").strip()
    if message_id:
        return f"message:{node_id}:{message_id}"
    return f"message:{node_id}:{request_id or 'request'}"


def _patch_has_ai_message(patch: dict[str, Any]) -> bool:
    for message in patch.get("messages", []) or []:
        if isinstance(message, dict) and message.get("type") == "AIMessage":
            return True
    return False


def _patch_ai_message_requests_tool(patch: dict[str, Any]) -> bool:
    for message in patch.get("messages", []) or []:
        if not isinstance(message, dict) or message.get("type") != "AIMessage":
            continue
        if message.get("tool_calls"):
            return True
        additional_kwargs = message.get("additional_kwargs")
        if isinstance(additional_kwargs, dict) and additional_kwargs.get("tool_calls"):
            return True
    return False


def _looks_like_tool_observation_text(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        return _looks_like_tool_observation_payload(payload)
    return _looks_like_keyed_tool_observation_text(normalized)


def _looks_like_tool_observation_payload(payload: dict[str, Any]) -> bool:
    if looks_like_internal_observation_payload(payload):
        return True
    keys = {str(key) for key in payload.keys()}
    if {"tool_id", "tool_call_id"}.issubset(keys):
        return True
    if "output_ref" in keys or "output_summary" in keys:
        return True
    return len(keys & TOOL_OBSERVATION_TEXT_KEYS) >= 3 and ("status" in keys or "content" in keys or "output" in keys)

def _looks_like_keyed_tool_observation_text(text: str) -> bool:
    keys: set[str] = set()
    for line in text.splitlines()[:20]:
        stripped = line.strip()
        if not stripped or ":" not in stripped:
            continue
        key = stripped.split(":", 1)[0].strip().strip("\"'")
        if key.isidentifier():
            keys.add(key)
    return len(keys & TOOL_OBSERVATION_TEXT_KEYS) >= 3 and ("status" in keys or "content" in keys)


def _json_text(value: Any) -> str:
    try:
        return json.dumps(json_safe(value), ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(value)


def _preview_text(value: str, limit: int) -> str:
    normalized = " ".join(str(value or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit]


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _message_part_payload(stream_id: str, part_type: str, *, status: str) -> dict[str, Any]:
    return {
        "message_id": stream_id,
        "part_id": f"{stream_id}:{part_type}",
        "part_type": part_type,
        "part_status": status,
    }


def _with_model_message_part_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    stream_id = str(payload.get("stream_id") or "").strip()
    if not stream_id or payload.get("part_id") or payload.get("part_type"):
        return payload
    if event_type in {"model_reasoning_delta", "model_reasoning_completed"}:
        status = "streaming" if event_type == "model_reasoning_delta" else "completed"
        return {**_message_part_payload(stream_id, "reasoning", status=status), **payload}
    if event_type in {"model_stream_delta", "model_message_completed"}:
        status = "streaming" if event_type == "model_stream_delta" else "completed"
        return {**_message_part_payload(stream_id, "text", status=status), **payload}
    return payload


def _is_tool_approval_resume_payload(payload: dict[str, Any]) -> bool:
    if _is_tool_approval_action_payload(payload):
        return True
    for value in payload.values():
        if isinstance(value, dict) and _is_tool_approval_action_payload(value):
            return True
    return False


def _is_tool_approval_action_payload(payload: dict[str, Any]) -> bool:
    if "approved" in payload:
        return True
    action = str(payload.get("action") or "").strip()
    return action in {"approve", "deny", "trust_tool", "revise"}


def json_safe(value: Any) -> Any:
    if isinstance(value, BaseMessage):
        payload: dict[str, Any] = {
            "type": value.__class__.__name__,
            "content": getattr(value, "content", ""),
            "name": getattr(value, "name", None),
        }
        tool_calls = getattr(value, "tool_calls", None)
        if tool_calls:
            payload["tool_calls"] = tool_calls
        tool_call_id = getattr(value, "tool_call_id", None)
        if tool_call_id:
            payload["tool_call_id"] = tool_call_id
        return payload
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
