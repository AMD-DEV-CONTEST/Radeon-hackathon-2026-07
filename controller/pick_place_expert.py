"""Phase-based DLS-IK expert and reproducible demonstration collection."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from data.robot_interaction_dataset import EpisodeTrajectory, TrajectoryHDF5Writer
from simulation.genesis_env import GenesisPickPlaceEnv

from .ik_controller import ExpertDatasetWriter, IKController


@dataclass(frozen=True)
class ExpertConfig:
    approach_height: float = 0.12
    lift_height: float = 0.16
    retreat_height: float = 0.16
    position_tolerance: float = 0.025
    place_tolerance: float = 0.01
    grasp_tolerance: float = 0.075
    close_hold_steps: int = 16
    min_dual_finger_contact_steps: int = 3
    open_gripper: float = 0.04
    closed_gripper: float = 0.0


class PickPlaceIKExpert:
    """A deterministic pick-and-place state machine over a DLS IK controller."""

    def __init__(self, env: GenesisPickPlaceEnv, *, config: ExpertConfig = ExpertConfig()) -> None:
        self.env = env
        self.config = config
        self.ik = IKController(env.robot.entity, env.robot.end_effector)
        self.phase = "approach"
        self._lift_target: np.ndarray | None = None
        self._grasp_object_position: np.ndarray | None = None
        self._phase_ticks = 0

    def reset(self) -> None:
        self.phase = "approach"
        self._lift_target = None
        self._grasp_object_position = None
        self._phase_ticks = 0

    def action(self, observation: dict[str, np.ndarray]) -> np.ndarray:
        target_position, opening = self._target(observation)
        current_pose = observation["end_effector_pose"]
        target_pose = np.concatenate((target_position, current_pose[3:]))
        joint_delta = self.ik.compute_action(current_pose, target_pose).detach().cpu().numpy()
        qpos = observation["joint_position"].copy()
        arm_dofs = qpos.size - 2
        qpos[:arm_dofs] += joint_delta[:arm_dofs]
        qpos[arm_dofs:] = opening
        self._advance(observation, target_position)
        return qpos.astype(np.float32)

    def _target(self, observation: dict[str, np.ndarray]) -> tuple[np.ndarray, float]:
        object_position = observation["object_pose"][:3]
        goal_position = observation["target_pose"][:3]
        if self.phase == "approach":
            return object_position + [0.0, 0.0, self.config.approach_height], self.config.open_gripper
        if self.phase == "grasp":
            return self._eef_target_for_object(self._grasp_position(object_position), observation), self.config.open_gripper
        if self.phase == "close":
            # Do not chase an object displaced by a finger contact. Chasing
            # turns a failed pinch into a sweeping/pushing motion.
            return self._eef_target_for_object(self._grasp_position(object_position), observation), self.config.closed_gripper
        if self.phase == "lift":
            if self._lift_target is None:
                self._lift_target = object_position + [0.0, 0.0, self.config.lift_height]
            return self._eef_target_for_object(self._lift_target, observation), self.config.closed_gripper
        if self.phase == "transfer":
            return self._eef_target_for_object(
                goal_position + [0.0, 0.0, self.config.lift_height], observation
            ), self.config.closed_gripper
        if self.phase == "place":
            return self._eef_target_for_object(goal_position, observation), self.config.closed_gripper
        if self.phase == "release":
            # Open at the placement pose for one control command.  The next
            # command retreats, avoiding prolonged hand--cube contact.
            return self._eef_target_for_object(goal_position, observation), self.config.open_gripper
        if self.phase == "retreat":
            return (
                self._eef_target_for_object(
                    goal_position + [0.0, 0.0, self.config.retreat_height], observation
                ),
                self.config.open_gripper,
            )
        raise RuntimeError(f"unknown expert phase: {self.phase}")

    def _eef_target_for_object(
        self, object_target: np.ndarray, observation: dict[str, np.ndarray]
    ) -> np.ndarray:
        """Convert a desired object center into an end-effector target.

        A Genesis weld constraint stores an offset in link coordinates.  It is
        not necessarily the configured world-frame ``grasp_offset`` after the
        hand has moved or rotated.  While held, use the measured offset so
        placement is calibrated from the actual simulated grasp.
        """
        if self.env.is_grasped:
            held_offset = (
                observation["object_pose"][:3] - observation["end_effector_pose"][:3]
            )
        else:
            held_offset = self.env.grasp_offset
        return np.asarray(object_target, dtype=np.float32) - held_offset

    def _grasp_position(self, fallback: np.ndarray) -> np.ndarray:
        """Return the object center captured on entry to the grasp phase."""
        return fallback if self._grasp_object_position is None else self._grasp_object_position

    def _advance(self, observation: dict[str, np.ndarray], target: np.ndarray) -> None:
        # ``action`` computes the command before calling ``_advance``.  Thus
        # this transition keeps exactly one open-gripper command at the object,
        # then makes all following commands retreat with the gripper open.
        if self.phase == "release":
            self.phase = "retreat"
            return
        distance = np.linalg.norm(observation["end_effector_pose"][:3] - target)
        if self.phase == "grasp":
            tolerance = self.config.grasp_tolerance
        elif self.phase == "place":
            tolerance = self.config.place_tolerance
        else:
            tolerance = self.config.position_tolerance
        if distance > tolerance:
            return
        if self.phase == "close":
            self._phase_ticks += 1
            if self._phase_ticks < self.config.close_hold_steps:
                return
            if (
                not self.env.assist_grasp
                and self.env.max_consecutive_dual_finger_contact_steps
                < self.config.min_dual_finger_contact_steps
            ):
                return
        transitions = {
            "approach": "grasp", "grasp": "close", "close": "lift",
            "lift": "transfer", "transfer": "place", "place": "release",
        }
        next_phase = transitions.get(self.phase, self.phase)
        if next_phase == "lift":
            self._lift_target = observation["object_pose"][:3] + [0.0, 0.0, self.config.lift_height]
        if next_phase == "grasp":
            self._grasp_object_position = observation["object_pose"][:3].copy()
        if next_phase != self.phase:
            self.phase = next_phase
            self._phase_ticks = 0


def collect_expert_demonstrations(
    env: GenesisPickPlaceEnv,
    expert: PickPlaceIKExpert,
    *,
    episodes: int,
    output_dir: str | Path = "datasets/expert",
    seed: int = 0,
) -> dict[str, Any]:
    """Collect flattened state/action pairs and persist metadata for replay."""
    if episodes < 1:
        raise ValueError("episodes must be positive")
    output = Path(output_dir)
    writer, successes, lengths = ExpertDatasetWriter(), 0, []
    episode_summaries: list[dict[str, Any]] = []
    with TrajectoryHDF5Writer(output, env_metadata={
        "environment": type(env).__name__,
        "observation_space": str(env.observation_space),
        "action_space": str(env.action_space),
    }) as hdf5_writer:
        for episode in range(episodes):
            observation, reset_info = env.reset(seed=seed + episode)
            expert.reset()
            trajectory = EpisodeTrajectory()
            terminated = truncated = False
            length = 0
            grasped_steps = 0
            max_contact_count = 0
            max_contact_force = 0.0
            dual_finger_contact_steps = 0
            max_consecutive_dual_finger_contact_steps = 0
            phase_counts: Counter[str] = Counter()
            while not (terminated or truncated):
                state = _privileged_state(observation)
                action = expert.action(observation)
                writer.append(state, action)
                next_observation, reward, terminated, truncated, info = env.step(action)
                trajectory.append(
                    state=state, action=action, reward=reward,
                    terminated=terminated, truncated=truncated,
                    next_state=_privileged_state(next_observation),
                    proprio=_proprioception(observation),
                    next_proprio=_proprioception(next_observation),
                    observation=observation, next_observation=next_observation,
                )
                observation = next_observation
                length += 1
                grasped_steps += int(info["is_grasped"])
                max_contact_count = max(max_contact_count, int(info["robot_object_contact_count"]))
                max_contact_force = max(max_contact_force, float(info["robot_object_contact_force"]))
                dual_finger_contact_steps += int(info["dual_finger_contact"])
                max_consecutive_dual_finger_contact_steps = max(
                    max_consecutive_dual_finger_contact_steps,
                    int(info["consecutive_dual_finger_contact_steps"]),
                )
                phase_counts[expert.phase] += 1
            successes += int(info["is_success"])
            lengths.append(length)
            summary = {
                "episode": episode,
                "success": bool(info["is_success"]),
                "final_phase": expert.phase,
                "final_distance_to_goal": float(info["distance_to_goal"]),
                "final_object_position": observation["object_pose"][:3].tolist(),
                "goal_position": observation["target_pose"][:3].tolist(),
                "randomization": reset_info.get("domain_randomization"),
                "grasped_steps": grasped_steps,
                "object_was_lifted": bool(info["object_was_lifted"]),
                "max_robot_object_contact_count": max_contact_count,
                "max_robot_object_contact_force": max_contact_force,
                "dual_finger_contact_steps": dual_finger_contact_steps,
                "max_consecutive_dual_finger_contact_steps": max_consecutive_dual_finger_contact_steps,
                "phase_steps": dict(phase_counts),
            }
            episode_summaries.append(summary)
            hdf5_writer.add_episode(trajectory, episode=episode, metadata=summary)
    state_path, action_path = writer.save(output)
    metadata = {
        "episodes": episodes, "success_rate": successes / episodes,
        "mean_episode_length": float(np.mean(lengths)), "seed": seed,
        "state_path": str(state_path), "action_path": str(action_path),
        "hdf5_path": str(output / "dataset.hdf5"),
        "manifest_path": str(output / "manifest.json"),
        "episodes_detail": episode_summaries,
    }
    metadata_path = Path(output_dir) / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def _privileged_state(observation: dict[str, np.ndarray]) -> np.ndarray:
    """Flatten non-image task state while keeping RGB as a separate modality."""
    return np.concatenate((
        observation["joint_position"], observation["joint_velocity"],
        observation["end_effector_pose"], observation["object_pose"], observation["target_pose"],
    )).astype(np.float32, copy=False)


def _proprioception(observation: dict[str, np.ndarray]) -> np.ndarray:
    """Robot-only input available to the visual student at inference time."""
    return np.concatenate((
        observation["joint_position"], observation["joint_velocity"], observation["end_effector_pose"],
    )).astype(np.float32, copy=False)
