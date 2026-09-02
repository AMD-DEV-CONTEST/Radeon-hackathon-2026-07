#!/usr/bin/env python3
"""Evaluate a frozen four-case claim corpus with generic field constraints.

This benchmark is a synthetic audit of already-frozen JSON evidence.  It does
not run a simulator and does not estimate robot capability, safety, or general
classification accuracy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Sequence


PROJECT_ROOT: Final = Path(__file__).resolve().parents[1]
SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")
ACCEPT: Final = "ACCEPT"
REJECT: Final = "REJECT"


class FrozenClaimError(RuntimeError):
    """Raised when an authority or constraint cannot be verified exactly."""


@dataclass(frozen=True)
class Constraint:
    field: str
    operator: str
    expected: Any


@dataclass(frozen=True)
class FrozenCase:
    case_id: str
    relative_path: str
    expected_sha256: str
    constraints: tuple[Constraint, ...]


CASE_CORPUS: Final[tuple[FrozenCase, ...]] = (
    FrozenCase(
        case_id="radeon_fixed_r5_scaling",
        relative_path="submission/evidence/radeon-formal-scaling.json",
        expected_sha256="98d9b331907f9968ae65054c6f9d840dc0440eb9209c14e955dc628df736f072",
        constraints=(
            Constraint("simulation_only", "eq", True),
            Constraint("status", "eq", "PASS"),
            Constraint("execution_contract.one_radeon_gpu", "eq", True),
            Constraint("execution_contract.strictly_serial", "eq", True),
            Constraint("scaling.status", "eq", "PASS"),
            Constraint("scaling.identity_consistent_across_fresh_serial_workers", "eq", True),
            Constraint("scaling.performance_acceptance.preregistered", "eq", True),
            Constraint("scaling.performance_acceptance.achieved", "eq", True),
            Constraint("scaling.performance_acceptance.checks.cv_each_env_count.32", "eq", True),
            Constraint("scaling.performance_acceptance.checks.cv_each_env_count.128", "eq", True),
            Constraint("scaling.performance_acceptance.checks.cv_each_env_count.256", "eq", True),
            Constraint("scaling.performance_acceptance.checks.cv_each_env_count.512", "eq", True),
            Constraint("scaling.performance_acceptance.checks.speedup_512_vs_32.achieved", "eq", True),
            Constraint("scaling.env_summaries.0.coefficient_of_variation", "le", 0.15),
            Constraint("scaling.env_summaries.1.coefficient_of_variation", "le", 0.15),
            Constraint("scaling.env_summaries.2.coefficient_of_variation", "le", 0.15),
            Constraint("scaling.env_summaries.3.coefficient_of_variation", "le", 0.15),
            Constraint("scaling.env_summaries.3.speedup_vs_32_envs", "ge", 1.5),
        ),
    ),
    FrozenCase(
        case_id="v4_repair_claim",
        relative_path="submission/evidence/v4-summary.json",
        expected_sha256="4ebab98a9b9c3b134548ef646c30aaafbd7d6ddeaa8a0485b667ee8054f80f8b",
        constraints=(
            Constraint(
                "capability_effect.patch_vs_action_only_failure_reduction_fraction",
                "ge",
                0.50,
            ),
            Constraint(
                "integrity.checks.patch_not_worse_than_raw_or_calibrated",
                "eq",
                True,
            ),
        ),
    ),
    FrozenCase(
        case_id="v5_incremental_capability_claim",
        relative_path="submission/evidence/v5-summary.json",
        expected_sha256="d546a620931fc3afb2c074d749e1fe017ba6c4dcdf2d05b570855a913e83b034",
        constraints=(
            Constraint("metrics.CausalIMUPatch.fault.mission_success_count", "ge", 11),
            Constraint(
                "integrity.fault_paired_patch_calibrated_trace.30.all_operational_legacy_fields_raw_bit_exact",
                "eq",
                False,
            ),
            Constraint(
                "integrity.fault_paired_patch_calibrated_trace.31.all_operational_legacy_fields_raw_bit_exact",
                "eq",
                False,
            ),
            Constraint(
                "integrity.fault_paired_patch_calibrated_trace.32.all_operational_legacy_fields_raw_bit_exact",
                "eq",
                False,
            ),
        ),
    ),
    FrozenCase(
        case_id="v6_observer_admission_claim",
        relative_path="submission/evidence/v6-checkpoint-30.json",
        expected_sha256="905925dedc62a41a8b4c35ace8b1c5a1bd1d97c9cb4d43a5f513f3827cf0a678",
        constraints=(Constraint("admitted_lane_count", "ge", 9),),
    ),
)

EXPECTED_LABELS: Final[dict[str, str]] = {
    "radeon_fixed_r5_scaling": ACCEPT,
    "v4_repair_claim": REJECT,
    "v5_incremental_capability_claim": REJECT,
    "v6_observer_admission_claim": REJECT,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_sha256(value: str, *, name: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise FrozenClaimError(f"{name} must be a lowercase SHA256")
    return value


def _reject_constant(value: str) -> None:
    raise FrozenClaimError(f"non-finite JSON constant is forbidden: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FrozenClaimError(f"duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result


def load_strict_json_bytes(raw: bytes, *, path: Path) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
        payload = json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise FrozenClaimError(f"cannot load strict JSON {path}: {error}") from error
    if not isinstance(payload, dict):
        raise FrozenClaimError(f"JSON root must be an object: {path}")
    return payload


def load_strict_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise FrozenClaimError(f"cannot read strict JSON {path}: {error}") from error
    return load_strict_json_bytes(raw, path=path)


def load_verified_artifact(path: Path, expected_sha256: str) -> tuple[dict[str, Any], str, int]:
    expected = require_sha256(expected_sha256, name="artifact expected SHA256")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise FrozenClaimError(f"artifact is not a regular file: {resolved}")
    try:
        raw = resolved.read_bytes()
    except OSError as error:
        raise FrozenClaimError(f"cannot read artifact {resolved}: {error}") from error
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise FrozenClaimError(f"artifact SHA256 mismatch: {resolved}")
    return load_strict_json_bytes(raw, path=resolved), actual, len(raw)


def resolve_field(payload: Any, field: str) -> Any:
    if not isinstance(field, str) or not field or field.startswith(".") or field.endswith("."):
        raise FrozenClaimError("constraint field path is invalid")
    current = payload
    for segment in field.split("."):
        if isinstance(current, dict):
            if segment not in current:
                raise FrozenClaimError(f"constraint field is missing: {field}")
            current = current[segment]
        elif isinstance(current, list):
            if not segment.isdigit():
                raise FrozenClaimError(f"list constraint segment must be an index: {field}")
            index = int(segment)
            if index >= len(current):
                raise FrozenClaimError(f"constraint list index is out of range: {field}")
            current = current[index]
        else:
            raise FrozenClaimError(f"constraint traverses a scalar: {field}")
    return current


def _is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value))


def _equal(actual: Any, expected: Any) -> bool:
    if _is_number(actual) and _is_number(expected):
        return float(actual) == float(expected)
    return type(actual) is type(expected) and actual == expected


def evaluate_constraints(
    artifact: dict[str, Any],
    constraints: Sequence[Constraint],
) -> tuple[str, list[dict[str, Any]]]:
    """Return a decision using only an artifact and generic constraints."""

    if not isinstance(artifact, dict) or not constraints:
        raise FrozenClaimError("artifact must be an object and constraints must be non-empty")
    results: list[dict[str, Any]] = []
    for constraint in constraints:
        actual = resolve_field(artifact, constraint.field)
        if constraint.operator == "eq":
            passed = _equal(actual, constraint.expected)
        elif constraint.operator in {"ge", "le"}:
            if not _is_number(actual) or not _is_number(constraint.expected):
                raise FrozenClaimError(
                    f"numeric constraint requires finite non-boolean numbers: {constraint.field}"
                )
            passed = (
                float(actual) >= float(constraint.expected)
                if constraint.operator == "ge"
                else float(actual) <= float(constraint.expected)
            )
        else:
            raise FrozenClaimError(f"unsupported constraint operator: {constraint.operator}")
        results.append(
            {
                "field": constraint.field,
                "operator": constraint.operator,
                "expected": constraint.expected,
                "actual": actual,
                "passed": passed,
            }
        )
    return (ACCEPT if all(item["passed"] for item in results) else REJECT), results


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def score_predictions(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    valid_labels = {ACCEPT, REJECT}
    if not rows:
        raise FrozenClaimError("at least one completed decision is required")
    if any(row.get("decision") not in valid_labels or row.get("expected_label") not in valid_labels for row in rows):
        raise FrozenClaimError("decision and expected labels must be ACCEPT or REJECT")
    tp = sum(row["decision"] == ACCEPT and row["expected_label"] == ACCEPT for row in rows)
    tn = sum(row["decision"] == REJECT and row["expected_label"] == REJECT for row in rows)
    fp = sum(row["decision"] == ACCEPT and row["expected_label"] == REJECT for row in rows)
    fn = sum(row["decision"] == REJECT and row["expected_label"] == ACCEPT for row in rows)
    return {
        "true_positive": tp,
        "true_negative": tn,
        "false_positive": fp,
        "false_negative": fn,
        "precision": _safe_ratio(tp, tp + fp),
        "recall": _safe_ratio(tp, tp + fn),
        "specificity": _safe_ratio(tn, tn + fp),
        "accuracy": _safe_ratio(tp + tn, len(rows)),
        "false_accept_count": fp,
        "false_accept_rate": _safe_ratio(fp, fp + tn),
    }


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def write_exclusive(path: Path, payload: dict[str, Any]) -> None:
    output = path.expanduser().resolve()
    if not output.parent.is_dir():
        raise FrozenClaimError(f"output parent does not exist: {output.parent}")
    data = canonical_json_bytes(payload)
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        created = True
        os.fchmod(descriptor, 0o444)
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset:])
            if written <= 0:
                raise OSError("short output write")
            offset += written
        os.fsync(descriptor)
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
            descriptor = None
        if created:
            output.unlink(missing_ok=True)
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)


def run_benchmark(*, expected_source_sha256: str) -> dict[str, Any]:
    expected_source = require_sha256(expected_source_sha256, name="source expected SHA256")
    source_path = Path(__file__).resolve()
    source_sha = sha256_file(source_path)
    if source_sha != expected_source:
        raise FrozenClaimError("running source SHA256 differs from --expected-source-sha256")

    decisions: list[dict[str, Any]] = []
    for case in CASE_CORPUS:
        artifact_path = PROJECT_ROOT / case.relative_path
        artifact, artifact_sha, size_bytes = load_verified_artifact(
            artifact_path, case.expected_sha256
        )
        started_ns = time.perf_counter_ns()
        decision, constraint_results = evaluate_constraints(artifact, case.constraints)
        latency_ns = time.perf_counter_ns() - started_ns
        decisions.append(
            {
                "case_id": case.case_id,
                "artifact": {
                    "path": str(artifact_path.resolve()),
                    "sha256": artifact_sha,
                    "size_bytes": size_bytes,
                },
                "decision": decision,
                "constraint_results": constraint_results,
                "decision_latency_ns": latency_ns,
            }
        )

    scored_decisions = []
    for row in decisions:
        expected_label = EXPECTED_LABELS[row["case_id"]]
        scored_decisions.append(
            {
                **row,
                "expected_label": expected_label,
                "correct": row["decision"] == expected_label,
            }
        )
    metrics = score_predictions(scored_decisions)
    latencies = [row["decision_latency_ns"] for row in decisions]
    return {
        "schema_version": "flightguard-frozen-claim-auditor-benchmark-v1",
        "status": "PASS" if metrics["false_positive"] == 0 and metrics["false_negative"] == 0 else "FAIL",
        "scope": {
            "name": "frozen 4-case synthetic corpus",
            "case_count": len(decisions),
            "simulation_only": True,
            "robot_capability_claim": False,
            "safety_claim": False,
            "general_accuracy_claim": False,
        },
        "source": {"path": str(source_path), "sha256": source_sha},
        "cases": scored_decisions,
        "confusion": metrics,
        "decision_latency_ns": {
            "samples": latencies,
            "mean": statistics.fmean(latencies),
            "median": statistics.median(latencies),
            "maximum": max(latencies),
        },
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def cli(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = run_benchmark(expected_source_sha256=args.expected_source_sha256)
        write_exclusive(args.output, payload)
    except (FrozenClaimError, OSError, TypeError, ValueError) as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "output": str(args.output.expanduser().resolve()),
                "status": payload["status"],
                "source_sha256": payload["source"]["sha256"],
                "false_accept_count": payload["confusion"]["false_accept_count"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
