from __future__ import annotations

import json
from typing import Any


def looks_like_internal_observation_text(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return False
    return looks_like_internal_observation_payload(payload)


def looks_like_internal_observation_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    keys = {str(key) for key in payload}
    if payload.get("type") == "tool_observation":
        return True
    if {"tool_id", "tool_call_id"}.issubset(keys):
        return True
    if "output_ref" in keys or "output_summary" in keys:
        return True
    return _looks_like_package_probe_payload(payload)


def _looks_like_package_probe_payload(payload: dict[str, Any]) -> bool:
    keys = {str(key) for key in payload}
    if not {"action", "probe"}.issubset(keys):
        return False
    probe = payload.get("probe")
    if not isinstance(probe, dict):
        return False
    probe_keys = {str(key) for key in probe}
    if probe_keys & {"current_package_digest", "current_tool_digests", "publish_gate", "freshness"}:
        return True
    tools = payload.get("tools")
    return isinstance(tools, list) and ("diagnostics" in keys or str(payload.get("action") or "") == "inspect")
