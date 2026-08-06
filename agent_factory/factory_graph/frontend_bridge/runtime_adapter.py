from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

from agent_factory.env import load_agentfactory_dotenv
from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentPackageRuntimeManager
from agent_factory.create_agent.runtime import CreateAgentRuntime
from agent_factory.evolution import AgentEvolutionRuntime
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand, FactoryMode, event
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_agent_packages import RuntimeAgentPackageCommandMixin
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_resources import RuntimeResourceCommandMixin
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_scheduler import RuntimeSchedulerCommandMixin
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_sessions import RuntimeSessionCommandMixin
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_types import (
    Emit,
    FactoryBridgeOptions,
    PendingAgentPackageRun,
    PendingCreateAgentRun,
    PendingEvolutionRun,
)
from agent_factory.factory_graph.session import FactorySessionManager
from agent_factory.memory_system.factory import shutdown_factory_memory_worker
from agent_factory.runtime_kernel.background_workers import RuntimeBackgroundWorkerManager
from agent_factory.scheduler_system import SchedulerRuntime


@dataclass(slots=True)
class RuntimeCommandContext:
    session_record: Any | None
    mode: FactoryMode | None


_NAVIGATION_COMMAND_TYPES = frozenset(
    {
        "start_session",
        "switch_session",
        "new_session",
        "delete_session",
        "set_mode",
        "select_agent_package",
    }
)

@dataclass(slots=True)
class FactoryRuntimeAdapter(
    RuntimeSessionCommandMixin,
    RuntimeAgentPackageCommandMixin,
    RuntimeResourceCommandMixin,
    RuntimeSchedulerCommandMixin,
):
    emit: Emit
    session_manager: FactorySessionManager | None = None
    checkpointer: Any = None
    checkpointer_handle: Any = None
    options: FactoryBridgeOptions = field(default_factory=FactoryBridgeOptions)
    _session_record: Any | None = None
    _mode: FactoryMode | None = None
    _command_context: ContextVar[RuntimeCommandContext | None] = field(
        default_factory=lambda: ContextVar("factory_runtime_command_context", default=None),
    )
    _navigation_lock: RLock = field(default_factory=RLock)
    _state_lock: RLock = field(default_factory=RLock)
    pending_agent_package_runs: dict[tuple[str, str], PendingAgentPackageRun] = field(default_factory=dict)
    pending_agent_package_runs_lock: RLock = field(default_factory=RLock)
    pending_agent_group_runs: dict[str, PendingAgentPackageRun] = field(default_factory=dict)
    pending_create_agent_run: PendingCreateAgentRun | None = None
    pending_evolution_run: PendingEvolutionRun | None = None
    agent_package_runtime: AgentPackageRuntimeManager | None = None
    create_agent_runtime: CreateAgentRuntime | None = None
    evolution_runtime: AgentEvolutionRuntime | None = None
    evolution_package_id: str | None = None
    scheduler_runtime: SchedulerRuntime | None = None
    background_workers: RuntimeBackgroundWorkerManager | None = None

    def __post_init__(self) -> None:
        load_agentfactory_dotenv()
        if self.session_manager is None:
            self.session_manager = FactorySessionManager.from_env()
        if self.agent_package_runtime is None:
            self.agent_package_runtime = AgentPackageRuntimeManager()
        if self.create_agent_runtime is None:
            self.create_agent_runtime = CreateAgentRuntime()
        if self.evolution_runtime is None:
            self.evolution_runtime = AgentEvolutionRuntime(
                package_restart_handler=(
                    lambda package_id, request_id: self.agent_package_runtime.restart_package_instance(
                        package_id,
                        request_id=request_id,
                    )
                )
            )
        self.agent_package_runtime.set_emit(self.emit)

    @property
    def session_record(self) -> Any | None:
        context = self._command_context.get()
        return context.session_record if context is not None else self._session_record

    @session_record.setter
    def session_record(self, value: Any | None) -> None:
        context = self._command_context.get()
        if context is not None:
            context.session_record = value
            return
        with self._state_lock:
            self._session_record = value

    @property
    def mode(self) -> FactoryMode | None:
        context = self._command_context.get()
        return context.mode if context is not None else self._mode

    @mode.setter
    def mode(self, value: FactoryMode | None) -> None:
        context = self._command_context.get()
        if context is not None:
            context.mode = value
            return
        with self._state_lock:
            self._mode = value

    def handle(self, command: FactoryFrontendCommand) -> bool:
        if command.type in _NAVIGATION_COMMAND_TYPES:
            with self._navigation_lock:
                return self._handle_with_command_context(command)
        return self._handle_with_command_context(command)

    def _handle_with_command_context(self, command: FactoryFrontendCommand) -> bool:
        with self._state_lock:
            context = RuntimeCommandContext(
                session_record=self._session_record,
                mode=self._mode,
            )
        token = self._command_context.set(context)
        try:
            if command.type == "shutdown":
                if self.agent_package_runtime is not None:
                    self.agent_package_runtime.close_all()
                self._shutdown_background_workers()
                shutdown_factory_memory_worker()
                return False
            handler = _COMMAND_HANDLERS.get(command.type)
            if handler is None:
                self._emit_error(command, f"unsupported command: {command.type}")
                return True
            getattr(self, handler)(command)
        except Exception as exc:
            self.emit(
                event(
                    "error",
                    request_id=command.request_id,
                    session_id=self._session_id(),
                    mode=self.mode,
                    message=f"{type(exc).__name__}: {exc}",
                )
            )
        finally:
            self._commit_command_context(command, context)
            self._command_context.reset(token)
        return True

    def _commit_command_context(
        self,
        command: FactoryFrontendCommand,
        context: RuntimeCommandContext,
    ) -> None:
        context_session_id = _record_session_id(context.session_record)
        with self._state_lock:
            current_session_id = _record_session_id(self._session_record)
            if command.type in _NAVIGATION_COMMAND_TYPES:
                self._session_record = context.session_record
                self._mode = context.mode
                return
            if context_session_id and context_session_id == current_session_id:
                self._session_record = context.session_record
                self._mode = context.mode


def _record_session_id(record: Any | None) -> str:
    return str(getattr(record, "session_id", "") or "").strip()


_COMMAND_HANDLERS: dict[str, str] = {
    "start_session": "start_session",
    "list_sessions": "list_sessions",
    "switch_session": "switch_session",
    "new_session": "new_session",
    "delete_session": "delete_session",
    "set_mode": "set_mode",
    "send_message": "send_message",
    "workspace_manage": "workspace_manage",
    "knowledge_manage": "knowledge_manage",
    "extensions_manage": "extensions_manage",
    "scheduler_manage": "scheduler_manage",
    "list_agent_packages": "list_agent_packages",
    "select_agent_package": "select_agent_package",
    "delete_agent_package": "delete_agent_package",
    "initialize_agent_package": "initialize_agent_package",
    "shutdown_agent_package_instance": "shutdown_agent_package_instance",
    "list_agent_package_instances": "list_agent_package_instances",
    "list_agent_package_sessions": "list_agent_package_sessions",
    "load_agent_package_session": "load_agent_package_session",
    "delete_agent_package_session": "delete_agent_package_session",
    "send_agent_package_message": "send_agent_package_message",
    "run_agent_package": "run_agent_package",
    "run_agent_group_member": "run_agent_group_member",
    "run_agent_evolution": "run_agent_evolution",
    "resume_interrupt": "resume_interrupt",
    "cancel_runtime_request": "cancel_runtime_request",
}
