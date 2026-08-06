from __future__ import annotations

from typing import Any

from agent_factory.tooling.builtins.filesystem.common import (
    filesystem_allowed_roots,
    filesystem_boundary,
    filesystem_mounts,
    path_risk_result,
    positive_int,
    required_string,
    resolve_path,
)
from agent_factory.tooling.builtins.filesystem.workspace_search import (
    DEFAULT_IGNORED_DIRECTORY_NAMES,
    workspace_path_record,
)
from agent_factory.tooling.envelope import tool_envelope


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return path_risk_result(
        arguments,
        context,
        path_key="base_path",
        default_action="allow",
        sensitive_action="ask",
    )


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    pattern = required_string(arguments, "pattern")
    normalized_pattern_parts = pattern.replace("\\", "/").split("/")
    if pattern.startswith("/") or ".." in normalized_pattern_parts:
        raise ValueError("pattern must stay within base_path")
    base_path = str(arguments.get("base_path") or ".")
    max_results = positive_int(arguments.get("max_results", 100), "max_results")
    if max_results > 5000:
        raise ValueError("max_results must be less than or equal to 5000")
    root, allow_external = filesystem_boundary(resources)
    target = resolve_path(
        path=base_path,
        root=root,
        allow_external=allow_external,
        allowed_roots=filesystem_allowed_roots(resources),
    )
    if not target.exists():
        raise FileNotFoundError(str(target))
    if not target.is_dir():
        raise NotADirectoryError(str(target))
    matches: list[dict[str, object]] = []
    truncated = False
    for item in sorted(target.glob(pattern), key=lambda candidate: (not candidate.is_dir(), str(candidate))):
        if any(part in DEFAULT_IGNORED_DIRECTORY_NAMES for part in item.relative_to(target).parts):
            continue
        if len(matches) >= max_results:
            truncated = True
            break
        matches.append(
            workspace_path_record(
                item,
                workspace_root=root,
                mounts=filesystem_mounts(resources),
            )
        )
    return tool_envelope({"matches": matches, "truncated": truncated})
