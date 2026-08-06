from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


SCHEMA = "ProofLaunchGTM100TodoExecutionLedgerV2"
ALLOWED_STATUSES = {"verified", "partial", "human_gate", "unverified"}
_TODO_PATTERN = re.compile(r"^T(?P<number>\d{3})\s+(?P<requirement>.+?)\s*$")


class GTM100TodoExecutionLedgerError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def parse_todo_spec(text: str) -> list[dict[str, str]]:
    rows = []
    for line in text.splitlines():
        match = _TODO_PATTERN.match(line.strip())
        if match:
            rows.append({"todo_id": f"T{match.group('number')}", "requirement": match.group("requirement")})
    expected = [f"T{value:03d}" for value in range(1, 101)]
    observed = [row["todo_id"] for row in rows]
    if observed != expected:
        raise GTM100TodoExecutionLedgerError("TODO source must contain the exact T001–T100 sequence")
    return rows


def compile_todo_execution_ledger(
    spec_text: str,
    evidence_map: Mapping[str, Mapping[str, Any]],
    *,
    project_root: Path,
) -> dict[str, Any]:
    todos = parse_todo_spec(spec_text)
    rows: list[dict[str, Any]] = []
    for todo in todos:
        todo_id = todo["todo_id"]
        evidence = dict(evidence_map.get(todo_id, {}))
        status = str(evidence.get("status") or "unverified")
        if status not in ALLOWED_STATUSES:
            raise GTM100TodoExecutionLedgerError(f"{todo_id} has invalid status: {status}")
        pointers = []
        for raw_path in evidence.get("evidence_paths", []):
            relative = str(raw_path)
            path = project_root / relative
            if not path.is_file():
                raise GTM100TodoExecutionLedgerError(f"{todo_id} evidence path does not exist: {relative}")
            pointers.append({
                "path": relative,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "byte_count": path.stat().st_size,
            })
        test_ids = sorted({str(value) for value in evidence.get("test_ids", []) if str(value).strip()})
        if status == "verified" and (not pointers or not test_ids):
            raise GTM100TodoExecutionLedgerError(f"{todo_id} cannot be verified without evidence paths and tests")
        rows.append({
            **todo,
            "status": status,
            "evidence_pointers": pointers,
            "test_ids": test_ids,
            "current_finding": str(evidence.get("current_finding") or "No requirement-scoped completion evidence has been audited."),
            "next_action": str(evidence.get("next_action") or "Audit existing implementation or build the missing requirement-scoped capability and tests."),
            "completion_credit": 1 if status == "verified" else 0,
        })

    status_counts = {status: sum(row["status"] == status for row in rows) for status in sorted(ALLOWED_STATUSES)}
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "source_spec_sha256": hashlib.sha256(spec_text.encode("utf-8")).hexdigest(),
        "todo_count": len(rows),
        "status_counts": status_counts,
        "verified_completion_count": status_counts["verified"],
        "completion_claim_allowed": status_counts["verified"] == 100,
        "todos": rows,
        "status_semantics": {
            "verified": "Requirement-scoped implementation and tests are both hash-bound.",
            "partial": "Useful implementation exists but one or more explicit clauses remain unproved.",
            "human_gate": "Machine work is ready but named human review or approval is required.",
            "unverified": "The requirement is missing or has not yet been audited with direct evidence.",
        },
        "truth_boundary": (
            "This ledger never infers completion from adjacent features, filenames, passing unrelated tests, or intent. "
            "Only requirement-scoped evidence and tests receive completion credit."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_todo_execution_ledger(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTM100TodoExecutionLedgerError("TODO execution ledger seal is invalid")
    rows = payload.get("todos")
    if not isinstance(rows, list) or len(rows) != 100 or payload.get("todo_count") != 100:
        raise GTM100TodoExecutionLedgerError("TODO ledger must contain exactly 100 rows")
    if [row.get("todo_id") for row in rows] != [f"T{value:03d}" for value in range(1, 101)]:
        raise GTM100TodoExecutionLedgerError("TODO sequence drifted")
    for row in rows:
        if row.get("status") not in ALLOWED_STATUSES:
            raise GTM100TodoExecutionLedgerError("TODO status is invalid")
        if row.get("status") == "verified" and (
            not row.get("evidence_pointers") or not row.get("test_ids") or row.get("completion_credit") != 1
        ):
            raise GTM100TodoExecutionLedgerError("verified TODO lacks direct implementation and test evidence")
        if row.get("status") != "verified" and row.get("completion_credit") != 0:
            raise GTM100TodoExecutionLedgerError("non-verified TODO received completion credit")
    status_counts = {status: sum(row["status"] == status for row in rows) for status in sorted(ALLOWED_STATUSES)}
    if payload.get("status_counts") != status_counts:
        raise GTM100TodoExecutionLedgerError("TODO status aggregate drifted")
    should_complete = status_counts["verified"] == 100
    if payload.get("completion_claim_allowed") is not should_complete:
        raise GTM100TodoExecutionLedgerError("TODO completion claim is inconsistent")


__all__ = [
    "GTM100TodoExecutionLedgerError",
    "compile_todo_execution_ledger",
    "parse_todo_spec",
    "verify_todo_execution_ledger",
]
