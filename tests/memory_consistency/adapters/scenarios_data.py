"""Scenario golden-reply tables for the mock adapter.

Kept separate from scenarios.json so the mock stays pure-data and the
JSON remains the single source of truth for scenario definitions.
"""

from __future__ import annotations


def _collect(scenarios: list[dict], key: str) -> dict[str, list[str]]:
    table: dict[str, list[str]] = {}
    for sc in scenarios:
        turns: list[str] = []
        for sess in sc.get("sessions", []):
            for t in sess.get("turns", []):
                turns.append(t.get(key, t.get("golden", "")))
        table[sc.get("id", "")] = turns
    return table


def golden_turns(scenarios: list[dict]) -> dict[str, list[str]]:
    """Turn-level golden replies (per-turn `golden` field)."""
    return _collect(scenarios, "golden")


def confused_turns(scenarios: list[dict]) -> dict[str, list[str]]:
    """Scenario-level `golden_confused` arrays (typical memory-mixing replies)."""
    table: dict[str, list[str]] = {}
    for sc in scenarios:
        table[sc.get("id", "")] = list(sc.get("golden_confused") or [])
    return table
