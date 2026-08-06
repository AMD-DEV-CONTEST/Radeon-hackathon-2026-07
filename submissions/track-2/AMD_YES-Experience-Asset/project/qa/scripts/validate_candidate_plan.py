#!/usr/bin/env python3
"""Validate a prospective performance candidate plan (AC-26/AC-29)."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

REQUIRED = (
    "schema_version",
    "candidate_name",
    "target_stage",
    "business_reason",
    "primary_metric",
    "hypothesis",
    "quality_floors",
    "frozen_manifest_ref",
    "declared_changes",
    "side_effects",
    "rollback",
    "approved_before_measurement",
)


def incomplete(value) -> bool:
    return value in (None, "", []) or (isinstance(value, str) and (value.startswith("<") or value.startswith("TODO")))


def validate(plan: dict) -> list[str]:
    failures = [key for key in REQUIRED if incomplete(plan.get(key))]
    if plan.get("schema_version") != "1.0":
        failures.append("schema_version must be 1.0")
    changes = plan.get("declared_changes", [])
    if isinstance(changes, list):
        for index, change in enumerate(changes):
            if not isinstance(change, dict):
                failures.append(f"declared_changes[{index}] must be an object")
                continue
            for key in ("path", "baseline", "candidate", "reason"):
                if incomplete(change.get(key)):
                    failures.append(f"declared_changes[{index}].{key}")
            if change.get("baseline") == change.get("candidate"):
                failures.append(f"declared_changes[{index}] does not change a value")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan")
    args = parser.parse_args()
    try:
        plan = json.loads(pathlib.Path(args.plan).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL AC-26: invalid plan: {exc}")
        return 1
    failures = validate(plan)
    for failure in failures:
        print(f"FAIL AC-26/29: missing or invalid {failure}")
    if failures:
        return 1
    print("PASS AC-26/29: candidate was prospectively and reversibly declared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
