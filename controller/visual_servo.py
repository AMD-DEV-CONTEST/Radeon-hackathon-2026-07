"""Image-based visual servo controller over the calibrated IK skill library."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from simulation.genesis_env import GenesisPickPlaceEnv

from .color_marker_perception import ColorMarkerPerception
from .contact_verifier import ContactAwareGraspVerifier, ContactVerifierConfig
from .pick_place_expert import PickPlaceIKExpert


@dataclass(frozen=True)
class VisualServoConfig:
    object_ema: float = 0.25
    table_height: float = 0.04
    relocalize_distance_m: float = 0.05
    close_timeout_steps: int = 24
    max_recoveries: int = 2
    post_release_verify_steps: int = 4
    grasp_offset: tuple[float, float, float] | None = None
    min_consecutive_dual_finger_steps: int = 3
    min_contact_force: float = 0.0
    unverified_lift_grace_steps: int = 4
    # Kept configurable for the controlled ``no_contact_gate`` ablation.  The
    # production controller must leave this enabled.
    require_contact_verification: bool = True


class VisualServoController:
    """Perceive table markers, filter estimates, and execute contact-aware IK."""

    def __init__(
        self, env: GenesisPickPlaceEnv, expert: PickPlaceIKExpert,
        perception: ColorMarkerPerception, *, config: VisualServoConfig = VisualServoConfig(),
    ) -> None:
        self.env = env
        self.expert = expert
        self.perception = perception
        self.config = config
        self.grasp_offset = np.asarray(
            env.grasp_offset if config.grasp_offset is None else config.grasp_offset, dtype=np.float32,
        )
        self.contact_verifier = ContactAwareGraspVerifier(ContactVerifierConfig(
            min_consecutive_dual_finger_steps=config.min_consecutive_dual_finger_steps,
            min_contact_force=config.min_contact_force,
            unverified_lift_grace_steps=config.unverified_lift_grace_steps,
        ))
        self.object_position: np.ndarray | None = None
        self.target_position: np.ndarray | None = None
        self.last_raw_estimate: tuple[np.ndarray | None, np.ndarray | None] = (None, None)
        self._close_steps = 0
        self.recovery_count = 0
        self.last_recovery_reason: str | None = None
        self.dual_finger_contact_steps = 0
        self.held_object_offset: np.ndarray | None = None
        self._was_grasped = False
        self.latch_visual_calibrations = 0
        self._retreat_steps = 0
        self.contact_verifier.reset()

    def reset(self) -> None:
        self.expert.reset()
        self.object_position = None
        self.target_position = None
        self.last_raw_estimate = (None, None)
        self._close_steps = 0
        self.recovery_count = 0
        self.last_recovery_reason = None
        self.dual_finger_contact_steps = 0
        self.held_object_offset = None
        self._was_grasped = False
        self.latch_visual_calibrations = 0
        self._retreat_steps = 0

    def update_feedback(self, info: dict[str, object], observation: dict[str, np.ndarray]) -> None:
        """Consume contact feedback from the previous control step.

        This keeps visual servoing separate from the physics engine while using
        the same dual-finger evidence that gates the temporary grasp latch.
        """
        self.dual_finger_contact_steps += int(bool(info.get("dual_finger_contact", False)))
        self.contact_verifier.update(info)
        grasped = bool(info.get("is_grasped", False))
        if grasped and not self._was_grasped:
            # This frame is rendered after the latch has been created. Unlike
            # the previous control-step estimate, its marker and EEF pose are
            # temporally aligned, so it can calibrate the placement-relevant
            # XY offset without accessing privileged object state.
            object_xy, _ = self.perception.estimate(observation["camera"])
            if object_xy is not None:
                offset = np.asarray(self.env.grasp_offset, dtype=np.float32).copy()
                offset[:2] = object_xy - observation["end_effector_pose"][:2]
                self.held_object_offset = offset
                self.latch_visual_calibrations += 1
        self._was_grasped = grasped

    def _recover_grasp(self, reason: str) -> None:
        if self.recovery_count >= self.config.max_recoveries:
            return
        self.recovery_count += 1
        self.last_recovery_reason = reason
        self._close_steps = 0
        # Re-open, return above the visually relocalized object, and retry.
        self.expert.reset()
        self.object_position = None

    def action(self, observation: dict[str, np.ndarray]) -> np.ndarray:
        if (
            self.config.require_contact_verification
            and self.expert.phase in {"lift", "transfer", "place"}
            and self.contact_verifier.requires_recovery_before_transport()
        ):
            self._recover_grasp("transport_without_contact_verified_grasp")
        if self.config.require_contact_verification and self.expert.phase == "close" and not self.env.is_grasped:
            self._close_steps += 1
            if self._close_steps >= self.config.close_timeout_steps:
                self._recover_grasp("close_timeout_without_contact_confirmed_grasp")
        else:
            self._close_steps = 0
        object_xy, target_xy = self.perception.estimate(observation["camera"])
        self.last_raw_estimate = (object_xy, target_xy)
        if self.target_position is None:
            if target_xy is None:
                raise RuntimeError("green target marker was not detected at reset")
            self.target_position = np.array([target_xy[0], target_xy[1], self.config.table_height], dtype=np.float32)
        if self.env.is_grasped:
            # The object is now commonly occluded by the hand. Propagate its
            # known relative position from proprioception instead of redetecting.
            offset = self.grasp_offset if self.held_object_offset is None else self.held_object_offset
            self.object_position = observation["end_effector_pose"][:3] + offset
        elif object_xy is not None:
            measured = np.array([object_xy[0], object_xy[1], self.config.table_height], dtype=np.float32)
            if self.object_position is None or np.linalg.norm(measured[:2] - self.object_position[:2]) > self.config.relocalize_distance_m:
                self.object_position = measured
            else:
                self.object_position = (
                    (1.0 - self.config.object_ema) * self.object_position + self.config.object_ema * measured
                ).astype(np.float32)
        if self.expert.phase == "retreat" and not self.env.is_grasped:
            self._retreat_steps += 1
            if (
                self._retreat_steps >= self.config.post_release_verify_steps
                and object_xy is not None
                and self.target_position is not None
                and np.linalg.norm(object_xy - self.target_position[:2]) > self.env.success_threshold
            ):
                # The object has been released but visually misses the green
                # tile. Re-run the verified pick-place skill from its measured
                # table position instead of accepting a near-miss at timeout.
                self._recover_grasp("post_release_visual_placement_error")
                self.object_position = np.array(
                    [object_xy[0], object_xy[1], self.config.table_height], dtype=np.float32,
                )
        else:
            self._retreat_steps = 0
        if self.object_position is None:
            raise RuntimeError("red object marker was not detected before grasp")
        estimated = dict(observation)
        object_pose = np.array(observation["object_pose"], dtype=np.float32, copy=True)
        target_pose = np.array(observation["target_pose"], dtype=np.float32, copy=True)
        object_pose[:3], target_pose[:3] = self.object_position, self.target_position
        estimated["object_pose"], estimated["target_pose"] = object_pose, target_pose
        return self.expert.action(estimated)
