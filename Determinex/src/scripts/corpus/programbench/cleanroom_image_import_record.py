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
class CleanroomImageImportRecord:
    schema_version: str
    record_type: str
    status: str
    provenance_record: str
    admission_record: str
    image_reference: str
    source_url_or_registry: str
    expected_digest: str
    observed_digest: str
    target: dict[str, Any]
    import_statuses: list[str] = field(default_factory=list)
    artifact_import_path: str = ""
    quarantine_path: str = ""
    scan_result: dict[str, Any] = field(default_factory=dict)
    policy_result: str = ""
    pull_command: list[str] = field(default_factory=list)
    save_command: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    pulled_layers: bool = False
    docker_executed: bool = False
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


def make_cleanroom_image_import_record(
    *,
    status: str,
    provenance_record: str,
    admission_record: str,
    image_reference: str,
    source_url_or_registry: str,
    expected_digest: str,
    observed_digest: str,
    target: dict[str, Any],
    import_statuses: list[str] | None = None,
    artifact_import_path: str = "",
    quarantine_path: str = "",
    scan_result: dict[str, Any] | None = None,
    policy_result: str = "",
    pull_command: list[str] | None = None,
    save_command: list[str] | None = None,
    reasons: list[str] | None = None,
    pulled_layers: bool = False,
    docker_executed: bool = False,
    cache_ready: bool = False,
    executable: bool = False,
) -> dict[str, Any]:
    return CleanroomImageImportRecord(
        schema_version="determinex-programbench-cleanroom-image-import-v1",
        record_type="programbench_cleanroom_image_import",
        status=status,
        provenance_record=provenance_record,
        admission_record=admission_record,
        image_reference=image_reference,
        source_url_or_registry=source_url_or_registry,
        expected_digest=expected_digest,
        observed_digest=observed_digest,
        target=target,
        import_statuses=import_statuses or [],
        artifact_import_path=artifact_import_path,
        quarantine_path=quarantine_path,
        scan_result=scan_result or {},
        policy_result=policy_result,
        pull_command=pull_command or [],
        save_command=save_command or [],
        reasons=reasons or [],
        pulled_layers=pulled_layers,
        docker_executed=docker_executed,
        cache_ready=cache_ready,
        executable=executable,
    ).signed()


def verify_cleanroom_image_import_record(record: dict[str, Any]) -> bool:
    signature = str(record.get("record_signature") or "")
    if not signature:
        return False
    return hmac.compare_digest(signature, _signature(record))


def write_cleanroom_image_import_record(record: dict[str, Any], output_dir: Path) -> Path:
    if not verify_cleanroom_image_import_record(record):
        raise ValueError("cleanroom image import record signature invalid")
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
    raw = os.environ.get("DETERMINEX_CLEANROOM_IMAGE_IMPORT_KEY", "").strip()
    if raw:
        try:
            key = bytes.fromhex(raw)
            if len(key) >= 32:
                return key
        except ValueError:
            pass
    return b"determinex-cleanroom-image-import-lock-001-test-key"


def _canonical_json(record: dict[str, Any]) -> bytes:
    raw = json.dumps(record, sort_keys=True, ensure_ascii=True)
    return unicodedata.normalize("NFC", raw).encode()


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)[:160]
