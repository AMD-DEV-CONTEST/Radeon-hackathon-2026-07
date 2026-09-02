#!/usr/bin/env python3
"""Corpus coverage and hygiene report.

This is the bench-campaign guardrail: benchmark runs are useful only when they
leave signed, provenance-rich traces. The report is intentionally structural;
full HMAC verification can be enabled by callers that have the same key used to
write the records.
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

from corpus.corpus_manager import hmac_key_scope, verify_signature

DEFAULT_ROOTS = [
    Path("T:/determinex_corpus"),
    Path("corpus/programbench/training_corpus"),
]


def _training_excluded(root: Path) -> bool:
    """A root whose TRAINING_EXCLUSION.json marks it training_eligible=false is LEGACY: its rows
    are unsigned/untagged by declaration. Counting them in the coverage dashboard buries the
    ACTIVE corpus's real coverage under ~600K 'unknown's (the 2026-07-18 audit finding: every
    dimension read 100% unknown because only legacy rows were being scanned)."""
    marker = root / "TRAINING_EXCLUSION.json"
    if not marker.exists():
        return False
    try:
        return json.loads(marker.read_text(encoding="utf-8")).get("training_eligible") is False
    except (OSError, json.JSONDecodeError):
        return False


@dataclass
class CoverageReport:
    roots: list[str]
    excluded_legacy_roots: list[str] = field(default_factory=list)
    total_rows: int = 0
    unsigned_count: int = 0
    invalid_signature_count: int = 0
    missing_language_count: int = 0
    missing_failure_type_count: int = 0
    missing_provenance_count: int = 0
    missing_verifier_count: int = 0
    duplicate_trace_hash_count: int = 0
    unsafe_rejected_count: int = 0
    ephemeral_signature_count: int = 0
    current_signature_key_scope: str = "unknown"
    by_language: dict[str, int] = field(default_factory=dict)
    by_framework: dict[str, int] = field(default_factory=dict)
    by_build_system: dict[str, int] = field(default_factory=dict)
    by_failure_type: dict[str, int] = field(default_factory=dict)
    by_validator: dict[str, int] = field(default_factory=dict)
    by_source_kind: dict[str, int] = field(default_factory=dict)
    by_license_bucket: dict[str, int] = field(default_factory=dict)
    by_benchmark: dict[str, int] = field(default_factory=dict)
    by_repair_outcome: dict[str, int] = field(default_factory=dict)
    by_safety_outcome: dict[str, int] = field(default_factory=dict)
    by_model_router: dict[str, int] = field(default_factory=dict)
    by_signature_key_scope: dict[str, int] = field(default_factory=dict)
    corpus_type_counts: dict[str, int] = field(default_factory=dict)
    files_scanned: list[str] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    parse_error_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CoverageThresholds:
    min_total_rows: int = 1
    min_signed_rows: int = 1
    required_languages: list[str] = field(default_factory=list)
    require_no_unsigned: bool = True
    require_no_duplicate_trace_hashes: bool = True
    require_language_labels: bool = True
    require_failure_types: bool = True
    require_provenance: bool = True
    require_verifier: bool = True
    require_durable_signature_key: bool = False
    require_no_ephemeral_signatures: bool = False


def check_minimum_gate(report: CoverageReport, thresholds: CoverageThresholds) -> list[str]:
    """Return gate failure reasons. Empty means the coverage gate passes."""
    failures: list[str] = []
    signed_rows = report.total_rows - report.unsigned_count
    if report.total_rows < thresholds.min_total_rows:
        failures.append(f"total_rows_below_floor:{report.total_rows}<{thresholds.min_total_rows}")
    if signed_rows < thresholds.min_signed_rows:
        failures.append(f"signed_rows_below_floor:{signed_rows}<{thresholds.min_signed_rows}")
    if thresholds.require_no_unsigned and report.unsigned_count:
        failures.append(f"unsigned_rows_present:{report.unsigned_count}")
    if thresholds.require_no_duplicate_trace_hashes and report.duplicate_trace_hash_count:
        failures.append(f"duplicate_trace_hashes:{report.duplicate_trace_hash_count}")
    if thresholds.require_language_labels and report.missing_language_count:
        failures.append(f"missing_language:{report.missing_language_count}")
    if thresholds.require_failure_types and report.missing_failure_type_count:
        failures.append(f"missing_failure_type:{report.missing_failure_type_count}")
    if thresholds.require_provenance and report.missing_provenance_count:
        failures.append(f"missing_provenance:{report.missing_provenance_count}")
    if thresholds.require_verifier and report.missing_verifier_count:
        failures.append(f"missing_verifier:{report.missing_verifier_count}")
    if thresholds.require_durable_signature_key and report.current_signature_key_scope != "durable":
        failures.append(f"durable_hmac_key_missing:{report.current_signature_key_scope}")
    if thresholds.require_no_ephemeral_signatures and report.ephemeral_signature_count:
        failures.append(f"ephemeral_signatures_present:{report.ephemeral_signature_count}")
    for language in thresholds.required_languages:
        if report.by_language.get(language, 0) <= 0:
            failures.append(f"missing_required_language:{language}")
    return failures


def generate_report(
    roots: Iterable[Path],
    *,
    verify_signatures: bool = False,
    max_parse_errors: int = 50,
) -> CoverageReport:
    root_list = []
    excluded_roots = []
    for r in roots:
        (excluded_roots if _training_excluded(Path(r)) else root_list).append(Path(r))
    report = CoverageReport(roots=[str(r) for r in root_list])
    report.excluded_legacy_roots = [str(r) for r in excluded_roots]
    report.current_signature_key_scope = hmac_key_scope()
    counters = {
        "language": Counter(),
        "framework": Counter(),
        "build_system": Counter(),
        "failure_type": Counter(),
        "validator": Counter(),
        "source_kind": Counter(),
        "license_bucket": Counter(),
        "benchmark": Counter(),
        "repair_outcome": Counter(),
        "safety_outcome": Counter(),
        "model_router": Counter(),
        "corpus_type": Counter(),
        "signature_key_scope": Counter(),
    }
    trace_hashes: set[str] = set()

    for path in _iter_jsonl_files(root_list):
        report.files_scanned.append(str(path))
        for line_no, record in _read_jsonl(path, report, max_parse_errors=max_parse_errors):
            report.total_rows += 1
            _count_record(report, counters, record)

            sig = record.get("_sig")
            if not sig:
                report.unsigned_count += 1
            elif verify_signatures and not verify_signature(record):
                report.invalid_signature_count += 1
            if _field(record, "signature_key_scope") == "ephemeral":
                report.ephemeral_signature_count += 1

            if not _field(record, "language", "lang"):
                report.missing_language_count += 1
            if not _field(record, "failure_type", "failure_class", "test_result", "compile_result"):
                report.missing_failure_type_count += 1
            if not _field(record, "source_benchmark", "benchmark", "source_kind"):
                report.missing_provenance_count += 1
            if not _field(
                record,
                "validator",
                "verifier",
                "verifier_command",
                "validation_commands",
                "final_command",
            ):
                report.missing_verifier_count += 1
            if _field(record, "safety_gate", "supply_chain_gate") == "reject":
                report.unsafe_rejected_count += 1

            trace_hash = _trace_hash(record, path, line_no)
            if trace_hash in trace_hashes:
                report.duplicate_trace_hash_count += 1
            trace_hashes.add(trace_hash)

    report.by_language = dict(counters["language"])
    report.by_framework = dict(counters["framework"])
    report.by_build_system = dict(counters["build_system"])
    report.by_failure_type = dict(counters["failure_type"])
    report.by_validator = dict(counters["validator"])
    report.by_source_kind = dict(counters["source_kind"])
    report.by_license_bucket = dict(counters["license_bucket"])
    report.by_benchmark = dict(counters["benchmark"])
    report.by_repair_outcome = dict(counters["repair_outcome"])
    report.by_safety_outcome = dict(counters["safety_outcome"])
    report.by_model_router = dict(counters["model_router"])
    report.corpus_type_counts = dict(counters["corpus_type"])
    report.by_signature_key_scope = dict(counters["signature_key_scope"])
    return report


def _iter_jsonl_files(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        if root.is_file() and root.suffix == ".jsonl":
            yield root
        elif root.is_dir():
            # A SUBDIR carrying training_eligible=false (e.g. programbench_legacy_offload/) is
            # legacy by declaration -- its untagged rows would bury the active corpus's coverage.
            excluded_dirs = [
                m.parent
                for m in root.rglob("TRAINING_EXCLUSION.json")
                if _training_excluded(m.parent)
            ]
            for f in sorted(root.rglob("*.jsonl")):
                if any(d in f.parents for d in excluded_dirs):
                    continue
                yield f


def _record_parse_error(report: CoverageReport, message: str, max_parse_errors: int) -> None:
    report.parse_error_count += 1
    if len(report.parse_errors) < max_parse_errors:
        report.parse_errors.append(message)


def _read_jsonl(
    path: Path, report: CoverageReport, *, max_parse_errors: int
) -> Iterable[tuple[int, dict[str, Any]]]:
    try:
        fh = path.open("r", encoding="utf-8", errors="replace")
    except OSError as exc:
        _record_parse_error(report, f"{path}:0:{exc}", max_parse_errors)
        return
    with fh:
        for i, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                _record_parse_error(report, f"{path}:{i}:{exc}", max_parse_errors)
                continue
            if isinstance(payload, dict):
                yield i, payload
            else:
                _record_parse_error(report, f"{path}:{i}:not_object", max_parse_errors)


def _count_record(
    report: CoverageReport, counters: dict[str, Counter], record: dict[str, Any]
) -> None:
    _inc(counters["language"], _field(record, "language", "lang"))
    _inc(counters["framework"], _field(record, "framework"))
    _inc(counters["build_system"], _field(record, "build_system"))
    _inc(
        counters["failure_type"],
        _field(record, "failure_type", "failure_class", "test_result", "compile_result"),
    )
    _inc(
        counters["validator"],
        _normalise_validator(
            _field(
                record,
                "validator",
                "verifier",
                "verifier_command",
                "final_command",
                "validation_commands",
            )
        ),
    )
    _inc(counters["source_kind"], _field(record, "source_kind", "source_benchmark"))
    _inc(counters["license_bucket"], _field(record, "license_bucket", "license_gate"))
    _inc(counters["benchmark"], _field(record, "source_benchmark", "benchmark"))
    _inc(counters["repair_outcome"], _field(record, "repair_outcome", "verdict", "final_verdict"))
    _inc(
        counters["safety_outcome"],
        _field(record, "safety_gate", "supply_chain_gate", "safety_verdict"),
    )
    _inc(counters["model_router"], _field(record, "model_router", "router_used", "model"))
    _inc(counters["corpus_type"], _field(record, "corpus_type"))
    _inc(counters["signature_key_scope"], _field(record, "signature_key_scope"))


def _inc(counter: Counter, value: Any) -> None:
    if value is None or value == "":
        counter["unknown"] += 1
    else:
        counter[str(value)] += 1


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


def _normalise_validator(value: Any) -> str:
    if isinstance(value, list):
        return " | ".join(str(v) for v in value)
    return str(value or "")


def _trace_hash(record: dict[str, Any], path: Path, line_no: int) -> str:
    for key in ("trace_hash", "row_hash", "repair_patch_hash"):
        value = _field(record, key)
        if value:
            return str(value)
    return "|".join(
        [
            str(_field(record, "task_id")),
            str(_field(record, "input_hash")),
            str(_field(record, "output_hash")),
            str(_field(record, "mutation_type", "failure_type", "failure_class")),
            str(path),
            str(line_no),
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="*", type=Path, default=DEFAULT_ROOTS)
    parser.add_argument("--verify-signatures", action="store_true")
    parser.add_argument("--strict-parse", action="store_true")
    parser.add_argument("--max-parse-errors", type=int, default=50)
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    parser.add_argument("--output", type=Path, help="Write JSON report to this path")
    args = parser.parse_args()

    report = generate_report(
        args.roots,
        verify_signatures=args.verify_signatures,
        max_parse_errors=args.max_parse_errors,
    )
    payload = report.to_dict()
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    if args.json or not args.output:
        print(text)
    return 2 if args.strict_parse and report.parse_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
