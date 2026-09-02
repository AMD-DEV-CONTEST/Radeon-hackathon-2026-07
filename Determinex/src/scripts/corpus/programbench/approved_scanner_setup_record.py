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
class ApprovedScannerSetupRecord:
    schema_version: str
    record_type: str
    status: str
    scanner_name: str
    scanner_path: str
    scanner_version: str
    capability: str
    setup_statuses: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    install_instructions: list[str] = field(default_factory=list)
    admission_record_path: str = ""
    admission_status: str = ""
    cache_ready: bool = False
    executable: bool = False
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


def make_approved_scanner_setup_record(
    *,
    status: str,
    scanner_name: str = "",
    scanner_path: str = "",
    scanner_version: str = "",
    capability: str = "",
    setup_statuses: list[str] | None = None,
    reasons: list[str] | None = None,
    install_instructions: list[str] | None = None,
    admission_record_path: str = "",
    admission_status: str = "",
    cache_ready: bool = False,
    executable: bool = False,
) -> dict[str, Any]:
    return ApprovedScannerSetupRecord(
        schema_version="determinex-programbench-approved-scanner-setup-v1",
        record_type="programbench_approved_scanner_setup",
        status=status,
        scanner_name=scanner_name,
        scanner_path=scanner_path,
        scanner_version=scanner_version,
        capability=capability,
        setup_statuses=setup_statuses or [],
        reasons=reasons or [],
        install_instructions=install_instructions or [],
        admission_record_path=admission_record_path,
        admission_status=admission_status,
        cache_ready=cache_ready,
        executable=executable,
    ).signed()


def verify_approved_scanner_setup_record(record: dict[str, Any]) -> bool:
    signature = str(record.get("record_signature") or "")
    if not signature:
        return False
    return hmac.compare_digest(signature, _signature(record))


def write_approved_scanner_setup_record(record: dict[str, Any], output_dir: Path) -> Path:
    if not verify_approved_scanner_setup_record(record):
        raise ValueError("approved scanner setup record signature invalid")
    output_dir.mkdir(parents=True, exist_ok=True)
    scanner = _safe(str(record.get("scanner_name") or "scanner"))
    status = _safe(str(record.get("status") or "status"))
    path = output_dir / f"{scanner}.{status}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _signature(record: dict[str, Any]) -> str:
    payload = {k: v for k, v in record.items() if k != "record_signature"}
    return hmac.new(_record_key(), _canonical_json(payload), hashlib.blake2b).hexdigest()


def _record_key() -> bytes:
    raw = os.environ.get("DETERMINEX_APPROVED_SCANNER_SETUP_KEY", "").strip()
    if raw:
        try:
            key = bytes.fromhex(raw)
            if len(key) >= 32:
                return key
        except ValueError:
            pass
    return b"determinex-approved-scanner-setup-lock-001-test-key"


def _canonical_json(record: dict[str, Any]) -> bytes:
    raw = json.dumps(record, sort_keys=True, ensure_ascii=True)
    return unicodedata.normalize("NFC", raw).encode()


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)[:120]
