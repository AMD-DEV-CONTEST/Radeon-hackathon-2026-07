"""Genesis environment whose action is a correction to a frozen SmolVLA action."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch

from franka_fruit_pick.eval_policy import PolicyBundle, apply_action, build_observation
from franka_fruit_pick.grasp_demo import TaskSpec
from franka_fruit_pick.randomize import EnvRandomizer, RandomizationConfig
from franka_fruit_pick.record_dataset import CONTROL_FPS, task_description

from .diagnostics import StageDiagnostics, TaskStage, TaskStageTracker
from .models import ResidualScales, combine_action


def _np(value) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value, dtype=np.float32).reshape(-1)


@dataclass
class ResidualEnvConfig:
    pick_object: str = "018_plum"
    place_object: str = "024_bowl"
    jitter: float = 0.03
    max_policy_steps: int = 450
    task_mode: str = "full"  # lift | full
    success_dwell: int = 12
    lift_dwell: int = 9
    terminate_on_drop: bool = True
    residual_scales: ResidualScales = ResidualScales()


class PlumReward:
    """Stage-aware shaped reward with explicit term reporting."""

    def __init__(self):
        self.previous: StageDiagnostics | None = None

    def reset(self, diagnostics: StageDiagnostics) -> None:
        self.previous = diagnostics

    def __call__(self, current: StageDiagnostics, residual: np.ndarray) -> tuple[float, dict[str, float]]:
        previous = self.previous or current
        terms = {
            "approach_progress": 2.0 * (previous.ee_target_distance - current.ee_target_distance),
            "reached_bonus": 2.0 * float(current.reached_target and not previous.reached_target),
            "grasp_bonus": 4.0 * float(current.grasped and not previous.grasped),
            "lift_bonus": 6.0 * float(current.lifted and not previous.lifted),
            "transport_progress": (
                3.0 * (previous.target_bowl_distance - current.target_bowl_distance) if current.lifted else 0.0
            ),
            "transport_bonus": 5.0 * float(current.transported and not previous.transported),
            "place_bonus": 25.0 * float(current.inside_bowl and not previous.inside_bowl),
            "drop_penalty": -8.0 * float(current.dropped and not previous.dropped),
            "wrong_contact_penalty": -10.0 * float(current.wrong_object_contact),
            "residual_penalty": -0.02 * float(np.square(residual).sum()),
            "time_penalty": -0.01,
        }
        self.previous = current
        return float(sum(terms.values())), terms


class PlumResidualEnv:
    """One-environment, 30 Hz residual-control wrapper.

    SmolVLA remains frozen and maintains its native action queue.  Each call to
    :meth:`step` consumes exactly one queued/base policy action and applies a
    bounded correction before advancing Genesis by the appropriate 3/4 control
    substeps.
    """

    action_dim = 9

    def __init__(
        self,
        bundle,
        base_policy: PolicyBundle,
        cfg: ResidualEnvConfig | None = None,
        randomizer: EnvRandomizer | None = None,
    ):
        self.bundle = bundle
        self.base_policy = base_policy
        self.cfg = cfg or ResidualEnvConfig()
        if self.cfg.task_mode not in {"lift", "full"}:
            raise ValueError("task_mode must be 'lift' or 'full'")
        self.randomizer = randomizer or EnvRandomizer(
            bundle,
            RandomizationConfig(pos_jitter=self.cfg.jitter, randomize_pick=False),
        )
        self.reward_fn = PlumReward()
        self.task = TaskSpec(self.cfg.pick_object, self.cfg.place_object)
        self.task_text = task_description(self.cfg.pick_object)
        self.steps_per_frame = CONTROL_FPS / base_policy.fps
        self._accum = 0.0
        self._base_action: np.ndarray | None = None
        self._state: np.ndarray | None = None
        self.tracker: TaskStageTracker | None = None
        self.policy_steps = 0
        self.success_streak = 0
        self.lift_streak = 0
        self.seed = 0

    @property
    def obs_dim(self) -> int:
        if self._state is None:
            raise RuntimeError("call reset() before reading obs_dim")
        return int(self._state.size)

    def _policy_action(self) -> np.ndarray:
        obs = build_observation(self.bundle, self.base_policy)
        return self.base_policy.select_action(obs, self.task_text)

    def _privileged_state(self, base_action: np.ndarray, diagnostics: StageDiagnostics) -> np.ndarray:
        qpos = _np(self.bundle.franka.get_qpos())
        qvel = _np(self.bundle.franka.get_dofs_velocity())
        hand = self.bundle.franka.get_link("hand")
        ee_pos = _np(hand.get_pos())[:3]
        ee_quat = _np(hand.get_quat())[:4]
        target = self.bundle.ycb[self.cfg.pick_object]
        bowl = self.bundle.ycb[self.cfg.place_object]
        target_pos = _np(target.get_pos())[:3]
        target_quat = _np(target.get_quat())[:4]
        target_vel = _np(target.get_vel())[:3]
        target_ang = _np(target.get_ang())[:3]
        bowl_pos = _np(bowl.get_pos())[:3]
        phase = np.eye(len(TaskStage), dtype=np.float32)[int(diagnostics.stage)]
        flags = np.asarray(
            [
                diagnostics.reached_target,
                diagnostics.grasped,
                diagnostics.lifted,
                diagnostics.transported,
                diagnostics.released,
                diagnostics.dropped,
            ],
            dtype=np.float32,
        )
        return np.concatenate(
            [
                qpos,
                qvel,
                ee_pos,
                ee_quat,
                target_pos - ee_pos,
                target_quat,
                target_vel,
                target_ang,
                bowl_pos - target_pos,
                np.asarray(base_action, dtype=np.float32),
                phase,
                flags,
            ]
        ).astype(np.float32)

    def reset(self, seed: int) -> tuple[np.ndarray, dict]:
        self.seed = int(seed)
        self.randomizer.reset(seed=self.seed)
        self.base_policy.reset()
        torch.manual_seed(self.seed)
        if self.base_policy.device.type == "cuda":
            torch.cuda.manual_seed_all(self.seed)
        self.tracker = TaskStageTracker(self.bundle, self.task)
        diagnostics = self.tracker.update()
        self._accum = 0.0
        self.policy_steps = 0
        self.success_streak = 0
        self.lift_streak = 0
        self._base_action = self._policy_action()
        self._state = self._privileged_state(self._base_action, diagnostics)
        self.reward_fn.reset(diagnostics)
        return self._state.copy(), {"diagnostics": diagnostics.to_dict(), "seed": self.seed}

    def _termination(self, diagnostics: StageDiagnostics) -> tuple[bool, bool]:
        self.success_streak = self.success_streak + 1 if diagnostics.inside_bowl else 0
        self.lift_streak = self.lift_streak + 1 if diagnostics.lifted and not diagnostics.dropped else 0
        success = (
            self.lift_streak >= self.cfg.lift_dwell
            if self.cfg.task_mode == "lift"
            else self.success_streak >= self.cfg.success_dwell
        )
        terminal_failure = self.cfg.terminate_on_drop and diagnostics.dropped
        truncated = self.policy_steps >= self.cfg.max_policy_steps
        return bool(success or terminal_failure), bool(truncated)

    def step(self, normalized_residual: np.ndarray) -> tuple[np.ndarray, float, bool, bool, dict]:
        if self._base_action is None or self.tracker is None:
            raise RuntimeError("call reset() before step()")
        residual = np.clip(np.asarray(normalized_residual, dtype=np.float32).reshape(9), -1.0, 1.0)
        base_action = self._base_action.copy()
        action = combine_action(base_action, residual, self.cfg.residual_scales)
        self._accum += self.steps_per_frame
        n_sub = max(1, int(self._accum))
        self._accum -= int(self._accum)
        apply_action(self.bundle, action, n_sub)
        self.policy_steps += 1

        diagnostics = self.tracker.update()
        reward, reward_terms = self.reward_fn(diagnostics, residual)
        terminated, truncated = self._termination(diagnostics)

        # Advance the frozen policy queue exactly once for the next residual step.
        self._base_action = self._policy_action()
        self._state = self._privileged_state(self._base_action, diagnostics)
        info = {
            "seed": self.seed,
            "policy_steps": self.policy_steps,
            "base_action": base_action,
            "next_base_action": self._base_action.copy(),
            "applied_action": action,
            "diagnostics": diagnostics.to_dict(),
            "reward_terms": reward_terms,
            "success": self.success_streak >= self.cfg.success_dwell
            if self.cfg.task_mode == "full"
            else self.lift_streak >= self.cfg.lift_dwell,
        }
        if terminated or truncated:
            info.update(self.tracker.summary())
        return self._state.copy(), reward, terminated, truncated, info
