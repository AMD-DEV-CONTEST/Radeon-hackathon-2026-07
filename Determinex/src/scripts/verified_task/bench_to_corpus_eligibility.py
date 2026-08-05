"""Benchmark trace schema and training eligibility gate.

New benchmark rows may become training fuel only when they are schema-complete
at write time. Older migrated rows can stay `active_eval_evidence`; new rows
must not recreate another cleanup backlog.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from corpus.corpus_manager import hmac_key_scope, verify_signature

TRACE_HASH_SCHEMA_VERSION = "canonical-v2"
TRAINING_ELIGIBLE_STATUS = "active_training_eligible"
INELIGIBLE_STATUS = "legacy_backfill_needed"

REQUIRED_TRAINING_FIELDS = (
    "schema_version",
    "record_status",
    "corpus_type",
    "source_kind",
    "verifier_command",
    "verifier_result",
    "failure_class",
    "failure_type",
    "repair_outcome",
    "trace_hash_schema_version",
    "trace_hash",
    "signature_key_scope",
)


def complete_benchmark_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a schema-complete benchmark payload for CorpusManager signing."""
    row = dict(payload)
    now = datetime.now(UTC).isoformat()
    _fill(row, "created_at", now)
    _fill(row, "schema_version", "determinex-agent-trace-v1")
    _fill(row, "corpus_type", "code_verdict")
    _fill(
        row,
        "source_kind",
        row.get("trace_kind") or row.get("source_benchmark") or "benchmark_attempt",
    )
    _fill(
        row,
        "verifier_command",
        row.get("validator") or row.get("verifier") or row.get("validation_commands"),
    )
    _fill(row, "verifier_result", row.get("verdict") or row.get("repair_outcome"))
    _fill(row, "failure_class", row.get("failure_type") or row.get("failure_class") or "none")
    _fill(row, "failure_type", row.get("failure_class") or row.get("failure_type") or "none")
    _fill(row, "repair_outcome", row.get("verdict") or "unknown")
    _fill(row, "signature_key_scope", hmac_key_scope())
    _fill(row, "trace_hash_schema_version", TRACE_HASH_SCHEMA_VERSION)
    row["trace_hash"] = canonical_trace_hash(row)
    _fill(row, "record_status", TRAINING_ELIGIBLE_STATUS)

    missing = missing_training_fields(row)
    if missing:
        row["record_status"] = INELIGIBLE_STATUS
        row["training_eligible"] = False
        row["training_exclusion_reason"] = "missing_" + ",".join(missing)
    else:
        row["record_status"] = TRAINING_ELIGIBLE_STATUS
        row["training_eligible"] = True
    return row


def _fill(row: dict[str, Any], key: str, value: Any) -> None:
    if not _present_required(row.get(key)):
        row[key] = value


def canonical_trace_hash(row: dict[str, Any]) -> str:
    excluded = {
        "_sig",
        "trace_hash",
        "record_status",
        "training_eligible",
        "training_exclusion_reason",
    }
    stable = {k: v for k, v in row.items() if k not in excluded}
    payload = json.dumps(stable, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()


def missing_training_fields(row: dict[str, Any]) -> list[str]:
    missing = [field for field in REQUIRED_TRAINING_FIELDS if not _present_required(row.get(field))]
    if not (_present_known(row.get("language")) or _present_known(row.get("environment_type"))):
        missing.append("language_or_environment_type")
    if not (
        _present_known(row.get("license_provenance")) or _present_known(row.get("license_bucket"))
    ):
        missing.append("license_provenance")
    if not (_present_known(row.get("source_benchmark")) or _present_known(row.get("benchmark"))):
        missing.append("source_benchmark")
    return sorted(set(missing))


def _present_required(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and value.strip().lower() not in {"unknown", "null"}
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _present_known(value: Any) -> bool:
    if not _present_required(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() != "none"
    return True


def signed_training_eligible(record: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate a signed corpus row for benchmark training eligibility."""
    reasons: list[str] = []
    if not verify_signature(record):
        reasons.append("invalid_or_missing_signature")
    missing = missing_training_fields(record)
    if missing:
        reasons.extend(f"missing_{field}" for field in missing)
    if record.get("record_status") != TRAINING_ELIGIBLE_STATUS:
        reasons.append(f"record_status:{record.get('record_status') or 'missing'}")
    if record.get("training_eligible") is not True:
        reasons.append("training_eligible_not_true")
    return not reasons, reasons
