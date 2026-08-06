"""Task-stage diagnostics shared by residual-RL training and evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import IntEnum, StrEnum

import numpy as np

from franka_fruit_pick.grasp_demo import TaskSpec, check_success
from franka_fruit_pick.scene_config import TABLE_TOP_Z


def _np(value) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value, dtype=np.float32).reshape(-1)


class TaskStage(IntEnum):
    APPROACH = 0
    GRASP = 1
    LIFT = 2
    TRANSPORT = 3
    PLACE = 4
    SUCCESS = 5


class FailureStage(StrEnum):
    SUCCESS = "success"
    TARGET_APPROACH = "target_approach"
    GRASP = "grasp"
    LIFT = "lift"
    TRANSPORT_DROP = "transport_drop"
    TRANSPORT = "transport"
    PLACEMENT = "placement"
    TIMEOUT = "timeout"


@dataclass
class StageThresholds:
    reached_distance: float = 0.10
    grasp_distance: float = 0.14
    grasp_lift: float = 0.012
    lifted_height: float = 0.06
    transport_xy: float = 0.11
    open_finger: float = 0.025
    drop_height: float = 0.025


@dataclass
class StageDiagnostics:
    stage: TaskStage
    ee_target_distance: float
    target_bowl_distance: float
    target_height_above_initial: float
    target_speed: float
    reached_target: bool
    grasped: bool
    lifted: bool
    transported: bool
    released: bool
    inside_bowl: bool
    dropped: bool
    wrong_object_contact: bool = False

    def to_dict(self) -> dict:
        out = asdict(self)
        out["stage"] = self.stage.name.lower()
        return out


class TaskStageTracker:
    """Infer task progress from privileged simulator state.

    The first version uses robust geometry/history predicates.  This avoids
    coupling the RL prototype to Genesis' lower-level geom indices.  Contact-pair
    signals can be added later without changing the public diagnostics schema.
    """

    def __init__(self, bundle, task: TaskSpec, thresholds: StageThresholds | None = None):
        self.bundle = bundle
        self.task = task
        self.thresholds = thresholds or StageThresholds()
        self.target = bundle.ycb[task.pick_object]
        self.bowl = bundle.ycb[task.place_target] if isinstance(task.place_target, str) else None
        self.hand = bundle.franka.get_link("hand")
        self.initial_target_z = float(_np(self.target.get_pos())[2])

        self.ever_reached = False
        self.ever_grasped = False
        self.ever_lifted = False
        self.ever_transported = False
        self.ever_released = False
        self.ever_inside = False
        self.ever_dropped = False
        self.min_ee_target_distance = float("inf")
        self.min_target_bowl_distance = float("inf")
        self.max_target_height = 0.0
        self.last: StageDiagnostics | None = None

    def update(self) -> StageDiagnostics:
        target_pos = _np(self.target.get_pos())[:3]
        ee_pos = _np(self.hand.get_pos())[:3]
        bowl_pos = _np(self.bowl.get_pos())[:3] if self.bowl is not None else target_pos
        try:
            target_vel = _np(self.target.get_vel())[:3]
        except (AttributeError, TypeError):
            target_vel = np.zeros(3, dtype=np.float32)
        fingers = _np(self.bundle.franka.get_qpos())[-2:]

        ee_distance = float(np.linalg.norm(ee_pos - target_pos))
        bowl_distance = float(np.linalg.norm(target_pos[:2] - bowl_pos[:2]))
        height = float(target_pos[2] - self.initial_target_z)
        speed = float(np.linalg.norm(target_vel))

        reached = ee_distance < self.thresholds.reached_distance
        grasped = height > self.thresholds.grasp_lift and ee_distance < self.thresholds.grasp_distance
        lifted = height > self.thresholds.lifted_height
        transported = lifted and bowl_distance < self.thresholds.transport_xy
        released = self.ever_transported and float(np.mean(fingers)) > self.thresholds.open_finger
        inside = bool(check_success(self.bundle, self.task))
        dropped = self.ever_lifted and not inside and height < self.thresholds.drop_height

        self.ever_reached |= reached
        self.ever_grasped |= grasped
        self.ever_lifted |= lifted
        self.ever_transported |= transported
        self.ever_released |= released
        self.ever_inside |= inside
        self.ever_dropped |= dropped
        self.min_ee_target_distance = min(self.min_ee_target_distance, ee_distance)
        self.min_target_bowl_distance = min(self.min_target_bowl_distance, bowl_distance)
        self.max_target_height = max(self.max_target_height, height)

        if inside:
            stage = TaskStage.SUCCESS
        elif self.ever_transported or released:
            stage = TaskStage.PLACE
        elif self.ever_lifted:
            stage = TaskStage.TRANSPORT
        elif self.ever_grasped:
            stage = TaskStage.LIFT
        elif self.ever_reached:
            stage = TaskStage.GRASP
        else:
            stage = TaskStage.APPROACH

        self.last = StageDiagnostics(
            stage=stage,
            ee_target_distance=ee_distance,
            target_bowl_distance=bowl_distance,
            target_height_above_initial=height,
            target_speed=speed,
            reached_target=reached,
            grasped=grasped,
            lifted=lifted,
            transported=transported,
            released=released,
            inside_bowl=inside,
            dropped=dropped,
        )
        return self.last

    def failure_stage(self, *, timed_out: bool = True) -> FailureStage:
        if self.ever_inside:
            return FailureStage.SUCCESS
        if not self.ever_reached:
            return FailureStage.TARGET_APPROACH
        if not self.ever_grasped:
            return FailureStage.GRASP
        if not self.ever_lifted:
            return FailureStage.LIFT
        if self.ever_dropped and not self.ever_transported:
            return FailureStage.TRANSPORT_DROP
        if not self.ever_transported:
            return FailureStage.TRANSPORT
        if self.ever_released or self.ever_transported:
            return FailureStage.PLACEMENT
        return FailureStage.TIMEOUT if timed_out else FailureStage.TRANSPORT

    def summary(self) -> dict:
        return {
            "failure_stage": self.failure_stage().value,
            "ever_reached": self.ever_reached,
            "ever_grasped": self.ever_grasped,
            "ever_lifted": self.ever_lifted,
            "ever_transported": self.ever_transported,
            "ever_released": self.ever_released,
            "ever_inside": self.ever_inside,
            "ever_dropped": self.ever_dropped,
            "min_ee_target_distance": self.min_ee_target_distance,
            "min_target_bowl_distance": self.min_target_bowl_distance,
            "max_target_height": self.max_target_height,
        }
