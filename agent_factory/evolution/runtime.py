from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langgraph.errors import GraphDrained
from langgraph.runtime import RunControl
from langgraph.types import Command

from agent_factory.create_agent.models import CreateAgentAction, initial_system_manufacturing_state
from agent_factory.create_agent.runtime import (
    _ModelTraceAccumulator,
    _context_window_payload_from_model_cache,
    _is_model_cache_chunk,
    _json_safe,
    _tool_trace_records,
)
from agent_factory.create_agent.output_safety import looks_like_internal_observation_text
from agent_factory.create_agent.tooling import CreateAgentToolEnvironmentBuilder
from agent_factory.create_agent.validation_state import package_fingerprint
from agent_factory.create_agent.workflow import CreateAgentWorkflow
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.evolution.trace_gate import decide_trace_relevance
from agent_factory.evolution.task_analysis import analyze_evolution_task
from agent_factory.evolution.target_gate import decide_evolution_target
from agent_factory.factory_graph.frontend_bridge.event_normalizer import RuntimeEventNormalizer
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import extract_interrupt_payload
from agent_factory.factory_graph.session import build_factory_checkpointer_handle
from agent_factory.model_pool.runtime_override import (
    RUNTIME_MAIN_MODEL_PROFILE_ID_KEY,
    RUNTIME_REASONING_INTENSITY_KEY,
    main_model_profile_id_from_user_config,
    runtime_reasoning_intensity_from_user_config,
)
from agent_factory.local_inference.request_context import inference_request_context
from agent_factory.paths import factory_artifact_path, project_root
from agent_factory.package_runtime.drained_checkpoint import (
    finalize_drained_message_checkpoint,
    repair_incomplete_message_checkpoint,
)
from agent_factory.package_runtime.run_control import RuntimeRunControlRegistry
from agent_factory.runtime_attachments import ATTACHMENT_INPUT_DIR, import_runtime_attachments, time_named_attachment_scope
from agent_factory.runtime_contracts import AgentPackageLoader
from agent_factory.runtime_kernel.persistence import delete_checkpoint_thread
from agent_factory.trace_system.diagnostics import TraceDiagnostics
from agent_factory.trace_system.projector import TraceProjector
from agent_factory.trace_system.reader import TraceReader
from agent_factory.trace_system.schema import RepairTracePack, TraceRunFilter
from agent_factory.tooling.execution_context import runtime_run_control_context


@dataclass(frozen=True, slots=True)
class AgentEvolutionStreamRun:
    package_id: str
    trace_id: str | None
    request_id: str
    events: Iterator[tuple[str, Any]]


@dataclass(slots=True)
class _EvolutionRunContext:
    package_id: str
    trace_id: str | None
    session_id: str | None
    request_id: str
    user_input: str
    package_path: Path
    graph_thread_id: str
    backup_path: Path | None
    before_fingerprint: dict[str, str]
    runtime_attachments: list[dict[str, Any]]
    runtime_main_model_profile_id: str | None = None
    runtime_reasoning_intensity: int | None = None


