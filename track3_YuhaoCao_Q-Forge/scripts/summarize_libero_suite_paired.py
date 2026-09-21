#!/usr/bin/env python3
"""Audit and summarize paired LIBERO suite rollouts across multiple tasks."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from summarize_paired_sweep import (
    bootstrap_interval,
    exact_mcnemar_pvalue,
    load_records,
    parse_states,
)


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> list[float]:
    if total <= 0:
        raise ValueError("Wilson interval requires at least one observation")
    rate = successes / total
    denominator = 1.0 + z * z / total
    center = (rate + z * z / (2.0 * total)) / denominator
    radius = (
        z
        * math.sqrt(rate * (1.0 - rate) / total + z * z / (4.0 * total * total))
        / denominator
    )
    return [center - radius, center + radius]


def load_records_from_roots(
    roots: list[Path], *, task: int, seed: int
) -> dict[int, dict]:
    """Merge disjoint state subsets for one task without hiding duplicates."""
    merged: dict[int, dict] = {}
    sources: dict[int, Path] = {}
    for root in roots:
        task_root = root / f"task_{task}"
        for state, record in load_records(task_root, seed).items():
            if state in merged:
                raise ValueError(
                    f"duplicate task={task}, state={state} across {sources[state]} "
                    f"and {task_root}"
                )
            merged[state] = record
            sources[state] = task_root
    return merged


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-dir",
        type=Path,
        action="append",
        required=True,
        help="Root containing task_N directories; repeat for disjoint state subsets.",
    )
    parser.add_argument(
        "--candidate-dir",
        type=Path,
        action="append",
        required=True,
        help="Root containing task_N directories; repeat for disjoint state subsets.",
    )
    parser.add_argument("--method", choices=("qvgm", "guidance", "selection"), required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--expected-tasks", default="0-9")
    parser.add_argument("--expected-states", default="0-4")
    parser.add_argument("--bootstrap-samples", type=int, default=500_000)
    parser.add_argument("--bootstrap-seed", type=int, default=1000)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()

    tasks = parse_states(args.expected_tasks)
    states = parse_states(args.expected_states)
    matrix: list[dict[str, object]] = []
    model_paths: set[str] = set()
    candidate_paths: set[str] = set()

    for task in tasks:
        base = load_records_from_roots(args.base_dir, task=task, seed=args.seed)
        candidate = load_records_from_roots(
            args.candidate_dir, task=task, seed=args.seed
        )
        missing_base = sorted(set(states) - set(base))
        missing_candidate = sorted(set(states) - set(candidate))
        if missing_base or missing_candidate:
            raise ValueError(
                f"task {task} is missing paired states: "
                f"base={missing_base}, candidate={missing_candidate}"
            )
        for state in states:
            left, right = base[state], candidate[state]
            base_plain = not left.get("guidance_enabled", False) and not left.get(
                "q_selection_enabled", False
            )
            if args.method == "qvgm":
                method_ok = (
                    not right.get("guidance_enabled", False)
                    and not right.get("q_selection_enabled", False)
                    and right.get("critic_checkpoint") is None
                    and right["model_path"] != left["model_path"]
                )
            elif args.method == "guidance":
                method_ok = (
                    right.get("critic_mode") == "guidance"
                    and right.get("guidance_enabled", False)
                    and not right.get("q_selection_enabled", False)
                    and right["model_path"] == left["model_path"]
                )
            else:
                method_ok = (
                    right.get("critic_mode") == "selection"
                    and not right.get("guidance_enabled", False)
                    and right.get("q_selection_enabled", False)
                    and right["model_path"] == left["model_path"]
                )
            invariants = {
                "seed": left["seed"] == right["seed"] == args.seed,
                "task": left["task_id"] == right["task_id"] == task,
                "state": left["task_reset_state_id"]
                == right["task_reset_state_id"]
                == state,
                "horizon": left["action_steps_per_replan"]
                == right["action_steps_per_replan"]
                == 5,
                "finite": bool(left["action_finite"] and right["action_finite"]),
                "base_plain": base_plain,
                "method": method_ok,
            }
            if not all(invariants.values()):
                raise ValueError(
                    f"paired invariant failed for task={task}, state={state}: {invariants}"
                )
            model_paths.add(str(left["model_path"]))
            candidate_paths.add(str(right["model_path"]))
            matrix.append(
                {
                    "task": task,
                    "state": state,
                    "base_success": bool(left["success"]),
                    "candidate_success": bool(right["success"]),
                    "base_steps": int(left["steps"]),
                    "candidate_steps": int(right["steps"]),
                }
            )

    base_success = np.asarray([row["base_success"] for row in matrix], dtype=np.int8)
    candidate_success = np.asarray(
        [row["candidate_success"] for row in matrix], dtype=np.int8
    )
    differences = candidate_success - base_success
    fail_to_success = [
        [row["task"], row["state"]]
        for row in matrix
        if not row["base_success"] and row["candidate_success"]
    ]
    success_to_fail = [
        [row["task"], row["state"]]
        for row in matrix
        if row["base_success"] and not row["candidate_success"]
    ]
    interval = bootstrap_interval(
        differences, samples=args.bootstrap_samples, seed=args.bootstrap_seed
    )
    per_task = []
    for task in tasks:
        rows = [row for row in matrix if row["task"] == task]
        base_count = sum(bool(row["base_success"]) for row in rows)
        candidate_count = sum(bool(row["candidate_success"]) for row in rows)
        per_task.append(
            {
                "task": task,
                "episodes": len(rows),
                "base_successes": base_count,
                "candidate_successes": candidate_count,
                "difference": (candidate_count - base_count) / len(rows),
            }
        )

    total = len(matrix)
    base_count = int(base_success.sum())
    candidate_count = int(candidate_success.sum())
    summary = {
        "protocol": {
            "tasks": tasks,
            "states_per_task": states,
            "seed": args.seed,
            "episodes_per_method": total,
            "action_steps_per_replan": 5,
            "paired": True,
            "method": args.method,
        },
        "base": {
            "model_paths": sorted(model_paths),
            "successes": base_count,
            "success_rate": base_count / total,
            "success_rate_95_wilson_ci": wilson_interval(base_count, total),
        },
        args.method: {
            "model_paths": sorted(candidate_paths),
            "successes": candidate_count,
            "success_rate": candidate_count / total,
            "success_rate_95_wilson_ci": wilson_interval(candidate_count, total),
        },
        "paired": {
            "success_rate_difference": float(differences.mean()),
            "success_rate_difference_95_percentile_ci": interval,
            "fail_to_success": fail_to_success,
            "success_to_fail": success_to_fail,
            "exact_mcnemar_two_sided_p": exact_mcnemar_pvalue(
                len(fail_to_success), len(success_to_fail)
            ),
        },
        "per_task": per_task,
        "all_actions_finite": True,
        "matrix": matrix,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(summary, indent=2) + "\n")

    method_label = {"qvgm": "Q-VGM", "guidance": "Q-guidance", "selection": "Q-selection"}[
        args.method
    ]
    base_ci = summary["base"]["success_rate_95_wilson_ci"]
    candidate_ci = summary[args.method]["success_rate_95_wilson_ci"]
    lines = [
        f"# LIBERO suite paired SFT versus {method_label}",
        "",
        f"- Protocol: {len(tasks)} tasks × {len(states)} reset states, seed {args.seed}, "
        "5 actions/replan.",
        f"- SFT: {base_count}/{total} ({base_count / total:.1%}), Wilson 95% CI "
        f"[{base_ci[0]:.1%}, {base_ci[1]:.1%}].",
        f"- {method_label}: {candidate_count}/{total} ({candidate_count / total:.1%}), "
        f"Wilson 95% CI [{candidate_ci[0]:.1%}, {candidate_ci[1]:.1%}].",
        f"- Paired difference: {differences.mean():+.1%}; bootstrap 95% CI "
        f"[{interval[0]:+.1%}, {interval[1]:+.1%}].",
        f"- Failure→success: {len(fail_to_success)}; success→failure: "
        f"{len(success_to_fail)}; exact two-sided McNemar p="
        f"{summary['paired']['exact_mcnemar_two_sided_p']:.6g}.",
        "- All recorded actions are finite.",
        "",
        f"| Task | Episodes | SFT | {method_label} | Difference |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in per_task:
        lines.append(
            f"| {row['task']} | {row['episodes']} | {row['base_successes']} | "
            f"{row['candidate_successes']} | {row['difference']:+.1%} |"
        )
    args.output_md.write_text("\n".join(lines) + "\n")
    print(json.dumps(summary | {"matrix": f"{len(matrix)} rows"}, indent=2))


if __name__ == "__main__":
    main()
