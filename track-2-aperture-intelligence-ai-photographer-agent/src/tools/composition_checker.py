"""Check whether a VLM observation contains actionable composition evidence."""

from __future__ import annotations

from typing import Any


def check_composition(analysis: dict[str, Any]) -> dict[str, Any]:
    composition = str(analysis.get("composition", "")).strip()
    recommendation = str(analysis.get("recommendation", "")).strip()
    issues = []
    if len(composition) < 20:
        issues.append("Composition description is too short.")
    if len(recommendation) < 20:
        issues.append("Recommendation is not yet actionable.")
    score = 100 - min(100, len(issues) * 35)
    return {
        "status": "pass" if not issues else "needs_review",
        "actionability_score": score,
        "issues": issues,
        "evidence": {
            "composition_characters": len(composition),
            "recommendation_characters": len(recommendation),
        },
    }