class AgentEvolutionRuntime:
    def __init__(
        self,
        *,
        package_root: str | Path | None = None,
        runtime_root: str | Path | None = None,
        model: Any | None = None,
        tool_environment_builder: CreateAgentToolEnvironmentBuilder | None = None,
        checkpointer: Any | None = None,
        package_restart_handler: Callable[[str, str | None], dict[str, Any]] | None = None,
    ) -> None:
        self.package_root = Path(package_root).expanduser() if package_root else factory_artifact_path("packages")
        self.runtime_root = Path(runtime_root).expanduser() if runtime_root else factory_artifact_path("agent_runtime")
        self.model = model
        self.tool_environment_builder = tool_environment_builder or CreateAgentToolEnvironmentBuilder()
        self.checkpointer = checkpointer or build_factory_checkpointer_handle().saver
        self.package_restart_handler = package_restart_handler
        self._active_runs: dict[str, _EvolutionRunContext] = {}
        self._run_controls = RuntimeRunControlRegistry()

    def stream(
        self,
        *,
        package_id: str,
        user_input: str,
        request_id: str | None,
        session_id: str | None,
        attachments: Any = None,
        user_config: dict[str, Any] | None = None,
    ) -> AgentEvolutionStreamRun:
        safe_package_id = _safe_id(package_id, label="package_id")
        resolved_request_id = request_id or uuid4().hex
        trace_id = self.latest_failed_trace_id(safe_package_id)
        run_control = self._register_run_control(resolved_request_id)
        return AgentEvolutionStreamRun(
            package_id=safe_package_id,
            trace_id=trace_id,
            request_id=resolved_request_id,
            events=_inference_scoped_events(
                self._owned_events(
                    request_id=resolved_request_id,
                    run_control=run_control,
                    events=self._events(
                        package_id=safe_package_id,
                        trace_id=trace_id,
                        user_input=user_input,
                        request_id=resolved_request_id,
                        session_id=session_id,
                        resume_payload=None,
                        attachments=attachments,
                        user_config=user_config,
                        run_control=run_control,
                    ),
                ),
                session_id=session_id or resolved_request_id,
                request_id=resolved_request_id,
                run_control=run_control,
            ),
        )

    def resume_stream(
        self,
        *,
        package_id: str,
        session_id: str,
        resume_payload: dict[str, Any] | None,
        request_id: str | None,
    ) -> AgentEvolutionStreamRun:
        safe_package_id = _safe_id(package_id, label="package_id")
        active_context = self._active_runs.get(_active_run_key(session_id, safe_package_id))
        if active_context is None:
            raise RuntimeError(f"no active evolution run to resume: {safe_package_id}")
        trace_id = active_context.trace_id if active_context is not None else None
        resolved_request_id = request_id or uuid4().hex
        run_control = self._register_run_control(resolved_request_id)
        return AgentEvolutionStreamRun(
            package_id=safe_package_id,
            trace_id=trace_id,
            request_id=resolved_request_id,
            events=_inference_scoped_events(
                self._owned_events(
                    request_id=resolved_request_id,
                    run_control=run_control,
                    events=self._events(
                        package_id=safe_package_id,
                        trace_id=trace_id,
                        user_input="",
                        request_id=resolved_request_id,
                        session_id=session_id,
                        resume_payload=resume_payload or {},
                        attachments=None,
                        user_config=None,
                        run_control=run_control,
                    ),
                ),
                session_id=session_id,
                request_id=resolved_request_id,
                run_control=run_control,
            ),
        )

    def cancel_active_requests(
        self,
        *,
        reason: str = "user_cancelled",
        request_id: str | None = None,
    ) -> int:
        return self._run_controls.request_drain(
            reason=reason,
            request_id=request_id,
        )

    def abort_session(self, *, package_id: str, session_id: str, reason: str) -> dict[str, Any]:
        safe_package_id = _safe_id(package_id, label="package_id")
        safe_session_id = str(session_id or "").strip()
        if not safe_session_id:
            raise RuntimeError("session_id must not be empty")
        active_context = self._active_runs.pop(
            _active_run_key(safe_session_id, safe_package_id),
            None,
        )
        restored = False
        if active_context is not None and active_context.backup_path is not None:
            if active_context.backup_path.exists():
                _restore_package(active_context.backup_path, active_context.package_path)
                restored = True
        checkpoint_threads = _evolution_checkpoint_threads(
            session_id=safe_session_id,
            package_id=safe_package_id,
            request_ids=[active_context.request_id] if active_context is not None else [],
            active_context=active_context,
        )
        deleted_checkpoint_count = sum(
            1
            for thread_id in checkpoint_threads
            if delete_checkpoint_thread(self.checkpointer, thread_id)
        )
        return {
            "package_id": safe_package_id,
            "session_id": safe_session_id,
            "reason": str(reason or "cancelled"),
            "restored": restored,
            "deleted_checkpoint_count": deleted_checkpoint_count,
        }

    def _register_run_control(self, request_id: str) -> RunControl:
        return self._run_controls.register(request_id)

    def _forget_run_control(self, request_id: str, control: RunControl) -> None:
        self._run_controls.release(request_id, control)

    def latest_failed_trace_id(self, package_id: str) -> str | None:
        safe_package_id = _safe_id(package_id, label="package_id")
        reader = TraceReader(self.runtime_root / safe_package_id / "trace")
        runs = reader.list_runs(TraceRunFilter(status=["failed"], limit=1))
        if not runs:
            return None
        return runs[0].trace_id

    def delete_session_artifacts(
        self,
        *,
        package_id: str,
        session_id: str,
        request_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        safe_package_id = _safe_id(package_id, label="package_id")
        safe_session_id = str(session_id or "").strip()
        if not safe_session_id:
            raise RuntimeError("session_id must not be empty")
        active_context = self._active_runs.pop(_active_run_key(safe_session_id, safe_package_id), None)
        checkpoint_threads = _evolution_checkpoint_threads(
            session_id=safe_session_id,
            package_id=safe_package_id,
            request_ids=request_ids or [],
            active_context=active_context,
        )
        deleted_checkpoint_count = sum(
            1
            for thread_id in checkpoint_threads
            if delete_checkpoint_thread(self.checkpointer, thread_id)
        )
        workspace = CreateAgentWorkspace(_safe_child(self.package_root, safe_package_id))
        trace_deleted = _delete_evolution_trace_for_session(workspace, safe_session_id)
        return {
            "package_id": safe_package_id,
            "session_id": safe_session_id,
            "trace_path": str(workspace.manufacturing_trace_path),
            "trace_deleted": trace_deleted,
            "deleted_checkpoint_count": deleted_checkpoint_count,
        }

    def _owned_events(
        self,
        *,
        request_id: str,
        run_control: RunControl,
        events: Iterator[tuple[str, Any]],
    ) -> Iterator[tuple[str, Any]]:
        try:
            yield from events
        finally:
            self._forget_run_control(request_id, run_control)

    def _events(
        self,
        *,
        package_id: str,
        trace_id: str | None,
        user_input: str,
        request_id: str,
        session_id: str | None,
        resume_payload: dict[str, Any] | None,
        attachments: Any,
        user_config: dict[str, Any] | None,
        run_control: RunControl,
    ) -> Iterator[tuple[str, Any]]:
        pending_events: list[FactoryFrontendEvent] = []

        def emit_frontend(item: FactoryFrontendEvent) -> None:
            pending_events.append(item)

        def drain_events() -> Iterator[tuple[str, FactoryFrontendEvent]]:
            while pending_events:
                yield "frontend_event", pending_events.pop(0)

        normalizer = RuntimeEventNormalizer(
            emit=emit_frontend,
            request_id=request_id,
            session_id=session_id,
            mode="evolve_agent",
            graph_id="agent_evolution",
            producer_type="agent_evolution",
        )
        package_path = _safe_child(self.package_root, package_id)
        active_run_key = _active_run_key(session_id or request_id, package_id)
        context = self._active_runs.get(active_run_key) if resume_payload is not None else None
        if context is None:
            context = _EvolutionRunContext(
                package_id=package_id,
                trace_id=trace_id,
                session_id=session_id,
                request_id=request_id,
                user_input=user_input,
                package_path=package_path,
                graph_thread_id=_thread_id(f"{session_id or 'sessionless'}:{request_id}", package_id),
                backup_path=None,
                before_fingerprint={},
                runtime_attachments=[],
                runtime_main_model_profile_id=main_model_profile_id_from_user_config(user_config),
                runtime_reasoning_intensity=runtime_reasoning_intensity_from_user_config(user_config),
            )
        resolved_thread_id = context.graph_thread_id
        normalizer.emit_run_started({"package_id": package_id, "trace_id": context.trace_id})
        yield from drain_events()
        workspace = CreateAgentWorkspace(package_path)
        try:
            if not package_path.is_dir():
                raise RuntimeError(f"agent package not found: {package_id}")
            _ensure_evolution_managed_files(workspace)
            if resume_payload is None:
                context.backup_path = _backup_package(package_path, package_id=package_id)
                context.before_fingerprint = package_fingerprint(package_path)
                attachment_scope = time_named_attachment_scope()
                attachment_result = import_runtime_attachments(
                    context.user_input,
                    attachments,
                    storage_root=package_path / ".factory" / ATTACHMENT_INPUT_DIR / attachment_scope,
                    runtime_path_root=f".factory/{ATTACHMENT_INPUT_DIR}/{attachment_scope}",
                    base_dir=project_root(),
                    scope=attachment_scope,
                )
                context.user_input = attachment_result.message
                context.runtime_attachments = attachment_result.attachments
                self._active_runs[active_run_key] = context
            package = AgentPackageLoader().load_path(package_path / "agent_package.json")
            if context.trace_id:
                repair_pack = _repair_pack(self.runtime_root, package_id=package_id, trace_id=context.trace_id)
                error_pack = _error_only_pack(repair_pack)
                trace_gate = decide_trace_relevance(user_goal=context.user_input, error_pack=error_pack)
                trace_context = trace_gate.model_dump(mode="json")
                provided_error_pack = error_pack if trace_gate.provide_trace else {}
            else:
                error_pack = {}
                provided_error_pack = {}
                trace_context = {
                    "provided": False,
                    "reason": "no failed trace is available for this package; evolution will use the user goal and package state only",
                }
            package_summary = _package_summary(package_id, package_path, package)
            if resume_payload is None:
                normalizer.runtime_event(
                    "node_started",
                    node_id="agent_evolution_task_analysis",
                    node_label="Evolution Task Analysis",
                    node_kind="control",
                    payload={"package_id": package_id, "visible_to_user": True},
                )
                yield from drain_events()
                task_analysis = analyze_evolution_task(
                    user_input=context.user_input,
                    package_summary=package_summary,
                    trace_context=trace_context,
                    model=self.model,
                )
                workspace.write_task_analysis(task_analysis)
                workspace.write_system_state(initial_system_manufacturing_state(workflow_kind="evolution"))
                normalizer.runtime_event(
                    "node_completed",
                    node_id="agent_evolution_task_analysis",
                    node_label="Evolution Task Analysis",
                    node_kind="control",
                    payload={
                        "package_id": package_id,
                        "visible_to_user": True,
                        "affected_systems": task_analysis.affected_systems,
                    },
                )
                yield from drain_events()
            else:
                task_analysis = workspace.read_task_analysis()
            target_plan = decide_evolution_target(
                task_analysis=task_analysis.model_dump(mode="json"),
                trace_context=trace_context,
                error_pack=provided_error_pack,
            )
            if resume_payload is None:
                workspace.reset_evolution_trace(
                    session_id=session_id,
                    request_id=request_id,
                    graph_id="agent_evolution",
                    package_id=package_id,
                    trace_id=context.trace_id,
                    target_plan=target_plan.to_context(),
                )
            trace_sequence = workspace.evolution_trace_record_count()

            def record_trace(kind: str, payload: dict[str, Any]) -> None:
                nonlocal trace_sequence
                trace_sequence += 1
                workspace.append_evolution_trace_record(
                    {
                        "sequence": trace_sequence,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "kind": kind,
                        "session_id": session_id,
                        "request_id": request_id,
                        "graph_id": "agent_evolution",
                        "package_id": package_id,
                        **payload,
                    }
                )

            model_trace = _ModelTraceAccumulator(record_trace)
            workflow: Any | None = None

            def emit_cancelled() -> Iterator[tuple[str, FactoryFrontendEvent]]:
                model_trace.flush()
                normalizer.complete_open_model_streams(reason="user_stopped")
                if context.backup_path is not None and context.backup_path.exists():
                    _restore_package(context.backup_path, context.package_path)
                self._active_runs.pop(active_run_key, None)
                normalizer.runtime_event(
                    "node_completed",
                    node_id="agent_evolution",
                    node_label="Agent Evolution",
                    node_kind="create_agent_workflow",
                    payload={"package_id": package_id, "status": "stopped", "trace_id": context.trace_id},
                )
                record_trace(
                    "lifecycle",
                    {
                        "event_type": "run_completed",
                        "payload": {"status": "stopped", "package_id": package_id, "trace_id": context.trace_id},
                    },
                )
                normalizer.emit_run_completed(
                    {
                        "status": "stopped",
                        "package_id": package_id,
                        "trace_id": context.trace_id,
                        "agent_session": {"session_id": session_id} if session_id else {},
                    }
                )
                yield from drain_events()

            record_trace(
                "lifecycle",
                {
                    "event_type": "run_started",
                    "payload": {
                        "package_id": package_id,
                        "trace_id": context.trace_id,
                        "package_path": str(package_path),
                        "trace_gate": _json_safe(trace_context),
                        "target_plan": _json_safe(target_plan.to_context()),
                    },
                },
            )
            if run_control.drain_requested:
                yield from emit_cancelled()
                return
            if target_plan.surface == "runtime_blocker":
                record_trace(
                    "lifecycle",
                    {
                        "event_type": "runtime_blocked",
                        "success": False,
                        "payload": _json_safe(target_plan.to_context()),
                    },
                )
                if context.backup_path is not None:
                    shutil.rmtree(context.backup_path, ignore_errors=True)
                self._active_runs.pop(active_run_key, None)
                normalizer.complete_visible_assistant_output_from_text(
                    "Evolution is blocked by a runtime-environment issue that cannot be fixed in the AgentPackage. Resolve the local runtime/model infrastructure blocker first.",
                    node_id="agent_evolution",
                    reason="runtime_blocked",
                )
                normalizer.emit_run_completed(
                    {
                        "status": "blocked",
                        "package_id": package_id,
                        "trace_id": context.trace_id,
                        "target_plan": target_plan.to_context(),
                    }
                )
                yield from drain_events()
                return
            tool_env = self.tool_environment_builder.build(
                workspace_root=package_path,
                mode="evolution",
                evolution_target_plan=target_plan.to_context(),
            )
            normalizer.runtime_event(
                "node_started",
                node_id="agent_evolution",
                node_label="Agent Evolution",
                node_kind="create_agent_workflow",
                payload={
                    "package_id": package_id,
                    "trace_id": context.trace_id,
                    "package_path": str(package_path),
                    "tool_ids": tool_env.tool_ids,
                    "extension_report": tool_env.extension_report,
                    "trace_gate": trace_context,
                    "target_plan": target_plan.to_context(),
                },
            )
            record_trace(
                "lifecycle",
                {
                    "event_type": "node_started",
                    "node_id": "agent_evolution",
                    "node_label": "Agent Evolution",
                    "payload": {
                        "package_id": package_id,
                        "tool_ids": tool_env.tool_ids,
                        "target_plan": _json_safe(target_plan.to_context()),
                    },
                },
            )
            yield from drain_events()
            if run_control.drain_requested:
                yield from emit_cancelled()
                return
            workflow = CreateAgentWorkflow(
                tools=tool_env.tools,
                model=self.model,
                capability_inventory=tool_env.capability_inventory,
                workflow_kind="evolution",
            ).compile(checkpointer=self.checkpointer)
            if resume_payload is None:
                repair_incomplete_message_checkpoint(
                    graph_app=workflow,
                    thread_id=resolved_thread_id,
                )
                stream_input: Any = {
                    "request": context.user_input,
                    "session_id": context.session_id,
                    "request_id": context.request_id,
                    "workspace_path": str(package_path),
                    "runtime_attachments": context.runtime_attachments,
                    RUNTIME_MAIN_MODEL_PROFILE_ID_KEY: context.runtime_main_model_profile_id or "",
                    RUNTIME_REASONING_INTENSITY_KEY: context.runtime_reasoning_intensity,
                    "graph_kind": "evolution",
                    "evolution_context": {
                        "package_id": package_id,
                        "package_path": str(package_path),
                        "package_summary": package_summary,
                        "trace_gate": trace_context,
                        "target_plan": target_plan.to_context(),
                        "task_analysis": task_analysis.model_dump(mode="json"),
                        **({"error_pack": provided_error_pack} if provided_error_pack else {}),
                    },
                    "iteration": 0,
                    "flow_status": "running",
                    "messages": [HumanMessage(content=context.user_input)],
                }
            else:
                stream_input = Command(resume=resume_payload)
                normalizer.emit_runtime_resumed(resume_payload)
                record_trace("lifecycle", {"event_type": "runtime_resumed", "payload": _json_safe(resume_payload)})
                yield from drain_events()
            final_state: dict[str, Any] | None = None
            config = {"configurable": {"thread_id": resolved_thread_id}}
            stream_iter = workflow.stream(
                stream_input,
                config=config,
                stream_mode=["messages", "custom", "values"],
                durability="sync",
                control=run_control,
            )
            graph_drained = False
            try:
                for stream_mode, chunk in stream_iter:
                    interrupt_payload = extract_interrupt_payload(chunk)
                    if interrupt_payload is not None:
                        normalizer.emit_interrupt(interrupt_payload)
                        record_trace(
                            "lifecycle",
                            {"event_type": "interrupt_requested", "payload": _json_safe(interrupt_payload)},
                        )
                        model_trace.flush()
                        yield from drain_events()
                        return
                    if stream_mode == "values" and isinstance(chunk, dict):
                        final_state = chunk
                        continue
                    if stream_mode == "messages":
                        model_trace.accept(chunk)
                    if stream_mode == "custom":
                        model_trace.flush()
                        if _is_model_cache_chunk(chunk):
                            cache_payload = _json_safe(chunk.get("payload") or {})
                            record_trace("model_cache", cache_payload)
                            node_id = str(cache_payload.get("node_id") or "evolution_supervisor")
                            normalizer.runtime_event(
                                "model_cache_metrics",
                                node_id=node_id,
                                payload={
                                    **cache_payload,
                                    "session_id": context.session_id,
                                    "run_id": context.request_id,
                                    "agent_id": "agent_evolution",
                                    "agent_name": "Evolution Agent",
                                    "package_id": package_id,
                                },
                            )
                            normalizer.runtime_event(
                                "context_window_updated",
                                node_id=node_id,
                                payload=_context_window_payload_from_model_cache(cache_payload, node_id=node_id),
                            )
                            continue
                        for record in _tool_trace_records(chunk):
                            record_trace("tool_call", record)
                    normalizer.emit_stream_item(stream_mode, chunk, updates_payload_key="evolution_update")
                    yield from drain_events()
            except GraphDrained:
                graph_drained = True
            finally:
                close = getattr(stream_iter, "close", None)
                if callable(close):
                    close()
            if graph_drained or run_control.drain_requested:
                finalize_drained_message_checkpoint(
                    graph_app=workflow,
                    thread_id=resolved_thread_id,
                    stop_reason=run_control.drain_reason or "user_cancelled",
                )
                yield from emit_cancelled()
                return
            model_trace.flush()
            if not final_state:
                raise RuntimeError("agent evolution workflow did not produce final state")
            flow_status = str(final_state.get("flow_status") or "running")
            if flow_status not in {"turn_complete", "package_complete"}:
                raise RuntimeError("agent evolution workflow stopped before completion")
            if flow_status == "turn_complete":
                current_fingerprint = package_fingerprint(package_path)
                if context.backup_path is not None:
                    if current_fingerprint != context.before_fingerprint:
                        _restore_package(context.backup_path, package_path)
                    else:
                        shutil.rmtree(context.backup_path, ignore_errors=True)
                self._active_runs.pop(active_run_key, None)
                final_answer = _safe_evolution_summary(str(final_state.get("final_answer") or ""))
                normalizer.complete_visible_assistant_output_from_text(
                    final_answer,
                    node_id="agent_evolution",
                    reason="turn_completed",
                )
                normalizer.emit_run_completed(
                    {
                        "status": "completed",
                        "package_id": package_id,
                        "trace_id": context.trace_id,
                        "changed_files": [],
                    }
                )
                yield from drain_events()
                return
            changed_files = _changed_files(context.before_fingerprint, package_fingerprint(package_path))
            final_answer = _safe_evolution_summary(str(final_state.get("final_answer") or ""))
            report_path = _write_evolution_publish_report(
                package_path=package_path,
                package_id=package_id,
                trace_id=context.trace_id,
                user_input=context.user_input,
                summary=final_answer,
                changed_files=changed_files,
                validation=final_state.get("validation") if isinstance(final_state.get("validation"), dict) else {},
            )
            if context.backup_path is not None:
                shutil.rmtree(context.backup_path, ignore_errors=True)
            restart = self._restart_evolved_package(package_id, request_id)
            if restart.get("status") == "ready":
                final_answer = f"{final_answer}\n\nThe child Agent restarted automatically and loaded this evolution."
            elif restart.get("status") == "failed":
                final_answer = (
                    f"{final_answer}\n\nThe evolution was saved, but automatic child-Agent restart failed: "
                    f"{restart.get('error') or 'unknown error'}"
                )
            self._active_runs.pop(active_run_key, None)
            normalizer.runtime_event(
                "node_completed",
                node_id="agent_evolution",
                node_label="Agent Evolution",
                node_kind="create_agent_workflow",
                payload={
                    "package_id": package_id,
                    "changed_files": changed_files,
                    "report_path": str(report_path),
                    "restart": restart,
                },
            )
            record_trace(
                "lifecycle",
                {
                    "event_type": "node_completed",
                    "node_id": "agent_evolution",
                    "node_label": "Agent Evolution",
                    "payload": {
                        "package_id": package_id,
                        "changed_files": changed_files,
                        "report_path": str(report_path),
                        "restart": restart,
                    },
                },
            )
            normalizer.complete_visible_assistant_output_from_text(
                final_answer,
                node_id="agent_evolution",
                reason="run_completed",
            )
            normalizer.emit_run_completed(
                {
                    "status": "published",
                    "package_id": package_id,
                    "trace_id": context.trace_id,
                    "changed_files": changed_files,
                    "report_path": str(report_path),
                    "restart": restart,
                }
            )
            record_trace(
                "lifecycle",
                {
                    "event_type": "run_completed",
                    "payload": {
                        "status": "published",
                        "package_id": package_id,
                        "trace_id": context.trace_id,
                        "changed_files": changed_files,
                        "report_path": str(report_path),
                        "restart": restart,
                    },
                },
            )
            yield from drain_events()
        except GraphDrained:
            stopped_trace_payload = _evolution_trace_payload_with_record(
                workspace,
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "kind": "lifecycle",
                    "session_id": session_id,
                    "request_id": request_id,
                    "graph_id": "agent_evolution",
                    "package_id": package_id,
                    "event_type": "run_completed",
                    "success": True,
                    "payload": {
                        "status": "stopped",
                        "stop_reason": run_control.drain_reason or "user_cancelled",
                    },
                },
            )
            normalizer.complete_open_model_streams(reason="user_stopped")
            if context.backup_path is not None and context.backup_path.exists():
                _restore_package(context.backup_path, package_path)
            if stopped_trace_payload is not None:
                _write_evolution_trace_payload(workspace, stopped_trace_payload)
            self._active_runs.pop(active_run_key, None)
            normalizer.emit_run_completed(
                {
                    "status": "stopped",
                    "package_id": package_id,
                    "trace_id": context.trace_id,
                    "stop_reason": run_control.drain_reason or "user_cancelled",
                    "agent_session": {"session_id": session_id} if session_id else {},
                }
            )
            yield from drain_events()
        except Exception as exc:
            failed_trace_payload = _evolution_trace_payload_with_record(
                workspace,
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "kind": "lifecycle",
                    "session_id": session_id,
                    "request_id": request_id,
                    "graph_id": "agent_evolution",
                    "package_id": package_id,
                    "event_type": "run_failed",
                    "success": False,
                    "message": f"{type(exc).__name__}: {exc}",
                    "payload": {"package_path": str(package_path)},
                },
            )
            if context.backup_path is not None and context.backup_path.exists():
                _restore_package(context.backup_path, package_path)
            if failed_trace_payload is not None:
                _write_evolution_trace_payload(workspace, failed_trace_payload)
            self._active_runs.pop(active_run_key, None)
            normalizer.emit_run_failed(exc)
            yield from drain_events()
    def _restart_evolved_package(self, package_id: str, request_id: str | None) -> dict[str, Any]:
        if self.package_restart_handler is None:
            return {"status": "not_configured", "package_id": package_id}
        try:
            result = self.package_restart_handler(package_id, request_id)
            return {"status": str(result.get("status") or "ready"), "package_id": package_id, **result}
        except Exception as exc:
            return {
                "status": "failed",
                "package_id": package_id,
                "error": f"{type(exc).__name__}: {exc}",
            }


