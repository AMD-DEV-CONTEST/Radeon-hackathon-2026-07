#!/usr/bin/env python3
"""Run and summarize the Track 2 context/controller/action/verifier ablations.

The runner deliberately executes variants serially.  This keeps each
variant's model, task order, and budget comparable and avoids sharing a
mutable execution environment between ablations.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from mini_swe_runner import MiniSWERunner
from swe_experiments.api import redact_base_url
from swe_experiments.config import ExperimentConfig


def _load_tasks(path: Path, limit: int | None) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                item = line
            if isinstance(item, dict):
                prompt = item.get("prompt", item.get("task", ""))
                record = dict(item)
            else:
                prompt = str(item)
                record = {}
            if prompt:
                record["prompt"] = prompt
                tasks.append(record)
            if limit is not None and len(tasks) >= limit:
                break
    return tasks


def _summarize(
    results: list[dict[str, Any]],
    official: dict[str, bool] | None = None,
) -> dict[str, Any]:
    total = len(results)
    completed = sum(bool(item.get("completed")) for item in results)
    calls = [int(item.get("api_calls", 0)) for item in results]
    metadata = [item.get("metadata", {}) for item in results]
    reports = [item.get("metadata", {}).get("verifier") for item in results]
    evaluated_reports = [report for report in reports if report]
    verifier_accepts = sum(bool(report.get("passed")) for report in evaluated_reports)
    llm_reviews = [report.get("llm_review") for report in reports if report and report.get("llm_review")]
    llm_rejects = sum(bool(review and review.get("verdict") == "reject") for review in llm_reviews)
    api_records = [item.get("metadata", {}).get("api", {}) for item in results]
    usage = {
        key: sum(int(record.get("usage", {}).get(key, 0)) for record in api_records)
        for key in ("input_tokens", "output_tokens", "total_tokens")
    }
    costs = [record.get("estimated_cost_usd") for record in api_records]
    known_costs = [float(value) for value in costs if value is not None]
    wall_times = [float(item.get("metadata", {}).get("wall_time_ms", 0)) for item in results]
    patch_results = [
        value
        for item in results
        for value in item.get("metadata", {}).get("patch_apply_results", [])
    ]
    check_results = [
        check
        for report in evaluated_reports
        for check in report.get("checks", [])
    ]
    targeted_checks = [check for check in check_results if check.get("name") == "targeted_tests"]
    json_valid = sum(int(item.get("metadata", {}).get("json_valid_responses", 0)) for item in results)
    json_responses = sum(int(item.get("metadata", {}).get("json_responses", 0)) for item in results)
    false_accept = false_reject = None
    if official:
        compared = [
            (bool(item.get("completed")), official[item.get("metadata", {}).get("instance_id")])
            for item in results
            if item.get("metadata", {}).get("instance_id") in official
        ]
        if compared:
            false_accept = sum(predicted and not actual for predicted, actual in compared)
            false_reject = sum(not predicted and actual for predicted, actual in compared)
    return {
        "tasks": total,
        "completed": completed,
        "resolve_rate": completed / total if total else 0.0,
        "agent_completion_rate": completed / total if total else 0.0,
        "mean_api_calls": sum(calls) / total if total else 0.0,
        "json_parse_retries": sum(int(item.get("json_parse_retries", 0)) for item in metadata),
        "verifier_accepts": verifier_accepts,
        "verifier_accept_rate": verifier_accepts / len(evaluated_reports) if evaluated_reports else None,
        "patch_apply_rate": sum(patch_results) / len(patch_results) if patch_results else None,
        "targeted_test_pass_rate": (
            sum(bool(check.get("passed")) for check in targeted_checks) / len(targeted_checks)
            if targeted_checks else None
        ),
        "false_accept": false_accept,
        "false_reject": false_reject,
        "llm_review_count": len(llm_reviews),
        "llm_review_rejects": llm_rejects,
        "valid_json_responses": json_valid,
        "json_responses": json_responses,
        "valid_json_rate": json_valid / json_responses if json_responses else None,
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "total_tokens": usage["total_tokens"],
        "mean_wall_time_ms": sum(wall_times) / total if total else 0.0,
        "estimated_cost_usd": round(sum(known_costs), 8) if known_costs else None,
        "api_error_count": sum(len(record.get("errors", [])) for record in api_records),
        "context_available_rate": (
            sum(bool(item.get("context_available")) for item in metadata) / total if total else 0.0
        ),
        "mean_tool_calls": (
            sum(int(item.get("tool_calls", item.get("metadata", {}).get("tool_calls", 0))) for item in results)
            / total
            if total else 0.0
        ),
        "tool_budget_rejections": sum(
            int(item.get("metadata", {}).get("tool_budget_rejections", 0)) for item in results
        ),
        "verifier_repairs": sum(
            int(item.get("metadata", {}).get("repair_attempts", 0)) for item in results
        ),
        "wall_time_exhausted": sum(
            bool(item.get("metadata", {}).get("wall_time_exhausted", False)) for item in results
        ),
    }


def _load_official_results(path: Path | None) -> dict[str, bool] | None:
    """Load optional SWE-bench evaluator output for error-rate accounting."""
    if path is None:
        return None
    values: dict[str, bool] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            instance_id = item.get("instance_id")
            value = item.get("resolved", item.get("passed", item.get("correct")))
            if instance_id is not None and isinstance(value, bool):
                values[str(instance_id)] = value
    return values


def _reset_workspace(task: dict[str, Any]) -> None:
    """Restore a prepared checkout before every variant/task combination.

    Without this reset, the first ablation leaves its patch in the checkout
    and every later variant is evaluated on a different starting state.  Only
    manifests containing the public task's base commit are reset; arbitrary
    prompt files pointing at a user's working directory are left untouched.
    """
    cwd = task.get("cwd")
    public_task = task.get("task") if isinstance(task.get("task"), dict) else {}
    base_commit = public_task.get("base_commit") or task.get("base_commit")
    if not cwd or not base_commit:
        return
    workspace = Path(str(cwd))
    if not (workspace / ".git").exists():
        raise RuntimeError(f"prepared task workspace is not a git checkout: {workspace}")
    subprocess.run(
        ["git", "reset", "--hard", str(base_commit)],
        cwd=workspace,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    subprocess.run(
        ["git", "clean", "-fdx"],
        cwd=workspace,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def _parse_variant(value: str) -> tuple[str, str, str, str]:
    pieces = value.upper().split("-")
    if len(pieces) == 3:
        try:
            config = ExperimentConfig.from_legacy_variant(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(str(exc)) from exc
        return config.context, config.action_protocol, config.controller_policy, config.verifier
    if len(pieces) != 4:
        raise argparse.ArgumentTypeError("variants must look like C0-J0-A0-V0")
    if pieces[0] not in {"C0", "C1", "C2"}:
        raise argparse.ArgumentTypeError("final context variants are C0, C1, and C2")
    if pieces[1] not in {"J0", "J3"}:
        raise argparse.ArgumentTypeError("unknown JSON variant")
    if pieces[2] not in {"A0", "A1"}:
        raise argparse.ArgumentTypeError("controller variants are A0 and A1")
    if pieces[3] not in {"V0", "V1", "V1R1"}:
        raise argparse.ArgumentTypeError("unknown verifier variant")
    try:
        ExperimentConfig(
            context=pieces[0],
            action_protocol=pieces[1],
            controller_policy=pieces[2],
            verifier=pieces[3],
        ).validated()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return pieces[0], pieces[1], pieces[2], pieces[3]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompts_file", required=True, type=Path)
    parser.add_argument("--output_dir", required=True, type=Path)
    parser.add_argument("--variant", action="append", required=True, type=_parse_variant)
    parser.add_argument("--model", default=None)
    parser.add_argument("--base_url", default=None)
    parser.add_argument("--api_key", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--env", default="local", choices=("local", "docker", "modal"))
    parser.add_argument("--image", default="python:3.11-slim")
    parser.add_argument("--cwd", default="/tmp")
    parser.add_argument("--max_iterations", type=int, default=15)
    parser.add_argument("--max_model_turns", type=int, default=12)
    parser.add_argument("--max_tool_calls", type=int, default=30)
    parser.add_argument("--max_wall_time_seconds", type=int, default=900)
    parser.add_argument("--max_completion_tokens", type=int, default=8192)
    parser.add_argument("--top_p", type=float, default=0.95)
    parser.add_argument("--top_k", type=int, default=20)
    parser.add_argument("--presence_penalty", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--api_timeout", type=int, default=120)
    parser.add_argument("--max_json_retries", type=int, default=1)
    parser.add_argument("--max_targeted_tests", type=int, default=3)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--official_results",
        type=Path,
        default=None,
        help="Optional official evaluator JSONL to compute false accept/reject",
    )
    parser.add_argument("--reproduction_before", default=None)
    parser.add_argument("--reproduction_after", default=None)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="append to an existing variant JSONL and skip completed instance IDs",
    )
    args = parser.parse_args()

    tasks = _load_tasks(args.prompts_file, args.limit)
    if not tasks:
        raise SystemExit("No prompts found")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    official_results = _load_official_results(args.official_results)

    summary: dict[str, Any] = {
        "model": args.model or os.getenv("TRACK2_MODEL", ""),
        "base_url": redact_base_url(args.base_url or os.getenv("TRACK2_BASE_URL", "")),
        "api_key_configured": bool(args.api_key or os.getenv("TRACK2_API_KEY")),
        "tasks": len(tasks),
        "variants": {},
    }
    for context_variant, json_mode, controller_policy, verifier_mode in args.variant:
        label = f"{context_variant}-{json_mode}-{controller_policy}-{verifier_mode}"
        output_file = args.output_dir / f"{label}.jsonl"
        runner = MiniSWERunner(
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key,
            env_type=args.env,
            image=args.image,
            cwd=args.cwd,
            max_iterations=args.max_iterations,
            max_model_turns=args.max_model_turns,
            max_tool_calls=args.max_tool_calls,
            max_wall_time_seconds=args.max_wall_time_seconds,
            max_completion_tokens=args.max_completion_tokens,
            top_p=args.top_p,
            top_k=args.top_k,
            presence_penalty=args.presence_penalty,
            seed=args.seed,
            command_timeout=args.timeout,
            api_timeout=args.api_timeout,
            verbose=args.verbose,
            context_variant=context_variant,
            json_mode=json_mode,
            controller_policy=controller_policy,
            verifier_mode=verifier_mode,
            max_json_retries=args.max_json_retries,
            max_targeted_tests=args.max_targeted_tests,
            reproduction_before=args.reproduction_before,
            reproduction_after=args.reproduction_after,
        )
        results: list[dict[str, Any]] = []
        completed_ids: set[str] = set()
        if args.resume and output_file.exists():
            with output_file.open(encoding="utf-8") as existing:
                for line in existing:
                    if not line.strip():
                        continue
                    try:
                        prior = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    results.append(prior)
                    instance_id = prior.get("metadata", {}).get("instance_id")
                    if instance_id:
                        completed_ids.add(str(instance_id))
        file_mode = "a" if args.resume and output_file.exists() else "w"
        with output_file.open(file_mode, encoding="utf-8") as handle:
            for task in tasks:
                task_id = task.get("instance_id") or (
                    task.get("task", {}).get("instance_id")
                    if isinstance(task.get("task"), dict)
                    else None
                )
                if args.resume and task_id and str(task_id) in completed_ids:
                    continue
                _reset_workspace(task)
                runner.cwd = str(task.get("cwd") or args.cwd)
                started = time.perf_counter()
                try:
                    result = runner.run_task(str(task["prompt"]))
                except Exception as exc:
                    result = {
                        "conversations": [],
                        "completed": False,
                        "api_calls": 0,
                        "error": str(exc),
                        "metadata": {
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                            "wall_time_ms": round((time.perf_counter() - started) * 1000, 2),
                        },
                    }
                result.setdefault("metadata", {})["instance_id"] = task.get("instance_id")
                result["metadata"]["task_base_commit"] = (
                    (task.get("task") or {}).get("base_commit")
                    if isinstance(task.get("task"), dict)
                    else task.get("base_commit")
                )
                results.append(result)
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                handle.flush()
        summary["variants"][label] = {
            "output_file": str(output_file),
            "metrics": _summarize(results, official_results),
        }

    summary_path = args.output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
