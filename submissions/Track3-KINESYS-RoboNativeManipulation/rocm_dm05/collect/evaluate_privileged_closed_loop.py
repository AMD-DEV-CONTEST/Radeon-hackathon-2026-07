#!/usr/bin/env python3
"""Evaluate the privileged feedback controller under expanded randomization."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from enhanced_randomization import apply_enhanced_randomization
from env_utils import build_env
from privileged_policy import PrivilegedExpertPolicy, dishwasher_unload_cutlery_status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-start", type=int, default=510000)
    parser.add_argument("--episodes", type=int, default=20)
    parser.add_argument("--max-steps", type=int, default=1600)
    parser.add_argument("--force-reference", type=str)
    parser.add_argument("--door", type=float)
    parser.add_argument("--bottom-tray", type=float)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--demo-root",
        type=Path,
        default=Path.home() / ".bigym" / "demonstrations" / "0.9.0",
    )
    parser.add_argument(
        "--validation-manifest",
        type=Path,
        required=True,
    )
    args = parser.parse_args()

    env = build_env("DishwasherUnloadCutleryLong", with_cameras=False)
    policy = PrivilegedExpertPolicy(
        "DishwasherUnloadCutleryLong",
        args.demo_root,
        validation_manifest=args.validation_manifest,
    )
    policy.bind_env(env)
    if args.force_reference:
        policy.references = [
            reference
            for reference in policy.references
            if reference.uuid == args.force_reference
        ]
        if not policy.references:
            raise ValueError(f"Unknown reference UUID: {args.force_reference}")
    results = []
    try:
        for seed in range(args.seed_start, args.seed_start + args.episodes):
            env.reset(seed=seed)
            randomization = apply_enhanced_randomization(env, seed)
            if args.door is not None or args.bottom_tray is not None:
                state = np.asarray(env.dishwasher.get_state(), dtype=np.float64)
                env.dishwasher.set_state(
                    door=float(args.door if args.door is not None else state[0]),
                    bottom_tray=float(
                        args.bottom_tray if args.bottom_tray is not None else state[1]
                    ),
                    middle_tray=float(state[2]),
                )
            policy.start(env, env.action_space)
            reward = 0.0
            terminated = False
            truncated = False
            left_gripper = next(iter(env.robot.grippers.values()))
            min_pinch_distance = float("inf")
            held_streak = 0
            max_held_streak = 0
            hold_events = []
            was_held = False
            phase_events = []
            previous_phase = policy.phase
            min_bottom_tray = float("inf")
            for step in range(1, args.max_steps + 1):
                action = policy.next_action(env)
                if action is None:
                    break
                _, reward, terminated, truncated, _ = env.step(action)
                fork_position = np.asarray(
                    env.cutlery[0].body.get_position(), dtype=np.float64
                )
                pinch_position = np.asarray(
                    left_gripper.pinch_position, dtype=np.float64
                )
                min_pinch_distance = min(
                    min_pinch_distance,
                    float(np.linalg.norm(fork_position - pinch_position)),
                )
                held = bool(
                    env.robot.is_gripper_holding_object(
                        env.cutlery[0], next(iter(env.robot.grippers))
                    )
                )
                held_streak = held_streak + 1 if held else 0
                max_held_streak = max(max_held_streak, held_streak)
                if held != was_held:
                    hold_events.append(
                        {
                            "step": step,
                            "held": held,
                            "phase": policy.phase,
                            "reference_index": policy.index,
                            "fork_position": fork_position.round(4).tolist(),
                            "pinch_position": pinch_position.round(4).tolist(),
                        }
                    )
                    was_held = held
                bottom_tray = float(env.dishwasher.get_state()[1])
                min_bottom_tray = min(min_bottom_tray, bottom_tray)
                if policy.phase != previous_phase:
                    phase_events.append(
                        {
                            "step": step,
                            "phase": policy.phase,
                            "reference_index": policy.index,
                            "bottom_tray": round(bottom_tray, 4),
                        }
                    )
                    previous_phase = policy.phase
                if reward > 0 or terminated or truncated:
                    break
            status = dishwasher_unload_cutlery_status(env)
            result = {
                "seed": seed,
                "success": bool(status["success"]),
                "steps": step,
                "phase": policy.phase,
                "failure_reason": policy.failure_reason,
                "retry_count": policy.retry_count,
                "reference_uuid": policy.demo_uuid,
                "reference_seed": policy.reference_seed,
                "reference_index": policy.index,
                "pose_score": policy.pose_score,
                "randomization": randomization.to_dict(),
                "status": status,
                "terminated": bool(terminated),
                "truncated": bool(truncated),
                "grasp_diagnostics": {
                    "min_pinch_distance": round(min_pinch_distance, 6),
                    "max_held_streak": max_held_streak,
                    "hold_events": hold_events,
                    "phase_events": phase_events,
                    "min_bottom_tray": round(min_bottom_tray, 6),
                },
            }
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        env.close()

    summary = {
        "episodes": len(results),
        "successes": sum(result["success"] for result in results),
        "success_rate": (
            sum(result["success"] for result in results) / len(results)
            if results
            else 0.0
        ),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    public_summary = {
        key: summary[key] for key in ("episodes", "successes", "success_rate")
    }
    print(json.dumps(public_summary))


if __name__ == "__main__":
    main()
