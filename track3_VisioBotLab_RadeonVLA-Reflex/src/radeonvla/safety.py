"""Execution safety, interruptible commands, and failure-aware recovery.

1. **CommandSession** — versioned natural-language commands. A mid-episode
   instruction change bumps the version so stale action chunks are discarded.
2. **SafetyMonitor** — clamps joint targets and can force a hold / open-gripper
   transition when a command is invalidated.
3. **FailureDetector** — empty-grasp, wrong-object, timeout, and placement
   checks that drive a single recovery retry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np

from radeonvla.protocol import (
    ACTION_DIM,
    ARM_POSITION_BOUNDS,
    FINGER_POSITION_BOUNDS,
    GRIPPER_OPEN,
    clamp_action,
)
from radeonvla.scene_config import FRANKA_QPOS, TABLE_TOP_Z
from radeonvla.tasks import TaskSpec


class FailureReason(StrEnum):
    NONE = "none"
    EMPTY_GRASP = "empty_grasp"
    WRONG_OBJECT = "wrong_object"
    WRONG_TARGET = "wrong_target"
    TIMEOUT = "timeout"
    ACTION_INVALID = "action_invalid"
    SLIP = "slip"
    UNSAFE_ACTION = "unsafe_action"


@dataclass
class CommandSession:
    """Tracks the active language command and invalidates stale action chunks."""

    instruction: str
    task_id: str
    version: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)

    def set_command(self, *, instruction: str, task_id: str, step: int | None = None) -> int:
        if instruction == self.instruction and task_id == self.task_id:
            return self.version
        self.instruction = instruction
        self.task_id = task_id
        self.version += 1
        self.events.append(
            {
                "type": "command_change",
                "version": self.version,
                "instruction": instruction,
                "task_id": task_id,
                "step": step,
            }
        )
        return self.version

    def is_current(self, version: int) -> bool:
        return version == self.version


@dataclass
class SafetyDecision:
    action: list[float]
    accepted: bool
    reason: str | None = None
    hold: bool = False
    invalidate_chunk: bool = False


class SafetyMonitor:
    """Bounds-check actions and react to command-version changes."""

    def __init__(self, *, max_joint_delta: float = 0.35):
        self.max_joint_delta = max_joint_delta
        self._last_action: np.ndarray | None = None
        self._tracked_version: int | None = None

    def reset(self) -> None:
        self._last_action = None
        self._tracked_version = None

    def process(
        self,
        action,
        *,
        command_version: int,
        force_open_gripper: bool = False,
    ) -> SafetyDecision:
        try:
            clamped = np.asarray(clamp_action(action), dtype=np.float64)
        except ValueError as exc:
            hold = list(FRANKA_QPOS)
            return SafetyDecision(action=hold, accepted=False, reason=str(exc), hold=True, invalidate_chunk=True)

        if self._tracked_version is None:
            self._tracked_version = command_version
        elif command_version != self._tracked_version:
            # Command interrupted: hold arm, open gripper, drop stale chunk.
            self._tracked_version = command_version
            hold = clamped.copy()
            if self._last_action is not None:
                hold[:7] = self._last_action[:7]
            hold[7:] = GRIPPER_OPEN
            self._last_action = hold
            return SafetyDecision(
                action=hold.tolist(),
                accepted=True,
                reason="command_invalidated",
                hold=True,
                invalidate_chunk=True,
            )

        if self._last_action is not None:
            delta = np.abs(clamped[:7] - self._last_action[:7])
            if float(delta.max()) > self.max_joint_delta:
                # Soft rate limit: blend toward the target instead of rejecting.
                scale = self.max_joint_delta / float(delta.max())
                clamped[:7] = self._last_action[:7] + (clamped[:7] - self._last_action[:7]) * scale

        if force_open_gripper:
            clamped[7:] = GRIPPER_OPEN

        # Re-clamp fingers after any open override.
        flo, fhi = FINGER_POSITION_BOUNDS
        clamped[7] = float(np.clip(clamped[7], flo, fhi))
        clamped[8] = float(np.clip(clamped[8], flo, fhi))
        for i, (lo, hi) in enumerate(ARM_POSITION_BOUNDS):
            clamped[i] = float(np.clip(clamped[i], lo, hi))

        self._last_action = clamped
        return SafetyDecision(action=clamped.tolist(), accepted=True)


@dataclass
class EpisodeDiagnostics:
    empty_grasp: bool = False
    object_lifted: bool = False
    object_correct: bool = False
    target_correct: bool = False
    success: bool = False
    failure_reason: FailureReason = FailureReason.NONE
    events: list[dict[str, Any]] = field(default_factory=list)


def _to_np(x) -> np.ndarray:
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    return np.asarray(x)


def entity_pos(entity) -> np.ndarray:
    return _to_np(entity.get_pos()).reshape(-1)


def entity_aabb(entity) -> np.ndarray:
    aabb = entity.get_AABB()
    aabb = _to_np(aabb)
    if aabb.ndim == 3:
        aabb = aabb[0]
    return aabb


def check_placement_success(
    bundle,
    task: TaskSpec,
    *,
    success_tol: float = 0.06,
    strict: bool = False,
) -> tuple[bool, bool, bool]:
    """Return (success, object_correct_proxy, target_correct).

    ``object_correct`` is True when the commanded fruit is the one that moved
    substantially from its resting height (simple proxy for the correct object).
    ``target_correct`` is True when that fruit is inside the commanded bowl.
    """
    fruit = task.target_object
    container = task.target_container
    if fruit not in bundle.objects or container not in bundle.objects:
        return False, False, False

    obj = bundle.objects[fruit]
    bowl = bundle.objects[container]
    pick_pos = entity_pos(obj)
    bowl_aabb = entity_aabb(bowl)
    rim_z = float(bowl_aabb[1, 2])
    rim_radius = 0.5 * float(min(bowl_aabb[1, 0] - bowl_aabb[0, 0], bowl_aabb[1, 1] - bowl_aabb[0, 1]))
    bowl_xy = entity_pos(bowl)[:2]
    horizontal = float(np.linalg.norm(pick_pos[:2] - bowl_xy))
    obj_bottom = float(entity_aabb(obj)[0, 2])
    if strict:
        # Formal demonstrations must finish with the fruit center clearly inside
        # the bowl footprint. A 60-step post-release settle in the expert precedes
        # this check, so no teleport/nudge or transient rim contact is accepted.
        within = horizontal < min(success_tol, rim_radius * 0.8)
        inside = obj_bottom < rim_z + 0.035
    else:
        # Runtime recovery uses a deliberately tolerant proxy: convex bowl hulls
        # can bounce a fruit a few centimetres beyond the geometric rim.
        within = horizontal < max(success_tol, rim_radius * 1.45, 0.12)
        inside = obj_bottom < rim_z + 0.05
    target_correct = bool(within and inside)

    # Object is considered "handled" if it is clearly above table rest height or inside bowl.
    object_correct = bool(target_correct or pick_pos[2] > TABLE_TOP_Z + 0.08)
    success = target_correct
    return success, object_correct, target_correct


def detect_empty_grasp(
    bundle,
    task: TaskSpec,
    *,
    gripper_width: float,
    closed_threshold: float = 0.015,
    lift_z: float | None = None,
) -> bool:
    """Heuristic: gripper is closed but the target fruit is still near the table."""
    if gripper_width > closed_threshold:
        return False
    fruit = bundle.objects.get(task.target_object)
    if fruit is None:
        return True
    pos = entity_pos(fruit)
    z_limit = TABLE_TOP_Z + 0.06 if lift_z is None else lift_z
    return bool(pos[2] < z_limit)


class FailureDetector:
    """Aggregates per-episode failure signals for recovery decisions."""

    def __init__(self, task: TaskSpec, *, max_steps: int):
        self.task = task
        self.max_steps = max_steps
        self.diag = EpisodeDiagnostics()
        self._saw_closed = False
        self._empty_grasp_hits = 0

    def observe_step(
        self,
        bundle,
        *,
        step: int,
        action: np.ndarray | list[float],
        unsafe: bool = False,
    ) -> FailureReason | None:
        action_arr = np.asarray(action, dtype=np.float64).reshape(-1)
        if action_arr.shape[0] != ACTION_DIM:
            self.diag.failure_reason = FailureReason.ACTION_INVALID
            self.diag.events.append({"type": "action_invalid", "step": step})
            return FailureReason.ACTION_INVALID

        if unsafe:
            self.diag.failure_reason = FailureReason.UNSAFE_ACTION
            self.diag.events.append({"type": "unsafe_action", "step": step})
            return FailureReason.UNSAFE_ACTION

        commanded_gripper = float(np.mean(action_arr[7:9]))
        if commanded_gripper < 0.015:
            # Use measured finger positions. A zero action marks the beginning
            # of the close/squeeze phase, before the real fingers have settled.
            measured = _to_np(bundle.franka.get_qpos()).reshape(-1)
            gripper = float(np.mean(measured[-2:]))
            if gripper >= 0.015:
                self._empty_grasp_hits = 0
            else:
                self._saw_closed = True
                if detect_empty_grasp(bundle, self.task, gripper_width=gripper):
                    self._empty_grasp_hits += 1
                # Require persistence to avoid false triggers during approach.
                if self._empty_grasp_hits >= 15:
                    self.diag.empty_grasp = True
                    self.diag.failure_reason = FailureReason.EMPTY_GRASP
                    self.diag.events.append({"type": "empty_grasp", "step": step})
                    return FailureReason.EMPTY_GRASP
        else:
            self._empty_grasp_hits = 0

        fruit = bundle.objects.get(self.task.target_object)
        if fruit is not None and float(entity_pos(fruit)[2]) > TABLE_TOP_Z + 0.12:
            self.diag.object_lifted = True

        if step + 1 >= self.max_steps:
            self.diag.failure_reason = FailureReason.TIMEOUT
            self.diag.events.append({"type": "timeout", "step": step})
            return FailureReason.TIMEOUT
        return None

    def finalize(self, bundle) -> EpisodeDiagnostics:
        success, object_correct, target_correct = check_placement_success(bundle, self.task)
        self.diag.success = success
        self.diag.object_correct = object_correct
        self.diag.target_correct = target_correct
        if success:
            self.diag.failure_reason = FailureReason.NONE
        elif self.diag.failure_reason == FailureReason.NONE:
            if object_correct and not target_correct:
                self.diag.failure_reason = FailureReason.WRONG_TARGET
            elif not object_correct:
                self.diag.failure_reason = FailureReason.WRONG_OBJECT
        return self.diag


@dataclass
class RecoveryPolicy:
    """Deterministic recovery: open gripper, retreat home, allow one retry."""

    max_retries: int = 1
    retreat_steps: int = 40

    def should_retry(self, retry_count: int, reason: FailureReason) -> bool:
        if retry_count >= self.max_retries:
            return False
        return reason in {
            FailureReason.EMPTY_GRASP,
            FailureReason.SLIP,
            FailureReason.TIMEOUT,
            FailureReason.WRONG_TARGET,
        }

    def recovery_action(self) -> list[float]:
        action = list(FRANKA_QPOS)
        action[7] = GRIPPER_OPEN
        action[8] = GRIPPER_OPEN
        return action
