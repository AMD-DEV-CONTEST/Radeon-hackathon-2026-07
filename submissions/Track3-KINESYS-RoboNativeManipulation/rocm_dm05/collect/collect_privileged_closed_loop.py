#!/usr/bin/env python3
"""Collect success-gated BiGym demonstrations with privileged feedback."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from demonstrations.demo import Demo
from demonstrations.demo_recorder import DemoRecorder
from env_utils import build_env

from enhanced_randomization import apply_enhanced_randomization
from privileged_policy import PrivilegedExpertPolicy, dishwasher_unload_cutlery_status


TASK = "DishwasherUnloadCutleryLong"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-root", required=True, type=Path)
    parser.add_argument("--validation-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--seed-start", type=int, default=510100)
    parser.add_argument("--episodes", type=int, default=70)
    parser.add_argument("--max-steps", type=int, default=1600)
    return parser.parse_args()


def append_record(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "manifest.jsonl"
    env = build_env(TASK, control_frequency=20, with_cameras=False)
    policy = PrivilegedExpertPolicy(
        TASK,
        args.demo_root,
        validation_manifest=args.validation_manifest,
    )
    policy.bind_env(env)
    try:
        for seed in range(args.seed_start, args.seed_start + args.episodes):
            output_path = args.output_dir / f"{TASK}_seed{seed}_privileged.safetensors"
            if output_path.is_file():
                print(f"seed={seed} status=skipped", flush=True)
                continue

            env.reset(seed=seed)
            randomization = apply_enhanced_randomization(env, seed)
            recorder = DemoRecorder(args.output_dir)
            recorder.record(env, lightweight_demo=True)
            policy.start(env, env.action_space)
            reward = 0.0
            success = False
            terminated = False
            truncated = False
            status = dishwasher_unload_cutlery_status(env)
            step = 0
            try:
                for step in range(1, args.max_steps + 1):
                    action = policy.next_action(env)
                    if action is None:
                        break
                    timestep = env.step(action)
                    recorder.add_timestep(timestep, action)
                    reward = float(timestep[1])
                    terminated = bool(timestep[2])
                    truncated = bool(timestep[3])
                    status = dishwasher_unload_cutlery_status(env)
                    success = bool(reward > 0 or status["success"])
                    if success or terminated or truncated:
                        break
            finally:
                recorder.stop()
                policy.stop()

            record = {
                "seed": seed,
                "status": "success" if success else "failed",
                "steps": step,
                "reward": reward,
                "terminated": terminated,
                "truncated": truncated,
                "randomization": randomization.to_dict(),
                "final_privileged_state": status,
                "reference_uuid": policy.demo_uuid,
                "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            if success:
                saved = recorder.save_demo(output_path.name)
                if saved is None:
                    raise RuntimeError("DemoRecorder returned no output path")
                loaded = Demo.from_safetensors(saved)
                if int(loaded.seed) != seed or not loaded.timesteps:
                    raise RuntimeError(f"Saved demo failed validation: {saved}")
                record["output"] = str(saved)
                record["saved_timesteps"] = len(loaded.timesteps)
            append_record(manifest_path, record)
            print(json.dumps(record, ensure_ascii=False), flush=True)
    finally:
        env.close()


if __name__ == "__main__":
    main()
