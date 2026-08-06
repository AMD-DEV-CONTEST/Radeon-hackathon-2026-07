from __future__ import annotations

from dataclasses import dataclass, field
import errno
import json
import sys
import threading
from pathlib import Path
from typing import Any

from langgraph.errors import GraphDrained
from langgraph.runtime import RunControl

from agent_factory.assembly.compiler import AgentAssemblyCompiler
from agent_factory.environment_system.runtime import RuntimeDependencyError, activate_runtime_dependencies
from agent_factory.factory_graph.frontend_bridge.event_normalizer import (
    RuntimeEventNormalizer,
    VisibleAssistantMessage,
    json_safe,
)
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent, event
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import interrupt_payload
from agent_factory.runtime_contracts import AgentPackageLoader, LoadedAgentPackage, RuntimeBuildPlanner
from agent_factory.runtime_contracts.builtins import default_runtime_contract_registry
from agent_factory.runtime_kernel.background_workers import RuntimeBackgroundWorkerManager, WorkerLifecycleEvent
from agent_factory.runtime_protocol.completion import runtime_completed, runtime_error_message
from agent_factory.runtime_kernel.kernel import RuntimeKernelFacade
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_kernel.session import AgentSessionConfig
from agent_factory.scheduler_system import (
    SchedulerExecutor,
    runtime_tool_runner,
    scheduler_run_session_id,
    scheduler_tool_approval_override,
)
from agent_factory.scheduler_system.events import SchedulerEventPayload
from agent_factory.scheduler_system.management import manage_scheduler_runtime
from agent_factory.scheduler_system.execution_config import (
    scheduler_run_max_retries,
    scheduler_run_timeout_seconds,
    scheduler_run_user_config,
)
from agent_factory.scheduler_system.seeds import apply_scheduler_seed_contract
from agent_factory.knowledge_system.events import KNOWLEDGE_EVENT_TYPES
from agent_factory.package_runtime.request_lifecycle import RuntimeRequestPolicy
from agent_factory.package_runtime.run_control import RuntimeRunControlRegistry
from agent_factory.package_runtime.drained_checkpoint import (
    finalize_drained_runtime_checkpoint,
    repair_incomplete_message_checkpoint,
)
from agent_factory.package_runtime import host_runtime_package_view
from agent_factory.package_runtime.workspace_scope import apply_runtime_workspace
from agent_factory.package_runtime.session_turns import (
    resume_user_input,
    session_attachments_from_state,
    session_final_answer,
    session_reasoning_content,
    session_trace_ref,
    session_user_input_from_state,
)
from agent_factory.runtime_attachments import has_attachment_payload, merge_attachments_into_user_config
from agent_factory.agent_runtime_bridge.paths import runtime_bridge_paths


_BRIDGE_PATHS = runtime_bridge_paths()
PACKAGE_ROOT = _BRIDGE_PATHS.package_root
PACKAGE_MANIFEST = PACKAGE_ROOT / "agent_package.json"
ARTIFACTS_ROOT = _BRIDGE_PATHS.artifacts_root
RUNTIME_ROOT = _BRIDGE_PATHS.runtime_root
WORKDIR_ROOT = _BRIDGE_PATHS.workdir_root
EXTENSION_ROOT = _BRIDGE_PATHS.extension_root
RUNTIME_INSTANCE_ID = _BRIDGE_PATHS.runtime_instance_id


@dataclass(slots=True)
class CompiledRuntime:
    package: LoadedAgentPackage
    compiled: Any
    facade: RuntimeKernelFacade


