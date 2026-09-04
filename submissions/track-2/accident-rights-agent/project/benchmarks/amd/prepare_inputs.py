#!/usr/bin/env python3
"""Deduplicate Case Capsule tool output while preserving protected fields."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.memory.context_builder import estimate_tokens  # noqa: E402
from app.memory.protected_fields import protected_set  # noqa: E402


def project_necessary_tool_fields(payload: dict[str, Any]) -> dict[str, Any]:
    projected = json.loads(json.dumps(payload, ensure_ascii=False))
    capsule = dict(projected.get("capsule") or {})
    if projected.get("facts"):
        capsule.pop("confirmed_facts", None)
    if projected.get("citations"):
        capsule.pop("citations", None)
    capsule = {
        key: value
        for key, value in capsule.items()
        if value not in (None, [], {}, "")
    }
    projected["capsule"] = capsule
    projected.pop("task", None)
    return projected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--capsule", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    capsule = json.loads(args.capsule.read_text(encoding="utf-8"))
    optimized = project_necessary_tool_fields(capsule)
    before = protected_set(baseline)
    after = protected_set(optimized)
    missing = sorted(before - after)
    report = {
        "baseline_estimated_tokens": estimate_tokens(baseline),
        "optimized_estimated_tokens": estimate_tokens(optimized),
        "estimated_token_reduction_ratio": round(
            1 - estimate_tokens(optimized) / max(1, estimate_tokens(baseline)), 6
        ),
        "protected_field_count": len(before),
        "protected_field_retained": len(before & after),
        "protected_field_retention": round(
            len(before & after) / max(1, len(before)), 6
        ),
        "missing_protected_fields": [
            {"kind": kind, "value": value} for kind, value in missing
        ],
        "projection": [
            "remove duplicated capsule.confirmed_facts",
            "remove duplicated capsule.citations",
            "remove empty capsule sections",
            "remove duplicated payload.task",
        ],
    }
    if missing:
        raise RuntimeError(f"Protected fields lost during projection: {missing}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(optimized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
