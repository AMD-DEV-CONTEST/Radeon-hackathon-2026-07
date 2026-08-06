"""Authenticated parent-conversation context for background-task tools."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_factory.collaboration_system.task_client import (
    BackgroundTaskClient,
    BackgroundTaskOwner,
)
from agent_factory.tooling.execution_context import current_tool_call


@dataclass(frozen=True, slots=True)
class ParentAgentContext:
    package_id: str
    session_id: str
    workspace_root: Path

    def task_owner(self) -> BackgroundTaskOwner:
        return BackgroundTaskOwner(
            package_id=self.package_id,
            session_id=self.session_id,
            workspace_root=self.workspace_root,
        )


def parent_agent_context(resources: dict[str, Any], *, tool_id: str) -> ParentAgentContext:
    runtime_config = resources.get("runtime_execution_config")
    identity = runtime_config.get("identity") if isinstance(runtime_config, dict) else None
    if not isinstance(identity, dict):
        raise ValueError(f"{tool_id} requires runtime identity")
    package_id = _required_text(identity, "agent_id")
    session_id = _required_text(identity, "session_id")
    workspace_root = Path(_required_text(resources, "workdir_root")).expanduser().resolve()
    if not workspace_root.is_dir() or workspace_root == Path(workspace_root.anchor):
        raise ValueError(f"{tool_id} requires a valid parent workspace")
    return ParentAgentContext(
        package_id=package_id,
        session_id=session_id,
        workspace_root=workspace_root,
    )


def background_task_client(resources: dict[str, Any]) -> BackgroundTaskClient:
    return BackgroundTaskClient.from_root(_required_text(resources, "background_task_root"))


def background_task_request_id(*, tool_id: str) -> str:
    call = current_tool_call()
    if call is None or call.tool_id != tool_id or not call.tool_call_id:
        raise RuntimeError(f"{tool_id} requires an active tool-call identity")
    return call.tool_call_id


def runtime_user_config(resources: dict[str, Any]) -> dict[str, Any]:
    execution = resources.get("runtime_execution_config")
    value = execution.get("user_config") if isinstance(execution, dict) else None
    return dict(value) if isinstance(value, dict) else {}


def _required_text(values: dict[str, Any], key: str) -> str:
    text = str(values.get(key) or "").strip()
    if not text:
        raise ValueError(f"{key} is required")
    return text
