"""Workflow schema helpers — Dify/LangChain-style portable step graphs."""

from __future__ import annotations

from typing import Any


ALLOWED_TOOLS = {
    "kb_search",
    "list_files",
    "read_file",
    "write_note",
    "save_fact",
    "recall_memory",
    "kb_stats",
    "list_workflows",
    "list_skills",
    "parse_image",
}


def normalize_step(raw: Any, index: int = 0) -> dict[str, Any]:
    """Normalize a step from YAML/dict/tuple into a portable dict."""
    if isinstance(raw, (list, tuple)) and len(raw) >= 3:
        step_id, label, call = raw[0], raw[1], raw[2]
        call = call if isinstance(call, dict) else {}
        return {
            "id": str(step_id),
            "label": str(label),
            "type": "tool",
            "tool": str(call.get("tool", "kb_search")),
            "args": dict(call.get("args") or {}),
        }
    if not isinstance(raw, dict):
        return {
            "id": f"step_{index}",
            "label": f"步骤 {index + 1}",
            "type": "tool",
            "tool": "kb_search",
            "args": {"query": str(raw)},
        }
    tool = str(raw.get("tool") or "kb_search")
    if tool not in ALLOWED_TOOLS:
        tool = "kb_search"
    return {
        "id": str(raw.get("id") or f"step_{index}"),
        "label": str(raw.get("label") or raw.get("name") or f"步骤 {index + 1}"),
        "type": str(raw.get("type") or "tool"),
        "tool": tool,
        "args": dict(raw.get("args") or {}),
        **(
            {"condition": raw["condition"]}
            if raw.get("condition")
            else {}
        ),
    }


def normalize_workflow(raw: dict[str, Any], fallback_id: str = "custom") -> dict[str, Any]:
    from src.security.paths import sanitize_id

    wid = sanitize_id(str(raw.get("id") or fallback_id).strip() or fallback_id, fallback_id)
    steps_in = raw.get("steps") or []
    steps = [normalize_step(s, i) for i, s in enumerate(steps_in)]
    if not steps:
        steps = [
            normalize_step(
                {
                    "id": "kb",
                    "label": "检索相关知识",
                    "tool": "kb_search",
                    "args": {"query": raw.get("title") or wid},
                },
                0,
            )
        ]
    keywords = raw.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [keywords]
    return {
        "id": wid,
        "title": str(raw.get("title") or wid),
        "description": str(raw.get("description") or ""),
        "keywords": [str(k) for k in keywords],
        "engine": str(raw.get("engine") or "private_local"),
        "version": str(raw.get("version") or "1.0"),
        "steps": steps,
        "requirement": str(raw.get("requirement") or ""),
        "exports": list(raw.get("exports") or ["yaml", "json", "dify", "langchain"]),
    }


def steps_as_legacy_tuples(meta: dict[str, Any]) -> list[tuple]:
    out = []
    for s in meta.get("steps") or []:
        out.append((s["id"], s["label"], {"tool": s["tool"], "args": s.get("args") or {}}))
    return out
