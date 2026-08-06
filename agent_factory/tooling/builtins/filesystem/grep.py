from __future__ import annotations

import re
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
    is_probably_binary,
    iter_workspace_files,
    matches_any_pattern,
    string_list,
    workspace_relative_path,
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
    base_path = str(arguments.get("base_path") or ".")
    include = string_list(arguments.get("include"), key="include")
    exclude = string_list(arguments.get("exclude"), key="exclude")
    case_sensitive = bool(arguments.get("case_sensitive", True))
    use_regex = bool(arguments.get("regex", True))
    context_before = _bounded_non_negative_int(arguments.get("context_before", 0), "context_before", maximum=20)
    context_after = _bounded_non_negative_int(arguments.get("context_after", 0), "context_after", maximum=20)
    max_file_bytes = positive_int(arguments.get("max_file_bytes", 2_000_000), "max_file_bytes")
    if max_file_bytes > 20_000_000:
        raise ValueError("max_file_bytes must be less than or equal to 20000000")
    max_results = positive_int(arguments.get("max_results", 100), "max_results")
    if max_results > 5000:
        raise ValueError("max_results must be less than or equal to 5000")
    matcher = _compile_matcher(pattern=pattern, case_sensitive=case_sensitive, use_regex=use_regex)
    root, allow_external = filesystem_boundary(resources)
    target = resolve_path(
        path=base_path,
        root=root,
        allow_external=allow_external,
        allowed_roots=filesystem_allowed_roots(resources),
    )
    if not target.exists():
        raise FileNotFoundError(str(target))
    matches: list[dict[str, Any]] = []
    truncated = False
    files_searched = 0
    for file_path in iter_workspace_files(target):
        search_root = target if target.is_dir() else target.parent
        if include and not matches_any_pattern(file_path, search_root=search_root, patterns=include):
            continue
        if exclude and matches_any_pattern(file_path, search_root=search_root, patterns=exclude):
            continue
        if file_path.stat().st_size > max_file_bytes:
            continue
        raw = file_path.read_bytes()
        if is_probably_binary(raw):
            continue
        try:
            lines = raw.decode("utf-8-sig").splitlines()
        except UnicodeDecodeError:
            continue
        files_searched += 1
        for line_number, line in enumerate(lines, start=1):
            if not matcher(line):
                continue
            if len(matches) >= max_results:
                truncated = True
                return tool_envelope({
                    "matches": matches,
                    "truncated": truncated,
                    "files_searched": files_searched,
                })
            line_index = line_number - 1
            matches.append({
                "path": workspace_relative_path(
                    file_path,
                    workspace_root=root,
                    mounts=filesystem_mounts(resources),
                ),
                "line": line,
                "line_number": line_number,
                "before": lines[max(0, line_index - context_before):line_index],
                "after": lines[line_index + 1:line_index + 1 + context_after],
            })
    return tool_envelope({
        "matches": matches,
        "truncated": truncated,
        "files_searched": files_searched,
    })


def _compile_matcher(*, pattern: str, case_sensitive: bool, use_regex: bool):
    if use_regex:
        flags = 0 if case_sensitive else re.IGNORECASE
        compiled = re.compile(pattern, flags=flags)
        return lambda line: bool(compiled.search(line))
    needle = pattern if case_sensitive else pattern.lower()
    return lambda line: needle in (line if case_sensitive else line.lower())


def _bounded_non_negative_int(value: Any, key: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    if value < 0 or value > maximum:
        raise ValueError(f"{key} must be between 0 and {maximum}")
    return value
