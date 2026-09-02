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
class InfraFailureTriageRecord:
    schema_version: str
    record_type: str
    status: str
    source_record: str
    packet_id: str
    target: dict[str, Any]
    failure_type: str
    missing_image: str = ""
    local_image_status: str = ""
    source_status: str = ""
    provenance_status: str = ""
    failure_statuses: list[str] = field(default_factory=list)
    allowed_actions: list[str] = field(default_factory=list)
    blocked_actions: list[str] = field(default_factory=list)
    recovery_recommendation: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
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


def make_infra_failure_triage_record(
    *,
    status: str,
    source_record: str,
    packet_id: str,
    target: dict[str, Any],
    failure_type: str,
    missing_image: str = "",
    local_image_status: str = "",
    source_status: str = "",
    provenance_status: str = "",
    failure_statuses: list[str] | None = None,
    allowed_actions: list[str] | None = None,
    blocked_actions: list[str] | None = None,
    recovery_recommendation: str = "",
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return InfraFailureTriageRecord(
        schema_version="determinex-programbench-infra-failure-triage-v1",
        record_type="programbench_infra_failure_triage",
        status=status,
        source_record=source_record,
        packet_id=packet_id,
        target=target,
        failure_type=failure_type,
        missing_image=missing_image,
        local_image_status=local_image_status,
        source_status=source_status,
        provenance_status=provenance_status,
        failure_statuses=failure_statuses or [],
        allowed_actions=allowed_actions or [],
        blocked_actions=blocked_actions or [],
        recovery_recommendation=recovery_recommendation,
        evidence=evidence or {},
    ).signed()


def verify_infra_failure_triage_record(record: dict[str, Any]) -> bool:
    signature = str(record.get("record_signature") or "")
    if not signature:
        return False
    return hmac.compare_digest(signature, _signature(record))


def write_infra_failure_triage_record(record: dict[str, Any], output_dir: Path) -> Path:
    if not verify_infra_failure_triage_record(record):
        raise ValueError("infra failure triage record signature invalid")
    output_dir.mkdir(parents=True, exist_ok=True)
    packet_id = _safe(str(record.get("packet_id") or "packet"))
    failure_type = _safe(str(record.get("failure_type") or "failure"))
    path = output_dir / f"{packet_id}.{failure_type}.triage.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _signature(record: dict[str, Any]) -> str:
    payload = {k: v for k, v in record.items() if k != "record_signature"}
    return hmac.new(_record_key(), _canonical_json(payload), hashlib.blake2b).hexdigest()


def _record_key() -> bytes:
    raw = os.environ.get("DETERMINEX_INFRA_FAILURE_TRIAGE_KEY", "").strip()
    if raw:
        try:
            key = bytes.fromhex(raw)
            if len(key) >= 32:
                return key
        except ValueError:
            pass
    return b"determinex-infra-failure-triage-lock-001-test-key"


def _canonical_json(record: dict[str, Any]) -> bytes:
    raw = json.dumps(record, sort_keys=True, ensure_ascii=True)
    return unicodedata.normalize("NFC", raw).encode()


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)[:160]
