from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_factory.memory_system.namespace import agent_memory_namespace
from agent_factory.runtime_kernel.kernel.models import CompiledKernelApp
from agent_factory.runtime_kernel.session import AgentSessionConfig, AgentSessionManager
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_kernel.state_contracts import PackageStateManager


@dataclass(slots=True)
class RuntimeKernelRunContext:
    state: RuntimeState
    thread_id: str
    session_manager: AgentSessionManager
    session_id: str
    first_user_input: str
    session_turn_request_id: str | None = None


def configure_memory_runtime_for_agent(services, agent_id: str) -> None:
    runtime = getattr(services, "memory_system", None)
    if runtime is None:
        return
    runtime.scope = "agent"
    runtime.namespace = agent_memory_namespace(agent_id)
    runtime.agent_id = agent_id


def session_manager_from_config(session_config: dict, *, default: AgentSessionManager) -> AgentSessionManager:
    root = session_config.get("session_root")
    if root:
        return AgentSessionManager(AgentSessionConfig(root=Path(str(root))))
    return default


def initial_package_state(compiled: CompiledKernelApp) -> dict[str, object]:
    manager = compiled.metadata.get("package_state_manager")
    if isinstance(manager, PackageStateManager):
        return manager.initial_state()
    return {}


def state_for_new_turn(compiled: CompiledKernelApp, *, thread_id: str) -> RuntimeState:
    state = checkpoint_runtime_state(compiled, thread_id=thread_id) or RuntimeState()
    state.package_state = merge_package_state_defaults(
        initial_package_state(compiled),
        state.package_state,
    )
    return state


def checkpoint_runtime_state(compiled: CompiledKernelApp, *, thread_id: str) -> RuntimeState | None:
    try:
        snapshot = compiled.graph_app.get_state({"configurable": {"thread_id": thread_id}})
    except Exception:
        return None
    values = getattr(snapshot, "values", {}) or {}
    if not isinstance(values, dict):
        return None
    runtime = values.get("runtime")
    if runtime is None:
        return None
    try:
        return RuntimeState.model_validate(runtime)
    except Exception:
        return None


def merge_package_state_defaults(defaults: dict[str, object], existing: dict[str, object]) -> dict[str, object]:
    merged: dict[str, object] = {
        key: dict(value) if isinstance(value, dict) else value
        for key, value in dict(defaults or {}).items()
    }
    for namespace, value in dict(existing or {}).items():
        if isinstance(merged.get(namespace), dict) and isinstance(value, dict):
            merged[namespace] = {**dict(merged[namespace]), **value}
        else:
            merged[namespace] = value
    return merged
