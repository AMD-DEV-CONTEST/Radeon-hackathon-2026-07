#!/usr/bin/env python3
"""Verify baseline/candidate comparability against declared changes."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

FROZEN = (
    "hardware.gpu",
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
)


def get(document: dict, dotted: str):
    value = document
    for part in dotted.split("."):
        value = value[part]
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan")
    parser.add_argument("baseline")
    parser.add_argument("candidate")
    args = parser.parse_args()
    load = lambda path: json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    try:
        plan, baseline, candidate = load(args.plan), load(args.baseline), load(args.candidate)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL AC-20: invalid input: {exc}")
        return 1

    declared = {change["path"]: change for change in plan.get("declared_changes", []) if isinstance(change, dict) and "path" in change}
    failures: list[str] = []
    checked = set(FROZEN) | set(declared)
    for path in sorted(checked):
        try:
            before, after = get(baseline, path), get(candidate, path)
        except (KeyError, TypeError):
            failures.append(f"missing comparison field: {path}")
            continue
        change = declared.get(path)
        if change:
            if before != change.get("baseline") or after != change.get("candidate"):
                failures.append(f"declared change does not match manifests: {path}")
        elif before != after:
            failures.append(f"undeclared frozen-condition drift: {path}: {before!r} -> {after!r}")
    for failure in failures:
        print(f"FAIL AC-20: {failure}")
    if failures:
        return 1
    print("PASS AC-20: manifests are comparable and all measured changes were declared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
