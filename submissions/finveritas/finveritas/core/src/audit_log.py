"""Tamper-evident audit log for DPDP Act 2023 and RBI IT Framework compliance.

Each entry is SHA-256 hashed and chains to the previous entry's hash, so any
post-hoc modification to a record breaks the chain and is detectable via
verify_chain().

Log format: newline-delimited JSON (JSONL) appended to output/audit_log.jsonl.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_LOG = Path("output/audit_log.jsonl")
_GENESIS_LABEL = "FINVERITAS_AUDIT_GENESIS_V1"


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _last_hash(path: Path) -> str:
    """Return the entry_hash of the final entry, or the genesis hash if log is empty."""
    if not path.exists():
        return _sha256(_GENESIS_LABEL)
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return _sha256(_GENESIS_LABEL)
    try:
        return json.loads(lines[-1]).get("entry_hash", _sha256(_GENESIS_LABEL))
    except json.JSONDecodeError:
        return _sha256(_GENESIS_LABEL)


def append_entry(
    *,
    run_id: str | None = None,
    entity: str,
    source_type: str,
    credibility_score: int | None,
    agents_run: list[str],
    agent_outputs: dict[str, Any],
    consent_timestamp: str | None = None,
    log_path: Path | None = None,
) -> Path:
    """Append a signed, chained entry to the audit log. Returns the log path."""
    path = log_path or _DEFAULT_LOG
    path.parent.mkdir(parents=True, exist_ok=True)

    prev_hash = _last_hash(path)
    output_hash = _sha256(json.dumps(agent_outputs, sort_keys=True, ensure_ascii=False))

    entry: dict[str, Any] = {
        "id": run_id or str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        "entity": entity,
        "source_type": source_type,
        "credibility_score": credibility_score,
        "agents_run": sorted(agents_run),
        "output_hash": output_hash,
        "consent_timestamp": consent_timestamp,
        "prev_hash": prev_hash,
    }
    # entry_hash covers all fields above — changing any field breaks verification
    entry["entry_hash"] = _sha256(json.dumps(entry, sort_keys=True, ensure_ascii=False))

    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return path


def read_log(log_path: Path | None = None) -> list[dict[str, Any]]:
    """Return all entries from the audit log, oldest first."""
    path = log_path or _DEFAULT_LOG
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return entries


def verify_chain(entries: list[dict[str, Any]]) -> list[str]:
    """Return a list of violation descriptions; empty list means the chain is intact."""
    violations: list[str] = []
    expected_prev = _sha256(_GENESIS_LABEL)

    for i, entry in enumerate(entries):
        eid = entry.get("id", f"index-{i}")

        if entry.get("prev_hash") != expected_prev:
            violations.append(
                f"[{eid}] prev_hash mismatch — entry may have been inserted or reordered"
            )

        stored_hash = entry.get("entry_hash")
        body = {k: v for k, v in entry.items() if k != "entry_hash"}
        computed_hash = _sha256(json.dumps(body, sort_keys=True, ensure_ascii=False))
        if stored_hash != computed_hash:
            violations.append(
                f"[{eid}] entry_hash mismatch — entry content may have been modified"
            )

        expected_prev = stored_hash or expected_prev

    return violations
