"""Structured action protocol used by the mini-SWE experiments.

The protocol deliberately keeps patches as a single string.  Constraining a
small model to produce a deeply nested patch AST tends to spend its output
budget on escaping and schema bookkeeping instead of code changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Mapping


ActionName = Literal["inspect", "search", "edit", "replace", "execute", "finish", "recover"]

ACTION_NAMES = frozenset({"inspect", "search", "edit", "replace", "execute", "finish", "recover"})

ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    # Keep every envelope field present (nullable when unused).  This is the
    # form supported by OpenAI-compatible structured-output servers and makes
    # the control plane easier for small models to follow than a sparse object.
    "required": [
        "action",
        "path",
        "query",
        "command",
        "patch",
        "old_text",
        "new_text",
        "reason",
    ],
    "properties": {
        "action": {"type": "string", "enum": sorted(ACTION_NAMES)},
        "path": {"type": ["string", "null"]},
        "query": {"type": ["string", "null"]},
        "command": {"type": ["string", "null"]},
        "patch": {
            "type": ["string", "null"],
            "description": "A complete unified diff beginning with diff --git; required for edit actions.",
        },
        "old_text": {
            "type": ["string", "null"],
            "description": "Exact existing text for a replace action; it must match exactly once.",
        },
        "new_text": {
            "type": ["string", "null"],
            "description": "Replacement text for a replace action; null or empty deletes the old text.",
        },
        "reason": {"type": "string"},
    },
}

VERIFIER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "confidence", "summary"],
    "properties": {
        "verdict": {"type": "string", "enum": ["accept", "reject", "needs_more_tests"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "summary": {"type": "string"},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
}


class ActionParseError(ValueError):
    """Raised when a model response is not a valid action envelope."""


@dataclass(frozen=True)
class ActionEnvelope:
    """A validated, model-produced action."""

    action: ActionName
    path: str | None = None
    query: str | None = None
    command: str | None = None
    patch: str | None = None
    old_text: str | None = None
    new_text: str | None = None
    reason: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ActionEnvelope":
        if not isinstance(value, Mapping):
            raise ActionParseError("action must be a JSON object")
        unknown = set(value) - set(ACTION_SCHEMA["properties"])
        if unknown:
            raise ActionParseError(f"unknown action fields: {sorted(unknown)}")
        action = value.get("action")
        if action not in ACTION_NAMES:
            raise ActionParseError(f"unsupported action: {action!r}")
        reason = value.get("reason", "")
        if not isinstance(reason, str):
            raise ActionParseError("reason must be a string")

        def optional_string(name: str) -> str | None:
            item = value.get(name)
            if item is not None and not isinstance(item, str):
                raise ActionParseError(f"{name} must be a string or null")
            return item

        result = cls(
            action=action,
            path=optional_string("path"),
            query=optional_string("query"),
            command=optional_string("command"),
            patch=optional_string("patch"),
            old_text=optional_string("old_text"),
            new_text=optional_string("new_text"),
            reason=reason,
        )
        result.validate_payload()
        return result

    def validate_payload(self) -> None:
        if self.action in {"inspect", "search"} and not (self.path or self.query or self.command):
            raise ActionParseError(f"{self.action} requires path, query, or command")
        if self.action in {"execute", "recover"} and not self.command:
            raise ActionParseError(f"{self.action} requires command")
        if self.action == "edit" and not (self.patch or self.command):
            raise ActionParseError("edit requires patch or command")
        if self.action == "replace":
            if not self.path:
                raise ActionParseError("replace requires path")
            if not self.old_text:
                raise ActionParseError("replace requires non-empty old_text")
            if self.new_text is None:
                raise ActionParseError("replace requires new_text (use an empty string to delete)")

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "path": self.path,
            "query": self.query,
            "command": self.command,
            "patch": self.patch,
            "old_text": self.old_text,
            "new_text": self.new_text,
            "reason": self.reason,
        }


def _extract_json_object(text: str) -> str:
    """Extract the first balanced JSON object, tolerating markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    if start < 0:
        raise ActionParseError("response does not contain a JSON object")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ActionParseError("JSON object is incomplete")


def parse_action_envelope(response: str | Mapping[str, Any]) -> ActionEnvelope:
    """Parse and validate a model response.

    A strict JSON decoder is used after extracting a balanced object.  The
    extractor only handles transport noise such as markdown fences; it does
    not repair invalid JSON, which keeps parser-retry metrics honest.
    """
    value = parse_json_object(response)
    return ActionEnvelope.from_mapping(value)


def parse_json_object(response: str | Mapping[str, Any]) -> dict[str, Any]:
    """Parse a JSON object while tolerating transport markdown fences."""
    if isinstance(response, Mapping):
        value = dict(response)
    elif isinstance(response, str):
        try:
            value = json.loads(_extract_json_object(response))
        except json.JSONDecodeError as exc:
            raise ActionParseError(f"invalid JSON: {exc.msg}") from exc
    else:
        raise ActionParseError("response must be a JSON object or string")
    if not isinstance(value, dict):
        raise ActionParseError("response must decode to a JSON object")
    return value