@dataclass(slots=True)
class BridgeRuntimeState:
    sandbox_initialized: bool = False
    compiled_runtime: CompiledRuntime | None = None
    background_workers: RuntimeBackgroundWorkerManager = field(default_factory=RuntimeBackgroundWorkerManager)
    sandbox_lock: threading.Lock = field(default_factory=threading.Lock)
    compile_lock: threading.Lock = field(default_factory=threading.Lock)
    run_controls: RuntimeRunControlRegistry = field(default_factory=RuntimeRunControlRegistry)
    worker_threads: list[threading.Thread] = field(default_factory=list)

    def handle(self, command: dict[str, Any]) -> int:
        command_type = str(command.get("type") or "")
        request_id = command.get("request_id")
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
        normalizer = RuntimeEventNormalizer(
            emit=_write_event,
            request_id=str(request_id) if request_id else None,
            session_id=str(payload.get("session_id") or "") or None,
            mode="agent_package",
            graph_id="agent_runtime_bridge",
            producer_type="agent_runtime",
        )
        if command_type == "shutdown":
            self.shutdown()
            return 0
        if command_type == "cancel_runtime_request":
            reason = str(payload.get("reason") or "user_cancelled")
            target_request_id = str(payload.get("target_request_id") or "").strip() or None
            stopped = self.cancel_active_requests(
                reason=reason,
                request_id=target_request_id,
            )
            normalizer.runtime_event(
                "debug_patch",
                payload={
                    "source": "runtime_request_cancel",
                    "reason": reason,
                    "target_request_id": target_request_id,
                    "stopped_requests": stopped,
                },
            )
            return 0
        if command_type == "initialize_runtime":
            package: LoadedAgentPackage | None = None
            try:
                package = self._load_package()
                self._ensure_sandbox_initialized(normalizer)
                runtime = self._ensure_compiled(normalizer)
                normalizer.runtime_event(
                    "agent_package_instance_updated",
                    payload=_instance_status_payload(runtime=runtime, status="ready"),
                )
                return 0
            except Exception as exc:
                normalizer.runtime_event(
                    "agent_package_instance_updated",
                    severity="error",
                    payload=_instance_status_payload(
                        package=package,
                        status="failed",
                        error=f"{type(exc).__name__}: {exc}",
                    ),
                )
                return 1
        if command_type == "scheduler_manage":
            try:
                self._ensure_sandbox_initialized(normalizer)
                runtime = self._ensure_compiled(normalizer)
                _manage_scheduler(normalizer=normalizer, payload=payload, runtime=runtime)
                return 0
            except Exception as exc:
                normalizer.runtime_event(
                    "error",
                    severity="error",
                    message=f"{type(exc).__name__}: {exc}",
                    payload={"message": str(exc), "error_type": type(exc).__name__},
                )
                return 1
        normalizer.emit_run_started({"command": command_type, "attachment_count": _attachment_count(payload)})
        run_control = self._register_run_control(str(request_id or ""), command_type)
        if command_type == "list_sessions":
            return _list_sessions(normalizer, self._load_package())
        try:
            if command_type in {"run_message", "resume_interrupt", "run_harness"}:
                self._ensure_sandbox_initialized(normalizer)
                runtime = self._ensure_compiled(normalizer)
                if command_type == "run_message":
                    return _run_message(normalizer, payload, runtime, run_control=run_control)
                if command_type == "resume_interrupt":
                    return _resume_interrupt(normalizer, payload, runtime, run_control=run_control)
                return _run_harness(normalizer, payload, runtime)
            normalizer.runtime_event("error", severity="error", payload={"message": f"unknown command: {command_type}"})
            return 1
        finally:
            self._forget_run_control(str(request_id or ""), run_control)

    def start(self, command: dict[str, Any]) -> None:
        worker = threading.Thread(
            target=self._run_worker_command,
            args=(command,),
            name=f"agent-runtime-stdio-{command.get('request_id') or 'request'}",
            daemon=True,
        )
        self.worker_threads.append(worker)
        worker.start()

    def cancel_active_requests(
        self,
        *,
        reason: str = "user_cancelled",
        request_id: str | None = None,
    ) -> int:
        return self.run_controls.request_drain(reason=reason, request_id=request_id)

    def _register_run_control(self, request_id: str, command_type: str) -> RunControl | None:
        if command_type not in {"run_message", "resume_interrupt"} or not request_id:
            return None
        return self.run_controls.register(request_id)

    def _forget_run_control(self, request_id: str, control: RunControl | None) -> None:
        if control is None or not request_id:
            return
        self.run_controls.release(request_id, control)

    def _run_worker_command(self, command: dict[str, Any]) -> None:
        try:
            self.handle(command)
        except Exception as exc:
            _write_event(
                event(
                    "run_failed",
                    request_id=str(command.get("request_id") or "") or None,
                    mode="agent_package",
                    graph_id="agent_runtime_bridge",
                    severity="error",
                    payload={"message": f"{type(exc).__name__}: {exc}"},
                )
            )

    def _ensure_sandbox_initialized(self, normalizer: RuntimeEventNormalizer) -> None:
        if self.sandbox_initialized:
            return
        with self.sandbox_lock:
            if self.sandbox_initialized:
                return
            self._load_package()
            normalizer.runtime_event(
                "node_started",
                node_id="runtime_container",
                node_label="Local Runtime",
                node_kind="system",
                payload={
                    "package_root": str(PACKAGE_ROOT),
                    "runtime_root": str(RUNTIME_ROOT),
                    "image": None,
                    "network_policy": {},
                    "service_count": 0,
                },
            )
            normalizer.runtime_event(
                "node_completed",
                node_id="runtime_container",
                node_label="Local Runtime",
                node_kind="system",
                payload={"status": "ready"},
            )
            normalizer.runtime_event(
                "node_started",
                node_id="sandbox_init",
                node_label="Sandbox Init",
                node_kind="system",
                payload={"package_root": str(PACKAGE_ROOT)},
            )
            try:
                dependency_status = activate_runtime_dependencies()
            except RuntimeDependencyError as exc:
                normalizer.runtime_event(
                    "node_failed",
                    node_id="sandbox_init",
                    node_label="Sandbox Init",
                    node_kind="system",
                    severity="error",
                    payload={"status": "failed", "source": "dependency_pool", "message": str(exc)},
                )
                raise
            normalizer.runtime_event(
                "node_completed",
                node_id="sandbox_init",
                node_label="Sandbox Init",
                node_kind="system",
                payload={"status": "complete", **dependency_status},
            )
            self.sandbox_initialized = True

    def _ensure_compiled(self, normalizer: RuntimeEventNormalizer) -> CompiledRuntime:
        if self.compiled_runtime is not None:
            return self.compiled_runtime
        with self.compile_lock:
            if self.compiled_runtime is not None:
                return self.compiled_runtime
            normalizer.runtime_event(
                "node_started",
                node_id="package_compile",
                node_label="Package Compile",
                node_kind="system",
                payload={"manifest": str(PACKAGE_MANIFEST)},
            )
            package = self._load_package()
            facade = RuntimeKernelFacade.for_contract_runtime(
                session_config=AgentSessionConfig(root=RUNTIME_ROOT / "sessions"),
            )
            runtime_build = RuntimeBuildPlanner(registry=default_runtime_contract_registry()).build(
                package,
                base_services=facade.instance.services,
                runtime_root=RUNTIME_ROOT,
                runtime_instance_id=RUNTIME_INSTANCE_ID,
                instance_extension_root=EXTENSION_ROOT,
            )
            compiler = AgentAssemblyCompiler(facade=facade)
            compiled = compiler.compile(package.assembly_spec, runtime_build=runtime_build)
            self.compiled_runtime = CompiledRuntime(package=package, compiled=compiled, facade=facade)
            _configure_scheduler_runtime(package=package, compiled=compiled, facade=facade)
            _configure_knowledge_runtime(compiled=compiled)
            _apply_scheduler_seeds(package=package, compiled=compiled)
            self.background_workers.add_many(runtime_build.background_workers)
            for lifecycle_event in self.background_workers.start_all():
                if lifecycle_event.status == "failed":
                    _emit_worker_lifecycle_failure(package=package, lifecycle_event=lifecycle_event)
            normalizer.runtime_event(
                "node_completed",
                node_id="package_compile",
                node_label="Package Compile",
                node_kind="system",
                payload={"agent_id": package.assembly_spec.agent.id, "package_id": package.package_root.name},
            )
            return self.compiled_runtime

    def _load_package(self) -> LoadedAgentPackage:
        return _load_package()

    def shutdown(self) -> None:
        for lifecycle_event in self.background_workers.shutdown_all():
            if lifecycle_event.status == "failed" and self.compiled_runtime is not None:
                _emit_worker_lifecycle_failure(
                    package=self.compiled_runtime.package,
                    lifecycle_event=lifecycle_event,
                )


