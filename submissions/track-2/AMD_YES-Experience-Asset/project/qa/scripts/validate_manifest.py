#!/usr/bin/env python3
"""Validate a public reproducibility manifest (AC-19)."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

REQUIRED = (
    "schema_version",
    "run_group_id",
    "timestamp_utc",
    "profile_label",
    "git_commit",
    "hardware.gpu",
    "hardware.vram_gib",
    "hardware.local_proof_ref",
    "software.container",
    "software.rocm",
    "software.torch",
    "software.vllm",
    "model.repository",
    "model.revision",
    "model.dtype",
    "model.quantization",
    "serving.context_length",
    "serving.max_output_tokens",
    "serving.gpu_memory_utilization",
    "serving.max_num_seqs",
    "serving.server_args",
    "workload.fixture_set_version",
    "workload.workflow_version",
    "workload.scenario_type",
    "measurement.num_prompts",
    "measurement.warmup_runs",
    "measurement.measured_runs",
    "measurement.concurrency",
    "measurement.temperature",
    "outcomes.success_count",
    "outcomes.failure_count",
    "outcomes.raw_result_ref",
)


def get(document: dict, dotted: str):
    value = document
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def placeholder(value) -> bool:
    return isinstance(value, str) and (value.startswith("<") or value.startswith("TODO"))


def validate(document: dict) -> list[str]:
    failures = [path for path in REQUIRED if get(document, path) in (None, "", []) or placeholder(get(document, path))]
    if document.get("schema_version") != "1.0":
        failures.append("schema_version must be 1.0")
    commit = document.get("git_commit", "")
    if commit and not placeholder(commit) and not re.fullmatch(r"[0-9a-f]{40}", commit):
        failures.append("git_commit must be a full 40-character SHA")
    scenario = get(document, "workload.scenario_type")
    if scenario not in {"interactive", "background", "stress"}:
        failures.append("workload.scenario_type must be interactive/background/stress")
    measured = get(document, "measurement.measured_runs")
    success = get(document, "outcomes.success_count")
    failed = get(document, "outcomes.failure_count")
    if all(isinstance(value, int) and not isinstance(value, bool) for value in (measured, success, failed)):
        if success + failed != measured:
            failures.append("success_count + failure_count must equal measured_runs")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    args = parser.parse_args()
    try:
        document = json.loads(pathlib.Path(args.manifest).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL AC-19: invalid manifest: {exc}")
        return 1
    failures = validate(document)
    for failure in failures:
        print(f"FAIL AC-19: {failure}")
    if failures:
        print("RESULT: FAIL — manifest is not admissible evidence")
        return 1
    print("RESULT: PASS — manifest is complete and internally consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
