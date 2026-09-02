from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PromotionBudget:
    max_attempts_per_scan: int = 10
    max_per_tool: int = 3
    max_per_cluster: int = 1
    selected: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)

    def select(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        by_tool: Counter[str] = Counter()
        by_cluster: Counter[str] = Counter()
        for candidate in candidates:
            if len(self.selected) >= self.max_attempts_per_scan:
                self._reject(candidate, "scan_budget_exhausted")
                continue
            tool = str(candidate.get("tool") or "unknown")
            cluster = _cluster_key(candidate)
            if by_tool[tool] >= self.max_per_tool:
                self._reject(candidate, "tool_budget_exhausted")
                continue
            if by_cluster[cluster] >= self.max_per_cluster:
                self._reject(candidate, "duplicate_cluster_budget_exhausted")
                continue
            by_tool[tool] += 1
            by_cluster[cluster] += 1
            self.selected.append(candidate)
        return {
            "selected": self.selected,
            "rejected": self.rejected,
            "selected_count": len(self.selected),
            "rejected_count": len(self.rejected),
            "budget": {
                "max_attempts_per_scan": self.max_attempts_per_scan,
                "max_per_tool": self.max_per_tool,
                "max_per_cluster": self.max_per_cluster,
            },
        }

    def _reject(self, candidate: dict[str, Any], reason: str) -> None:
        row = dict(candidate)
        row["promotion_reject_reason"] = reason
        self.rejected.append(row)


def _cluster_key(candidate: dict[str, Any]) -> str:
    classes = candidate.get("failure_classes") or []
    first = classes[0] if classes else "uncategorized"
    return f"{candidate.get('tool') or 'unknown'}::{first}"
