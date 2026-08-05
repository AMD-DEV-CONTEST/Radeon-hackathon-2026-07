#!/usr/bin/env python3
"""Audit paired SFT versus test-time Q-selection rollouts."""

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
    parser.add_argument("--selection-dir", type=Path, required=True)
    parser.add_argument("--candidate-count", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--expected-states", default="0-49")
    parser.add_argument("--bootstrap-samples", type=int, default=500_000)
    parser.add_argument("--bootstrap-seed", type=int, default=1000)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    states = parse_states(args.expected_states)
    base = load_records(args.base_dir, args.seed)
    selected = load_records(args.selection_dir, args.seed)
    if sorted(base) != states or sorted(selected) != states:
        raise ValueError("base/selection state coverage does not match the protocol")

    matrix = []
    for state in states:
        left, right = base[state], selected[state]
        invariants = {
            "seed": left["seed"] == right["seed"] == args.seed,
            "task": left["task_id"] == right["task_id"] == 7,
            "state": left["task_reset_state_id"] == right["task_reset_state_id"] == state,
            "model": left["model_path"] == right["model_path"],
            "horizon": left["action_steps_per_replan"]
            == right["action_steps_per_replan"]
            == 5,
            "finite": bool(left["action_finite"] and right["action_finite"]),
            "base_has_no_critic": not left["guidance_enabled"]
            and not left.get("q_selection_enabled", False),
            "selection_mode": not right["guidance_enabled"]
            and right.get("q_selection_enabled", False)
            and right.get("critic_mode") == "selection",
            "candidate_count": right["selection"]["candidate_count"]
            == args.candidate_count,
            "no_action_gradient": right["selection"]["action_gradient"] is False,
        }
        if not all(invariants.values()):
            raise ValueError(f"paired invariant failed for state {state}: {invariants}")
        matrix.append(
            {
                "state": state,
                "base_success": bool(left["success"]),
                "selection_success": bool(right["success"]),
                "base_steps": int(left["steps"]),
                "selection_steps": int(right["steps"]),
                "predicted_q_improvement": right[
                    "selection_q_improvement_over_first_mean"
                ],
                "candidate_q_std": right["selection_candidate_q_std_mean"],
                "selected_disagreement": right[
                    "selection_selected_disagreement_mean"
                ],
            }
        )

    base_success = np.asarray([row["base_success"] for row in matrix], dtype=np.int8)
    selection_success = np.asarray(
        [row["selection_success"] for row in matrix], dtype=np.int8
    )
    differences = selection_success - base_success
    fail_to_success = [
        row["state"]
        for row in matrix
        if not row["base_success"] and row["selection_success"]
    ]
    success_to_fail = [
        row["state"]
        for row in matrix
        if row["base_success"] and not row["selection_success"]
    ]
    interval = bootstrap_interval(
        differences, samples=args.bootstrap_samples, seed=args.bootstrap_seed
    )
    summary = {
        "protocol": {
            "task_id": 7,
            "states": states,
            "seed": args.seed,
            "candidate_count": args.candidate_count,
            "action_steps_per_replan": 5,
            "aggregation": "five_head_ensemble_mean",
            "action_gradient": False,
            "paired": True,
        },
        "base": {
            "successes": int(base_success.sum()),
            "success_rate": float(base_success.mean()),
        },
        "q_selection": {
            "successes": int(selection_success.sum()),
            "success_rate": float(selection_success.mean()),
            "episode_mean_predicted_q_improvement": float(
                np.mean([row["predicted_q_improvement"] for row in matrix])
            ),
            "episode_mean_candidate_q_std": float(
                np.mean([row["candidate_q_std"] for row in matrix])
            ),
            "episode_mean_selected_disagreement": float(
                np.mean([row["selected_disagreement"] for row in matrix])
            ),
        },
        "paired": {
            "success_rate_difference": float(differences.mean()),
            "success_rate_difference_95_percentile_ci": interval,
            "fail_to_success_states": fail_to_success,
            "success_to_fail_states": success_to_fail,
            "exact_mcnemar_two_sided_p": exact_mcnemar_pvalue(
                len(fail_to_success), len(success_to_fail)
            ),
        },
        "all_actions_finite": True,
        "matrix": matrix,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(summary, indent=2) + "\n")
    lines = [
        f"# Task 7 test-time Q selection (N={args.candidate_count})",
        "",
        f"- Base: {base_success.sum()}/50 ({base_success.mean():.1%}).",
        f"- Q selection: {selection_success.sum()}/50 ({selection_success.mean():.1%}).",
        f"- Paired difference: {differences.mean():+.1%}; 95% bootstrap CI "
        f"[{interval[0]:+.1%}, {interval[1]:+.1%}].",
        f"- Fail→success: {fail_to_success}; success→fail: {success_to_fail}.",
        f"- Exact two-sided McNemar p={summary['paired']['exact_mcnemar_two_sided_p']:.6g}.",
        f"- Mean predicted Q gain over candidate 0: "
        f"{summary['q_selection']['episode_mean_predicted_q_improvement']:.6g}.",
        "",
        "| State | Base | Selection | Base steps | Selection steps | Predicted ΔQ |",
        "|---:|:---:|:---:|---:|---:|---:|",
    ]
    for row in matrix:
        lines.append(
            f"| {row['state']} | {'✓' if row['base_success'] else '✗'} | "
            f"{'✓' if row['selection_success'] else '✗'} | {row['base_steps']} | "
            f"{row['selection_steps']} | {row['predicted_q_improvement']:.6f} |"
        )
    args.output_md.write_text("\n".join(lines) + "\n")
    print(json.dumps(summary | {"matrix": f"{len(matrix)} rows"}, indent=2))


if __name__ == "__main__":
    main()