def _ensure_evolution_managed_files(workspace: CreateAgentWorkspace) -> None:
    workspace.root.mkdir(parents=True, exist_ok=True)
    workspace.factory_dir.mkdir(parents=True, exist_ok=True)
    if not workspace.system_state_path.exists():
        workspace.write_system_state(initial_system_manufacturing_state())
    workspace.write_action(CreateAgentAction())
    if not workspace.resources_path.exists():
        workspace._write_json(workspace.resources_path, {"version": "resource_facts.v0", "facts": []})


def _repair_pack(runtime_root: Path, *, package_id: str, trace_id: str) -> RepairTracePack:
    diagnostics = TraceDiagnostics(TraceProjector(TraceReader(runtime_root / package_id / "trace")))
    return diagnostics.build_repair_pack(trace_id)


def _error_only_pack(pack: RepairTracePack) -> dict[str, Any]:
    return {
        "trace_id": pack.trace_id,
        "run_id": pack.run_id,
        "status": pack.status,
        "failed_node": pack.failed_node,
        "failed_span_id": pack.failed_span_id,
        "failure_category": pack.failure_category,
        "error_chain": [item.model_dump(mode="json") for item in pack.error_chain],
        "suspected_root_causes": pack.suspected_root_causes,
        "repair_targets": pack.repair_targets,
    }