def main() -> int:
    state = BridgeRuntimeState()
    _write_event(
        event(
            "runtime_ready",
            mode="agent_package",
            graph_id="agent_runtime_bridge",
            producer_type="agent_runtime",
            payload={"status": "ready", "transport": "stdio"},
        )
    )
    for line in sys.stdin:
        if _STDOUT_WRITER.closed:
            break
        if not line.strip():
            continue
        try:
            command = json.loads(line)
            if not isinstance(command, dict):
                raise ValueError("command must be a JSON object")
        except Exception as exc:
            _write_event(event("error", mode="agent_package", payload={"message": f"invalid command: {exc}"}))
            continue
        if str(command.get("type") or "") == "shutdown":
            state.shutdown()
            break
        command_type = str(command.get("type") or "")
        request_id = str(command.get("request_id") or "") or None
        _write_event(
            event(
                "node_progress",
                request_id=request_id,
                mode="agent_package",
                graph_id="agent_runtime_bridge",
                producer_type="agent_runtime",
                node_id="runtime_container",
                node_label="Local Runtime",
                node_kind="system",
                payload={"status": "command_received", "command_type": command_type},
            )
        )
        if command_type == "cancel_runtime_request":
            state.handle(command)
        else:
            state.start(command)
        if _STDOUT_WRITER.closed:
            break
    return 0


def _configure_scheduler_runtime(*, package: LoadedAgentPackage, compiled: Any, facade: RuntimeKernelFacade) -> None:
    scheduler_runtime = getattr(compiled.compiled_app.services, "scheduler_runtime", None)
    if scheduler_runtime is None:
        return
    tool_registry = getattr(compiled.compiled_app.services, "tool_registry", None)
    scheduler_runtime.event_sink = _scheduler_event_sink_for_package(package)
    scheduler_runtime.executor = SchedulerExecutor(
        graph_runner=_scheduled_graph_runner(package=package, compiled=compiled, facade=facade),
        tool_runner=runtime_tool_runner(tool_registry) if tool_registry is not None else None,
    )


def _configure_knowledge_runtime(*, compiled: Any) -> None:
    knowledge_runtime = getattr(compiled.compiled_app.services, "knowledge_runtime", None)
    if knowledge_runtime is None:
        return
    knowledge_runtime.event_sink = _knowledge_event_sink


def _apply_scheduler_seeds(*, package: LoadedAgentPackage, compiled: Any) -> None:
    scheduler_runtime = getattr(compiled.compiled_app.services, "scheduler_runtime", None)
    if scheduler_runtime is None:
        return
    contract = package.contracts.get("scheduler_seed") if isinstance(package.contracts, dict) else None
    package_id = package.manifest.factory_run_id or package.package_root.name
    apply_scheduler_seed_contract(
        runtime=scheduler_runtime,
        contract_payload=contract if isinstance(contract, dict) else None,
        package_id=package_id,
    )


