"""
Tool invocation layer.

Every tool Nova can call is registered here with:
  - a name the router can match on,
  - a description shown to the LLM (for future function-calling upgrades),
  - a handler function.

Privacy / permission control: file-based tools are hard-restricted to
`config.ALLOWED_TOOL_DIRS`. Any path outside that allow-list is refused,
regardless of what the model or user asks for. This is Nova's permission
control & privacy protection mechanism.
"""
from __future__ import annotations

import ast
import logging
import operator
from pathlib import Path
from typing import Callable

import config

logger = logging.getLogger(__name__)

_SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}


class PermissionError_(Exception):
    """Raised when a tool tries to access something outside the allow-list."""


def _resolve_and_check(path_str: str) -> Path:
    """Resolve a path and enforce it lives under an allowed directory."""
    candidate = Path(path_str).expanduser().resolve()
    for allowed in config.ALLOWED_TOOL_DIRS:
        try:
            candidate.relative_to(allowed)
            return candidate
        except ValueError:
            continue
    raise PermissionError_(
        f"Access denied: '{path_str}' is outside the allowed directories "
        f"({[str(d) for d in config.ALLOWED_TOOL_DIRS]}). "
        "Update config.ALLOWED_TOOL_DIRS if this should be permitted."
    )


def tool_list_files(_: str = "") -> str:
    """List files Nova is permitted to read."""
    files = []
    for allowed in config.ALLOWED_TOOL_DIRS:
        files.extend(str(p.relative_to(allowed)) for p in allowed.rglob("*") if p.is_file())
    if not files:
        return "No files found in the allowed data directory."
    return "Files available:\n" + "\n".join(f"- {f}" for f in files)


def tool_read_file(filename: str) -> str:
    """Read the contents of a file inside the allowed data directory."""
    try:
        path = _resolve_and_check(str(config.DATA_DIR / filename.strip()))
    except PermissionError_ as exc:
        return str(exc)

    if not path.exists():
        return f"File not found: {filename}"

    text = path.read_text(errors="ignore")
    return text[:4000]  # cap to keep prompts bounded


def tool_calculator(expression: str) -> str:
    """Safely evaluate a basic arithmetic expression (no eval())."""

    def _eval(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPERATORS:
            return _SAFE_OPERATORS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPERATORS:
            return _SAFE_OPERATORS[type(node.op)](_eval(node.operand))
        raise ValueError("Unsupported expression")

    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval(tree.body)
        return f"{expression} = {result}"
    except Exception:
        return f"Could not evaluate expression: {expression!r}"


TOOL_REGISTRY: dict[str, Callable[[str], str]] = {
    "list_files": tool_list_files,
    "read_file": tool_read_file,
    "calculator": tool_calculator,
}

TOOL_DESCRIPTIONS = {
    "list_files": "List documents available in the local, permitted data directory.",
    "read_file": "Read a specific file by name from the local data directory.",
    "calculator": "Evaluate a basic arithmetic expression, e.g. '12 * (3 + 4)'.",
}
