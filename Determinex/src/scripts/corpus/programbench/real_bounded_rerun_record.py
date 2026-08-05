from __future__ import annotations

import hashlib
import hmac
import json
import os
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RealBoundedRerunRecord:
    schema_version: str
    record_type: str
    status: str
    packet_id: str
    target: dict[str, Any]
    rerun_scope: dict[str, Any]
    outcome: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    record_status: str = "active_eval_evidence"
    training_eligible: bool = False
    created_at: str = ""
    record_signature: str = ""

    def signed(self) -> dict[str, Any]:
        row = asdict(self)
        if not row["created_at"]:
            row["created_at"] = datetime.now(UTC).isoformat()
        row["record_signature"] = _signature(row)
        return row


def make_real_rerun_record(
    *,
    status: str,
    packet_id: str,
    target: dict[str, Any],
    rerun_scope: dict[str, Any],
    outcome: dict[str, Any] | None = None,
    reasons: list[str] | None = None,
) -> dict[str, Any]:
    return RealBoundedRerunRecord(
        schema_version="determinex-programbench-real-bounded-rerun-v1",
        record_type="real_bounded_rerun_outcome",
        status=status,
        packet_id=packet_id,
        target=target,
        rerun_scope=rerun_scope,
        outcome=outcome or {},
        reasons=reasons or [],
    ).signed()


def verify_real_rerun_record(record: dict[str, Any]) -> bool:
    signature = str(record.get("record_signature") or "")
    if not signature:
        return False
    return hmac.compare_digest(signature, _signature(record))


def write_real_rerun_record(record: dict[str, Any], output_dir: Path) -> Path:
    if not verify_real_rerun_record(record):
        raise ValueError("real bounded rerun record signature invalid")
    output_dir.mkdir(parents=True, exist_ok=True)
    packet_id = _safe(str(record.get("packet_id") or "packet"))
    status = _safe(str(record.get("status") or "status"))
    path = output_dir / f"{packet_id}.{status}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _signature(record: dict[str, Any]) -> str:
    payload = {k: v for k, v in record.items() if k != "record_signature"}
    return hmac.new(_record_key(), _canonical_json(payload), hashlib.blake2b).hexdigest()


def _record_key() -> bytes:
    raw = os.environ.get("DETERMINEX_REAL_BOUNDED_RERUN_KEY", "").strip()
    if raw:
        try:
            key = bytes.fromhex(raw)
            if len(key) >= 32:
                return key
        except ValueError:
            pass
    return b"determinex-real-bounded-rerun-lock-001-test-key"


def _canonical_json(record: dict[str, Any]) -> bytes:
    raw = json.dumps(record, sort_keys=True, ensure_ascii=True)
    return unicodedata.normalize("NFC", raw).encode()


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)[:160]
