"""Explicit preference / rule extraction into Tier-3 SemanticMemory.

Closes the design gap found by the memory-consistency test suite (S3/S8):
SemanticMemory previously learned preferences only from strategies and
backtests (``learn_from_session``); user-stated long-term rules spoken in
plain conversation were never persisted, so cross-session retrieval (S3)
and rule cancellation (S8) could not work.

This module is a lightweight, dependency-free rule layer (no LLM calls):

- ``extract_preferences(text)``  — recognize explicit statements like
  "我的风险偏好是保守型", "最大单日回撤容忍 2%", "止损线统一设在 -8%"
  and return {key: value}.
- ``extract_cancellations(text)`` — recognize rule cancellation like
  "取消这条规则，不用统一止损" and return the keys to remove.
- ``apply_memory_updates(memory, text)`` — persist both into
  ``memory.semantic`` (which auto-persists to semantic_memory.json).

Design guardrails (avoid false positives):
- Whitelist-only patterns: queries ("止损规则是什么"), opinions
  ("我认为茅台明年到 2500") and session state (仓位/持仓) are NEVER
  extracted — position data stays in working/episodic memory.
- Cancellation only matches explicit verbs (取消/撤销/删除/去掉/不用...).
"""

from __future__ import annotations

import re

from .memory import AgentMemory

# ── Value mapping ────────────────────────────────────────────────────

_RISK_MAP = [
    (("保守", "稳健低", "低风险"), "conservative"),
    (("稳健", "中等", "中风险", "平衡"), "moderate"),
    (("激进", "高风", "高风险", "进取"), "aggressive"),
]


def _map_risk(raw: str) -> str | None:
    for keys, value in _RISK_MAP:
        if any(k in raw for k in keys):
            return value
    return None


# ── Extraction patterns: (key, regex, value_fn) ──────────────────────

_PATTERNS: list[tuple[str, re.Pattern, callable]] = [
    # 风险偏好 → risk_tolerance (支持两种语序: "中等风险偏好" / "风险偏好是保守型")
    (
        "risk_tolerance",
        re.compile(
            r"(?:(保守|稳健|激进|中等|进取|低风险|高风险|中风险|平衡)\s*风险偏好|"
            r"风险偏好\s*(?:是|为|：|:)?\s*([^，。；;、\s]{1,8}))"
        ),
        lambda m: _map_risk(m.group(1) or m.group(2)),
    ),
    # 最大单日回撤容忍 → max_daily_drawdown
    (
        "max_daily_drawdown",
        re.compile(
            r"(?:最大单日回撤|单日回撤|最大回撤)\s*(?:容忍|容忍度)?\s*(?:是|为|：|:)?"
            r"\s*(\d+(?:\.\d+)?)\s*%"
        ),
        lambda m: f"{m.group(1)}%",
    ),
    # 统一止损线 → unified_stop_loss
    (
        "unified_stop_loss",
        re.compile(
            r"(?:止损线|止损)\s*(?:统一)?\s*(?:设在|设置为|设为|定在|是|为|：|:)?"
            r"\s*(-?\d+(?:\.\d+)?)\s*%"
        ),
        lambda m: f"{m.group(1)}%",
    ),
]

# ── Cancellation verbs → affected keys ───────────────────────────────

_CANCEL_VERBS = r"(?:取消|撤销|作废|删除|去掉|移除|不要|不用|停用)"
_CANCEL_TARGETS: list[tuple[str, re.Pattern]] = [
    ("unified_stop_loss", re.compile(_CANCEL_VERBS + r"[^。；;\n]{0,24}?止损")),
    ("max_daily_drawdown", re.compile(_CANCEL_VERBS + r"[^。；;\n]{0,24}?回撤")),
    ("risk_tolerance", re.compile(_CANCEL_VERBS + r"[^。；;\n]{0,24}?风险偏好")),
]

# ── Public API ───────────────────────────────────────────────────────


def extract_preferences(text: str) -> dict[str, str]:
    """Return {key: value} for explicit long-term rules found in text."""
    found: dict[str, str] = {}
    for key, pattern, value_fn in _PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        value = value_fn(m)
        if value is not None:
            found[key] = value
    return found


def extract_cancellations(text: str) -> list[str]:
    """Return keys of rules the user explicitly cancels in text."""
    removed: list[str] = []
    for key, pattern in _CANCEL_TARGETS:
        if pattern.search(text):
            removed.append(key)
    return removed


def apply_memory_updates(memory: AgentMemory, text: str) -> dict:
    """Persist extracted preferences and cancellations into semantic memory.

    Returns a summary dict for logging/tests: {"stored": {...}, "removed": [...]}.
    Safe to call on every user turn — extraction is whitelist-based, so
    ordinary messages are no-ops.
    """
    summary: dict = {"stored": {}, "removed": []}

    for key, value in extract_preferences(text).items():
        memory.semantic.update_preferences(key, value)
        summary["stored"][key] = value

    for key in extract_cancellations(text):
        if memory.semantic.remove_preference(key):
            summary["removed"].append(key)

    return summary
