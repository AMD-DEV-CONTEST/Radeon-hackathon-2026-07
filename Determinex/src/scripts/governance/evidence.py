"""
governance.evidence -- evidence spine + proof records
=====================================================
The reconciled count of trustworthy evidence behind a claim, and the proof-record
writer. Consolidated (2026-06-14) from scripts/status/_shared_evidence_spine.py
and scripts/proof/proof_record.py. proof-record writing is a thin passthrough to
the existing platform-record schema (corpus.programbench.programbench_platform_record),
imported lazily so this module has no hard dependency.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def current_evidence_spine_count(
    *,
    index: dict[str, Any],
    ledger: dict[str, Any] | None,
    count_guard: dict[str, Any] | None,
    lock_id: str,
    pre_lock_count: int,
    final_count: int,
    successor_counts: dict[str, int] | None = None,
) -> int:
    """Return the current reconciled evidence spine count when it is trustworthy."""
    live_index = int(index.get("entry_count") or len(index.get("entries", [])))
    validation_errors = index.get("validation_errors") or []
    ledger_count = int((ledger or {}).get("ledger_entry_count") or 0)
    count_actual = int((count_guard or {}).get("actual_evidence_count") or 0)
    count_expected = int((count_guard or {}).get("expected_evidence_count") or 0)
    if (
        not validation_errors
        and live_index > 0
        and ledger_count == live_index
        and count_actual == live_index
        and count_expected == live_index
    ):
        return live_index
    indexed = {entry.get("evidence_id") for entry in index.get("entries", [])}
    base = final_count if lock_id in indexed else pre_lock_count
    successors = successor_counts or {}
    return max([base] + [n for lock, n in successors.items() if lock in indexed])


def make_proof_record(
    *, record_type: str, schema_version: str, status: str, payload: dict[str, Any]
) -> dict[str, Any]:
    from corpus.programbench.programbench_platform_record import make_platform_record

    return make_platform_record(
        record_type=record_type, schema_version=schema_version, status=status, payload=payload
    )


def write_proof_record(record: dict[str, Any], output_dir: Path) -> Path:
    from corpus.programbench.programbench_platform_record import write_platform_record

    return write_platform_record(record, output_dir, name_key="record_id")


def verify_proof_record(record: dict[str, Any]) -> bool:
    from corpus.programbench.programbench_platform_record import verify_platform_record

    return verify_platform_record(record)
