"""Cost Estimator — estimates the cost of executing a plan.

Costs include:
  - Time: estimated execution duration
  - Tokens: LLM tokens for planning/verification
  - Memory: peak RAM usage
  - Network: bytes transferred
  - Risk: aggregate risk score
  - Reversibility: whether the plan can be undone

The estimator uses tool-specific cost profiles and the parallel plan
to compute realistic estimates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .task_decomposer import Task
from .parallel_planner import ParallelPlan


@dataclass
class CostBreakdown:
    """Detailed cost breakdown."""
    time_seconds: float = 0.0
    tokens: int = 0
    memory_mb: float = 0.0
    network_bytes: int = 0
    risk_score: float = 0.0
    reversible: bool = True
    tool_costs: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "time_seconds": round(self.time_seconds, 2),
            "tokens": self.tokens,
            "memory_mb": round(self.memory_mb, 2),
            "network_bytes": self.network_bytes,
            "risk_score": round(self.risk_score, 2),
            "reversible": self.reversible,
            "tool_costs": self.tool_costs,
        }


@dataclass
class CostEstimate:
    """Total cost estimate for a plan."""
    total: CostBreakdown
    per_wave: List[CostBreakdown] = field(default_factory=list)
    confidence: float = 0.7
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total.to_dict(),
            "per_wave": [w.to_dict() for w in self.per_wave],
            "confidence": round(self.confidence, 2),
            "notes": self.notes,
        }


class CostEstimator:
    """Estimates execution cost of a plan."""

    # Tool cost profiles
    TOOL_PROFILES = {
        "browser.warmup": {"time": 2.0, "memory": 50.0, "tokens": 0, "network": 0},
        "browser.open": {"time": 5.0, "memory": 100.0, "tokens": 50, "network": 500_000},
        "browser.search": {"time": 3.0, "memory": 80.0, "tokens": 30, "network": 200_000},
        "browser.verify_loaded": {"time": 1.0, "memory": 20.0, "tokens": 0, "network": 0},
        "browser.submit": {"time": 3.0, "memory": 50.0, "tokens": 20, "network": 100_000},
        "system.open_app": {"time": 4.0, "memory": 150.0, "tokens": 0, "network": 0},
        "system.status": {"time": 1.0, "memory": 10.0, "tokens": 0, "network": 0},
        "system.keep_awake": {"time": 0.5, "memory": 5.0, "tokens": 0, "network": 0},
        "system.mouse_jiggle": {"time": 0.5, "memory": 5.0, "tokens": 0, "network": 0},
        "file.list": {"time": 2.0, "memory": 30.0, "tokens": 0, "network": 0},
        "file.scan": {"time": 5.0, "memory": 50.0, "tokens": 0, "network": 0},
        "file.quarantine": {"time": 3.0, "memory": 40.0, "tokens": 0, "network": 0},
        "screen.scan": {"time": 2.0, "memory": 80.0, "tokens": 100, "network": 0},
        "screen.locate": {"time": 1.0, "memory": 30.0, "tokens": 50, "network": 0},
        "screen.click": {"time": 1.0, "memory": 10.0, "tokens": 0, "network": 0},
        "vault.unlock": {"time": 3.0, "memory": 20.0, "tokens": 0, "network": 0},
        "auth.fill_credentials": {"time": 2.0, "memory": 20.0, "tokens": 0, "network": 0},
        "approval.request": {"time": 30.0, "memory": 5.0, "tokens": 0, "network": 0},
        "download.verify_source": {"time": 1.0, "memory": 10.0, "tokens": 0, "network": 0},
        "download.file": {"time": 30.0, "memory": 50.0, "tokens": 0, "network": 5_000_000},
        "download.hash": {"time": 2.0, "memory": 20.0, "tokens": 0, "network": 0},
    }

    DEFAULT_PROFILE = {"time": 5.0, "memory": 30.0, "tokens": 20, "network": 0}

    # Risk weights for tools
    RISK_WEIGHTS = {
        "delete": 4.0, "quarantine": 3.0, "credential": 4.0,
        "vault": 3.0, "login": 3.0, "download": 2.0,
        "click": 1.0, "submit": 1.5, "fill": 1.5,
        "open": 0.5, "navigate": 0.5, "search": 0.3,
    }

    def estimate(
        self,
        tasks: List[Task],
        parallel_plan: Optional[ParallelPlan] = None,
    ) -> CostEstimate:
        """Estimate the cost of executing the given tasks."""
        total = CostBreakdown()
        per_wave: List[CostBreakdown] = []
        notes: List[str] = []

        if parallel_plan:
            # Use parallel plan for wave-based estimation
            for group in parallel_plan.groups:
                wave_breakdown = self._estimate_wave(group.task_ids, tasks)
                per_wave.append(wave_breakdown)
                # Aggregate (take max for time/memory, sum for tokens/network)
                total.time_seconds += wave_breakdown.time_seconds
                total.memory_mb = max(total.memory_mb, wave_breakdown.memory_mb)
                total.tokens += wave_breakdown.tokens
                total.network_bytes += wave_breakdown.network_bytes
                total.risk_score = max(total.risk_score, wave_breakdown.risk_score)
                total.reversible = total.reversible and wave_breakdown.reversible
        else:
            # Sequential estimation
            for task in tasks:
                breakdown = self._estimate_task(task)
                total.time_seconds += breakdown.time_seconds
                total.memory_mb = max(total.memory_mb, breakdown.memory_mb)
                total.tokens += breakdown.tokens
                total.network_bytes += breakdown.network_bytes
                total.risk_score = max(total.risk_score, breakdown.risk_score)
                total.reversible = total.reversible and breakdown.reversible
                total.tool_costs[task.tool] = breakdown.to_dict()

        # Add notes
        if total.time_seconds > 60:
            notes.append("Long-running plan (>60s)")
        if total.risk_score >= 3:
            notes.append("High risk plan")
        if not total.reversible:
            notes.append("Plan contains irreversible actions")
        if total.memory_mb > 500:
            notes.append("High memory usage (>500MB)")

        # Confidence based on how many tools we have profiles for
        known = sum(1 for t in tasks if t.tool in self.TOOL_PROFILES)
        confidence = known / max(len(tasks), 1) if tasks else 1.0

        return CostEstimate(
            total=total,
            per_wave=per_wave,
            confidence=confidence,
            notes=notes,
        )

    def _estimate_wave(self, task_ids: List[str], tasks: List[Task]) -> CostBreakdown:
        """Estimate cost of a wave (parallel group)."""
        wave_tasks = [t for t in tasks if t.id in task_ids]
        if not wave_tasks:
            return CostBreakdown()

        # For parallel: take max time, sum memory/tokens/network
        breakdown = CostBreakdown()
        for task in wave_tasks:
            task_cost = self._estimate_task(task)
            breakdown.time_seconds = max(breakdown.time_seconds, task_cost.time_seconds)
            breakdown.memory_mb += task_cost.memory_mb
            breakdown.tokens += task_cost.tokens
            breakdown.network_bytes += task_cost.network_bytes
            breakdown.risk_score = max(breakdown.risk_score, task_cost.risk_score)
            breakdown.reversible = breakdown.reversible and task_cost.reversible
            breakdown.tool_costs[task.tool] = task_cost.to_dict()
        return breakdown

    def _estimate_task(self, task: Task) -> CostBreakdown:
        """Estimate cost of a single task."""
        profile = self.TOOL_PROFILES.get(task.tool, self.DEFAULT_PROFILE)
        risk = self._estimate_risk(task.tool)
        reversible = not any(k in task.tool.lower() for k in ("delete", "credential"))

        return CostBreakdown(
            time_seconds=profile["time"],
            memory_mb=profile["memory"],
            tokens=profile["tokens"],
            network_bytes=profile["network"],
            risk_score=risk,
            reversible=reversible,
        )

    def _estimate_risk(self, tool: str) -> float:
        """Estimate risk score from tool name."""
        tool_lower = tool.lower()
        score = 0.0
        for keyword, weight in self.RISK_WEIGHTS.items():
            if keyword in tool_lower:
                score = max(score, weight)
        return score
