from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agent_factory.runtime_attachments import workspace_attachment_root
from agent_factory.runtime_workspace import (
    RUNTIME_OUTPUT_ROOT_SESSION_KEY,
    RUNTIME_WORKSPACE_MOUNTS_SESSION_KEY,
    RUNTIME_WORKSPACE_ROOT_SESSION_KEY,
)


PACKAGE_TOOL_SYSTEM_RESOURCE_IDS = frozenset(
    {"artifacts_root", "package_root", "runtime_root", "workdir_root", "workspace_root"}
)
RUNTIME_EXECUTION_CONFIG_RESOURCE_ID = "runtime_execution_config"


def runtime_resource_overrides_from_state(state: Any) -> dict[str, Any]:
    runtime_config = _runtime_config_from_state(state)
    session_config = (
        runtime_config.get("session_config", {})
        if isinstance(runtime_config, Mapping)
        else getattr(runtime_config, "session_config", {})
    )
    user_config = (
        runtime_config.get("user_config", {})
        if isinstance(runtime_config, Mapping)
        else getattr(runtime_config, "user_config", {})
    )
    overrides: dict[str, Any] = {
        RUNTIME_EXECUTION_CONFIG_RESOURCE_ID: {
            "user_config": dict(user_config) if isinstance(user_config, Mapping) else {},
            "runtime_request": _runtime_request_from_state(state),
            "identity": _runtime_identity_from_state(state),
        }
    }
    if not isinstance(session_config, dict):
        return overrides
    root = str(session_config.get(RUNTIME_WORKSPACE_ROOT_SESSION_KEY) or "").strip()
    if not root:
        return overrides
    output_root = str(session_config.get(RUNTIME_OUTPUT_ROOT_SESSION_KEY) or "").strip()
    if not output_root:
        output_root = root
    read_only_input = str(workspace_attachment_root(Path(root)))
    mounts = session_config.get(RUNTIME_WORKSPACE_MOUNTS_SESSION_KEY)
    mount_paths = {
        str(item.get("name") or "").strip(): str(
            Path(str(item.get("source_path"))).expanduser().resolve(strict=False)
        )
        for item in mounts
        if isinstance(item, Mapping)
        and str(item.get("name") or "").strip()
        and str(item.get("source_path") or "").strip()
    } if isinstance(mounts, list) else {}
    workspace_boundary = {
        "root": root,
        "read_only_paths": [read_only_input],
        "allowed_roots": list(mount_paths.values()),
        "mounts": mount_paths,
    }
    return {
        **overrides,
        "filesystem": dict(workspace_boundary),
        "process_runtime": dict(workspace_boundary),
        "artifacts_root": output_root,
        "workdir_root": root,
        "workspace_root": root,
    }


def _runtime_identity_from_state(state: Any) -> dict[str, str]:
    runtime_state = _runtime_state_from_state(state)
    run = (
        runtime_state.get("run")
        if isinstance(runtime_state, Mapping)
        else getattr(runtime_state, "run", None)
    )
    values = {
        key: run.get(key) if isinstance(run, Mapping) else getattr(run, key, None)
        for key in ("agent_id", "session_id", "workspace_id", "pattern_id")
    }
    return {
        key: text
        for key, value in values.items()
        if (text := str(value or "").strip())
    }


def _runtime_request_from_state(state: Any) -> dict[str, Any]:
    runtime_state = _runtime_state_from_state(state)
    execution = (
        runtime_state.get("execution", {})
        if isinstance(runtime_state, Mapping)
        else getattr(runtime_state, "execution", None)
    )
    values = {
        key: execution.get(key) if isinstance(execution, Mapping) else getattr(execution, key, None)
        for key in ("timeout_seconds", "max_retries")
    }
    return {
        key: value
        for key, value in values.items()
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
    }


def _runtime_config_from_state(state: Any) -> Any:
    runtime_state = _runtime_state_from_state(state)
    if isinstance(runtime_state, Mapping):
        return runtime_state.get("runtime_config")
    return getattr(runtime_state, "runtime_config", None)


def _runtime_state_from_state(state: Any) -> Any:
    if not isinstance(state, Mapping):
        return state
    runtime_state = state.get("runtime")
    if isinstance(runtime_state, Mapping) or hasattr(runtime_state, "run"):
        return runtime_state
    return state


def merge_runtime_resource(base: Any, override: Any) -> Any:
    if not isinstance(base, Mapping) or not isinstance(override, Mapping):
        return override
    merged = dict(base)
    for key, value in override.items():
        if key == "read_only_paths" and isinstance(merged.get(key), list) and isinstance(value, list):
            merged[key] = list(dict.fromkeys([*merged[key], *value]))
            continue
        if key in merged and isinstance(merged[key], Mapping) and isinstance(value, Mapping):
            merged[key] = merge_runtime_resource(merged[key], value)
            continue
        merged[key] = value
    return merged


def resolve_resource_selector(resources: Mapping[str, Any], selector: str) -> Any:
    current: Any = resources
    for part in selector.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise KeyError(selector)
        current = current[part]
    return current