def _package_summary(package_id: str, package_path: Path, package: Any) -> dict[str, Any]:
    return {
        "package_id": package_id,
        "package_path": str(package_path),
        "agent_id": package.assembly_spec.agent.id,
        "agent_name": package.assembly_spec.agent.name,
        "agent_description": package.assembly_spec.agent.description,
        "pattern_id": package.assembly_spec.runtime.pattern_id,
        "tool_ids": [tool.id for tool in package.assembly_spec.tools],
        "contract_keys": sorted(package.contracts.keys()),
    }


def _backup_package(package_path: Path, *, package_id: str) -> Path:
    root = package_path.parent / ".evolution_backups"
    root.mkdir(parents=True, exist_ok=True)
    backup_path = root / f"{package_id}-{uuid4().hex}"
    shutil.copytree(package_path, backup_path)
    return backup_path


def _restore_package(backup_path: Path, package_path: Path) -> None:
    if package_path.exists():
        shutil.rmtree(package_path)
    shutil.copytree(backup_path, package_path)
    shutil.rmtree(backup_path, ignore_errors=True)


def _changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    keys = sorted(set(before) | set(after))
    return [key for key in keys if before.get(key) != after.get(key)]


def _write_evolution_publish_report(
    *,
    package_path: Path,
    package_id: str,
    trace_id: str | None,
    user_input: str,
    summary: str,
    changed_files: list[str],
    validation: dict[str, Any],
) -> Path:
    now = datetime.now(UTC).isoformat()
    report_path = package_path / "package_report.json"
    previous: dict[str, Any] = {}
    if report_path.is_file():
        try:
            value = json.loads(report_path.read_text(encoding="utf-8"))
            previous = value if isinstance(value, dict) else {}
        except Exception:
            previous = {}
    evolution_history = list(previous.get("evolution_history") or []) if isinstance(previous.get("evolution_history"), list) else []
    evolution_history.append(
        {
            "version": "agent_evolution_publish.v0",
            "package_id": package_id,
            "trace_id": trace_id,
            "user_goal": user_input,
            "summary": summary,
            "changed_files": changed_files,
            "validation": validation,
            "published_at": now,
        }
    )
    report = {
        **previous,
        "version": previous.get("version") or "agent_package_publish_report.v0",
        "status": "available",
        "package_id": package_id,
        "package_path": str(package_path),
        "manifest_path": str(package_path / "agent_package.json"),
        "published_at": now,
        "package_fingerprint": package_fingerprint(package_path),
        "last_evolution": evolution_history[-1],
        "evolution_history": evolution_history[-20:],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_path


def _safe_evolution_summary(value: str) -> str:
    text = str(value or "").strip()
    if text and not looks_like_internal_observation_text(text):
        return text
    return "AgentPackage evolution completed and was published automatically."


def _safe_id(value: str, *, label: str) -> str:
    raw = str(value).strip()
    if not raw:
        raise RuntimeError(f"{label} must not be empty")
    if raw in {".", ".."} or "/" in raw or "\\" in raw:
        raise RuntimeError(f"invalid {label}: {value}")
    return raw


def _safe_child(root: Path, child: str) -> Path:
    target = (root / child).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"path escapes root: {child}") from exc
    return target


