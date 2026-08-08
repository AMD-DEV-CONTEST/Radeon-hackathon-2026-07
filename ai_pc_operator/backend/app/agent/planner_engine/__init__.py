"""Planner Engine — 7-stage pipeline for building execution plans.

Stages:
  1. Goal Planner        (goal_planner.py)
  2. Task Decomposer     (task_decomposer.py)
  3. Pipeline Selector   (pipeline_selector.py)
  4. Dependency Graph    (dependency_graph.py)
  5. Parallel Planner    (parallel_planner.py)
  6. Cost Estimator      (cost_estimator.py)
  7. Risk Analyzer       (risk_analyzer.py)

Orchestrator:
  - PlannerEngine        (engine.py)

Usage:
    from app.agent.planner_engine import PlannerEngine

    engine = PlannerEngine()
    plan = engine.plan(intent="open_website", params={"url": "https://..."})
    # plan.tasks, plan.graph, plan.cost_estimate, plan.risk_analysis
"""

from .goal_planner import (
    GoalPlanner,
    Goal,
)
from .task_decomposer import (
    TaskDecomposer,
    Task,
)
from .pipeline_selector import (
    PipelineSelector,
    PipelineSpec,
)
from .dependency_graph import (
    DependencyGraph,
    GraphNode,
    GraphValidation,
)
from .parallel_planner import (
    ParallelPlanner,
    ParallelGroup,
    ParallelPlan,
)
from .cost_estimator import (
    CostEstimator,
    CostBreakdown,
    CostEstimate,
)
from .risk_analyzer import (
    RiskAnalyzer,
    RiskFactor,
    RiskAnalysis,
)
from .engine import (
    PlannerEngine,
    Plan,
)

__all__ = [
    # Stage 1
    "GoalPlanner",
    "Goal",
    # Stage 2
    "TaskDecomposer",
    "Task",
    # Stage 3
    "PipelineSelector",
    "PipelineSpec",
    # Stage 4
    "DependencyGraph",
    "GraphNode",
    "GraphValidation",
    # Stage 5
    "ParallelPlanner",
    "ParallelGroup",
    "ParallelPlan",
    # Stage 6
    "CostEstimator",
    "CostBreakdown",
    "CostEstimate",
    # Stage 7
    "RiskAnalyzer",
    "RiskFactor",
    "RiskAnalysis",
    # Orchestrator
    "PlannerEngine",
    "Plan",
]
