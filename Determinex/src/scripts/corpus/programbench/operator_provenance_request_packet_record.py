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
class OperatorProvenanceRequestPacketRecord:
    schema_version: str
    record_type: str
    status: str
    image_reference: str
    image_digest: str
    rebuild_quarantine_decision: str
    current_decision: str
    required_evidence: list[dict[str, Any]] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    acceptance_criteria: list[dict[str, Any]] = field(default_factory=list)
    acceptable_provenance_forms: list[str] = field(default_factory=list)
    unacceptable_provenance_forms: list[str] = field(default_factory=list)
    operator_admission_checklist: list[str] = field(default_factory=list)
    toolchain_requirements: dict[str, Any] = field(default_factory=dict)
    benchmark_fidelity_impact: dict[str, Any] = field(default_factory=dict)
    authorization: dict[str, bool] = field(default_factory=dict)
    request_statuses: list[str] = field(default_factory=list)
    upstream_records: dict[str, str] = field(default_factory=dict)
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


def make_operator_provenance_request_packet_record(
    *,
    status: str,
    image_reference: str,
    image_digest: str,
    rebuild_quarantine_decision: str,
    current_decision: str,
    required_evidence: list[dict[str, Any]] | None = None,
    missing_evidence: list[str] | None = None,
    acceptance_criteria: list[dict[str, Any]] | None = None,
    acceptable_provenance_forms: list[str] | None = None,
    unacceptable_provenance_forms: list[str] | None = None,
    operator_admission_checklist: list[str] | None = None,
    toolchain_requirements: dict[str, Any] | None = None,
    benchmark_fidelity_impact: dict[str, Any] | None = None,
    authorization: dict[str, bool] | None = None,
    request_statuses: list[str] | None = None,
    upstream_records: dict[str, str] | None = None,
    reasons: list[str] | None = None,
    cache_ready: bool = False,
    executable: bool = False,
) -> dict[str, Any]:
    return OperatorProvenanceRequestPacketRecord(
        schema_version="determinex-programbench-operator-provenance-request-packet-v1",
        record_type="programbench_operator_provenance_request_packet",
        status=status,
        image_reference=image_reference,
        image_digest=image_digest,
        rebuild_quarantine_decision=rebuild_quarantine_decision,
        current_decision=current_decision,
        required_evidence=required_evidence or [],
        missing_evidence=missing_evidence or [],
        acceptance_criteria=acceptance_criteria or [],
        acceptable_provenance_forms=acceptable_provenance_forms or [],
        unacceptable_provenance_forms=unacceptable_provenance_forms or [],
        operator_admission_checklist=operator_admission_checklist or [],
        toolchain_requirements=toolchain_requirements or {},
        benchmark_fidelity_impact=benchmark_fidelity_impact or {},
        authorization=authorization or {},
        request_statuses=request_statuses or [],
        upstream_records=upstream_records or {},
        reasons=reasons or [],
        cache_ready=cache_ready,
        executable=executable,
    ).signed()


def verify_operator_provenance_request_packet_record(record: dict[str, Any]) -> bool:
    signature = str(record.get("record_signature") or "")
    if not signature:
        return False
    return hmac.compare_digest(signature, _signature(record))


def write_operator_provenance_request_packet_record(
    record: dict[str, Any], output_dir: Path
) -> Path:
    if not verify_operator_provenance_request_packet_record(record):
        raise ValueError("operator provenance request packet signature invalid")
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
    raw = os.environ.get("DETERMINEX_OPERATOR_PROVENANCE_REQUEST_PACKET_KEY", "").strip()
    if raw:
        try:
            key = bytes.fromhex(raw)
            if len(key) >= 32:
                return key
        except ValueError:
            pass
    return b"determinex-operator-provenance-request-packet-lock-001-test-key"


def _canonical_json(record: dict[str, Any]) -> bytes:
    raw = json.dumps(record, sort_keys=True, ensure_ascii=True)
    return unicodedata.normalize("NFC", raw).encode()


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)[:160]
