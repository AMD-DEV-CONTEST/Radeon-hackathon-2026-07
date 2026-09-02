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
class CleanroomImageScanRecord:
    schema_version: str
    record_type: str
    status: str
    import_record: str
    image_reference: str
    artifact_path: str
    expected_digest: str
    observed_digest: str
    file_sha256: str
    file_size: int
    scanner: str
    scanner_version: str
    scanner_command: list[str] = field(default_factory=list)
    scan_statuses: list[str] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""
    findings_summary: dict[str, Any] = field(default_factory=dict)
    normalized_findings: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
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


def make_cleanroom_image_scan_record(
    *,
    status: str,
    import_record: str,
    image_reference: str,
    artifact_path: str,
    expected_digest: str,
    observed_digest: str,
    file_sha256: str,
    file_size: int,
    scanner: str,
    scanner_version: str,
    scanner_command: list[str] | None = None,
    scan_statuses: list[str] | None = None,
    started_at: str = "",
    completed_at: str = "",
    findings_summary: dict[str, Any] | None = None,
    normalized_findings: list[dict[str, Any]] | None = None,
    reasons: list[str] | None = None,
    cache_ready: bool = False,
    executable: bool = False,
) -> dict[str, Any]:
    return CleanroomImageScanRecord(
        schema_version="determinex-programbench-cleanroom-image-scan-v1",
        record_type="programbench_cleanroom_image_scan",
        status=status,
        import_record=import_record,
        image_reference=image_reference,
        artifact_path=artifact_path,
        expected_digest=expected_digest,
        observed_digest=observed_digest,
        file_sha256=file_sha256,
        file_size=file_size,
        scanner=scanner,
        scanner_version=scanner_version,
        scanner_command=scanner_command or [],
        scan_statuses=scan_statuses or [],
        started_at=started_at,
        completed_at=completed_at,
        findings_summary=findings_summary or {},
        normalized_findings=normalized_findings or [],
        reasons=reasons or [],
        cache_ready=cache_ready,
        executable=executable,
    ).signed()


def verify_cleanroom_image_scan_record(record: dict[str, Any]) -> bool:
    signature = str(record.get("record_signature") or "")
    if not signature:
        return False
    return hmac.compare_digest(signature, _signature(record))


def write_cleanroom_image_scan_record(record: dict[str, Any], output_dir: Path) -> Path:
    if not verify_cleanroom_image_scan_record(record):
        raise ValueError("cleanroom image scan record signature invalid")
    output_dir.mkdir(parents=True, exist_ok=True)
    image = _safe(str(record.get("image_reference") or "artifact"))
    status = _safe(str(record.get("status") or "status"))
    path = output_dir / f"{image}.{status}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _signature(record: dict[str, Any]) -> str:
    payload = {k: v for k, v in record.items() if k != "record_signature"}
    return hmac.new(_record_key(), _canonical_json(payload), hashlib.blake2b).hexdigest()


def _record_key() -> bytes:
    raw = os.environ.get("DETERMINEX_CLEANROOM_IMAGE_SCAN_KEY", "").strip()
    if raw:
        try:
            key = bytes.fromhex(raw)
            if len(key) >= 32:
                return key
        except ValueError:
            pass
    return b"determinex-cleanroom-image-scan-lock-001-test-key"


def _canonical_json(record: dict[str, Any]) -> bytes:
    raw = json.dumps(record, sort_keys=True, ensure_ascii=True)
    return unicodedata.normalize("NFC", raw).encode()


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)[:160]
