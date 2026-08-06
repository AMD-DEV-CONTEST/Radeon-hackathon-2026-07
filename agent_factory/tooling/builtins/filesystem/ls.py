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
    iter_workspace_entries,
    workspace_path_record,
)
from agent_factory.tooling.envelope import tool_envelope


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return path_risk_result(arguments, context, default_action="allow", sensitive_action="ask")


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    path = required_string(arguments, "path")
    recursive = bool(arguments.get("recursive", False))
    max_entries = positive_int(arguments.get("max_entries", 200), "max_entries")
    if max_entries > 5000:
        raise ValueError("max_entries must be less than or equal to 5000")
    root, allow_external = filesystem_boundary(resources)
    target = resolve_path(
        path=path,
        root=root,
        allow_external=allow_external,
        allowed_roots=filesystem_allowed_roots(resources),
    )
    if not target.exists():
        raise FileNotFoundError(str(target))
    if not target.is_dir():
        raise NotADirectoryError(str(target))
    entries: list[dict[str, object]] = []
    truncated = False
    for item in iter_workspace_entries(target, recursive=recursive):
        if len(entries) >= max_entries:
            truncated = True
            break
        entries.append(
            workspace_path_record(
                item,
                workspace_root=root,
                mounts=filesystem_mounts(resources),
            )
        )
    return tool_envelope({"entries": entries, "truncated": truncated})
