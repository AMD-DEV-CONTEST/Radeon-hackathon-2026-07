from __future__ import annotations

from typing import Any


RUNTIME_PROMPT_FRAGMENTS_SESSION_KEY = "runtime_prompt_fragments"


def runtime_prompt_fragments_from_state(state: Any) -> list[str]:
    session_config = getattr(getattr(state, "runtime_config", None), "session_config", {}) or {}
    if not isinstance(session_config, dict):
        return []
    raw_fragments = session_config.get(RUNTIME_PROMPT_FRAGMENTS_SESSION_KEY)
    if not isinstance(raw_fragments, list):
        return []
    fragments: list[str] = []
    seen_ids: set[str] = set()
    for item in raw_fragments:
        if not isinstance(item, dict):
            continue
        fragment_id = str(item.get("fragment_id") or "").strip()
        content = str(item.get("content") or "").strip()
        if not fragment_id or not content or fragment_id in seen_ids:
            continue
        fragments.append(content)
        seen_ids.add(fragment_id)
    return fragments
