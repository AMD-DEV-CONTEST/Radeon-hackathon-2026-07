"""Core contracts for the Parcel Sorter ROCm project."""

from .config import ExperimentConfig, load_config
from .contracts import CartesianAction, PolicyContext, RobotState, TrajectoryFrame
from .metrics import EpisodeResult, MetricsAccumulator
from .randomization import DomainRandomizer, ParcelSample
from .state_machine import ClosedLoopSupervisor, Command, Stage

__all__ = [
    "ClosedLoopSupervisor",
    "CartesianAction",
    "Command",
    "DomainRandomizer",
    "EpisodeResult",
    "ExperimentConfig",
    "MetricsAccumulator",
    "ParcelSample",
    "PolicyContext",
    "RobotState",
    "Stage",
    "TrajectoryFrame",
    "load_config",
]
