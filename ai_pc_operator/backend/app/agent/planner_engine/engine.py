"""Planner Engine — orchestrator that ties all 6 stages together.

Pipeline:
  1. Goal Planner        → high-level Goal from intent
  2. Task Decomposer     → atomic Tasks from Goal
  3. Pipeline Selector   → execution strategy
  4. Dependency Graph    → DAG with topological order
  5. Parallel Planner    → wave-based parallel groups
  6. Cost Estimator      → time/memory/token estimates
  7. Risk Analyzer       → aggregate risk + approval needs

The engine returns a complete Plan that the executor can run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .goal_planner import GoalPlanner, Goal
from .task_decomposer import TaskDecomposer, Task
from .pipeline_selector import PipelineSelector, PipelineSpec
from .dependency_graph import DependencyGraph, GraphValidation
from .parallel_planner import ParallelPlanner, ParallelPlan
from .cost_estimator import CostEstimator, CostEstimate
from .risk_analyzer import RiskAnalyzer, RiskAnalysis


@dataclass
class Plan:
    """A complete execution plan."""
    goal: Goal
    tasks: List[Task]
    pipeline: PipelineSpec
    graph: DependencyGraph
    graph_validation: GraphValidation
    parallel_plan: ParallelPlan
    cost_estimate: CostEstimate
    risk_analysis: RiskAnalysis
    topological_order: List[str] = field(default_factory=list)
    waves: List[List[str]] = field(default_factory=list)
    critical_path: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal.to_dict(),
            "tasks": [t.to_dict() for t in self.tasks],
            "pipeline": self.pipeline.to_dict(),
            "graph": self.graph.to_dict(),
            "graph_validation": self.graph_validation.to_dict(),
            "parallel_plan": self.parallel_plan.to_dict(),
            "cost_estimate": self.cost_estimate.to_dict(),
            "risk_analysis": self.risk_analysis.to_dict(),
            "topological_order": self.topological_order,
            "waves": self.waves,
            "critical_path": self.critical_path,
        }


class PlannerEngine:
    """The full Planner Engine pipeline."""

    def __init__(
        self,
        goal_planner: Optional[GoalPlanner] = None,
        task_decomposer: Optional[TaskDecomposer] = None,
        pipeline_selector: Optional[PipelineSelector] = None,
        parallel_planner: Optional[ParallelPlanner] = None,
        cost_estimator: Optional[CostEstimator] = None,
        risk_analyzer: Optional[RiskAnalyzer] = None,
    ):
        self.goal_planner = goal_planner or GoalPlanner()
        self.task_decomposer = task_decomposer or TaskDecomposer()
        self.pipeline_selector = pipeline_selector or PipelineSelector()
        self.parallel_planner = parallel_planner or ParallelPlanner()
        self.cost_estimator = cost_estimator or CostEstimator()
        self.risk_analyzer = risk_analyzer or RiskAnalyzer()

    def plan(self, intent: str, params: Dict[str, Any]) -> Plan:
        """Build a complete plan from an intent and its parameters.

        Args:
            intent: the classified intent (e.g., "open_website")
            params: extracted parameters (e.g., {"url": "https://..."})

        Returns:
            A complete Plan with goal, tasks, pipeline, graph, costs, risks.
        """
        # Stage 1: Goal Planner
        goal = self.goal_planner.plan(intent, params)

        # Stage 2: Task Decomposer
        tasks = self.task_decomposer.decompose(goal)

        # Stage 3: Pipeline Selector (preliminary, refined after risk analysis)
        pipeline = self.pipeline_selector.select(
            intent=intent,
            tasks=tasks,
            risk_level=0,
            requires_approval=False,
        )

        # Stage 4: Dependency Graph
        graph = DependencyGraph.from_tasks(tasks)
        graph_validation = graph.validate()
        topological_order = graph.topological_sort()
        waves = graph.build_waves()
        critical_path = graph.critical_path()

        # Stage 5: Parallel Planner
        parallel_plan = self.parallel_planner.plan(graph)

        # Stage 6: Cost Estimator
        cost_estimate = self.cost_estimator.estimate(tasks, parallel_plan)

        # Stage 7: Risk Analyzer
        risk_analysis = self.risk_analyzer.analyze(tasks)

        # Refine pipeline selection based on risk analysis
        if risk_analysis.requires_approval and pipeline.name not in ("approval-gated", "interactive"):
            pipeline = self.pipeline_selector.select(
                intent=intent,
                tasks=tasks,
                risk_level=risk_analysis.level,
                requires_approval=True,
            )

        return Plan(
            goal=goal,
            tasks=tasks,
            pipeline=pipeline,
            graph=graph,
            graph_validation=graph_validation,
            parallel_plan=parallel_plan,
            cost_estimate=cost_estimate,
            risk_analysis=risk_analysis,
            topological_order=topological_order,
            waves=waves,
            critical_path=critical_path,
        )
