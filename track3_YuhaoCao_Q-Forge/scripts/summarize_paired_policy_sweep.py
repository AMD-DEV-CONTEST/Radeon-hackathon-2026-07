#!/usr/bin/env python3
"""Summarize paired base versus critic-free Q-VGM policy rollouts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from summarize_paired_sweep import (
    bootstrap_interval,
    exact_mcnemar_pvalue,
    load_records,
    parse_states,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--qvgm-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--expected-states", default="0-49")
    parser.add_argument("--bootstrap-samples", type=int, default=500_000)
    parser.add_argument("--bootstrap-seed", type=int, default=1000)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    states = parse_states(args.expected_states)
    base = load_records(args.base_dir, args.seed)
    qvgm = load_records(args.qvgm_dir, args.seed)
    if sorted(base) != states or sorted(qvgm) != states:
        raise ValueError(
            f"state coverage mismatch: expected={states}, base={sorted(base)}, qvgm={sorted(qvgm)}"
        )

    matrix = []
    for state in states:
        left, right = base[state], qvgm[state]
        invariants = {
            "seed": left["seed"] == right["seed"] == args.seed,
            "task": left["task_id"] == right["task_id"] == 7,
            "state": left["task_reset_state_id"] == right["task_reset_state_id"] == state,
            "horizon": left["action_steps_per_replan"]
            == right["action_steps_per_replan"]
            == 5,
            "finite": bool(left["action_finite"] and right["action_finite"]),
            "critic_free": not left["guidance_enabled"] and not right["guidance_enabled"],
            "distinct_policy": left["model_path"] != right["model_path"],
        }
        if not all(invariants.values()):
            raise ValueError(f"paired invariant failed for state {state}: {invariants}")
        matrix.append(
            {
                "state": state,
                "base_success": bool(left["success"]),
                "qvgm_success": bool(right["success"]),
                "base_steps": int(left["steps"]),
                "qvgm_steps": int(right["steps"]),
            }
        )

    base_success = np.asarray([row["base_success"] for row in matrix], dtype=np.int8)
    qvgm_success = np.asarray([row["qvgm_success"] for row in matrix], dtype=np.int8)
    differences = qvgm_success - base_success
    fail_to_success = [row["state"] for row in matrix if not row["base_success"] and row["qvgm_success"]]
    success_to_fail = [row["state"] for row in matrix if row["base_success"] and not row["qvgm_success"]]
    joint_success = [row for row in matrix if row["base_success"] and row["qvgm_success"]]
    interval = bootstrap_interval(
        differences, samples=args.bootstrap_samples, seed=args.bootstrap_seed
    )
    summary = {
        "protocol": {
            "task_id": 7,
            "states": states,
            "seed": args.seed,
            "episodes_per_policy": len(states),
            "action_steps_per_replan": 5,
            "paired": True,
            "qvgm_critic_required_at_inference": False,
        },
        "base": {
            "model_path": base[states[0]]["model_path"],
            "successes": int(base_success.sum()),
            "success_rate": float(base_success.mean()),
        },
        "qvgm": {
            "model_path": qvgm[states[0]]["model_path"],
            "successes": int(qvgm_success.sum()),
            "success_rate": float(qvgm_success.mean()),
        },
        "paired": {
            "success_rate_difference": float(differences.mean()),
            "success_rate_difference_95_percentile_ci": interval,
            "fail_to_success_states": fail_to_success,
            "success_to_fail_states": success_to_fail,
            "exact_mcnemar_two_sided_p": exact_mcnemar_pvalue(
                len(fail_to_success), len(success_to_fail)
            ),
            "joint_success_mean_steps": {
                "base": float(np.mean([row["base_steps"] for row in joint_success])),
                "qvgm": float(np.mean([row["qvgm_steps"] for row in joint_success])),
            },
        },
        "all_actions_finite": True,
        "matrix": matrix,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(summary, indent=2) + "\n")
    lines = [
        "# Task 7 paired base versus Q-VGM policy evaluation",
        "",
        f"- Base: {int(base_success.sum())}/{len(states)} ({base_success.mean():.1%}).",
        f"- Q-VGM: {int(qvgm_success.sum())}/{len(states)} ({qvgm_success.mean():.1%}).",
        f"- Paired difference: {differences.mean():+.1%}; 95% bootstrap CI "
        f"[{interval[0]:+.1%}, {interval[1]:+.1%}].",
        f"- Fail→success: {fail_to_success}; success→fail: {success_to_fail}.",
        f"- Exact two-sided McNemar p={summary['paired']['exact_mcnemar_two_sided_p']:.6g}.",
        "- Q-VGM inference is critic-free.",
        "",
        "| State | Base | Q-VGM | Base steps | Q-VGM steps |",
        "|---:|:---:|:---:|---:|---:|",
    ]
    for row in matrix:
        lines.append(
            f"| {row['state']} | {'✓' if row['base_success'] else '✗'} | "
            f"{'✓' if row['qvgm_success'] else '✗'} | {row['base_steps']} | {row['qvgm_steps']} |"
        )
    args.output_md.write_text("\n".join(lines) + "\n")
    print(json.dumps(summary | {"matrix": f"{len(matrix)} rows"}, indent=2))


if __name__ == "__main__":
    main()
