"""Resource set store and tool implementation."""

from __future__ import annotations

from typing import Any

from agent_factory.tooling.spec import ToolRiskResult
from agent_factory.tooling.envelope import tool_envelope


RESOURCE_SET_STORE_KEY = "resource_set_store"

# Tool IDs for read-like tools that auto-populate the resource set
READ_TOOL_IDS = frozenset({"read", "glob", "grep", "ls"})


class ResourceSetStore:
    """In-memory set of resource paths explored during a workflow session."""

    def __init__(self) -> None:
        self._paths: set[str] = set()

    def add(self, path: str) -> None:
        cleaned = path.strip()
        if cleaned:
            self._paths.add(cleaned)

    def add_many(self, paths: list[str]) -> None:
        for path in paths:
            self.add(path)

    def remove(self, path: str) -> None:
        self._paths.discard(path.strip())

    def list_paths(self) -> list[str]:
        return sorted(self._paths)

    def contains(self, path: str) -> bool:
        return path.strip() in self._paths

    def size(self) -> int:
        return len(self._paths)

    def clear(self) -> None:
        self._paths.clear()


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    store = _get_store(resources)
    action = str(arguments.get("action") or "").strip()

    if action == "add":
        paths = _paths_from_arguments(arguments)
        store.add_many(paths)
        return tool_envelope({
            "action": "add",
            "status": "completed",
            "added": paths,
            "total": store.size(),
            "message": f"Added {len(paths)} path(s) to resource set. Total: {store.size()}.",
        })

    if action == "list":
        paths = store.list_paths()
        return tool_envelope({
            "action": "list",
            "status": "completed",
            "paths": paths,
            "total": store.size(),
            "message": f"Resource set contains {store.size()} path(s).",
        })

    if action == "remove":
        paths = _paths_from_arguments(arguments)
        for path in paths:
            store.remove(path)
        return tool_envelope({
            "action": "remove",
            "status": "completed",
            "removed": paths,
            "total": store.size(),
            "message": f"Removed {len(paths)} path(s). Total: {store.size()}.",
        })

    raise ValueError(f"action must be one of: add, list, remove (got: {action!r})")


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip()
    if action not in {"add", "list", "remove"}:
        return ToolRiskResult(
            action="deny",
            risk_level="low",
            reasons=[f"invalid resource_set action: {action!r}"],
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="allow",
        risk_level="low",
        reasons=["resource_set is a read-only tracking tool"],
        facts={"action": action},
    ).model_dump(mode="json")


def auto_record_path(store: ResourceSetStore | None, tool_id: str, arguments: dict[str, Any]) -> None:
    """Automatically record paths from read-like tool invocations."""
    if store is None or tool_id not in READ_TOOL_IDS:
        return
    path = arguments.get("path") or arguments.get("base_path") or ""
    if isinstance(path, str) and path.strip():
        store.add(path.strip())
    pattern = arguments.get("pattern") or ""
    if isinstance(pattern, str) and pattern.strip():
        store.add(f"{path}:{pattern}" if path else pattern)


def _get_store(resources: dict[str, Any]) -> ResourceSetStore:
    store = resources.get("store")
    if isinstance(store, ResourceSetStore):
        return store
    raise ValueError("resource_set_store resource is not configured")


def _paths_from_arguments(arguments: dict[str, Any]) -> list[str]:
    paths = arguments.get("paths")
    if isinstance(paths, list):
        result = [str(p).strip() for p in paths if str(p).strip()]
        if not result:
            raise ValueError("paths must contain at least one non-empty string")
        return result
    path = arguments.get("path")
    if isinstance(path, str) and path.strip():
        return [path.strip()]
    raise ValueError("either 'paths' (array) or 'path' (string) is required for add/remove")
