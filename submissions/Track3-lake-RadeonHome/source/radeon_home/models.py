"""Shared, simulator-independent data models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ActionType(str, Enum):
    PICK_AND_PLACE = "pick_and_place"
    PLACE_NEAR = "place_near"


class FailureType(str, Enum):
    GRASP_MISS = "grasp_miss"
    OBJECT_SLIP = "object_slip"
    PATH_BLOCKED = "path_blocked"
    TARGET_MOVED = "target_moved"
    PLACEMENT_FAILED = "placement_failed"


@dataclass(frozen=True)
class SafetyConstraint:
    kind: str
    object_id: str
    minimum_clearance_m: float = 0.08


@dataclass(frozen=True)
class TaskStep:
    action: ActionType
    object_id: str
    target_id: str | None = None
    reference_id: str | None = None
    constraints: tuple[SafetyConstraint, ...] = ()


@dataclass
class TaskPlan:
    instruction: str
    steps: list[TaskStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GraspCandidate:
    offset_x_m: float
    offset_y_m: float
    yaw_deg: float
    approach_height_m: float
    obstacle_clearance_m: float
    previous_failures: int = 0


@dataclass(frozen=True)
class ScoredGrasp:
    candidate: GraspCandidate
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RecoveryDecision:
    failure: FailureType
    action: str
    parameter_changes: dict[str, float | bool]
    explanation: str

