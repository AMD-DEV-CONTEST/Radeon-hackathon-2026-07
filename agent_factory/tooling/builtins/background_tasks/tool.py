from __future__ import annotations

from typing import Any

from agent_factory.collaboration_system.parent_controller import (
    background_task_client,
    parent_agent_context,
)
from agent_factory.tooling.envelope import tool_envelope


TOOL_ID = "background_tasks"


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip()
    parent = parent_agent_context(resources, tool_id=TOOL_ID)
    client = background_task_client(resources)
    if action == "list":
        tasks = [task.model_dump(mode="json") for task in client.list_owned(parent.session_id)]
        output = {
            "action": "list",
            "tasks": tasks,
            "count": len(tasks),
            "message": f"Read {len(tasks)} background tasks for the current session.",
        }
    elif action == "get":
        task = client.owned_task(parent.session_id, _required_text(arguments, "task_id"))
        output = {
            "action": "get",
            "task": task.model_dump(mode="json"),
            "message": "Background-task details were read.",
        }
    elif action == "cancel":
        reason = str(arguments.get("reason") or "The primary Agent cancelled the background task.").strip()
        task = client.cancel_owned(
            parent.session_id,
            _required_text(arguments, "task_id"),
            reason=reason,
        )
        output = {
            "action": "cancel",
            "task": task.model_dump(mode="json"),
            "message": reason,
        }
    else:
        raise ValueError(f"unsupported background_tasks action: {action}")
    return tool_envelope(output, summary=output["message"])


def _required_text(values: dict[str, Any], key: str) -> str:
    text = str(values.get(key) or "").strip()
    if not text:
        raise ValueError(f"{key} is required")
    return text
