#!/usr/bin/env python3
"""Run leakage-free, model-fixed harness comparisons on SWE-bench tasks.

Gold patches, test patches and test IDs stay in the evaluator dataset.  The
agent-facing task object is rebuilt from an explicit allowlist and contains
only repository identity, base commit and problem statement.  Official
SWE-bench Docker evaluation is optional and happens after candidate patches
and trajectories have been frozen to disk.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import random
import re
import shutil
import statistics
import subprocess
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from track2_harness_benchmark import (
    AIDER_BIN,
    MINI_CONFIGS,
    QWEN_BIN,
    REPOGRAPH_PYTHON,
    ROOT,
    infrastructure_incomplete,
    keychain_secret,
    load_results,
    percentile,
    run_command,
    run_mini,
    sha256_text,
)
from track2_qwen_code import QWEN_CODE_VERSION, run_qwen_code


DEFAULT_DATASET = (
    ROOT
    / "benchmarks"
    / "RepoGraph"
    / "SWE-agent"
    / "tests"
    / "test_data"
    / "data_sources"
    / "swe-bench-lite-test.json"
)
DEFAULT_REPO_CACHE = ROOT / "workspaces" / "smoke" / ".repo-cache"
SWEBENCH_PYTHON = ROOT / "benchmarks" / "SWE-bench" / ".venv-track2" / "bin" / "python"
HARNESSES = (
    "mini-original",
    "mini-repomap",
    "mini-repograph-clean",
    "mini-budget",
    "mini-verifier-repair",
    "mini-json-structured",
    "qwen-code",
)
ALLOWED_HARNESSES = tuple(MINI_CONFIGS) + ("qwen-code",)
FORBIDDEN_AGENT_FIELDS = {
    "patch",
    "test_patch",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
    "hints_text",
}


def load_evaluator_records(
    path: Path,
    limit: int,
    *,
    require_gold: bool = False,
) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        records = [json.loads(line) for line in raw.splitlines() if line.strip()]
    else:
        records = json.loads(raw)
    if not isinstance(records, list):
        raise ValueError("SWE-bench dataset must be a JSON list or JSONL file")
    required = {"repo", "instance_id", "base_commit", "problem_statement"}
    if require_gold:
        required |= {"patch", "test_patch", "FAIL_TO_PASS", "PASS_TO_PASS"}
    for record in records:
        missing = required - set(record)
        if missing:
            raise ValueError(f"{record.get('instance_id', '<unknown>')} missing {sorted(missing)}")
    return records[:limit]


def agent_task(record: dict[str, Any]) -> dict[str, str]:
    """Return the only task representation allowed to cross into the agent."""
    public = {
        "repo": str(record["repo"]),
        "instance_id": str(record["instance_id"]),
        "base_commit": str(record["base_commit"]),
        "problem_statement": str(record["problem_statement"]),
    }
    if FORBIDDEN_AGENT_FIELDS & set(public):  # defensive invariant
        raise AssertionError("evaluator-only fields crossed the agent boundary")
    public["prompt"] = (
        "Resolve the following repository issue. Work only inside the current repository, "
        "implement the smallest correct fix, preserve public APIs, and run focused checks "
        "that are already available. Hidden evaluator tests are unavailable.\n\n"
        + public["problem_statement"]
    )
    return public


def prepare_workspace(
    public: dict[str, str],
    workspace: Path,
    repo_cache_root: Path,
) -> None:
    cache = repo_cache_root / public["repo"].replace("/", "__")
    if not cache.is_dir():
        raise FileNotFoundError(f"repository cache missing: {cache}")
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    # The shared cache may be a partial clone (for example blob:none).  A local
    # shared clone does not inherit its promisor remote, so missing blobs can
    # otherwise leave tracked files deleted while `git checkout` still exits 0.
    # Archiving the target tree forces the promisor cache to materialize every
    # blob before it is used as an object store.
    archive_path = ""
    try:
        with tempfile.NamedTemporaryFile(prefix="track2-hydrate-", suffix=".tar", delete=False) as archive:
            archive_path = archive.name
        hydrate = run_command(
            [
                "git",
                "-C",
                str(cache.resolve()),
                "archive",
                "--format=tar",
                f"--output={archive_path}",
                public["base_commit"],
            ],
            timeout=600,
        )
        if hydrate.returncode != 0:
            raise RuntimeError(f"repository hydration failed\n{hydrate.stdout[-4000:]}")
    finally:
        if archive_path:
            Path(archive_path).unlink(missing_ok=True)

    # Build a self-contained depth-1 repository.  `clone --shared` writes an
    # absolute alternates path to the host cache; that path is intentionally
    # unavailable inside the isolated agent container, which breaks git diff
    # and final patch capture even when ordinary file reads appear to work.
    commands = (
        (["git", "init", "-q", str(workspace)], None),
        (
            [
                "git",
                "fetch",
                "-q",
                "--no-tags",
                "--depth=1",
                str(cache.resolve()),
                public["base_commit"],
            ],
            workspace,
        ),
        (["git", "checkout", "-q", "--force", "--detach", "FETCH_HEAD"], workspace),
        (["git", "clean", "-q", "-fdx"], workspace),
    )
    for command, cwd in commands:
        result = run_command(command, cwd=cwd, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"workspace command failed: {' '.join(command)}\n{result.stdout[-4000:]}")

    missing = run_command(["git", "ls-files", "--deleted"], cwd=workspace, timeout=60)
    dirty = run_command(["git", "status", "--short"], cwd=workspace, timeout=60)
    if missing.returncode != 0 or dirty.returncode != 0:
        raise RuntimeError("workspace integrity checks could not run")
    if missing.stdout.strip():
        raise RuntimeError(f"workspace has unmaterialized tracked files:\n{missing.stdout[-4000:]}")
    if dirty.stdout.strip():
        raise RuntimeError(f"workspace is not clean after checkout:\n{dirty.stdout[-4000:]}")


def write_predictions(
    output_dir: Path,
    results: list[dict[str, Any]],
    harnesses: list[str],
    repeats: int,
) -> dict[tuple[str, int], Path]:
    paths: dict[tuple[str, int], Path] = {}
    for harness in harnesses:
        for repeat_id in range(1, repeats + 1):
            rows = [
                row
                for row in results
                if row["harness"] == harness and int(row.get("repeat", 1)) == repeat_id
            ]
            predictions = [
                {
                    "instance_id": row["task_id"],
                    "model_patch": Path(row["patch_path"]).read_text() if row.get("patch_path") else "",
                    "model_name_or_path": harness,
                }
                for row in rows
            ]
            path = output_dir / "predictions" / harness / f"repeat-{repeat_id:02d}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(predictions, ensure_ascii=False, indent=2) + "\n")
            paths[(harness, repeat_id)] = path
    return paths


def patch_files(patch: str) -> set[str]:
    return {
        match.group(1)
        for match in re.finditer(r"^diff --git a/(.+?) b/.+$", patch, flags=re.MULTILINE)
    }


def localization_diagnostics(trajectory: Any, gold_patch: str) -> dict[str, Any]:
    """Compute evaluator-only aggregate localization metrics after patch freeze.

    Gold filenames are intentionally not returned, so neither results.jsonl nor
    any future agent invocation can recover evaluator-only labels from this data.
    """

    gold_files = patch_files(gold_patch)
    if not gold_files:
        return {
            "gold_file_count": 0,
            "referenced_gold_file_count": 0,
            "gold_file_recall": None,
            "first_gold_reference_event": None,
        }
    events = trajectory if isinstance(trajectory, list) else []
    referenced: set[str] = set()
    first_event: int | None = None
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        # Exclude the original user prompt: issue statements sometimes name the
        # target file, which is not evidence that a harness localized it.
        if event.get("role") == "user" and index == 0:
            continue
        text = json.dumps(event, ensure_ascii=False, sort_keys=True)
        found = {path for path in gold_files if path in text}
        if found and first_event is None:
            first_event = index
        referenced.update(found)
    return {
        "gold_file_count": len(gold_files),
        "referenced_gold_file_count": len(referenced),
        "gold_file_recall": len(referenced) / len(gold_files),
        "first_gold_reference_event": first_event,
    }


def compact_instance_report(report_path: Path, instance_id: str) -> dict[str, Any]:
    raw = json.loads(report_path.read_text())
    report = raw.get(instance_id, raw)
    tests = report.get("tests_status", {}) if isinstance(report, dict) else {}

    def counts(group: str) -> tuple[int, int]:
        values = tests.get(group, {}) if isinstance(tests, dict) else {}
        success = len(values.get("success", [])) if isinstance(values, dict) else 0
        failure = len(values.get("failure", [])) if isinstance(values, dict) else 0
        return success, success + failure

    f2p_success, f2p_total = counts("FAIL_TO_PASS")
    p2p_success, p2p_total = counts("PASS_TO_PASS")
    resolved = bool(report.get("resolved"))
    partial = not resolved and (f2p_success > 0 or p2p_success > 0)
    return {
        "instance_id": instance_id,
        "patch_exists": bool(report.get("patch_exists")),
        "patch_applied": bool(report.get("patch_successfully_applied")),
        "resolved": resolved,
        "resolution_status": "FULL" if resolved else ("PARTIAL" if partial else "NO"),
        "fail_to_pass_success": f2p_success,
        "fail_to_pass_total": f2p_total,
        "fail_to_pass_rate": f2p_success / f2p_total if f2p_total else None,
        "pass_to_pass_success": p2p_success,
        "pass_to_pass_total": p2p_total,
        "pass_to_pass_rate": p2p_success / p2p_total if p2p_total else None,
    }


def evaluate_predictions(
    *,
    dataset: Path,
    predictions: Path,
    task_ids: list[str],
    output_dir: Path,
    harness: str,
    repeat_id: int,
    timeout: int,
) -> dict[str, Any]:
    if not SWEBENCH_PYTHON.exists():
        raise FileNotFoundError(f"official SWE-bench environment missing: {SWEBENCH_PYTHON}")
    eval_dir = output_dir / "official-eval" / harness / f"repeat-{repeat_id:02d}"
    eval_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"track2-{harness}-r{repeat_id:02d}"
    command = [
        str(SWEBENCH_PYTHON),
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        str(dataset.resolve()),
        "--instance_ids",
        *task_ids,
        "--predictions_path",
        str(predictions.resolve()),
        "--max_workers",
        "1",
        "--timeout",
        str(timeout),
        "--cache_level",
        "env",
        "--clean",
        "false",
        "--run_id",
        run_id,
        "--namespace",
        "none",
        "--report_dir",
        str((eval_dir / "logs").resolve()),
    ]
    result = run_command(command, cwd=eval_dir, timeout=max(timeout * len(task_ids) + 3600, 7200))
    (eval_dir / "evaluator.log").write_text(result.stdout)
    reports = sorted(eval_dir.glob(f"*.{run_id}.json"))
    report = json.loads(reports[-1].read_text()) if reports else {}
    search_roots = [eval_dir / "logs" / "run_evaluation", ROOT / "logs" / "run_evaluation"]
    instance_reports: list[dict[str, Any]] = []
    for instance_id in task_ids:
        candidates = [
            root / run_id / harness / instance_id / "report.json" for root in search_roots
        ]
        found = next((candidate for candidate in candidates if candidate.exists()), None)
        if found:
            instance_reports.append(compact_instance_report(found, instance_id))
    return {
        "harness": harness,
        "repeat": repeat_id,
        "returncode": result.returncode,
        "report_path": str(reports[-1].resolve()) if reports else "",
        "log_path": str((eval_dir / "evaluator.log").resolve()),
        "report": report,
        "instance_reports": instance_reports,
    }


def _official_instance_cache(output_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Load per-task official reports keyed by the frozen patch hash.

    SWE-bench removes instance images after each run.  Re-running an identical
    task+patch under another harness would otherwise rebuild the same x86 image
    (especially slow on an ARM laptop).  The prediction artifact is the source
    of the patch hash; the report remains the official evaluator evidence.
    """

    cache: dict[tuple[str, str], dict[str, Any]] = {}
    prediction_root = output_dir / "predictions"
    for prediction_path in prediction_root.glob("*/repeat-*.json"):
        try:
            rows = json.loads(prediction_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(rows, list):
            continue
        for report_path in prediction_root.parent.glob(
            f"official-eval/{prediction_path.parent.name}/{prediction_path.stem}/"
            "logs/run_evaluation/*/*/*/report.json"
        ):
            instance_id = report_path.parent.name
            row = next((item for item in rows if item.get("instance_id") == instance_id), None)
            if not isinstance(row, dict):
                continue
            patch_hash = sha256_text(str(row.get("model_patch") or ""))
            try:
                compact = compact_instance_report(report_path, instance_id)
            except (OSError, json.JSONDecodeError):
                continue
            cache[(instance_id, patch_hash)] = {
                **compact,
                "source_report_path": str(report_path.resolve()),
            }
    return cache


def _cached_evaluation(
    *,
    harness: str,
    repeat_id: int,
    prediction_rows: list[dict[str, Any]],
    cache: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    """Build an official-result aggregate when every task is safely reusable."""

    instance_reports: list[dict[str, Any]] = []
    for row in prediction_rows:
        instance_id = str(row.get("instance_id"))
        patch = str(row.get("model_patch") or "")
        if not patch:
            instance_reports.append(
                {
                    "instance_id": instance_id,
                    "patch_exists": False,
                    "patch_applied": False,
                    "resolved": False,
                    "resolution_status": "NO",
                    "fail_to_pass_success": 0,
                    "fail_to_pass_total": 0,
                    "fail_to_pass_rate": None,
                    "pass_to_pass_success": 0,
                    "pass_to_pass_total": 0,
                    "pass_to_pass_rate": None,
                }
            )
            continue
        cached = cache.get((instance_id, sha256_text(patch)))
        if cached is None:
            return None
        instance_reports.append({key: value for key, value in cached.items() if key != "source_report_path"})

    completed = [row for row in instance_reports if row["patch_exists"]]
    resolved = [row for row in completed if row["resolved"]]
    report = {
        "total_instances": len(prediction_rows),
        "submitted_instances": len(prediction_rows),
        "completed_instances": len(completed),
        "resolved_instances": len(resolved),
        "unresolved_instances": len(completed) - len(resolved),
        "empty_patch_instances": len(prediction_rows) - len(completed),
        "error_instances": 0,
        "completed_ids": [row["instance_id"] for row in completed],
        "incomplete_ids": [],
        "empty_patch_ids": [row["instance_id"] for row in instance_reports if not row["patch_exists"]],
        "submitted_ids": [row["instance_id"] for row in instance_reports],
        "resolved_ids": [row["instance_id"] for row in resolved],
        "unresolved_ids": [row["instance_id"] for row in completed if not row["resolved"]],
        "error_ids": [],
        "schema_version": 2,
    }
    return {
        "harness": harness,
        "repeat": repeat_id,
        "returncode": 0,
        "report_path": "",
        "log_path": "",
        "report": report,
        "instance_reports": instance_reports,
        "reused_official_instance_reports": True,
    }


def write_summary(output_dir: Path, results: list[dict[str, Any]], evaluations: list[dict[str, Any]]) -> None:
    by_harness: dict[str, dict[str, Any]] = {}
    harness_names = list(dict.fromkeys(row["harness"] for row in results))
    eval_by_key = {
        (evaluation["harness"], int(evaluation["repeat"]), row["instance_id"]): row
        for evaluation in evaluations
        for row in evaluation.get("instance_reports", [])
    }
    expected_runs = max((sum(row["harness"] == name for row in results) for name in harness_names), default=0)
    for harness in harness_names:
        rows = [row for row in results if row["harness"] == harness]
        eval_rows = [row for row in evaluations if row["harness"] == harness]
        resolved = sum(int(row.get("report", {}).get("resolved_instances", 0)) for row in eval_rows)
        completed = sum(int(row.get("report", {}).get("completed_instances", 0)) for row in eval_rows)
        submitted = sum(int(row.get("report", {}).get("submitted_instances", 0)) for row in eval_rows)
        instance_outcomes = [
            eval_by_key.get((harness, int(row.get("repeat", 1)), row["task_id"]), {
                "instance_id": row["task_id"],
                "resolved": False,
                "resolution_status": "NO",
                "patch_exists": bool(row.get("patch_bytes")),
                "patch_applied": False,
                "fail_to_pass_success": 0,
                "fail_to_pass_total": 0,
                "pass_to_pass_success": 0,
                "pass_to_pass_total": 0,
            })
            for row in rows
        ] if eval_rows else []
        f2p_success = sum(int(row.get("fail_to_pass_success", 0)) for row in instance_outcomes)
        f2p_total = sum(int(row.get("fail_to_pass_total", 0)) for row in instance_outcomes)
        p2p_success = sum(int(row.get("pass_to_pass_success", 0)) for row in instance_outcomes)
        p2p_total = sum(int(row.get("pass_to_pass_total", 0)) for row in instance_outcomes)
        diagnostics = [row.get("trajectory_diagnostics", {}) for row in rows]
        wall_times = [float(row.get("wall_time_ms", 0)) for row in rows]
        tokens = sum(int(row.get("usage", {}).get("total_tokens", 0) or 0) for row in rows)
        repeated: dict[str, list[bool]] = defaultdict(list)
        for row in rows:
            outcome = eval_by_key.get((harness, int(row.get("repeat", 1)), row["task_id"]))
            if outcome is not None:
                repeated[row["task_id"]].append(bool(outcome.get("resolved")))
        k_rows = [values for values in repeated.values() if len(values) > 1]
        integrity_failures = sum(
            not bool(item.get("integrity_eligible", True)) for item in diagnostics
        ) + sum(bool(row.get("qwen_settings_contains_secret")) for row in rows)
        infra_failures = sum(infrastructure_incomplete(row) for row in rows)
        by_harness[harness] = {
            "generated_tasks": len(rows),
            "complete_generator_runs": len(rows) - infra_failures,
            "patches": sum(bool(row.get("patch_bytes")) for row in rows),
            "patch_rate": sum(bool(row.get("patch_bytes")) for row in rows) / len(rows) if rows else 0,
            "semantic_calls": sum(int(row.get("semantic_calls", 0)) for row in rows),
            "model_turns": sum(int(row.get("model_turns", 0)) for row in rows),
            "tool_calls": sum(int(item.get("tool_calls", 0)) for item in diagnostics),
            "edit_rate": sum(int(item.get("edit_tool_calls", 0)) > 0 for item in diagnostics) / len(rows) if rows else 0,
            "test_after_edit_rate": sum(bool(item.get("tests_after_edit")) for item in diagnostics) / len(rows) if rows else 0,
            "repeated_commands": sum(int(item.get("repeated_commands", 0)) for item in diagnostics),
            "tool_errors": sum(int(item.get("tool_errors", 0)) for item in diagnostics),
            "integrity_failures": integrity_failures,
            "localization_rate": (
                sum(float(row.get("localization", {}).get("gold_file_recall") or 0) for row in rows)
                / len(rows)
                if rows
                else 0
            ),
            "first_edit_mean_ms": (
                statistics.mean(
                    float(item["first_edit_ms"])
                    for item in diagnostics
                    if item.get("first_edit_ms") is not None
                )
                if any(item.get("first_edit_ms") is not None for item in diagnostics)
                else None
            ),
            "usage": {"total_tokens": tokens},
            "mean_tokens": tokens / len(rows) if rows else 0,
            "mean_wall_time_ms": statistics.mean(wall_times) if wall_times else 0,
            "p95_wall_time_ms": percentile(wall_times, 0.95),
            "api_error_tasks": sum(bool(row.get("api_errors")) for row in rows),
            "infrastructure_incomplete_tasks": infra_failures,
            "official_submitted": submitted,
            "official_completed": completed,
            "official_resolved": resolved,
            "official_resolve_rate": resolved / len(rows) if eval_rows and rows else None,
            "official_partial": sum(row.get("resolution_status") == "PARTIAL" for row in instance_outcomes),
            "official_patch_apply_rate": (
                sum(bool(row.get("patch_applied")) for row in instance_outcomes) / len(rows)
                if eval_rows and rows
                else None
            ),
            "fail_to_pass_rate": f2p_success / f2p_total if f2p_total else None,
            "pass_to_pass_rate": p2p_success / p2p_total if p2p_total else None,
            "pass_at_k": sum(any(values) for values in k_rows) / len(k_rows) if k_rows else None,
            "pass_power_k": sum(all(values) for values in k_rows) / len(k_rows) if k_rows else None,
        }
    ranking_valid = bool(evaluations) and all(
        row["generated_tasks"] == expected_runs
        and row["infrastructure_incomplete_tasks"] == 0
        and row["integrity_failures"] == 0
        for row in by_harness.values()
    )
    ranked = sorted(
        by_harness,
        key=lambda name: (
            -float(by_harness[name]["official_resolve_rate"] or 0),
            -float(by_harness[name]["pass_power_k"] or 0),
            float(by_harness[name]["mean_tokens"]),
            float(by_harness[name]["mean_wall_time_ms"]),
        ),
    )
    pareto = []
    for candidate in ranked:
        current = by_harness[candidate]
        dominated = any(
            other != candidate
            and float(by_harness[other]["official_resolve_rate"] or 0)
            >= float(current["official_resolve_rate"] or 0)
            and float(by_harness[other]["mean_tokens"]) <= float(current["mean_tokens"])
            and float(by_harness[other]["mean_wall_time_ms"]) <= float(current["mean_wall_time_ms"])
            and (
                float(by_harness[other]["official_resolve_rate"] or 0)
                > float(current["official_resolve_rate"] or 0)
                or float(by_harness[other]["mean_tokens"]) < float(current["mean_tokens"])
                or float(by_harness[other]["mean_wall_time_ms"]) < float(current["mean_wall_time_ms"])
            )
            for other in ranked
        )
        if not dominated:
            pareto.append(candidate)
    payload = {
        "metrics_version": 3,
        "benchmark": "SWE-bench Lite official fixture pilot",
        "gold_fields_agent_visible": False,
        "harnesses": by_harness,
        "evaluations": evaluations,
        "ranking_valid": ranking_valid,
        "ranking": ranked if ranking_valid else [],
        "pilot_leader": ranked[0] if ranking_valid and ranked else None,
        "accuracy_token_latency_pareto": pareto if ranking_valid else [],
    }
    (output_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--evaluator-dataset",
        type=Path,
        default=None,
        help="gold-field SWE-bench dataset used only with --evaluate after patch freeze",
    )
    parser.add_argument("--repo-cache", type=Path, default=DEFAULT_REPO_CACHE)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "runs" / "swebench-repomap-pilot")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--instance-id",
        action="append",
        help="select explicit fixture IDs in the supplied order (overrides --limit)",
    )
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--harness", action="append", choices=ALLOWED_HARNESSES)
    parser.add_argument("--max-calls", type=int, default=12)
    parser.add_argument("--qwen-bin", type=Path, default=QWEN_BIN)
    parser.add_argument("--max-wall-time", type=int, default=900)
    parser.add_argument("--max-tool-calls", type=int, default=30)
    parser.add_argument("--api-timeout", type=int, default=90)
    parser.add_argument("--transport-retries", type=int, default=3)
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="sampling seed passed to mini-SWE runs (use a different value for stability reruns)",
    )
    parser.add_argument("--evaluate", action="store_true")
    parser.add_argument("--eval-timeout", type=int, default=900)
    parser.add_argument("--base-url", default=os.getenv("TRACK2_BASE_URL", "http://127.0.0.1:8000/v1"))
    parser.add_argument("--model", default=os.getenv("TRACK2_MODEL", "Qwen3-14B-BF16"))
    parser.add_argument("--agent-image", default="track2-python-agent:py312")
    parser.add_argument("--agent-env", choices=("local", "docker"), default="docker")
    args = parser.parse_args()

    if (
        args.limit <= 0
        or args.repeat <= 0
        or args.max_calls <= 0
        or args.max_wall_time <= 0
        or args.max_tool_calls <= 0
    ):
        parser.error("limit/repeat/max-calls/wall-time/tool-calls must be positive")
    harnesses = args.harness or list(HARNESSES)
    if "mini-repomap" in harnesses and not AIDER_BIN.exists():
        raise SystemExit(f"Aider dependency missing: {AIDER_BIN}")
    if "mini-repograph-clean" in harnesses and not REPOGRAPH_PYTHON.exists():
        raise SystemExit(f"RepoGraph dependency missing: {REPOGRAPH_PYTHON}")
    if "qwen-code" in harnesses and not args.qwen_bin.exists():
        raise SystemExit(f"Qwen Code dependency missing: {args.qwen_bin}")
    api_key = keychain_secret()
    if not api_key and args.base_url.startswith(("http://127.0.0.1", "http://localhost")):
        api_key = "local-vllm"
    if not api_key:
        raise SystemExit("TRACK2_API_KEY is missing and macOS Keychain entry was not found")

    records = load_evaluator_records(args.dataset.resolve(), 10**9, require_gold=False)
    if args.evaluate:
        if args.evaluator_dataset is None:
            parser.error("--evaluate requires --evaluator-dataset; keep gold fields off the agent host")
        evaluator_records = load_evaluator_records(
            args.evaluator_dataset.resolve(), 10**9, require_gold=True
        )
        evaluator_by_id_for_eval = {str(record["instance_id"]): record for record in evaluator_records}
    else:
        evaluator_by_id_for_eval = {}
    if args.instance_id:
        records_by_id = {record["instance_id"]: record for record in records}
        missing = [instance_id for instance_id in args.instance_id if instance_id not in records_by_id]
        if missing:
            raise SystemExit("unknown fixture instance ID(s): " + ", ".join(missing))
        records = [records_by_id[instance_id] for instance_id in args.instance_id]
    else:
        records = records[: args.limit]
    public_tasks = [agent_task(record) for record in records]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    public_manifest = [
        {key: task[key] for key in ("repo", "instance_id", "base_commit", "problem_statement")}
        for task in public_tasks
    ]
    serialized_manifest = json.dumps(public_manifest, ensure_ascii=False, indent=2) + "\n"
    for forbidden in FORBIDDEN_AGENT_FIELDS:
        if re.search(rf'"{re.escape(forbidden)}"\s*:', serialized_manifest):
            raise AssertionError(f"forbidden field in public manifest: {forbidden}")
    (args.output_dir / "public-manifest.json").write_text(serialized_manifest)
    config = {
        "protocol_version": 3,
        "dataset_path": str(args.dataset.resolve()),
        "dataset_sha256": sha256_text(args.dataset.read_text()),
        "harnesses": harnesses,
        "limit": len(records),
        "instance_ids": [record["instance_id"] for record in records],
        "repeats": args.repeat,
        "max_calls": args.max_calls,
        "max_wall_time": args.max_wall_time,
        "max_tool_calls": args.max_tool_calls,
        "model": args.model,
        "base_url": args.base_url,
        "agent_env": args.agent_env,
        "hardware": "AMD Radeon Graphics (gfx1100), 51.52 GB VRAM, RadeonX Cloud",
        "model_profile": "configs/qwen3_14b_bf16.json",
        "gold_fields_agent_visible": False,
        "hidden_test_policy": "official-evaluator-after-freeze",
        "qwen_code_version": QWEN_CODE_VERSION if "qwen-code" in harnesses else None,
        "seed": args.seed,
    }
    config_path = args.output_dir / "run-config.json"
    if config_path.exists() and json.loads(config_path.read_text()) != config:
        raise SystemExit("existing run-config.json differs; use a new output directory")
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")

    results_path = args.output_dir / "results.jsonl"
    results = load_results(results_path)
    completed = {
        (row["harness"], int(row.get("repeat", 1)), row["task_id"])
        for row in results
    }
    for repeat_id in range(1, args.repeat + 1):
        for public in public_tasks:
            unit_harnesses = list(harnesses)
            random.Random(f"swe:{repeat_id}:{public['instance_id']}").shuffle(unit_harnesses)
            for harness in unit_harnesses:
                key = (harness, repeat_id, public["instance_id"])
                if key in completed:
                    continue
                print(f"RUN SWE-bench r{repeat_id} {harness} {public['instance_id']}", flush=True)
                workspace = (
                    args.output_dir
                    / "workspaces"
                    / harness
                    / f"repeat-{repeat_id:02d}"
                    / public["instance_id"]
                )
                started = time.perf_counter()
                try:
                    prepare_workspace(public, workspace, args.repo_cache)
                    runner_task = {
                        "task_id": public["instance_id"],
                        "prompt": public["prompt"],
                        "solution_files": [],
                    }
                    if harness == "qwen-code":
                        agent_result = run_qwen_code(
                            runner_task,
                            workspace,
                            args.output_dir
                            / "qwen-runtime"
                            / f"repeat-{repeat_id:02d}"
                            / public["instance_id"],
                            qwen_bin=args.qwen_bin,
                            base_url=args.base_url,
                            api_key=api_key,
                            model=args.model,
                            max_calls=args.max_calls,
                            max_tool_calls=args.max_tool_calls,
                            max_wall_time=args.max_wall_time,
                            api_timeout=args.api_timeout,
                            transport_retries=args.transport_retries,
                        )
                    else:
                        agent_result = run_mini(
                            harness,
                            runner_task,
                            workspace,
                            base_url=args.base_url,
                            api_key=api_key,
                            model=args.model,
                            max_calls=args.max_calls,
                            api_timeout=args.api_timeout,
                            transport_retries=args.transport_retries,
                            agent_image=args.agent_image,
                            agent_env=args.agent_env,
                            max_wall_time=args.max_wall_time,
                            max_tool_calls=args.max_tool_calls,
                            seed=args.seed,
                        )
                    patch = str(agent_result.pop("final_patch", ""))
                    trajectory = agent_result.pop("_trajectory", [])
                    context = str(agent_result.pop("_context_text", ""))
                    stderr = str(agent_result.pop("_stderr", ""))
                    localization = localization_diagnostics(
                        trajectory,
                        "",
                    )
                    suffix = f"repeat-{repeat_id:02d}/{public['instance_id']}"
                    patch_path = args.output_dir / "patches" / harness / f"{suffix}.patch"
                    trajectory_path = args.output_dir / "trajectories" / harness / f"{suffix}.json"
                    context_path = args.output_dir / "contexts" / harness / f"{suffix}.txt"
                    stderr_path = args.output_dir / "stderr" / harness / f"{suffix}.log"
                    for path in (patch_path, trajectory_path, context_path, stderr_path):
                        path.parent.mkdir(parents=True, exist_ok=True)
                    patch_path.write_text(patch)
                    trajectory_path.write_text(json.dumps(trajectory, ensure_ascii=False, indent=2) + "\n")
                    context_path.write_text(context)
                    stderr_path.write_text(stderr)
                    result = {
                        "harness": harness,
                        "repeat": repeat_id,
                        "task_id": public["instance_id"],
                        "patch_path": str(patch_path.resolve()),
                        "trajectory_path": str(trajectory_path.resolve()),
                        "context_path": str(context_path.resolve()),
                        "stderr_path": str(stderr_path.resolve()),
                        "patch_sha256": sha256_text(patch),
                        "patch_bytes": len(patch.encode()),
                        "context_sha256": sha256_text(context),
                        "model": args.model,
                        "max_calls": args.max_calls,
                        "localization": localization,
                        "evaluator_fields_visible": False,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "wall_time_ms": round((time.perf_counter() - started) * 1000, 2),
                        **agent_result,
                    }
                except Exception as exc:
                    result = {
                        "harness": harness,
                        "repeat": repeat_id,
                        "task_id": public["instance_id"],
                        "patch_path": "",
                        "patch_bytes": 0,
                        "semantic_calls": 0,
                        "model_turns": 0,
                        "max_calls": args.max_calls,
                        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                        "api_errors": [str(exc)[:2000]],
                        "evaluator_fields_visible": False,
                        "exception": repr(exc),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "wall_time_ms": round((time.perf_counter() - started) * 1000, 2),
                    }
                with results_path.open("a") as handle:
                    handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                results.append(result)
                completed.add(key)
                write_predictions(args.output_dir, results, harnesses, args.repeat)

    predictions = write_predictions(args.output_dir, results, harnesses, args.repeat)
    evaluations: list[dict[str, Any]] = []
    if args.evaluate:
        task_ids = [task["instance_id"] for task in public_tasks]
        evaluation_cache: dict[str, dict[str, Any]] = {}
        official_instance_cache = _official_instance_cache(args.output_dir)
        for harness in harnesses:
            for repeat_id in range(1, args.repeat + 1):
                prediction_rows = json.loads(predictions[(harness, repeat_id)].read_text())
                cached_evaluation = _cached_evaluation(
                    harness=harness,
                    repeat_id=repeat_id,
                    prediction_rows=prediction_rows,
                    cache=official_instance_cache,
                )
                if cached_evaluation is not None:
                    evaluations.append(cached_evaluation)
                    print(
                        f"REUSE OFFICIAL INSTANCE REPORTS r{repeat_id} {harness}",
                        flush=True,
                    )
                    continue
                candidate_key = sha256_text(
                    json.dumps(
                        [
                            (row["instance_id"], row.get("model_patch", ""))
                            for row in prediction_rows
                        ],
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                if candidate_key in evaluation_cache:
                    reused = copy.deepcopy(evaluation_cache[candidate_key])
                    reused["harness"] = harness
                    reused["repeat"] = repeat_id
                    reused["reused_from"] = evaluation_cache[candidate_key]["harness"]
                    evaluations.append(reused)
                    print(
                        f"REUSE EVALUATION r{repeat_id} {harness} "
                        f"from {reused['reused_from']} (identical candidates)",
                        flush=True,
                    )
                    continue
                print(f"EVALUATE r{repeat_id} {harness}", flush=True)
                evaluation = evaluate_predictions(
                    dataset=args.evaluator_dataset or args.dataset,
                        predictions=predictions[(harness, repeat_id)],
                        task_ids=task_ids,
                        output_dir=args.output_dir,
                        harness=harness,
                        repeat_id=repeat_id,
                        timeout=args.eval_timeout,
                    )
                evaluations.append(evaluation)
                evaluation_cache[candidate_key] = evaluation
    write_summary(args.output_dir, results, evaluations)
    print(json.dumps(json.loads((args.output_dir / "summary.json").read_text()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
