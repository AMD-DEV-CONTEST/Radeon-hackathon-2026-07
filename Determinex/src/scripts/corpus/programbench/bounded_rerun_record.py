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
class BoundedRerunRecord:
    schema_version: str
    record_type: str
    status: str
    packet_id: str
    target: dict[str, Any]
    rerun_scope: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    outcome: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    record_signature: str = ""

    def signed(self) -> dict[str, Any]:
        row = asdict(self)
        if not row["created_at"]:
            row["created_at"] = datetime.now(UTC).isoformat()
        row["record_signature"] = _signature(row)
        return row


def make_authorization_record(
    *,
    status: str,
    packet_id: str,
    target: dict[str, Any],
    rerun_scope: dict[str, Any],
    reasons: list[str] | None = None,
) -> dict[str, Any]:
    return BoundedRerunRecord(
        schema_version="determinex-programbench-bounded-rerun-v1",
        record_type="bounded_rerun_authorization",
        status=status,
        packet_id=packet_id,
        target=target,
        rerun_scope=rerun_scope,
        reasons=reasons or [],
    ).signed()


def make_outcome_record(
    *,
    packet_id: str,
    target: dict[str, Any],
    rerun_scope: dict[str, Any],
    outcome: dict[str, Any],
) -> dict[str, Any]:
    return BoundedRerunRecord(
        schema_version="determinex-programbench-bounded-rerun-v1",
        record_type="bounded_rerun_outcome",
        status="BOUNDED_RERUN_OUTCOME_RECORDED",
        packet_id=packet_id,
        target=target,
        rerun_scope=rerun_scope,
        outcome=outcome,
    ).signed()


def verify_bounded_rerun_record(record: dict[str, Any]) -> bool:
    signature = str(record.get("record_signature") or "")
    if not signature:
        return False
    return hmac.compare_digest(signature, _signature(record))


def write_bounded_rerun_record(record: dict[str, Any], output_dir: Path) -> Path:
    if not verify_bounded_rerun_record(record):
        raise ValueError("bounded rerun record signature invalid")
    output_dir.mkdir(parents=True, exist_ok=True)
    packet_id = _safe(str(record.get("packet_id") or "packet"))
    record_type = _safe(str(record.get("record_type") or "record"))
    path = output_dir / f"{packet_id}.{record_type}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _signature(record: dict[str, Any]) -> str:
    payload = {k: v for k, v in record.items() if k != "record_signature"}
    return hmac.new(_record_key(), _canonical_json(payload), hashlib.blake2b).hexdigest()


def _record_key() -> bytes:
    raw = os.environ.get("DETERMINEX_BOUNDED_RERUN_KEY", "").strip()
    if raw:
        try:
            key = bytes.fromhex(raw)
            if len(key) >= 32:
                return key
        except ValueError:
            pass
    return b"determinex-bounded-rerun-lock-001-test-key"


def _canonical_json(record: dict[str, Any]) -> bytes:
    raw = json.dumps(record, sort_keys=True, ensure_ascii=True)
    return unicodedata.normalize("NFC", raw).encode()


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)[:160]
