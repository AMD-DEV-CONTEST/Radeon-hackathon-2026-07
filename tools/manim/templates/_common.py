from __future__ import annotations

from typing import Any, Dict

# Project-wide layout safe-zone (matches the Manim code-generstion bounding box
# used elsewhere in the pipeline: x in [-7, 7], y in [-4, 4]).
BOUND_X = 7
BOUND_Y = 4
SAFE_WIDTH = 2 * BOUND_X - 1.5   
SAFE_HEIGHT = 2 * BOUND_Y - 1.0


class TemplateParamError(ValueError):
    """Raised when a template's params dict is missing/invalid required data.

    Kept as its own subclass (not bare ValueError) so callers/tests can
    distinguish "bad template input" from other ValueErrors.
    """


def require(params: Dict[str, Any], key: str) -> Any:
    """Fetch a required param, raising a clear error if missing or empty."""
    if not isinstance(params, dict):
        raise TemplateParamError(f"params must be a dict, got {type(params).__name__}")
    value = params.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise TemplateParamError(f"Missing required parameter: '{key}'")
    return value


def optional(params: Dict[str, Any], key: str, default: Any = "") -> Any:
    """Fetch an optional param with a safe default. Never raises."""
    if not isinstance(params, dict):
        return default
    value = params.get(key)
    return value if value is not None else default


def safe_number(value: Any, default: float = 0.0) -> float:
    """Coerce arbitrary input to a float, falling back to `default` on failure."""
    try:
        result = float(value)
        if result != result:  # NaN check without importing math here
            return float(default)
        return result
    except (TypeError, ValueError):
        return float(default)


def safe_str_literal(value: Any, max_chars: int = 200) -> str:
    """
    Turn arbitrary input into a Python string literal safe to splice into
    generated source code (via an f-string {} placeholder).

    Always returns a valid Python literal (via repr), and defensively caps
    length so a runaway LLM string can't blow up the generated file size.
    """
    text = "" if value is None else str(value)
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "\u2026"
    return repr(text)


def scene_class_name(scene_id: "int | str") -> str:
    """Project-wide Scene{N} naming convention, sanitized to a valid identifier."""
    suffix = "".join(ch for ch in str(scene_id) if ch.isalnum())
    if not suffix:
        suffix = "0"
    return f"Scene{suffix}"