def _emit_worker_lifecycle_failure(*, package: LoadedAgentPackage, lifecycle_event: WorkerLifecycleEvent) -> None:
    _emit_scheduler_event(
        SchedulerEventPayload(
            event_type="scheduler_run_failed",
            owner_type="agent",
            owner_id=package.assembly_spec.agent.id,
            status="failed",
            error_summary=(
                f"background worker {lifecycle_event.action} failed: "
                f"{lifecycle_event.worker_id}: {lifecycle_event.message}"
            ),
        ),
        package=package,
    )


def _scheduled_graph_runner(*, package: LoadedAgentPackage, compiled: Any, facade: RuntimeKernelFacade):
    def run(job, run_record) -> dict[str, Any]:
        payload = dict(job.target.payload)
        message = str(payload.get("message") or "").strip()
        session_config = dict(compiled.runtime_config["session_config"])
        session_config["session_id"] = scheduler_run_session_id(
            job,
            run_record,
            namespace=f"agent_package:{package.package_root.name}",
        )
        session_config["session_kind"] = "scheduler"
        session_config["visible_in_agent_session_list"] = False
        session_config["create_session_if_missing"] = True
        normalizer = RuntimeEventNormalizer(
            emit=_write_event,
            request_id=None,
            session_id=None,
            mode="agent_package",
            graph_id="agent_package_scheduler",
            producer_type="agent_runtime",
        )
        normalizer.emit_run_started(
            {
                "command": "scheduler_graph_run",
                "job_id": job.job_id,
                "scheduler_run_id": run_record.run_id,
                "package_id": package.package_root.name,
                "agent_id": package.assembly_spec.agent.id,
            }
        )
        run_context = facade.prepare_run_context(
            compiled.compiled_app,
            user_input=message,
            user_config=scheduler_run_user_config(
                job,
                compiled.runtime_config["user_config"],
            ),
            agent_config=compiled.runtime_config["agent_config"],
            session_config=session_config,
        )
        run_context.state.execution.max_retries = scheduler_run_max_retries(
            job,
            run_context.state.execution.max_retries,
        )
        run_context.state.execution.timeout_seconds = scheduler_run_timeout_seconds(
            job,
            run_context.state.execution.timeout_seconds,
        )
        normalizer.session_id = run_context.session_id
        final_state = None
        interrupted = False
        with scheduler_tool_approval_override(job=job, tool_id="graph_run"):
            for stream_mode, chunk in facade.instance.controller.stream(
                compiled.compiled_app,
                run_context.state,
                thread_id=run_context.thread_id,
            ):
                if _handle_stream_item(normalizer, stream_mode, chunk):
                    interrupted = True
                    break
                if stream_mode == "runtime_final":
                    final_state = chunk
        if interrupted:
            normalizer.emit_run_failed(RuntimeError("scheduled graph run requires interrupt handling"))
            return {"status": "failed", "error": "scheduled graph run requires interrupt handling"}
        if final_state is None:
            normalizer.emit_run_failed(RuntimeError("scheduled graph run did not produce a final state"))
            return {"status": "failed", "error": "scheduled graph run did not produce a final state"}
        if not runtime_completed(final_state):
            error = runtime_error_message(final_state, command="scheduler_graph_run")
            normalizer.emit_run_failed(RuntimeError(error))
            return {"status": "failed", "error": error}
        visible_output = normalizer.complete_visible_assistant_output_from_state(final_state, reason="run_completed")
        final_answer = visible_output.content or session_final_answer(final_state)
        agent_session = run_context.session_manager.touch_turn(
            run_context.session_id,
            first_user_input=run_context.first_user_input,
            user_input=run_context.first_user_input,
            reasoning_content=visible_output.reasoning_content or session_reasoning_content(final_state),
            final_answer=final_answer,
            status=final_state.execution.finish_status,
            trace_ref=session_trace_ref(compiled, final_state),
        )
        normalizer.emit_run_completed(
            {
                "status": final_state.execution.finish_status,
                "command": "scheduler_graph_run",
                "package_id": package.package_root.name,
                "agent_id": package.assembly_spec.agent.id,
                "agent_session": agent_session.model_dump(mode="json"),
            }
        )
        return {
            "status": final_state.execution.finish_status or "completed",
            "final_answer": final_answer,
            "output_summary": final_answer,
        }

    return run


def _scheduler_event_sink_for_package(package: LoadedAgentPackage):
    def emit(payload: SchedulerEventPayload) -> None:
        _emit_scheduler_event(payload, package=package)

    return emit


def _emit_scheduler_event(payload: SchedulerEventPayload, *, package: LoadedAgentPackage) -> None:
    normalizer = RuntimeEventNormalizer(
        emit=_write_event,
        request_id=None,
        session_id=None,
        mode="agent_package",
        graph_id="agent_package_scheduler",
        producer_type="agent_runtime",
    )
    value = payload.model_dump(mode="json")
    value["package_id"] = package.package_root.name
    value["package_name"] = package.assembly_spec.agent.name
    value["agent_id"] = package.assembly_spec.agent.id
    normalizer.emit_custom_event({"type": "scheduler_event", "payload": value})


