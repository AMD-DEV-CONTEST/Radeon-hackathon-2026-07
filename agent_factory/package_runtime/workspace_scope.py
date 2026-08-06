from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_factory.runtime_workspace import (
    RUNTIME_OUTPUT_ROOT_SESSION_KEY,
    RUNTIME_WORKSPACE_MOUNTS_SESSION_KEY,
    RUNTIME_WORKSPACE_ROOT_SESSION_KEY,
)


def apply_runtime_workspace(
    session_config: dict[str, Any],
    payload: dict[str, Any],
    *,
    workdir_root: Path,
) -> None:
    workspace = payload.get("runtime_workspace")
    if not isinstance(workspace, dict):
        return
    scope = str(workspace.get("scope") or "").strip()
    relative = Path(scope)
    if relative.is_absolute():
        raise ValueError("runtime workspace scope must be relative")
    root = workdir_root.expanduser().resolve()
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"runtime workspace scope escapes package workdir: {scope}") from exc
    target.mkdir(parents=True, exist_ok=True)
    session_config["builtin_workspace_root"] = str(target)
    session_config[RUNTIME_WORKSPACE_ROOT_SESSION_KEY] = str(target)
    session_config[RUNTIME_OUTPUT_ROOT_SESSION_KEY] = str(target)
    session_config[RUNTIME_WORKSPACE_MOUNTS_SESSION_KEY] = _runtime_workspace_mounts(
        workspace.get("mounts")
    )
    workspace_id = str(workspace.get("workspace_id") or "").strip()
    if workspace_id:
        session_config["workspace_id"] = workspace_id


def _runtime_workspace_mounts(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    mounts: list[dict[str, str]] = []
    names: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        source_path = str(item.get("source_path") or "").strip()
        source = Path(source_path).expanduser()
        if (
            not name
            or name in {".", ".."}
            or Path(name).name != name
            or "/" in name
            or "\\" in name
            or name.casefold() in names
            or not source.is_absolute()
        ):
            raise ValueError("runtime workspace mount is invalid")
        names.add(name.casefold())
        mounts.append(
            {
                "name": name,
                "source_path": str(source.resolve(strict=False)),
            }
        )
    return mounts
