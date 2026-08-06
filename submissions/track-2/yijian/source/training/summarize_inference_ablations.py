#!/usr/bin/env python3
"""Summarize prefix-cache and maximum-context W7900 inference ablations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


def read_report(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("cycles") != 30 or len(value.get("rows") or []) != 30:
        raise ValueError(f"{path} must contain exactly 30 cycles")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def profile(name: str, report: dict[str, Any]) -> dict[str, Any]:
    rows = report["rows"]
    completion_tokens = sum(int((row["llm"].get("usage") or {}).get("completion_tokens") or 0) for row in rows)
    generation_seconds = sum(float(row["llm"]["totalSeconds"]) for row in rows)
    return {
        "name": name,
        "cycles": report["cycles"],
        "passed": bool(report["passed"]),
        "oomCount": int(report["oomCount"]),
        "combinedP95Seconds": float(report["combined"]["p95Seconds"]),
        "firstTokenP95Seconds": float(report["llm"]["p95FirstTokenSeconds"]),
        "generationP95Seconds": float(report["llm"]["p95TotalSeconds"]),
        "completionTokensPerSecond": round(completion_tokens / generation_seconds, 4),
        "peakVramUsedGiB": float(report["telemetry"]["peakVramUsedGiB"]),
    }


def agreement(reference: dict[str, Any], candidate: dict[str, Any]) -> float:
    reference_hashes = [str(row["llm"]["textHash"]) for row in reference["rows"]]
    candidate_hashes = [str(row["llm"]["textHash"]) for row in candidate["rows"]]
    return sum(left == right for left, right in zip(reference_hashes, candidate_hashes)) / len(reference_hashes)


def response_shape_consistency(reference: dict[str, Any], candidate: dict[str, Any]) -> float:
    """Check comparable complete responses without pretending stochastic text must be identical."""
    passed = 0
    for reference_row, candidate_row in zip(reference["rows"], candidate["rows"]):
        reference_chars = int(reference_row["llm"].get("chars") or 0)
        candidate_chars = int(candidate_row["llm"].get("chars") or 0)
        completion_tokens = int((candidate_row["llm"].get("usage") or {}).get("completion_tokens") or 0)
        ratio = candidate_chars / reference_chars if reference_chars else 0
        passed += bool(candidate_chars > 0 and 0 < completion_tokens <= 220 and .33 <= ratio <= 3.0)
    return passed / len(reference["rows"])


def build_summary(*, baseline_path: Path, prefix_off_path: Path, context_16384_path: Path) -> dict[str, Any]:
    baseline = read_report(baseline_path)
    prefix_off = read_report(prefix_off_path)
    context_16384 = read_report(context_16384_path)
    profiles = {
        "prefixOnContext8192": profile("prefix-on-context-8192", baseline),
        "prefixOffContext8192": profile("prefix-off-context-8192", prefix_off),
        "prefixOnContext16384": profile("prefix-on-context-16384", context_16384),
    }
    prefix_agreement = agreement(baseline, prefix_off)
    context_agreement = agreement(baseline, context_16384)
    prefix_shape = response_shape_consistency(baseline, prefix_off)
    context_shape = response_shape_consistency(baseline, context_16384)
    gates = {
        "allProfilesThirtyOfThirty": all(item["cycles"] == 30 for item in profiles.values()),
        "allProfilesNoOom": all(item["oomCount"] == 0 for item in profiles.values()),
        "prefixResponseShapeConsistencyAtLeast95Percent": prefix_shape >= .95,
        "contextResponseShapeConsistencyAtLeast95Percent": context_shape >= .95,
    }
    return {
        "schemaVersion": "yijian-w7900-inference-ablation-summary-v1",
        "passed": all(gates.values()),
        "gates": gates,
        "profiles": profiles,
        "comparisons": {
            "prefixCacheOnVsOff": {
                "exactTextHashAgreementDiagnostic": prefix_agreement,
                "responseShapeConsistency": prefix_shape,
                "samplingNote": "temperature 0.2 permits wording variation; exact hashes are diagnostic, not a quality gate",
                "combinedP95DeltaSeconds": round(
                    profiles["prefixOnContext8192"]["combinedP95Seconds"]
                    - profiles["prefixOffContext8192"]["combinedP95Seconds"], 4
                ),
                "firstTokenP95DeltaSeconds": round(
                    profiles["prefixOnContext8192"]["firstTokenP95Seconds"]
                    - profiles["prefixOffContext8192"]["firstTokenP95Seconds"], 4
                ),
            },
            "context8192Vs16384": {
                "exactTextHashAgreementDiagnostic": context_agreement,
                "responseShapeConsistency": context_shape,
                "samplingNote": "temperature 0.2 permits wording variation; exact hashes are diagnostic, not a quality gate",
                "combinedP95DeltaSeconds": round(
                    profiles["prefixOnContext8192"]["combinedP95Seconds"]
                    - profiles["prefixOnContext16384"]["combinedP95Seconds"], 4
                ),
                "peakVramDeltaGiB": round(
                    profiles["prefixOnContext8192"]["peakVramUsedGiB"]
                    - profiles["prefixOnContext16384"]["peakVramUsedGiB"], 4
                ),
            },
        },
        "inputs": {
            "prefixOnContext8192Sha256": sha256(baseline_path),
            "prefixOffContext8192Sha256": sha256(prefix_off_path),
            "prefixOnContext16384Sha256": sha256(context_16384_path),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--prefix-off", type=Path, required=True)
    parser.add_argument("--context-16384", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_summary(
        baseline_path=args.baseline,
        prefix_off_path=args.prefix_off,
        context_16384_path=args.context_16384,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
