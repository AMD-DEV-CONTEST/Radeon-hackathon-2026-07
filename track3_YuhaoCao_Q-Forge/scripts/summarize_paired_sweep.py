#!/usr/bin/env python3
"""Audit and summarize paired base/guided LIBERO sweep outputs."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np


def parse_states(value: str) -> list[int]:
    states: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if "-" in item:
            start, stop = (int(part) for part in item.split("-", 1))
            states.update(range(start, stop + 1))
        else:
            states.add(int(item))
    if not states:
        raise ValueError("expected-states must not be empty")
    return sorted(states)


def exact_mcnemar_pvalue(fail_to_success: int, success_to_fail: int) -> float:
    discordant = fail_to_success + success_to_fail
    if discordant == 0:
        return 1.0
    tail = min(fail_to_success, success_to_fail)
    one_sided = sum(math.comb(discordant, index) for index in range(tail + 1)) / (
        2**discordant
    )
    return min(1.0, 2.0 * one_sided)


def load_records(root: Path, seed: int) -> dict[int, dict]:
    records = {}
    for path in sorted((root / f"seed_{seed}").glob("reset_*/closed_loop_metrics.json")):
        record = json.loads(path.read_text())
        state = int(record["task_reset_state_id"])
        if state in records:
            raise ValueError(f"duplicate state {state} under {root}")
        records[state] = record
    return records


def bootstrap_interval(
    differences: np.ndarray, *, samples: int, seed: int, chunk_size: int = 10_000
) -> list[float]:
    rng = np.random.default_rng(seed)
    estimates = np.empty(samples, dtype=np.float32)
    for start in range(0, samples, chunk_size):
        count = min(chunk_size, samples - start)
        indices = rng.integers(0, len(differences), size=(count, len(differences)))
        estimates[start : start + count] = differences[indices].mean(axis=1)
    return [float(value) for value in np.percentile(estimates, [2.5, 97.5])]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--guided-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--expected-states", default="0-49")
    parser.add_argument("--bootstrap-samples", type=int, default=500_000)
    parser.add_argument("--bootstrap-seed", type=int, default=1000)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    states = parse_states(args.expected_states)
    base = load_records(args.base_dir, args.seed)
    guided = load_records(args.guided_dir, args.seed)
    if sorted(base) != states or sorted(guided) != states:
        raise ValueError(
            f"state coverage mismatch: expected={states}, base={sorted(base)}, guided={sorted(guided)}"
        )

    matrix = []
    for state in states:
        left, right = base[state], guided[state]
        invariants = {
            "seed": left["seed"] == right["seed"] == args.seed,
            "task": left["task_id"] == right["task_id"] == 7,
            "state": left["task_reset_state_id"] == right["task_reset_state_id"] == state,
            "model": left["model_path"] == right["model_path"],
            "horizon": left["action_steps_per_replan"]
            == right["action_steps_per_replan"]
            == 5,
            "finite": bool(left["action_finite"] and right["action_finite"]),
            "guidance_flags": not left["guidance_enabled"] and right["guidance_enabled"],
        }
        if not all(invariants.values()):
            raise ValueError(f"paired invariant failed for state {state}: {invariants}")
        matrix.append(
            {
                "state": state,
                "base_success": bool(left["success"]),
                "guided_success": bool(right["success"]),
                "base_steps": int(left["steps"]),
                "guided_steps": int(right["steps"]),
                "guidance_q_improvement_mean": right["guidance_q_improvement_mean"],
                "guidance_delta_abs_mean": right["guidance_delta_abs_mean"],
            }
        )

    base_success = np.asarray([row["base_success"] for row in matrix], dtype=np.int8)
    guided_success = np.asarray([row["guided_success"] for row in matrix], dtype=np.int8)
    differences = guided_success - base_success
    fail_to_success = [row["state"] for row in matrix if not row["base_success"] and row["guided_success"]]
    success_to_fail = [row["state"] for row in matrix if row["base_success"] and not row["guided_success"]]
    joint_success = [row for row in matrix if row["base_success"] and row["guided_success"]]
    joint_failure = [row["state"] for row in matrix if not row["base_success"] and not row["guided_success"]]
    q_improvements = np.asarray(
        [row["guidance_q_improvement_mean"] for row in matrix], dtype=np.float64
    )
    action_deltas = np.asarray(
        [row["guidance_delta_abs_mean"] for row in matrix], dtype=np.float64
    )
    summary = {
        "protocol": {
            "task_id": 7,
            "states": states,
            "seed": args.seed,
            "episodes_per_method": len(states),
            "action_steps_per_replan": 5,
            "paired": True,
        },
        "base": {
            "successes": int(base_success.sum()),
            "failures": int((1 - base_success).sum()),
            "success_rate": float(base_success.mean()),
            "mean_steps": float(np.mean([row["base_steps"] for row in matrix])),
        },
        "guided": {
            "successes": int(guided_success.sum()),
            "failures": int((1 - guided_success).sum()),
            "success_rate": float(guided_success.mean()),
            "mean_steps": float(np.mean([row["guided_steps"] for row in matrix])),
            "mean_predicted_q_improvement": float(q_improvements.mean()),
            "minimum_episode_predicted_q_improvement": float(q_improvements.min()),
            "mean_action_delta": float(action_deltas.mean()),
            "maximum_episode_mean_action_delta": float(action_deltas.max()),
        },
        "paired": {
            "success_rate_difference": float(differences.mean()),
            "fail_to_success_states": fail_to_success,
            "success_to_fail_states": success_to_fail,
            "joint_success_states": [row["state"] for row in joint_success],
            "joint_failure_states": joint_failure,
            "exact_mcnemar_two_sided_p": exact_mcnemar_pvalue(
                len(fail_to_success), len(success_to_fail)
            ),
            "bootstrap_samples": args.bootstrap_samples,
            "bootstrap_seed": args.bootstrap_seed,
            "success_rate_difference_95_percentile_ci": bootstrap_interval(
                differences,
                samples=args.bootstrap_samples,
                seed=args.bootstrap_seed,
            ),
            "joint_success_mean_steps": {
                "base": float(np.mean([row["base_steps"] for row in joint_success])),
                "guided": float(np.mean([row["guided_steps"] for row in joint_success])),
            },
        },
        "all_actions_finite": all(
            base[state]["action_finite"] and guided[state]["action_finite"] for state in states
        ),
        "matrix": matrix,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(summary, indent=2) + "\n")

    paired = summary["paired"]
    lines = [
        "# Task 7 paired H=5 Q-guidance evaluation",
        "",
        f"- Protocol: 50 reset states, one base and one guided rollout per state, seed {args.seed}.",
        f"- Base: {summary['base']['successes']}/50 ({summary['base']['success_rate']:.1%}).",
        f"- Guided: {summary['guided']['successes']}/50 ({summary['guided']['success_rate']:.1%}).",
        f"- Paired difference: {paired['success_rate_difference']:+.1%}; 95% paired bootstrap CI "
        f"[{paired['success_rate_difference_95_percentile_ci'][0]:+.1%}, "
        f"{paired['success_rate_difference_95_percentile_ci'][1]:+.1%}].",
        f"- Fail→success: {fail_to_success}; success→fail: {success_to_fail}.",
        f"- Exact two-sided McNemar p={paired['exact_mcnemar_two_sided_p']:.6g}.",
        f"- Mean predicted ΔQ={summary['guided']['mean_predicted_q_improvement']:.6g}; "
        f"mean |ΔA|={summary['guided']['mean_action_delta']:.6g}.",
        "",
        "| State | Base | Guided | Base steps | Guided steps | Predicted ΔQ | Mean |ΔA| |",
        "|---:|:---:|:---:|---:|---:|---:|---:|",
    ]
    for row in matrix:
        lines.append(
            f"| {row['state']} | {'✓' if row['base_success'] else '✗'} | "
            f"{'✓' if row['guided_success'] else '✗'} | {row['base_steps']} | "
            f"{row['guided_steps']} | {row['guidance_q_improvement_mean']:.6f} | "
            f"{row['guidance_delta_abs_mean']:.6f} |"
        )
    args.output_md.write_text("\n".join(lines) + "\n")
    print(json.dumps(summary | {"matrix": f"{len(matrix)} rows"}, indent=2))


if __name__ == "__main__":
    main()
