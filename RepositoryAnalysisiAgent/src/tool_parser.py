"""Tool call parsing for RepositoryAnalysisAgent Agent engine.

Supports multiple formats:
1. Structured: vLLM returns ``tool_calls`` array in OpenAI-compatible JSON.
2. XML tags: ``<tool_call>...</tool_call>`` blocks.
3. Bare JSON: Qwen2.5 outputs ``{ "name": "...", "arguments": {...} }`` without tags.
4. Markdown wrapped: ```` ```json { ... } ``` ````

Provides a unified ToolCall dataclass and ``parse_tool_calls()`` that handles all.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    raw: str = ""


@dataclass
class ToolCallResult:
    calls: list[ToolCall] = field(default_factory=list)
    text_before: str = ""
    text_after: str = ""
    mode: str = "none"  # "structured" | "text" | "none"


# ── Helpers ──

_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(.*?)\s*</tool_call>",
    re.DOTALL,
)

# Match the start of a potential tool call JSON: {"name" or {"tool"
_TOOL_CALL_START_RE = re.compile(
    r'(\{[^{}]*?"name"\s*:\s*")',
    re.DOTALL,
)


def _find_json_objects(text: str) -> list[tuple[int, int, str]]:
    """Find all top-level JSON objects containing a "name" key.

    Uses bracket matching to correctly handle nested braces.
    Returns list of (start, end, json_string) tuples.
    """
    objects: list[tuple[int, int, str]] = []
    i = 0
    while i < len(text):
        # Find a potential start: a { followed eventually by "name"
        if text[i] == '{':
            # Check if this JSON object contains "name"
            end = _match_braces(text, i)
            if end is not None:
                json_str = text[i:end + 1]
                # Quick check: does it look like a tool call?
                if '"name"' in json_str or '"tool"' in json_str:
                    objects.append((i, end, json_str))
                i = end + 1
                continue
        i += 1
    return objects


def _match_braces(text: str, start: int) -> int | None:
    """Match opening { to its closing }, handling nested braces and strings."""
    depth = 0
    in_string = False
    escape = False
    i = start
    while i < len(text):
        ch = text[i]
        if escape:
            escape = False
        elif ch == '\\':
            escape = True
        elif ch == '"' and not escape:
            in_string = not in_string
        elif not in_string:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return None


def _extract_json_from_text(block: str) -> dict[str, Any] | None:
    """Try to parse a JSON object from a text block."""
    block = block.strip()
    # Remove markdown code fences if present
    if block.startswith("```"):
        lines = block.split("\n")
        block = "\n".join(lines[1:])
        if block.rstrip().endswith("```"):
            block = block.rstrip()[:-3]
        block = block.strip()
    try:
        obj = json.loads(block)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _parse_tool_call_json(obj: dict[str, Any]) -> ToolCall | None:
    """Extract a ToolCall from a parsed JSON dict."""
    # Standard format: {"name": "...", "arguments": {...}}
    if "name" in obj:
        return ToolCall(
            name=obj["name"],
            arguments=obj.get("arguments", obj.get("parameters", {})),
            raw=json.dumps(obj),
        )
    # OpenAI function format: {"function": {"name": "...", "arguments": "..."}}
    if "function" in obj:
        func = obj["function"]
        name = func.get("name", "")
        args_raw = func.get("arguments", "{}")
        if isinstance(args_raw, str):
            try:
                args = json.loads(args_raw)
            except json.JSONDecodeError:
                args = {"_raw": args_raw}
        else:
            args = args_raw
        if name:
            return ToolCall(name=name, arguments=args, raw=json.dumps(obj))
    return None


def parse_text_tool_calls(text: str) -> ToolCallResult:
    """Parse text-format tool calls from LLM output.

    Handles:
    - <tool_call>...</tool_call> XML blocks
    - Bare JSON objects with "name" key
    - Markdown-wrapped JSON
    """
    calls: list[ToolCall] = []
    consumed_ranges: list[tuple[int, int]] = []  # ranges of text that are tool calls

    # Strategy 1: <tool_call>...</tool_call> XML blocks
    for m in _TOOL_CALL_RE.finditer(text):
        obj = _extract_json_from_text(m.group(1))
        if obj:
            tc = _parse_tool_call_json(obj)
            if tc:
                calls.append(tc)
                consumed_ranges.append((m.start(), m.end()))

    # Strategy 2: bare JSON objects with "name" key (Qwen2.5 format)
    if not calls:
        json_objects = _find_json_objects(text)
        for start, end, json_str in json_objects:
            obj = _extract_json_from_text(json_str)
            if obj:
                tc = _parse_tool_call_json(obj)
                if tc:
                    calls.append(tc)
                    consumed_ranges.append((start, end))

    if not calls:
        return ToolCallResult(mode="none", text_before=text)

    # Determine text_before (everything before first tool call)
    if consumed_ranges:
        consumed_ranges.sort()
        first_start = consumed_ranges[0][0]
        last_end = consumed_ranges[-1][1]
        text_before = text[:first_start].strip()
        text_after = text[last_end:].strip()
    else:
        text_before = ""
        text_after = ""

    return ToolCallResult(
        calls=calls,
        text_before=text_before,
        text_after=text_after,
        mode="text",
    )


def parse_structured_tool_calls(
    message: dict[str, Any],
    full_text: str = "",
) -> ToolCallResult:
    """Parse structured tool_calls from OpenAI-compatible API response."""
    tool_calls_raw = message.get("tool_calls", [])
    calls: list[ToolCall] = []
    text = message.get("content") or full_text or ""

    for tc in tool_calls_raw:
        func = tc.get("function", {})
        name = func.get("name", "")
        args_raw = func.get("arguments", "{}")
        if isinstance(args_raw, str):
            try:
                arguments = json.loads(args_raw)
            except json.JSONDecodeError:
                arguments = {"_raw": args_raw}
        else:
            arguments = args_raw
        if name:
            calls.append(ToolCall(name=name, arguments=arguments, raw=json.dumps(tc)))

    # If structured calls found, return them
    if calls:
        return ToolCallResult(calls=calls, text_before=text, text_after="", mode="structured")

    # No structured calls — try text parsing as fallback
    if text:
        return parse_text_tool_calls(text)

    return ToolCallResult(mode="none")


def parse_tool_calls(
    message: dict[str, Any],
    full_text: str = "",
    prefer_structured: bool = True,
) -> ToolCallResult:
    """Unified entry point.

    Tries structured tool_calls first, then falls back to text parsing
    (XML tags, bare JSON, markdown-wrapped).
    """
    if prefer_structured and message.get("tool_calls"):
        result = parse_structured_tool_calls(message, full_text)
        if result.calls:
            return result
        # Structured tool_calls present but empty/unparseable — fall through to text

    text = message.get("content") or full_text or ""
    if text:
        return parse_text_tool_calls(text)

    return ToolCallResult(mode="none")
