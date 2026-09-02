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
class ArtifactSourceEscalationRecord:
    schema_version: str
    record_type: str
    status: str
    triage_record: str
    missing_image: str
    target: dict[str, Any]
    escalation_statuses: list[str] = field(default_factory=list)
    required_provenance_fields: list[str] = field(default_factory=list)
    accepted_forms: list[str] = field(default_factory=list)
    rejected_forms: list[str] = field(default_factory=list)
    operator_checklist: list[str] = field(default_factory=list)
    discovered_admissions: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    hydration_authorized: bool = False
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


def make_artifact_source_escalation_record(
    *,
    status: str,
    triage_record: str,
    missing_image: str,
    target: dict[str, Any],
    escalation_statuses: list[str] | None = None,
    required_provenance_fields: list[str] | None = None,
    accepted_forms: list[str] | None = None,
    rejected_forms: list[str] | None = None,
    operator_checklist: list[str] | None = None,
    discovered_admissions: list[dict[str, Any]] | None = None,
    reasons: list[str] | None = None,
    hydration_authorized: bool = False,
    executable: bool = False,
) -> dict[str, Any]:
    return ArtifactSourceEscalationRecord(
        schema_version="determinex-programbench-artifact-source-escalation-v1",
        record_type="programbench_artifact_source_escalation",
        status=status,
        triage_record=triage_record,
        missing_image=missing_image,
        target=target,
        escalation_statuses=escalation_statuses or [],
        required_provenance_fields=required_provenance_fields or [],
        accepted_forms=accepted_forms or [],
        rejected_forms=rejected_forms or [],
        operator_checklist=operator_checklist or [],
        discovered_admissions=discovered_admissions or [],
        reasons=reasons or [],
        hydration_authorized=hydration_authorized,
        executable=executable,
    ).signed()


def verify_artifact_source_escalation_record(record: dict[str, Any]) -> bool:
    signature = str(record.get("record_signature") or "")
    if not signature:
        return False
    return hmac.compare_digest(signature, _signature(record))


def write_artifact_source_escalation_record(record: dict[str, Any], output_dir: Path) -> Path:
    if not verify_artifact_source_escalation_record(record):
        raise ValueError("artifact source escalation record signature invalid")
    output_dir.mkdir(parents=True, exist_ok=True)
    image = _safe(str(record.get("missing_image") or "artifact"))
    status = _safe(str(record.get("status") or "status"))
    path = output_dir / f"{image}.{status}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _signature(record: dict[str, Any]) -> str:
    payload = {k: v for k, v in record.items() if k != "record_signature"}
    return hmac.new(_record_key(), _canonical_json(payload), hashlib.blake2b).hexdigest()


def _record_key() -> bytes:
    raw = os.environ.get("DETERMINEX_ARTIFACT_SOURCE_ESCALATION_KEY", "").strip()
    if raw:
        try:
            key = bytes.fromhex(raw)
            if len(key) >= 32:
                return key
        except ValueError:
            pass
    return b"determinex-artifact-source-escalation-lock-001-test-key"


def _canonical_json(record: dict[str, Any]) -> bytes:
    raw = json.dumps(record, sort_keys=True, ensure_ascii=True)
    return unicodedata.normalize("NFC", raw).encode()


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)[:160]
