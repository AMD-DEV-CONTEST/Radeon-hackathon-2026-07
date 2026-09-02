#!/usr/bin/env python3
"""Training corpus maturity dashboard.

This report intentionally counts `active_training_eligible` rows separately
from eval evidence. It is the guardrail for corpus compounding: a large signed
corpus is not enough; the training split needs balanced, verifier-backed,
schema-complete rows.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


DEFAULT_TARGETS = {
    "python": 100,
    "rust": 100,
    "go": 100,
    "typescript": 50,
    "c": 50,
    "cpp": 50,
    "java": 50,
    "sql": 50,
}


@dataclass
class TrainingDashboard:
    roots: list[str]
    total_rows: int = 0
    active_training_eligible: int = 0
    active_eval_evidence: int = 0
    ineligible_or_unknown: int = 0
    unsigned_training_rows: int = 0
    verifier_missing_training_rows: int = 0
    license_missing_training_rows: int = 0
    duplicate_training_trace_hashes: int = 0
    by_language: dict[str, int] = field(default_factory=dict)
    by_failure_class: dict[str, int] = field(default_factory=dict)
    by_source_kind: dict[str, int] = field(default_factory=dict)
    by_benchmark: dict[str, int] = field(default_factory=dict)
    by_license: dict[str, int] = field(default_factory=dict)
    by_verifier: dict[str, int] = field(default_factory=dict)
    by_repair_outcome: dict[str, int] = field(default_factory=dict)
    by_record_status: dict[str, int] = field(default_factory=dict)
    target_progress: dict[str, dict[str, Any]] = field(default_factory=dict)
    maturity_failures: list[str] = field(default_factory=list)
    parse_error_count: int = 0
    parse_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def generate_dashboard(
    roots: Iterable[Path],
    *,
    targets: dict[str, int] | None = None,
    max_parse_errors: int = 50,
) -> TrainingDashboard:
    root_list = [Path(r) for r in roots]
    dashboard = TrainingDashboard(roots=[str(r) for r in root_list])
    counters = {
        "language": Counter(),
        "failure_class": Counter(),
        "source_kind": Counter(),
        "benchmark": Counter(),
        "license": Counter(),
        "verifier": Counter(),
        "repair_outcome": Counter(),
        "record_status": Counter(),
    }
    training_hashes: set[str] = set()

    for path in _iter_jsonl(root_list):
        for line_no, record in _read_jsonl(path, dashboard, max_parse_errors=max_parse_errors):
            dashboard.total_rows += 1
            status = str(_field(record, "record_status") or "unknown")
            counters["record_status"][status] += 1
            if status == "active_eval_evidence":
                dashboard.active_eval_evidence += 1
            if status != "active_training_eligible" or record.get("training_eligible") is not True:
                dashboard.ineligible_or_unknown += 1
                continue

            dashboard.active_training_eligible += 1
            _count_training_record(counters, record)
            if not record.get("_sig"):
                dashboard.unsigned_training_rows += 1
            if not _field(record, "verifier_command", "validator", "validation_commands"):
                dashboard.verifier_missing_training_rows += 1
            if not _field(record, "license_provenance", "license_bucket"):
                dashboard.license_missing_training_rows += 1
            trace_hash = str(_field(record, "trace_hash"))
            if trace_hash:
                if trace_hash in training_hashes:
                    dashboard.duplicate_training_trace_hashes += 1
                training_hashes.add(trace_hash)

    dashboard.by_language = dict(counters["language"])
    dashboard.by_failure_class = dict(counters["failure_class"])
    dashboard.by_source_kind = dict(counters["source_kind"])
    dashboard.by_benchmark = dict(counters["benchmark"])
    dashboard.by_license = dict(counters["license"])
    dashboard.by_verifier = dict(counters["verifier"])
    dashboard.by_repair_outcome = dict(counters["repair_outcome"])
    dashboard.by_record_status = dict(counters["record_status"])
    dashboard.target_progress = _target_progress(dashboard.by_language, targets or DEFAULT_TARGETS)
    dashboard.maturity_failures = _maturity_failures(dashboard)
    return dashboard


def _count_training_record(counters: dict[str, Counter], record: dict[str, Any]) -> None:
    _inc(counters["language"], _field(record, "language", "lang", "environment_type"))
    _inc(counters["failure_class"], _field(record, "failure_class", "failure_type"))
    _inc(counters["source_kind"], _field(record, "source_kind"))
    _inc(counters["benchmark"], _field(record, "source_benchmark", "benchmark"))
    _inc(counters["license"], _field(record, "license_provenance", "license_bucket"))
    _inc(
        counters["verifier"],
        _normalise(_field(record, "verifier_command", "validator", "validation_commands")),
    )
    _inc(counters["repair_outcome"], _field(record, "repair_outcome", "verdict"))


def _target_progress(counts: dict[str, int], targets: dict[str, int]) -> dict[str, dict[str, Any]]:
    progress: dict[str, dict[str, Any]] = {}
    for language, target in targets.items():
        count = int(counts.get(language, 0))
        progress[language] = {
            "count": count,
            "target": target,
            "remaining": max(0, target - count),
            "met": count >= target,
        }
    return progress


def _maturity_failures(dashboard: TrainingDashboard) -> list[str]:
    failures: list[str] = []
    if dashboard.unsigned_training_rows:
        failures.append(f"unsigned_training_rows:{dashboard.unsigned_training_rows}")
    if dashboard.verifier_missing_training_rows:
        failures.append(
            f"verifier_missing_training_rows:{dashboard.verifier_missing_training_rows}"
        )
    if dashboard.license_missing_training_rows:
        failures.append(f"license_missing_training_rows:{dashboard.license_missing_training_rows}")
    if dashboard.duplicate_training_trace_hashes:
        failures.append(
            f"duplicate_training_trace_hashes:{dashboard.duplicate_training_trace_hashes}"
        )
    return failures


def _iter_jsonl(roots: Iterable[Path]):
    for root in roots:
        if root.is_file() and root.suffix == ".jsonl":
            yield root
        elif root.is_dir():
            yield from sorted(root.rglob("*.jsonl"))


def _read_jsonl(path: Path, dashboard: TrainingDashboard, *, max_parse_errors: int):
    try:
        fh = path.open("r", encoding="utf-8", errors="replace")
    except OSError as exc:
        _parse_error(dashboard, f"{path}:0:{exc}", max_parse_errors)
        return
    with fh:
        for i, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                _parse_error(dashboard, f"{path}:{i}:{exc}", max_parse_errors)
                continue
            if isinstance(row, dict):
                yield i, row
            else:
                _parse_error(dashboard, f"{path}:{i}:not_object", max_parse_errors)


def _parse_error(dashboard: TrainingDashboard, message: str, max_parse_errors: int) -> None:
    dashboard.parse_error_count += 1
    if len(dashboard.parse_errors) < max_parse_errors:
        dashboard.parse_errors.append(message)


def _field(record: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = record.get(name)
        if value not in (None, "", []):
            return value
    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        for name in names:
            value = metadata.get(name)
            if value not in (None, "", []):
                return value
    return ""


def _inc(counter: Counter, value: Any) -> None:
    counter[str(value or "unknown")] += 1


def _normalise(value: Any) -> str:
    if isinstance(value, list):
        return " | ".join(str(v) for v in value)
    return str(value or "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("roots", nargs="+", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()

    dashboard = generate_dashboard(args.roots)
    payload = dashboard.to_dict()
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    if args.json or not args.output:
        print(text)
    return 1 if dashboard.maturity_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
