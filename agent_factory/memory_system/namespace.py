from __future__ import annotations


def factory_memory_namespace(project_id: str = "default") -> tuple[str, ...]:
    return ("memory", "factory", _clean(project_id))


def agent_memory_namespace(agent_id: str) -> tuple[str, ...]:
    return ("memory", "agent", _clean(agent_id))


def workspace_memory_namespace(workspace_id: str) -> tuple[str, ...]:
    return ("memory", "workspace", _clean(workspace_id))


def user_memory_namespace(user_id: str) -> tuple[str, ...]:
    return ("memory", "user", _clean(user_id))


def _clean(value: str) -> str:
    cleaned = str(value or "").strip().replace("/", "_").replace("\\", "_")
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError("memory namespace identifier must not be empty")
    return cleaned
