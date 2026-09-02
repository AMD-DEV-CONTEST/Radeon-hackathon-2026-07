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
class AlternateCleanroomImageProvenanceRecord:
    schema_version: str
    record_type: str
    status: str
    decision: str
    original_image_reference: str
    original_image_digest: str
    operator_provenance_request: str
    searched_sources: list[dict[str, Any]] = field(default_factory=list)
    alternate_candidates: list[dict[str, Any]] = field(default_factory=list)
    selected_candidate: dict[str, Any] = field(default_factory=dict)
    provenance_findings: dict[str, Any] = field(default_factory=dict)
    benchmark_fidelity_impact: dict[str, Any] = field(default_factory=dict)
    authorization: dict[str, bool] = field(default_factory=dict)
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


def make_alternate_cleanroom_image_provenance_record(
    *,
    status: str,
    decision: str,
    original_image_reference: str,
    original_image_digest: str,
    operator_provenance_request: str,
    searched_sources: list[dict[str, Any]] | None = None,
    alternate_candidates: list[dict[str, Any]] | None = None,
    selected_candidate: dict[str, Any] | None = None,
    provenance_findings: dict[str, Any] | None = None,
    benchmark_fidelity_impact: dict[str, Any] | None = None,
    authorization: dict[str, bool] | None = None,
    reasons: list[str] | None = None,
    cache_ready: bool = False,
    executable: bool = False,
) -> dict[str, Any]:
    return AlternateCleanroomImageProvenanceRecord(
        schema_version="determinex-programbench-alternate-cleanroom-image-provenance-v1",
        record_type="programbench_alternate_cleanroom_image_provenance",
        status=status,
        decision=decision,
        original_image_reference=original_image_reference,
        original_image_digest=original_image_digest,
        operator_provenance_request=operator_provenance_request,
        searched_sources=searched_sources or [],
        alternate_candidates=alternate_candidates or [],
        selected_candidate=selected_candidate or {},
        provenance_findings=provenance_findings or {},
        benchmark_fidelity_impact=benchmark_fidelity_impact or {},
        authorization=authorization or {},
        reasons=reasons or [],
        cache_ready=cache_ready,
        executable=executable,
    ).signed()


def verify_alternate_cleanroom_image_provenance_record(record: dict[str, Any]) -> bool:
    signature = str(record.get("record_signature") or "")
    if not signature:
        return False
    return hmac.compare_digest(signature, _signature(record))


def write_alternate_cleanroom_image_provenance_record(
    record: dict[str, Any], output_dir: Path
) -> Path:
    if not verify_alternate_cleanroom_image_provenance_record(record):
        raise ValueError("alternate cleanroom image provenance record signature invalid")
    output_dir.mkdir(parents=True, exist_ok=True)
    image = _safe(str(record.get("original_image_reference") or "artifact"))
    status = _safe(str(record.get("status") or "status"))
    path = output_dir / f"{image}.{status}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _signature(record: dict[str, Any]) -> str:
    payload = {k: v for k, v in record.items() if k != "record_signature"}
    return hmac.new(_record_key(), _canonical_json(payload), hashlib.blake2b).hexdigest()


def _record_key() -> bytes:
    raw = os.environ.get("DETERMINEX_ALTERNATE_CLEANROOM_IMAGE_PROVENANCE_KEY", "").strip()
    if raw:
        try:
            key = bytes.fromhex(raw)
            if len(key) >= 32:
                return key
        except ValueError:
            pass
    return b"determinex-alternate-cleanroom-image-provenance-lock-001-test-key"


def _canonical_json(record: dict[str, Any]) -> bytes:
    raw = json.dumps(record, sort_keys=True, ensure_ascii=True)
    return unicodedata.normalize("NFC", raw).encode()


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)[:160]