def _knowledge_event_sink(payload: dict[str, Any]) -> None:
    normalizer = RuntimeEventNormalizer(
        emit=_write_event,
        request_id=None,
        session_id=None,
        mode="agent_package",
        graph_id="agent_package_knowledge",
        producer_type="agent_runtime",
    )
    normalizer.emit_custom_event({"type": "knowledge_event", "payload": _normalized_knowledge_payload(payload)})


def _instance_status_payload(
    *,
    status: str,
    runtime: CompiledRuntime | None = None,
    package: LoadedAgentPackage | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    resolved_package = runtime.package if runtime is not None else package
    payload = {
        "package_id": resolved_package.package_root.name if resolved_package is not None else PACKAGE_ROOT.name,
        "agent_id": resolved_package.assembly_spec.agent.id if resolved_package is not None else PACKAGE_ROOT.name,
        "agent_name": resolved_package.assembly_spec.agent.name if resolved_package is not None else PACKAGE_ROOT.name,
        "backend": "local",
        "status": status,
        "ready": status == "ready",
    }
    if error:
        payload["error"] = error
    return payload


def _manage_scheduler(
    *,
    normalizer: RuntimeEventNormalizer,
    payload: dict[str, Any],
    runtime: CompiledRuntime,
) -> None:
    scheduler_runtime = getattr(runtime.compiled.compiled_app.services, "scheduler_runtime", None)
    if scheduler_runtime is None:
        raise RuntimeError("scheduler runtime is not enabled for this package")
    tool_registry = getattr(runtime.compiled.compiled_app.services, "tool_registry", None)
    manage_scheduler_runtime(
        runtime=scheduler_runtime,
        payload=payload,
        tool_registry=tool_registry,
        emit=lambda scheduler_payload: normalizer.emit_custom_event(
            {"type": "scheduler_event", "payload": _scheduler_event_payload(scheduler_payload, runtime.package)}
        ),
    )


def _scheduler_event_payload(payload: SchedulerEventPayload, package: LoadedAgentPackage) -> dict[str, Any]:
    value = payload.model_dump(mode="json")
    value["package_id"] = package.package_root.name
    value["package_name"] = package.assembly_spec.agent.name
    value["agent_id"] = package.assembly_spec.agent.id
    return value


def _run_message(
    normalizer: RuntimeEventNormalizer,
    payload: dict[str, Any],
    runtime: CompiledRuntime,
    *,
    run_control: RunControl | None = None,
) -> int:
    message = str(payload.get("message") or "").strip()
    if not message and not has_attachment_payload(payload.get("attachments")):
        normalizer.emit_run_failed(ValueError("run_message requires payload.message"))
        return 1
    package = runtime.package
    compiled = runtime.compiled
    facade = runtime.facade
    session_config = dict(compiled.runtime_config["session_config"])
    if payload.get("session_id"):
        session_config["session_id"] = str(payload["session_id"])
    apply_runtime_workspace(session_config, payload, workdir_root=WORKDIR_ROOT)
    user_config = merge_attachments_into_user_config(
        {**compiled.runtime_config["user_config"], **(payload.get("user_config") if isinstance(payload.get("user_config"), dict) else {})},
        payload.get("attachments"),
    )
    run_context = facade.prepare_run_context(
        compiled.compiled_app,
        user_input=message,
        user_config=user_config,
        agent_config=compiled.runtime_config["agent_config"],
        session_config=session_config,
    )
    request_policy = RuntimeRequestPolicy.from_payload(payload.get("runtime_request"))
    run_context.state.execution.timeout_seconds = 0
    run_context.state.execution.max_retries = request_policy.max_retries
    normalizer.session_id = run_context.session_id
    if _emit_pending_checkpoint_interrupt(normalizer, compiled.compiled_app, run_context.thread_id):
        return 0
    repair_incomplete_message_checkpoint(
        graph_app=compiled.compiled_app.graph_app,
        thread_id=run_context.thread_id,
    )
    run_context.session_manager.touch_turn(
        run_context.session_id,
        request_id=normalizer.request_id,
        first_user_input=run_context.first_user_input,
        user_input=run_context.first_user_input,
        attachments=user_config.get("attachments"),
        status="running",
    )
    final_state = None
    graph_drained = False
    stream_iter = facade.instance.controller.stream(
        compiled.compiled_app,
        run_context.state,
        thread_id=run_context.thread_id,
        control=run_control,
    )
    try:
        for stream_mode, chunk in stream_iter:
            if _handle_stream_item(normalizer, stream_mode, chunk):
                return 0
            if stream_mode == "runtime_final":
                final_state = chunk
    except GraphDrained:
        graph_drained = True
    finally:
        close = getattr(stream_iter, "close", None)
        if callable(close):
            close()
    if graph_drained or bool(run_control and run_control.drain_requested):
        return _emit_stopped_runtime(
            normalizer,
            run_context,
            compiled,
            package=package,
            command="run_message",
            request_id=normalizer.request_id,
            fallback_user_input=run_context.first_user_input,
            fallback_attachments=user_config.get("attachments"),
            stop_reason=run_control.drain_reason if run_control else None,
        )
    if final_state is None:
        normalizer.emit_run_failed(RuntimeError("agent runtime did not produce a final state"))
        return 1
    if not runtime_completed(final_state):
        agent_session = _touch_session_turn_from_final_state(
            run_context,
            compiled,
            final_state,
            request_id=normalizer.request_id,
            fallback_user_input=run_context.first_user_input,
            fallback_attachments=user_config.get("attachments"),
        )
        return _emit_failed_runtime_final(
            normalizer,
            final_state,
            command="run_message",
            package=package,
            agent_session=agent_session.model_dump(mode="json"),
        )
    visible_output = normalizer.complete_visible_assistant_output_from_state(final_state, reason="run_completed")
    agent_session = _touch_session_turn_from_final_state(
        run_context,
        compiled,
        final_state,
        request_id=normalizer.request_id,
        fallback_user_input=run_context.first_user_input,
        fallback_attachments=user_config.get("attachments"),
        visible_output=visible_output,
    )
    normalizer.emit_run_completed(
        {
            "status": final_state.execution.finish_status,
            "command": "run_message",
            "package_id": package.package_root.name,
            "agent_id": package.assembly_spec.agent.id,
            "agent_session": agent_session.model_dump(mode="json"),
        }
    )
    return 0


def _emit_pending_checkpoint_interrupt(normalizer: RuntimeEventNormalizer, compiled_app: Any, thread_id: str) -> bool:
    try:
        snapshot = compiled_app.graph_app.get_state({"configurable": {"thread_id": thread_id}})
    except Exception:
        return False
    interrupts = tuple(getattr(snapshot, "interrupts", ()) or ())
    if not interrupts:
        return False
    first = interrupts[0]
    normalizer.emit_interrupt(json_safe(interrupt_payload(first)))
    return True


def _resume_interrupt(
    normalizer: RuntimeEventNormalizer,
    payload: dict[str, Any],
    runtime: CompiledRuntime,
    *,
    run_control: RunControl | None = None,
) -> int:
    session_id = str(payload.get("session_id") or "").strip()
    resume_payload = payload.get("resume_payload")
    if not session_id:
        normalizer.emit_run_failed(ValueError("resume_interrupt requires payload.session_id"))
        return 1
    package = runtime.package
    compiled = runtime.compiled
    facade = runtime.facade
    session_config = dict(compiled.runtime_config["session_config"])
    session_config["session_id"] = session_id
    apply_runtime_workspace(session_config, payload, workdir_root=WORKDIR_ROOT)
    normalizer.session_id = session_id
    normalizer.emit_runtime_resumed(resume_payload if isinstance(resume_payload, dict) else {})
    run_context = facade.prepare_resume_context(
        compiled.compiled_app,
        session_id=session_id,
        session_config=session_config,
    )
    request_policy = RuntimeRequestPolicy.from_payload(payload.get("runtime_request"))
    run_context.state.execution.timeout_seconds = 0
    run_context.state.execution.max_retries = request_policy.max_retries
    final_state = None
    graph_drained = False
    stream_iter = facade.instance.controller.stream_resume(
        compiled.compiled_app,
        run_context.state,
        thread_id=run_context.thread_id,
        resume_payload=resume_payload if isinstance(resume_payload, dict) else {},
        control=run_control,
    )
    try:
        for stream_mode, chunk in stream_iter:
            if _handle_stream_item(normalizer, stream_mode, chunk):
                return 0
            if stream_mode == "runtime_final":
                final_state = chunk
    except GraphDrained:
        graph_drained = True
    finally:
        close = getattr(stream_iter, "close", None)
        if callable(close):
            close()
    if graph_drained or bool(run_control and run_control.drain_requested):
        return _emit_stopped_runtime(
            normalizer,
            run_context,
            compiled,
            package=package,
            command="resume_interrupt",
            request_id=run_context.session_turn_request_id,
            session_id=session_id,
            fallback_user_input=resume_user_input(resume_payload) or run_context.first_user_input,
            stop_reason=run_control.drain_reason if run_control else None,
        )
    if final_state is None:
        normalizer.emit_run_failed(RuntimeError("agent runtime resume did not produce a final state"))
        return 1
    if not runtime_completed(final_state):
        agent_session = _touch_session_turn_from_final_state(
            run_context,
            compiled,
            final_state,
            request_id=run_context.session_turn_request_id,
            session_id=session_id,
            fallback_user_input=resume_user_input(resume_payload) or run_context.first_user_input,
        )
        return _emit_failed_runtime_final(
            normalizer,
            final_state,
            command="resume_interrupt",
            package=package,
            agent_session=agent_session.model_dump(mode="json"),
        )
    visible_output = normalizer.complete_visible_assistant_output_from_state(final_state, reason="run_completed")
    agent_session = _touch_session_turn_from_final_state(
        run_context,
        compiled,
        final_state,
        request_id=run_context.session_turn_request_id,
        session_id=session_id,
        fallback_user_input=resume_user_input(resume_payload) or run_context.first_user_input,
        visible_output=visible_output,
    )
    normalizer.emit_run_completed(
        {
            "status": "completed",
            "command": "resume_interrupt",
            "package_id": package.package_root.name,
            "agent_id": package.assembly_spec.agent.id,
            "agent_session": agent_session.model_dump(mode="json"),
        }
    )
    return 0


def _list_sessions(normalizer: RuntimeEventNormalizer, package: LoadedAgentPackage) -> int:
    session_root = RUNTIME_ROOT / "sessions"
    sessions = []
    for path in sorted(session_root.glob("*.json")):
        try:
            sessions.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    normalizer.runtime_event(
        "agent_package_sessions_listed",
        payload={"package_id": package.package_root.name, "sessions": sessions},
    )
    return 0


def _run_harness(normalizer: RuntimeEventNormalizer, payload: dict[str, Any], runtime: CompiledRuntime) -> int:
    plan = payload.get("execution_plan") if isinstance(payload.get("execution_plan"), dict) else {}
    compiled = runtime.compiled
    facade = runtime.facade
    result = {
        "dependency_results": [json.loads((ARTIFACTS_ROOT / "dependency_report.json").read_text(encoding="utf-8"))],
        "scenario_results": [],
        "tool_test_results": [],
        "errors": [],
    }
    for scenario in plan.get("scenarios") or []:
        input_text = str(scenario.get("input_text") or "")
        if not input_text:
            continue
        run_context = facade.prepare_run_context(
            compiled.compiled_app,
            user_input=input_text,
            user_config=compiled.runtime_config["user_config"],
            agent_config=compiled.runtime_config["agent_config"],
            session_config=compiled.runtime_config["session_config"],
        )
        final_state = None
        for stream_mode, chunk in facade.instance.controller.stream(
            compiled.compiled_app,
            run_context.state,
            thread_id=run_context.thread_id,
        ):
            _handle_stream_item(normalizer, stream_mode, chunk)
            if stream_mode == "runtime_final":
                final_state = chunk
        result["scenario_results"].append(
            {
                "scenario_id": scenario.get("scenario_id"),
                "status": getattr(getattr(final_state, "execution", None), "finish_status", "failed") if final_state else "failed",
                "final_answer": getattr(getattr(final_state, "conversation", None), "final_answer", None) if final_state else None,
            }
        )
    _run_harness_tool_tests(compiled, plan, result)
    (ARTIFACTS_ROOT / "sandbox_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    normalizer.emit_run_completed({"status": "failed" if result["errors"] else "passed", "command": "run_harness"})
    return 1 if result["errors"] else 0


def _run_harness_tool_tests(compiled: Any, plan: dict[str, Any], result: dict[str, Any]) -> None:
    registry = compiled.compiled_app.services.tool_registry
    if registry is None:
        return

    state = RuntimeState()
    for item in plan.get("tool_tests") or []:
        tool_id = str(item.get("tool_id") or "")
        if not tool_id:
            continue
        try:
            output = registry.execute(tool_id, dict(item.get("arguments") or {}), state=state)
            result["tool_test_results"].append({"tool_id": tool_id, **output.model_dump(mode="json")})
            if output.status != "completed":
                result["errors"].append({"where": f"tool_test.{tool_id}", "why": "tool_failed", "message": output.error or output.observation_summary or "tool failed", "evidence": output.model_dump(mode="json")})
        except Exception as exc:
            result["errors"].append({"where": f"tool_test.{tool_id}", "why": "tool_failed", "message": f"{type(exc).__name__}: {exc}", "evidence": {}})


def _load_package() -> LoadedAgentPackage:
    package = AgentPackageLoader().load_path(PACKAGE_MANIFEST)
    return host_runtime_package_view(
        package,
        runtime_root=RUNTIME_ROOT,
        artifacts_root=ARTIFACTS_ROOT,
        workdir_root=WORKDIR_ROOT,
        extension_root=EXTENSION_ROOT,
    )


def _handle_stream_item(normalizer: RuntimeEventNormalizer, stream_mode: str, chunk: Any) -> bool:
    interrupt_payload = _extract_interrupt_payload(chunk)
    if interrupt_payload is not None:
        normalizer.emit_interrupt(json_safe(interrupt_payload))
        return True
    normalizer.emit_stream_item(stream_mode, chunk, updates_payload_key="agent_package_update")
    return False


def _touch_session_turn_from_final_state(
    run_context: Any,
    compiled: Any,
    final_state: Any,
    *,
    request_id: str | None = None,
    session_id: str | None = None,
    fallback_user_input: str | None = None,
    fallback_attachments: Any = None,
    visible_output: VisibleAssistantMessage | None = None,
) -> Any:
    session_user_input = session_user_input_from_state(
        final_state,
        fallback_user_input=fallback_user_input or run_context.first_user_input,
    )
    session_attachments = session_attachments_from_state(
        final_state,
        fallback_attachments=fallback_attachments,
    )
    final_answer = (visible_output.content if visible_output else None) or session_final_answer(final_state)
    reasoning_content = (
        (visible_output.reasoning_content if visible_output else None)
        or session_reasoning_content(final_state)
    )
    return run_context.session_manager.touch_turn(
        session_id or run_context.session_id,
        request_id=request_id,
        first_user_input=session_user_input,
        user_input=session_user_input,
        attachments=session_attachments,
        reasoning_content=reasoning_content,
        final_answer=final_answer,
        status=getattr(getattr(final_state, "execution", None), "finish_status", None),
        trace_ref=session_trace_ref(compiled, final_state),
    )


def _emit_stopped_runtime(
    normalizer: RuntimeEventNormalizer,
    run_context: Any,
    compiled: Any,
    *,
    package: LoadedAgentPackage,
    command: str,
    request_id: str | None = None,
    session_id: str | None = None,
    fallback_user_input: str | None = None,
    fallback_attachments: Any = None,
    stop_reason: str | None = None,
) -> int:
    normalizer.complete_open_model_streams(reason="user_stopped")
    drained_checkpoint = finalize_drained_runtime_checkpoint(
        compiled_app=compiled.compiled_app,
        thread_id=run_context.thread_id,
        base_state=run_context.state,
        fallback_user_input=fallback_user_input or run_context.first_user_input,
        stop_reason=stop_reason or "user_cancelled",
    )
    visible_output = normalizer.visible_assistant_output
    agent_session = run_context.session_manager.touch_turn(
        session_id or run_context.session_id,
        request_id=request_id,
        first_user_input=fallback_user_input or run_context.first_user_input,
        user_input=fallback_user_input or run_context.first_user_input,
        attachments=fallback_attachments,
        reasoning_content=(
            visible_output.reasoning_content
            or drained_checkpoint.state.conversation.reasoning_content
        ),
        final_answer=(
            visible_output.content
            or drained_checkpoint.state.conversation.final_answer
        ),
        status="stopped",
        trace_ref=session_trace_ref(compiled, drained_checkpoint.state),
    )
    normalizer.emit_run_completed(
        {
            "status": "stopped",
            "command": command,
            "package_id": package.package_root.name,
            "agent_id": package.assembly_spec.agent.id,
            "agent_session": agent_session.model_dump(mode="json"),
        }
    )
    return 0


def _emit_failed_runtime_final(
    normalizer: RuntimeEventNormalizer,
    final_state: Any,
    *,
    command: str,
    package: LoadedAgentPackage | None = None,
    agent_session: dict[str, Any] | None = None,
) -> int:
    extra_payload: dict[str, Any] = {
        "status": getattr(getattr(final_state, "execution", None), "finish_status", None) or "failed",
        "command": command,
    }
    if package is not None:
        extra_payload.update(
            {
                "package_id": package.package_root.name,
                "agent_id": package.assembly_spec.agent.id,
            }
        )
    if agent_session is not None:
        extra_payload["agent_session"] = agent_session
    normalizer.complete_open_model_streams(reason="run_failed")
    normalizer.emit_run_failed(RuntimeError(runtime_error_message(final_state, command=command)), extra_payload)
    return 1


def _extract_interrupt_payload(chunk: Any) -> Any | None:
    if not isinstance(chunk, dict):
        return None
    interrupts = chunk.get("__interrupt__")
    if not interrupts:
        return None
    first = interrupts[0]
    return interrupt_payload(first)


def _normalized_knowledge_payload(payload: dict[str, Any]) -> dict[str, Any]:
    event_type = str(payload.get("event_type") or "")
    if event_type in KNOWLEDGE_EVENT_TYPES:
        return payload
    return {**payload, "event_type": "knowledge_ingestion_progress"}


def _attachment_count(payload: dict[str, Any]) -> int:
    attachments = payload.get("attachments")
    return len(attachments) if isinstance(attachments, list) else 0


def _write_event(item: FactoryFrontendEvent) -> None:
    _STDOUT_WRITER.write(item)


class _JsonLineWriter:
    def __init__(self) -> None:
        self.closed = False
        self._lock = threading.Lock()

    def write(self, item: FactoryFrontendEvent) -> None:
        if self.closed:
            return
        with self._lock:
            if self.closed:
                return
            try:
                sys.stdout.write(item.model_dump_json() + "\n")
                sys.stdout.flush()
            except BrokenPipeError:
                self.closed = True
            except OSError as exc:
                if exc.errno != errno.EPIPE:
                    raise
                self.closed = True


def _runtime_path(value: str) -> Path:
    raw = str(value or "").strip() or ".agent_runtime"
    if raw == "/runtime":
        return RUNTIME_ROOT
    if raw.startswith("/runtime/"):
        return RUNTIME_ROOT / raw.removeprefix("/runtime/")
    if raw == ".agent_runtime":
        return RUNTIME_ROOT
    if raw.startswith(".agent_runtime/"):
        return RUNTIME_ROOT / raw.removeprefix(".agent_runtime/")
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return PACKAGE_ROOT / path


_STDOUT_WRITER = _JsonLineWriter()


if __name__ == "__main__":
    raise SystemExit(main())
