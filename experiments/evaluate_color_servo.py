"""Evaluate calibrated color-marker visual servoing with contact-aware IK."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from controller.color_marker_perception import ColorMarkerPerception, MarkerCalibration
from controller.pick_place_expert import ExpertConfig, PickPlaceIKExpert
from controller.visual_servo import VisualServoConfig, VisualServoController
from simulation.randomization import TaskRandomizationConfig, make_domain_randomizer
from simulation.task_factory import PickPlaceTaskConfig, initialize_genesis, make_pick_place_env


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/evaluate_color_servo.yaml"))
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    task_yaml = yaml.safe_load(Path(config["task_config"]).read_text())
    initialize_genesis(backend=task_yaml["genesis_backend"])
    randomizer = make_domain_randomizer(
        TaskRandomizationConfig(**task_yaml["domain_randomization"]), seed=int(config["seed"]),
    )
    env = make_pick_place_env(
        config=PickPlaceTaskConfig(**task_yaml["task"]), domain_randomizer=randomizer,
    )
    perception = ColorMarkerPerception(MarkerCalibration.load(config["calibration"]))
    servo_config = dict(config.get("visual_servo", {}))
    if config.get("grasp_offset_calibration"):
        grasp_calibration = json.loads(Path(config["grasp_offset_calibration"]).read_text())
        servo_config["grasp_offset"] = tuple(grasp_calibration["median_offset"])
    controller = VisualServoController(
        env, PickPlaceIKExpert(env, config=ExpertConfig(**task_yaml["expert"])), perception,
        config=VisualServoConfig(**servo_config),
    )
    successes = 0
    object_errors: list[float] = []
    target_errors: list[float] = []
    detection_failures = 0
    total_recoveries = 0
    episodes_with_recovery = 0
    dual_finger_contact_steps = 0
    latch_visual_calibrations = 0
    contact_verified_episodes = 0
    max_contact_forces: list[float] = []
    max_consecutive_dual_contact_steps: list[int] = []
    final_phase_counts: dict[str, int] = {}
    failed_after_lift = 0
    final_distances: list[float] = []
    for episode in range(int(config["episodes"])):
        observation, _ = env.reset(seed=int(config["seed"]) + episode)
        controller.reset()
        terminated = truncated = False
        info: dict[str, Any] = {}
        while not (terminated or truncated):
            try:
                action = controller.action(observation)
            except RuntimeError:
                detection_failures += 1
                break
            object_xy, target_xy = controller.last_raw_estimate
            if object_xy is not None:
                object_errors.append(float(np.linalg.norm(object_xy - observation["object_pose"][:2])))
            if target_xy is not None:
                target_errors.append(float(np.linalg.norm(target_xy - observation["target_pose"][:2])))
            observation, _, terminated, truncated, info = env.step(action)
            controller.update_feedback(info, observation)
        successes += int(bool(info.get("is_success", False)))
        phase = controller.expert.phase
        final_phase_counts[phase] = final_phase_counts.get(phase, 0) + 1
        failed_after_lift += int(not bool(info.get("is_success", False)) and bool(info.get("object_was_lifted", False)))
        if "distance_to_goal" in info:
            final_distances.append(float(info["distance_to_goal"]))
        total_recoveries += controller.recovery_count
        episodes_with_recovery += int(controller.recovery_count > 0)
        dual_finger_contact_steps += controller.dual_finger_contact_steps
        latch_visual_calibrations += controller.latch_visual_calibrations
        contact_verified_episodes += int(controller.contact_verifier.verification_events > 0)
        max_contact_forces.append(controller.contact_verifier.max_contact_force)
        max_consecutive_dual_contact_steps.append(controller.contact_verifier.max_consecutive_dual_finger_contact_steps)
    print({
        "color_visual_servo": {
            "success_rate": successes / int(config["episodes"]),
            "object_xy_mean_error_m": float(np.mean(object_errors)) if object_errors else None,
            "target_xy_mean_error_m": float(np.mean(target_errors)) if target_errors else None,
            "detection_failure_episodes": detection_failures,
            "total_grasp_recoveries": total_recoveries,
            "episodes_with_recovery": episodes_with_recovery,
            "dual_finger_contact_steps": dual_finger_contact_steps,
            "latch_visual_calibrations": latch_visual_calibrations,
            "controller_grasp_offset": controller.grasp_offset.tolist(),
            "contact_verified_episodes": contact_verified_episodes,
            "mean_max_contact_force": float(np.mean(max_contact_forces)),
            "mean_max_consecutive_dual_finger_contact_steps": float(np.mean(max_consecutive_dual_contact_steps)),
            "final_phase_counts": final_phase_counts,
            "failed_after_lift_episodes": failed_after_lift,
            "mean_final_distance_m": float(np.mean(final_distances)) if final_distances else None,
        }
    })


if __name__ == "__main__":
    main()
