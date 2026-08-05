#!/usr/bin/env python3
"""Corpus schema maturity classifier and backfill migration.

Integrity answers "is the row signed and unchanged?"
Maturity answers "is the row schema-complete enough for training?"

This tool never upgrades legacy rows directly to training eligibility. Legacy
ProgramBench verdict rows can be backfilled into `active_eval_evidence`, while
rows that still lack required fields remain `legacy_backfill_needed` or
`quarantined`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.corpus_manager import hmac_key_scope, resign_record, verify_signature

REQUIRED_ACTIVE_FIELDS = (
    "schema_version",
    "corpus_type",
    "source_kind",
    "trace_hash",
    "signature_key_scope",
    "record_status",
    "created_at",
)

CODE_REQUIRED_FIELDS = (
    "language",
    "verifier_command",
    "verifier_result",
    "failure_type",
)

ACTIVE_STATUSES = {
    "active_training_eligible",
    "active_eval_evidence",
    "legacy_backfill_needed",
    "quarantined",
    "rejected",
}


@dataclass
class MaturityReport:
    roots: list[str]
    total_rows: int = 0
    active_training_eligible: int = 0
    active_eval_evidence: int = 0
    legacy_backfill_needed: int = 0
    quarantined: int = 0
    rejected: int = 0
    training_ineligible: int = 0
    missing_required_field_count: int = 0
    invalid_signature_count: int = 0
    unsigned_count: int = 0
    parse_error_count: int = 0
    by_record_status: dict[str, int] = field(default_factory=dict)
    by_backfill_reason: dict[str, int] = field(default_factory=dict)
    by_training_eligible: dict[str, int] = field(default_factory=dict)
    files_scanned: list[str] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_record(record: dict[str, Any]) -> tuple[str, list[str]]:
    missing = missing_required_fields(record)
    if not record.get("_sig"):
        return "quarantined", ["unsigned"]
    status = str(record.get("record_status") or "")
    if status in ACTIVE_STATUSES and not missing:
        return status, []
    if missing:
        return "legacy_backfill_needed", [f"missing_{name}" for name in missing]
    return "legacy_backfill_needed", ["missing_record_status"]


def missing_required_fields(record: dict[str, Any]) -> list[str]:
    missing = [name for name in REQUIRED_ACTIVE_FIELDS if not record.get(name)]
    if record.get("corpus_type") == "code_verdict":
        missing.extend(name for name in CODE_REQUIRED_FIELDS if not record.get(name))
    if not (record.get("language") or record.get("environment_type")):
        if "language" not in missing:
            missing.append("language")
    return sorted(set(missing))


def mature_record(record: dict[str, Any], *, migrated_at: str) -> dict[str, Any]:
    row = dict(record)
    row.setdefault("schema_version", "determinex-agent-trace-v1")
    row.setdefault("corpus_type", "code_verdict")
    row.setdefault("signature_key_scope", hmac_key_scope())
    if not row.get("created_at"):
        row["created_at"] = row.get("timestamp") or migrated_at

    if not row.get("language") and row.get("lang"):
        row["language"] = row["lang"]

    if not row.get("source_kind") and row.get("source_benchmark") == "programbench":
        row["source_kind"] = "programbench_legacy_verdict"

    if not row.get("verifier_command"):
        row["verifier_command"] = (
            row.get("validator") or row.get("final_command") or _infer_verifier(row)
        )
    if not row.get("validator") and row.get("verifier_command"):
        row["validator"] = row["verifier_command"]

    if not row.get("verifier_result"):
        verdict = row.get("test_result") or row.get("compile_result") or row.get("repair_outcome")
        if verdict in ("pass", "fail", "reject"):
            row["verifier_result"] = verdict

    if not row.get("failure_type"):
        result = row.get("verifier_result") or row.get("test_result") or row.get("compile_result")
        row["failure_type"] = "none" if result == "pass" else "programbench_failure"

    if not row.get("trace_hash") or row.get("trace_hash_schema_version") != "canonical-v2":
        row["trace_hash"] = _make_trace_hash(row)
        row["trace_hash_schema_version"] = "canonical-v2"

    status, reasons = classify_record(row)
    if status == "legacy_backfill_needed" and not missing_required_fields(row):
        status = "active_eval_evidence"
        reasons = ["legacy_programbench_verdict_backfilled"]
    row["record_status"] = row.get("record_status") or status
    if row["record_status"] == "legacy_backfill_needed" and not missing_required_fields(row):
        row["record_status"] = "active_eval_evidence"
        reasons = ["legacy_programbench_verdict_backfilled"]

    if row["record_status"] == "active_training_eligible":
        row["training_eligible"] = True
    else:
        row["training_eligible"] = False
    if row["record_status"] != "active_training_eligible":
        row.setdefault("training_exclusion_reason", row["record_status"])

    row["migrated_at"] = row.get("migrated_at") or migrated_at
    if reasons:
        row["backfill_reason"] = row.get("backfill_reason") or ",".join(reasons)
    return resign_record(row)


def generate_maturity_report(
    roots: list[Path], *, verify_signatures: bool = False, max_parse_errors: int = 50
) -> MaturityReport:
    report = MaturityReport(roots=[str(r) for r in roots])
    status_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    eligible_counts: Counter[str] = Counter()
    for path in _iter_jsonl(roots):
        report.files_scanned.append(str(path))
        for record in _read_jsonl(path, report, max_parse_errors=max_parse_errors):
            report.total_rows += 1
            if not record.get("_sig"):
                report.unsigned_count += 1
            elif verify_signatures and not verify_signature(record):
                report.invalid_signature_count += 1
            status, reasons = classify_record(record)
            status_counts[status] += 1
            if bool(record.get("training_eligible")):
                eligible_counts["true"] += 1
            else:
                eligible_counts["false"] += 1
            missing = missing_required_fields(record)
            if missing:
                report.missing_required_field_count += 1
            for reason in reasons or ["none"]:
                reason_counts[reason] += 1

    report.by_record_status = dict(status_counts)
    report.by_backfill_reason = dict(reason_counts)
    report.by_training_eligible = dict(eligible_counts)
    report.active_training_eligible = status_counts["active_training_eligible"]
    report.active_eval_evidence = status_counts["active_eval_evidence"]
    report.legacy_backfill_needed = status_counts["legacy_backfill_needed"]
    report.quarantined = status_counts["quarantined"]
    report.rejected = status_counts["rejected"]
    report.training_ineligible = eligible_counts["false"]
    return report


def backfill_file(path: Path, *, dry_run: bool = False) -> dict[str, Any]:
    migrated_at = datetime.now(UTC).isoformat()
    rows = list(_read_jsonl(path, MaturityReport(roots=[str(path)]), max_parse_errors=0))
    matured = [mature_record(row, migrated_at=migrated_at) for row in rows]
    changed = sum(1 for before, after in zip(rows, matured) if before != after)
    backup = path.with_suffix(path.suffix + ".pre_schema_maturity.bak")
    if not dry_run and changed:
        if not backup.exists():
            shutil.copy2(path, backup)
        tmp = path.with_suffix(path.suffix + ".schema.tmp")
        tmp.write_text(
            "".join(json.dumps(row, ensure_ascii=True) + "\n" for row in matured),
            encoding="utf-8",
        )
        tmp.replace(path)
    return {
        "path": str(path),
        "records": len(rows),
        "changed": changed,
        "backup": str(backup),
        "dry_run": dry_run,
    }


def _infer_verifier(row: dict[str, Any]) -> str:
    if row.get("source_benchmark") == "programbench" or str(row.get("task_id", "")).startswith(
        "pb_"
    ):
        return "programbench eval"
    return "unknown"


def _make_trace_hash(row: dict[str, Any]) -> str:
    excluded = {
        "_sig",
        "signature_key_scope",
        "record_status",
        "training_eligible",
        "training_exclusion_reason",
        "migrated_at",
        "backfill_reason",
        "trace_hash",
        "trace_hash_schema_version",
    }
    stable = {k: v for k, v in row.items() if k not in excluded}
    payload = json.dumps(stable, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()


def _iter_jsonl(roots: list[Path]):
    for root in roots:
        if root.is_file() and root.suffix == ".jsonl":
            yield root
        elif root.is_dir():
            yield from sorted(root.rglob("*.jsonl"))


def _read_jsonl(path: Path, report: MaturityReport, *, max_parse_errors: int):
    try:
        fh = path.open("r", encoding="utf-8", errors="replace")
    except OSError as exc:
        report.parse_error_count += 1
        if len(report.parse_errors) < max_parse_errors:
            report.parse_errors.append(f"{path}:0:{exc}")
        return
    with fh:
        for i, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                report.parse_error_count += 1
                if len(report.parse_errors) < max_parse_errors:
                    report.parse_errors.append(f"{path}:{i}:{exc}")
                continue
            if isinstance(payload, dict):
                yield payload
            else:
                report.parse_error_count += 1
                if len(report.parse_errors) < max_parse_errors:
                    report.parse_errors.append(f"{path}:{i}:not_object")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("roots", nargs="+", type=Path)
    ap.add_argument("--verify-signatures", action="store_true")
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-parse-errors", type=int, default=50)
    args = ap.parse_args()

    if args.backfill:
        results = [
            backfill_file(path, dry_run=args.dry_run)
            for root in args.roots
            for path in _iter_jsonl([root])
        ]
        print(json.dumps({"backfill": results}, indent=2))

    report = generate_maturity_report(
        args.roots,
        verify_signatures=args.verify_signatures,
        max_parse_errors=args.max_parse_errors,
    )
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
