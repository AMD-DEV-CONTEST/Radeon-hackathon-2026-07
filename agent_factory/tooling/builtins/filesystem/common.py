from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_factory.create_agent.stage_context import stage_context_from_resources
from agent_factory.tooling.spec import ToolRiskResult
from agent_factory.tooling.workspace_paths import workspace_path_candidate


SENSITIVE_FILE_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519"}
SENSITIVE_DIR_NAMES = {".ssh", ".gnupg", "secrets", "secret", "credentials"}


def required_string(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def positive_int(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    if value < 1:
        raise ValueError(f"{key} must be greater than or equal to 1")
    return value


def filesystem_boundary(resources: dict[str, Any]) -> tuple[Path, bool]:
    config = resources.get("filesystem", {})
    if isinstance(config, str):
        root_value: Any = config
        allow_external = False
    elif isinstance(config, dict):
        root_value = config.get("root") or config.get("cwd") or "."
        allow_external = bool(config.get("allow_external", False))
    else:
        root_value = "."
        allow_external = False
    root = Path(str(root_value)).expanduser().resolve()
    return root, allow_external


def filesystem_allowed_roots(resources: dict[str, Any]) -> tuple[Path, ...]:
    config = resources.get("filesystem", {})
    values = config.get("allowed_roots", []) if isinstance(config, dict) else []
    if not isinstance(values, list):
        return ()
    return tuple(
        Path(value).expanduser().resolve(strict=False)
        for value in values
        if isinstance(value, str) and value.strip()
    )


def filesystem_mounts(resources: dict[str, Any]) -> dict[str, Path]:
    config = resources.get("filesystem", {})
    values = config.get("mounts", {}) if isinstance(config, dict) else {}
    if not isinstance(values, dict):
        return {}
    return {
        str(name): Path(value).expanduser().resolve(strict=False)
        for name, value in values.items()
        if isinstance(name, str)
        and name.strip()
        and isinstance(value, str)
        and value.strip()
    }


def resolve_path(
    *,
    path: str,
    root: Path,
    allow_external: bool,
    allowed_roots: tuple[Path, ...] = (),
) -> Path:
    candidate = workspace_path_candidate(path, root=root)
    resolved = candidate.resolve(strict=False)
    if allow_external:
        return resolved
    if _path_is_within(resolved, root):
        return resolved
    if any(_path_is_within(resolved, allowed_root) for allowed_root in allowed_roots):
        return resolved
    raise ValueError(f"path escapes filesystem root: {path}")


def path_type(path: Path) -> str:
    if path.is_file():
        return "file"
    if path.is_dir():
        return "directory"
    return "other"


def path_risk_result(
    arguments: dict[str, Any],
    context: dict[str, Any],
    *,
    path_key: str = "path",
    default_action: str,
    sensitive_action: str,
) -> dict[str, Any]:
    path_value = arguments.get(path_key) or "."
    if not isinstance(path_value, str) or not path_value.strip():
        return ToolRiskResult(
            action="deny",
            risk_level="high",
            reasons=[f"{path_key} must be a non-empty string"],
        ).model_dump(mode="json")
    tool_resources = dict(context.get("resources") or {})
    root, allow_external = filesystem_boundary(tool_resources)
    try:
        resolved = resolve_path(
            path=path_value,
            root=root,
            allow_external=allow_external,
            allowed_roots=filesystem_allowed_roots(tool_resources),
        )
    except Exception as exc:
        return ToolRiskResult(
            action="deny",
            risk_level="high",
            reasons=[
                f"path is outside the configured filesystem boundary: {exc}",
                _workspace_path_guidance(root),
            ],
            facts={"path": path_value, "filesystem_root": str(root)},
        ).model_dump(mode="json")
    is_write_like = default_action != "allow"
    managed_path = _managed_path_spec(resolved, root=root, resources=tool_resources)
    managed_write_path = _managed_write_path_spec(resolved, root=root, resources=tool_resources) if is_write_like else None
    protected = (
        managed_path is not None
        or managed_write_path is not None
        or _is_protected_write_path(resolved, root=root, resources=tool_resources)
    )
    if protected:
        tool_key = "write_tool" if is_write_like else "read_tool"
        path_spec = managed_write_path or managed_path or {}
        dedicated_tool = str(path_spec.get(tool_key) or path_spec.get("tool") or "").strip()
        reason = (
            "path is managed by a dedicated control tool and cannot be modified through generic filesystem tools"
            if is_write_like
            else "path is managed by a dedicated control tool and cannot be read through generic filesystem tools"
        )
        suggested_action = (
            f"Use {dedicated_tool} to update this managed file."
            if dedicated_tool
            else "Use the dedicated control tool to update this managed file."
        ) if is_write_like else (
            f"Use {dedicated_tool} to inspect this managed file."
            if dedicated_tool
            else "Use the dedicated control tool to inspect this managed file."
        )
        return ToolRiskResult(
            action="deny",
            risk_level="high",
            reasons=[reason, suggested_action],
            facts={
                "path": path_value,
                "resolved_path": str(resolved),
                "filesystem_root": str(root),
                "managed_file_operation": "write" if is_write_like else "read",
                "dedicated_tool": dedicated_tool,
            },
        ).model_dump(mode="json")
    if is_write_like and _is_read_only_write_path(resolved, root=root, resources=tool_resources):
        return ToolRiskResult(
            action="deny",
            risk_level="high",
            reasons=["path is read-only runtime input and cannot be modified through generic filesystem tools"],
            facts={
                "path": path_value,
                "resolved_path": str(resolved),
                "filesystem_root": str(root),
                "read_only_runtime_input": True,
            },
        ).model_dump(mode="json")
    if is_write_like and not _is_allowed_write_path(resolved, root=root, resources=tool_resources):
        return ToolRiskResult(
            action="deny",
            risk_level="high",
            reasons=[
                "path is outside configured allowed_write_paths",
                _workspace_path_guidance(root),
            ],
            facts={
                "path": path_value,
                "resolved_path": str(resolved),
                "filesystem_root": str(root),
            },
        ).model_dump(mode="json")
    focus_facts = _focus_write_facts(resolved, root=root, resources=tool_resources) if is_write_like else {}
    sensitive = _is_sensitive_path(resolved)
    reasons = []
    action = default_action
    risk_level = "low"
    if sensitive:
        action = sensitive_action
        risk_level = "medium"
        reasons.append("path targets a sensitive file or directory")
    return ToolRiskResult(
        action=action,
        risk_level=risk_level,
        reasons=reasons,
        facts={
            "path": path_value,
            "resolved_path": str(resolved),
            "filesystem_root": str(root),
            "sensitive_path": sensitive,
            **focus_facts,
        },
    ).model_dump(mode="json")


def assert_not_protected_write_path(path: Path, *, root: Path, resources: dict[str, Any]) -> None:
    if _managed_write_path_spec(path, root=root, resources=resources) is not None:
        raise PermissionError(f"path is managed by a dedicated write tool: {path}")
    if _is_protected_write_path(path, root=root, resources=resources):
        raise PermissionError(f"path is managed by a dedicated control tool: {path}")
    if _is_read_only_write_path(path, root=root, resources=resources):
        raise PermissionError(f"path is read-only runtime input: {path}")
    if not _is_allowed_write_path(path, root=root, resources=resources):
        raise PermissionError(f"path is outside configured allowed_write_paths: {path}")


def write_focus_facts(path: Path, *, root: Path, resources: dict[str, Any]) -> dict[str, Any]:
    return _focus_write_facts(path, root=root, resources=resources)


def _is_sensitive_path(path: Path) -> bool:
    if path.name in SENSITIVE_FILE_NAMES:
        return True
    return any(part in SENSITIVE_DIR_NAMES for part in path.parts)


def _is_protected_write_path(path: Path, *, root: Path, resources: dict[str, Any]) -> bool:
    config = resources.get("filesystem", {})
    values = config.get("protected_write_paths", []) if isinstance(config, dict) else []
    if not isinstance(values, list):
        return False
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        requested = Path(value).expanduser()
        candidate = requested if requested.is_absolute() else root / requested
        resolved = candidate.resolve(strict=False)
        if path == resolved or resolved in path.parents:
            return True
    return False


def _is_read_only_write_path(path: Path, *, root: Path, resources: dict[str, Any]) -> bool:
    config = resources.get("filesystem", {})
    values = config.get("read_only_paths", []) if isinstance(config, dict) else []
    if not isinstance(values, list):
        return False
    return _path_matches_focus_files(path, root=root, focus_files=values)


def _managed_path_spec(path: Path, *, root: Path, resources: dict[str, Any]) -> dict[str, Any] | None:
    config = resources.get("filesystem", {})
    values = config.get("managed_paths", {}) if isinstance(config, dict) else {}
    if not isinstance(values, dict):
        return None
    for raw_path, raw_spec in values.items():
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        requested = Path(raw_path).expanduser()
        candidate = requested if requested.is_absolute() else root / requested
        if path != candidate.resolve(strict=False):
            continue
        return raw_spec if isinstance(raw_spec, dict) else {}
    return None


def _managed_write_path_spec(path: Path, *, root: Path, resources: dict[str, Any]) -> dict[str, Any] | None:
    config = resources.get("filesystem", {})
    values = config.get("managed_write_paths", {}) if isinstance(config, dict) else {}
    if not isinstance(values, dict):
        return None
    for raw_path, raw_spec in values.items():
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        requested = Path(raw_path).expanduser()
        candidate = requested if requested.is_absolute() else root / requested
        resolved = candidate.resolve(strict=False)
        if path == resolved or resolved in path.parents:
            return raw_spec if isinstance(raw_spec, dict) else {}
    return None


def _is_allowed_write_path(path: Path, *, root: Path, resources: dict[str, Any]) -> bool:
    config = resources.get("filesystem", {})
    values = config.get("allowed_write_paths", []) if isinstance(config, dict) else []
    if not isinstance(values, list) or not values:
        return True
    return _path_matches_focus_files(path, root=root, focus_files=values)


def _path_matches_focus_files(path: Path, *, root: Path, focus_files: list[Any]) -> bool:
    if not focus_files:
        return False
    for value in focus_files:
        if not isinstance(value, str) or not value.strip():
            continue
        requested = Path(value).expanduser()
        candidate = requested if requested.is_absolute() else root / requested
        resolved = candidate.resolve(strict=False)
        if path == resolved or resolved in path.parents:
            return True
    return False


def _focus_write_facts(path: Path, *, root: Path, resources: dict[str, Any]) -> dict[str, Any]:
    stage_context = stage_context_from_resources(resources)
    if stage_context is not None:
        relative_path = _relative_path_text(path, root=root)
        active = stage_context.active_stage()
        focus_files = stage_context.active_focus_files()
        target_focus_id = _target_focus_for_path(relative_path, stage_context.file_focuses())
        return {
            "relative_path": relative_path,
            "active_focus_id": active.system_id if active else "",
            "active_focus_files": focus_files,
            "target_focus_id": target_focus_id,
            "outside_focus": bool(focus_files and not _path_matches_focus_files(path, root=root, focus_files=focus_files)),
        }
    return {"relative_path": _relative_path_text(path, root=root)}


def _relative_path_text(path: Path, *, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _workspace_path_guidance(root: Path) -> str:
    return (
        "Use a relative path inside the workspace or an absolute path under "
        f"filesystem root {root}; do not use /tmp, host paths, or arbitrary absolute paths "
        "unless external paths are explicitly enabled."
    )


def _target_focus_for_path(relative_path: str, focuses: dict[Any, Any]) -> str:
    for raw_focus_path, raw_focus_id in focuses.items():
        focus_path = str(raw_focus_path or "").strip()
        focus_id = str(raw_focus_id or "").strip()
        if not focus_path or not focus_id:
            continue
        if focus_path.endswith("/"):
            if relative_path.startswith(focus_path):
                return focus_id
            continue
        if relative_path == focus_path:
            return focus_id
    return ""
