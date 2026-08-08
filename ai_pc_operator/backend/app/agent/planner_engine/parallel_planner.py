"""Parallel Planner — identifies which tasks can run in parallel.

Uses the dependency graph to find waves of tasks that have no
inter-dependencies and can be executed concurrently.

Also considers:
  - Resource limits (max concurrent tasks)
  - Risk isolation (don't run risky tasks in parallel with safe ones)
  - Approval gates (risky tasks must run alone)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .task_decomposer import Task
from .dependency_graph import DependencyGraph


@dataclass
class ParallelGroup:
    """A group of tasks that can run in parallel."""
    wave_index: int
    task_ids: List[str]
    parallel_safe: bool = True
    requires_approval: bool = False
    max_risk: int = 0
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wave_index": self.wave_index,
            "task_ids": self.task_ids,
            "parallel_safe": self.parallel_safe,
            "requires_approval": self.requires_approval,
            "max_risk": self.max_risk,
            "reason": self.reason,
        }


@dataclass
class ParallelPlan:
    """A parallel execution plan."""
    groups: List[ParallelGroup] = field(default_factory=list)
    total_waves: int = 0
    max_concurrency: int = 1
    estimated_speedup: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "groups": [g.to_dict() for g in self.groups],
            "total_waves": self.total_waves,
            "max_concurrency": self.max_concurrency,
            "estimated_speedup": round(self.estimated_speedup, 2),
        }


class ParallelPlanner:
    """Plans parallel execution of tasks."""

    # Tools that should never run in parallel with anything else
    EXCLUSIVE_TOOLS = {
        "approval.request",
        "vault.unlock",
        "system.shutdown",
        "system.restart",
    }

    # Tools that are safe to parallelize
    PARALLEL_SAFE_TOOLS = {
        "file.scan",
        "file.list",
        "system.status",
        "browser.verify_loaded",
        "download.verify_source",
    }

    def __init__(self, max_concurrency: int = 3):
        self.max_concurrency = max_concurrency

    def plan(self, graph: DependencyGraph) -> ParallelPlan:
        """Build a parallel execution plan from a dependency graph."""
        waves = graph.build_waves()
        groups: List[ParallelGroup] = []

        for i, wave in enumerate(waves):
            tasks = [graph.nodes[tid].task for tid in wave]
            group = self._build_group(i, wave, tasks)
            groups.append(group)

        # Compute speedup estimate
        total_tasks = sum(len(g.task_ids) for g in groups)
        speedup = total_tasks / max(len(groups), 1) if groups else 1.0

        return ParallelPlan(
            groups=groups,
            total_waves=len(groups),
            max_concurrency=self.max_concurrency,
            estimated_speedup=speedup,
        )

    def _build_group(
        self,
        wave_index: int,
        task_ids: List[str],
        tasks: List[Task],
    ) -> ParallelGroup:
        """Build a parallel group from a wave of tasks."""
        # Check for exclusive tools
        has_exclusive = any(t.tool in self.EXCLUSIVE_TOOLS for t in tasks)
        # Check for approval requirement
        requires_approval = any(t.tool == "approval.request" for t in tasks)
        # Compute max risk (from tool name heuristics)
        max_risk = max((self._estimate_risk(t.tool) for t in tasks), default=0)
        # Check parallel safety
        parallel_safe = (
            not has_exclusive
            and not requires_approval
            and all(t.tool in self.PARALLEL_SAFE_TOOLS or self._is_read_only(t.tool)
                    for t in tasks)
        )

        # If wave has more than max_concurrency, split conceptually
        reason = ""
        if has_exclusive:
            reason = "contains_exclusive_tool"
        elif requires_approval:
            reason = "contains_approval_request"
        elif not parallel_safe:
            reason = "mixed_risk_levels"
        else:
            reason = "all_parallel_safe"

        return ParallelGroup(
            wave_index=wave_index,
            task_ids=task_ids,
            parallel_safe=parallel_safe,
            requires_approval=requires_approval,
            max_risk=max_risk,
            reason=reason,
        )

    def _estimate_risk(self, tool: str) -> int:
        """Estimate risk level from tool name."""
        tool_lower = tool.lower()
        if any(k in tool_lower for k in ("delete", "quarantine", "shutdown", "restart")):
            return 4
        if any(k in tool_lower for k in ("credential", "vault", "login", "download")):
            return 3
        if any(k in tool_lower for k in ("click", "type", "submit", "fill")):
            return 2
        if any(k in tool_lower for k in ("open", "navigate", "search")):
            return 1
        return 0

    def _is_read_only(self, tool: str) -> bool:
        """Check if a tool is read-only."""
        read_only_keywords = ["scan", "list", "status", "verify", "locate", "read"]
        return any(k in tool.lower() for k in read_only_keywords)
