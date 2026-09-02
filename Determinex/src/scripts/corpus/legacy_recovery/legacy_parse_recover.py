from __future__ import annotations

import json
from typing import Any


def recover_json_line(raw: str) -> tuple[dict[str, Any] | None, str]:
    """Parse a legacy JSONL row with conservative recovery attempts."""
    line = raw.strip().lstrip("\ufeff").replace("\x00", "")
    if not line:
        return None, "blank_line"
    for candidate in _candidates(line):
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value, ""
        return None, "json_value_not_object"
    return None, "json_decode_error"


def _candidates(line: str) -> list[str]:
    candidates = [line]
    if line.endswith(","):
        candidates.append(line[:-1])
    start = line.find("{")
    end = line.rfind("}")
    if start >= 0 and end > start:
        candidates.append(line[start : end + 1])
    return candidates