def _thread_id(session_id: str, package_id: str) -> str:
    return f"{session_id}:evolution:{package_id}"


def _inference_scoped_events(
    events: Iterator[tuple[str, Any]],
    *,
    session_id: str,
    request_id: str,
    run_control: RunControl,
) -> Iterator[tuple[str, Any]]:
    with (
        inference_request_context(session_id=session_id, request_id=request_id),
        runtime_run_control_context(run_control),
    ):
        yield from events


def _active_run_key(session_id: str, package_id: str) -> str:
    return f"{session_id}:evolution-active:{package_id}"


def _evolution_checkpoint_threads(
    *,
    session_id: str,
    package_id: str,
    request_ids: list[str],
    active_context: _EvolutionRunContext | None,
) -> list[str]:
    threads: list[str] = []
    if active_context is not None:
        threads.append(active_context.graph_thread_id)
    for request_id in request_ids:
        normalized_request_id = str(request_id or "").strip()
        if normalized_request_id:
            threads.append(_thread_id(f"{session_id}:{normalized_request_id}", package_id))
    return list(dict.fromkeys(threads))


def _delete_evolution_trace_for_session(workspace: CreateAgentWorkspace, session_id: str) -> bool:
    path = workspace.manufacturing_trace_path
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    if payload.get("version") != "agent_evolution_manufacturing_trace.v0":
        return False
    if str(payload.get("session_id") or "").strip() != session_id:
        return False
    path.unlink(missing_ok=True)
    return True


def _evolution_trace_payload_with_record(workspace: CreateAgentWorkspace, record: dict[str, Any]) -> dict[str, Any] | None:
    try:
        path = workspace.manufacturing_trace_path
        payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        if not isinstance(payload, dict) or payload.get("version") != "agent_evolution_manufacturing_trace.v0":
            payload = {
                "version": "agent_evolution_manufacturing_trace.v0",
                "workspace_path": str(workspace.root),
                "created_at": datetime.now(UTC).isoformat(),
                "records": [],
            }
        records = payload.get("records")
        if not isinstance(records, list):
            records = []
            payload["records"] = records
        records.append({"sequence": len(records) + 1, **record})
        payload["updated_at"] = datetime.now(UTC).isoformat()
        return payload
    except Exception:
        return None


def _write_evolution_trace_payload(workspace: CreateAgentWorkspace, payload: dict[str, Any]) -> None:
    try:
        workspace._write_json(workspace.manufacturing_trace_path, payload)
    except Exception:
        pass
