#!/usr/bin/env python3
"""Audit and summarize a complete multi-task LIBERO closed-loop sweep."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean

from summarize_libero_suite_paired import load_records_from_roots, wilson_interval
from summarize_paired_sweep import parse_states


def numeric_summary(values: list[float]) -> dict[str, float | int] | None:
    if not values:
        return None
    return {
        "count": len(values),
        "min": min(values),
        "mean": mean(values),
        "max": max(values),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir",
        type=Path,
        action="append",
        required=True,
        help="Root containing task_N directories; repeat for disjoint state subsets.",
    )
    parser.add_argument(
        "--method", choices=("base", "qvgm", "guidance", "selection"), required=True
    )
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--expected-tasks", default="0-9")
    parser.add_argument("--expected-states", default="0-49")
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()

    tasks = parse_states(args.expected_tasks)
    states = parse_states(args.expected_states)
    rows: list[dict[str, object]] = []
    model_paths: set[str] = set()
    critic_paths: set[str] = set()
    feature_paths: set[str] = set()
    guidance_configs: set[str] = set()
    selection_configs: set[str] = set()

    for task in tasks:
        records = load_records_from_roots(args.input_dir, task=task, seed=args.seed)
        if sorted(records) != states:
            raise ValueError(
                f"task {task} coverage mismatch: expected={states}, got={sorted(records)}"
            )
        for state in states:
            record = records[state]
            plain = not record.get("guidance_enabled", False) and not record.get(
                "q_selection_enabled", False
            )
            if args.method in ("base", "qvgm"):
                method_ok = plain and record.get("critic_checkpoint") is None
            elif args.method == "guidance":
                method_ok = (
                    record.get("critic_mode") == "guidance"
                    and record.get("guidance_enabled", False)
                    and not record.get("q_selection_enabled", False)
                    and record.get("critic_checkpoint") is not None
                )
            else:
                method_ok = (
                    record.get("critic_mode") == "selection"
                    and not record.get("guidance_enabled", False)
                    and record.get("q_selection_enabled", False)
                    and record.get("critic_checkpoint") is not None
                )
            invariants = {
                "task": record["task_id"] == task,
                "state": record["task_reset_state_id"] == state,
                "seed": record["seed"] == args.seed,
                "horizon": record["action_steps_per_replan"] == 5,
                "finite": record["action_finite"] is True,
                "method": method_ok,
            }
            if not all(invariants.values()):
                raise ValueError(
                    f"protocol invariant failed for task={task}, state={state}: {invariants}"
                )
            model_paths.add(str(record["model_path"]))
            if record.get("critic_checkpoint") is not None:
                critic_paths.add(str(record["critic_checkpoint"]))
            if record.get("feature_extractor_checkpoint") is not None:
                feature_paths.add(str(record["feature_extractor_checkpoint"]))
            if record.get("guidance") is not None:
                guidance_configs.add(json.dumps(record["guidance"], sort_keys=True))
            if record.get("selection") is not None:
                selection_configs.add(json.dumps(record["selection"], sort_keys=True))
            rows.append(record)

    if len(model_paths) != 1:
        raise ValueError(f"expected one model path, got {sorted(model_paths)}")
    if len(critic_paths) > 1 or len(feature_paths) > 1:
        raise ValueError("critic or feature extractor path changed within the sweep")
    if len(guidance_configs) > 1 or len(selection_configs) > 1:
        raise ValueError("method configuration changed within the sweep")

    total = len(rows)
    successes = sum(bool(row["success"]) for row in rows)
    per_task = []
    for task in tasks:
        task_rows = [row for row in rows if row["task_id"] == task]
        count = sum(bool(row["success"]) for row in task_rows)
        per_task.append(
            {
                "task": task,
                "successes": count,
                "episodes": len(task_rows),
                "success_rate": count / len(task_rows),
                "success_rate_95_wilson_ci": wilson_interval(count, len(task_rows)),
            }
        )
    diagnostics = {
        "elapsed_seconds": numeric_summary(
            [float(row["elapsed_seconds"]) for row in rows]
        ),
        "guidance_q_improvement_mean": numeric_summary(
            [
                float(row["guidance_q_improvement_mean"])
                for row in rows
                if row.get("guidance_q_improvement_mean") is not None
            ]
        ),
        "guidance_delta_abs_mean": numeric_summary(
            [
                float(row["guidance_delta_abs_mean"])
                for row in rows
                if row.get("guidance_delta_abs_mean") is not None
            ]
        ),
        "selection_q_improvement_over_first_mean": numeric_summary(
            [
                float(row["selection_q_improvement_over_first_mean"])
                for row in rows
                if row.get("selection_q_improvement_over_first_mean") is not None
            ]
        ),
        "selection_candidate_q_std_mean": numeric_summary(
            [
                float(row["selection_candidate_q_std_mean"])
                for row in rows
                if row.get("selection_candidate_q_std_mean") is not None
            ]
        ),
    }
    summary = {
        "protocol": {
            "tasks": tasks,
            "states_per_task": states,
            "seed": args.seed,
            "episodes": total,
            "method": args.method,
            "action_steps_per_replan": 5,
        },
        "artifacts": {
            "model_path": next(iter(model_paths)),
            "critic_checkpoint": next(iter(critic_paths)) if critic_paths else None,
            "feature_extractor_checkpoint": next(iter(feature_paths))
            if feature_paths
            else None,
        },
        "method_config": {
            "guidance": json.loads(next(iter(guidance_configs)))
            if guidance_configs
            else None,
            "selection": json.loads(next(iter(selection_configs)))
            if selection_configs
            else None,
        },
        "successes": successes,
        "success_rate": successes / total,
        "success_rate_95_wilson_ci": wilson_interval(successes, total),
        "per_task": per_task,
        "diagnostics": diagnostics,
        "all_actions_finite": True,
        "unique_task_state_seed_keys": total,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(summary, indent=2) + "\n")

    ci = summary["success_rate_95_wilson_ci"]
    lines = [
        f"# LIBERO suite {args.method} closed-loop results",
        "",
        f"- Protocol: {len(tasks)} tasks × {len(states)} reset states, seed {args.seed}, "
        "5 actions/replan.",
        f"- Success: {successes}/{total} ({successes / total:.1%}), Wilson 95% CI "
        f"[{ci[0]:.1%}, {ci[1]:.1%}].",
        "- Complete coverage, unique `(task, state, seed)` keys, and all actions finite.",
        "",
        "| Task | Success | Rate | Wilson 95% CI |",
        "|---:|---:|---:|---:|",
    ]
    for row in per_task:
        task_ci = row["success_rate_95_wilson_ci"]
        lines.append(
            f"| {row['task']} | {row['successes']}/{row['episodes']} | "
            f"{row['success_rate']:.1%} | [{task_ci[0]:.1%}, {task_ci[1]:.1%}] |"
        )
    args.output_md.write_text("\n".join(lines) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
