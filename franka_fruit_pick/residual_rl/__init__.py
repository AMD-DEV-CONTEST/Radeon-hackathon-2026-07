"""Residual reinforcement learning on top of a frozen LeRobot policy.

The first implementation deliberately uses privileged simulator state for the
residual actor.  It is an oracle experiment: establish whether small corrections
can improve the plum task before investing in a deployable visual residual actor.
"""

from .diagnostics import FailureStage, StageDiagnostics, TaskStage, TaskStageTracker
from .models import ResidualActor, ResidualCritic, ResidualScales, combine_action

__all__ = [
    "FailureStage",
    "ResidualActor",
    "ResidualCritic",
    "ResidualScales",
    "StageDiagnostics",
    "TaskStage",
    "TaskStageTracker",
    "combine_action",
]
