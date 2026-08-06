"""Physics-only verification for a formal replay plan.

This gate runs before video/3DGS rendering.  It rechecks every selected UUID on
the current 20 Hz runtime.  Delta demonstrations are additionally replayed in
an absolute-action environment using the exact labels that will be written to
LeRobot, proving that a mixed source pool still has one action-label contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from env_utils import build_env
from generate_dataset import _absolute_dataset_action, _actions_sha256
from replay_plan import load_replay_plan, plan_entries


def _qpos(env) -> np.ndarray:
    return np.asarray(env.action_mode._mojo.data.qpos, dtype=np.float64).copy()


def verify_plan(plan_path: str | Path) -> dict:
    from demonstrations.demo_store import DemoStore
    from demonstrations.utils import Metadata

    plan_path = Path(plan_path)
    plan = load_replay_plan(plan_path)
    receipt = {
        "schema_version": 1,
        "status": "running",
        "replay_plan": str(plan_path.resolve()),
        "replay_plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "runtime": "current",
        "control_frequency_hz": 20,
        "dataset_action_representation": "absolute",
        "episodes": [],
    }

    started = time.perf_counter()
    try:
        failed_replays = []
        for task in plan["tasks"]:
            entries = plan_entries(plan, task)
            for representation in ("absolute", "delta"):
                selected = [
                    entry
                    for entry in entries
                    if entry["source_action_representation"] == representation
                ]
                if not selected:
                    continue
                source_env = build_env(
                    task,
                    action_absolute=representation == "absolute",
                    with_cameras=False,
                )
                canonical_env = (
                    build_env(task, action_absolute=True, with_cameras=False)
                    if representation == "delta"
                    else None
                )
                try:
                    metadata = Metadata.from_env(source_env, is_lightweight=True)
                    demos = DemoStore().get_demos(
                        metadata,
                        amount=-1,
                        frequency=20,
                    )
                    demos_by_uuid = {str(demo.uuid): demo for demo in demos}
                    for entry in selected:
                        demo_uuid = entry["demo_uuid"]
                        if demo_uuid not in demos_by_uuid:
                            raise RuntimeError(f"missing planned demo: {task}/{demo_uuid}")
                        demo = demos_by_uuid[demo_uuid]
                        source_env.reset(seed=demo.seed)
                        if canonical_env is not None:
                            canonical_env.reset(seed=demo.seed)
                        source_actions = np.asarray(
                            [step.executed_action for step in demo.timesteps[:-1]],
                            dtype=np.float32,
                        )
                        dataset_actions = []
                        max_qpos_error = 0.0
                        for source_action in source_actions:
                            dataset_action = _absolute_dataset_action(
                                source_env,
                                source_action,
                            )
                            dataset_actions.append(dataset_action)
                            source_env.step(source_action, fast=True)
                            if canonical_env is not None:
                                canonical_env.step(dataset_action, fast=True)
                                max_qpos_error = max(
                                    max_qpos_error,
                                    float(
                                        np.max(
                                            np.abs(
                                                _qpos(source_env)
                                                - _qpos(canonical_env)
                                            )
                                        )
                                    ),
                                )
                        source_reward = float(source_env.reward)
                        canonical_reward = (
                            float(canonical_env.reward)
                            if canonical_env is not None
                            else source_reward
                        )
                        passed = source_reward > 0 and canonical_reward > 0
                        row = {
                            **entry,
                            "task": task,
                            "seed": int(demo.seed),
                            "frames": int(len(source_actions)),
                            "source_reward": source_reward,
                            "canonical_absolute_reward": canonical_reward,
                            "max_qpos_error": max_qpos_error,
                            "source_actions_sha256": _actions_sha256(source_actions),
                            "dataset_actions_sha256": _actions_sha256(dataset_actions),
                            "passed": passed,
                        }
                        receipt["episodes"].append(row)
                        print(
                            f"{task} {demo_uuid} source={representation} "
                            f"reward={source_reward:g}/{canonical_reward:g} "
                            f"qpos_error={max_qpos_error:.3g}"
                        )
                        if not passed:
                            failed_replays.append(f"{task}/{demo_uuid}")
                finally:
                    source_env.close()
                    if canonical_env is not None:
                        canonical_env.close()
    except Exception as exc:
        receipt["status"] = "failed"
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    else:
        if failed_replays:
            receipt["status"] = "failed"
            receipt["error"] = (
                f"{len(failed_replays)} planned replay(s) failed canonical "
                "absolute verification"
            )
            receipt["failed_replays"] = failed_replays
        else:
            receipt["status"] = "passed"
    finally:
        receipt["elapsed_seconds"] = time.perf_counter() - started
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--replay-plan", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    output = Path(args.output)
    receipt = verify_plan(args.replay_plan)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    print(f"status={receipt['status']} output={output}")
    return 0 if receipt["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
