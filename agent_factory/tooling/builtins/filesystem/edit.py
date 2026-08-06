from __future__ import annotations

from hashlib import sha256
from typing import Any

from agent_factory.tooling.builtins.filesystem.common import (
    assert_not_protected_write_path,
    filesystem_allowed_roots,
    filesystem_boundary,
    path_risk_result,
    required_string,
    resolve_path,
    write_focus_facts,
)
from agent_factory.tooling.builtins.filesystem.text_changes import atomic_write_bytes, text_change_summary
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskResult


FOCUS_EVIDENCE_KEY = "focus"


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return ToolRiskResult.model_validate(
        path_risk_result(arguments, context, default_action="ask", sensitive_action="ask")
    ).model_dump(mode="json")


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    path = required_string(arguments, "path")
    old_text = required_string(arguments, "old_text")
    new_text = arguments.get("new_text")
    if not isinstance(new_text, str):
        raise ValueError("new_text must be a string")
    replace_all = bool(arguments.get("replace_all", False))
    root, allow_external = filesystem_boundary(resources)
    target = resolve_path(
        path=path,
        root=root,
        allow_external=allow_external,
        allowed_roots=filesystem_allowed_roots(resources),
    )
    assert_not_protected_write_path(target, root=root, resources=resources)
    if not target.exists():
        raise FileNotFoundError(str(target))
    if not target.is_file():
        raise IsADirectoryError(str(target))
    raw = target.read_bytes()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"file is not valid utf-8 text: {target}") from exc
    count = content.count(old_text)
    if count == 0:
        raise ValueError("old_text was not found")
    if not replace_all and count != 1:
        raise ValueError(
            f"old_text matched {count} times; set replace_all=true or provide a more specific old_text"
        )
    updated = content.replace(old_text, new_text) if replace_all else content.replace(old_text, new_text, 1)
    updated_bytes = updated.encode("utf-8")
    atomic_write_bytes(target, updated_bytes)
    output = {
        "path": str(target),
        "replacements": count if replace_all else 1,
        "before_hash": sha256(raw).hexdigest(),
        "after_hash": sha256(updated_bytes).hexdigest(),
        "change_summary": text_change_summary(content, updated),
    }
    return tool_envelope(
        output,
        evidence={FOCUS_EVIDENCE_KEY: write_focus_facts(target, root=root, resources=resources)},
    )
