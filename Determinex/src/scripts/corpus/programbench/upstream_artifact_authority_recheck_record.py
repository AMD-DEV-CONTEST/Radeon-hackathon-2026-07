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
class UpstreamArtifactAuthorityRecheckRecord:
    schema_version: str
    record_type: str
    status: str
    decision: str
    instance_id: str
    image_reference: str
    image_digest: str
    expected_image_reference: str
    expected_image_digest: str
    upstream_benchmark_artifact_authority: str
    rebuild_provenance_authority: str
    remediation_authority: str
    execution_security_policy: str
    authority_findings: dict[str, Any] = field(default_factory=dict)
    consumed_records: dict[str, str] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)
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


def make_upstream_artifact_authority_recheck_record(
    *,
    status: str,
    decision: str,
    instance_id: str,
    image_reference: str,
    image_digest: str,
    expected_image_reference: str,
    expected_image_digest: str,
    upstream_benchmark_artifact_authority: str,
    rebuild_provenance_authority: str,
    remediation_authority: str,
    execution_security_policy: str,
    authority_findings: dict[str, Any] | None = None,
    consumed_records: dict[str, str] | None = None,
    verification: dict[str, Any] | None = None,
    authorization: dict[str, bool] | None = None,
    reasons: list[str] | None = None,
    cache_ready: bool = False,
    executable: bool = False,
) -> dict[str, Any]:
    return UpstreamArtifactAuthorityRecheckRecord(
        schema_version="determinex-programbench-upstream-artifact-authority-recheck-v1",
        record_type="programbench_upstream_artifact_authority_recheck",
        status=status,
        decision=decision,
        instance_id=instance_id,
        image_reference=image_reference,
        image_digest=image_digest,
        expected_image_reference=expected_image_reference,
        expected_image_digest=expected_image_digest,
        upstream_benchmark_artifact_authority=upstream_benchmark_artifact_authority,
        rebuild_provenance_authority=rebuild_provenance_authority,
        remediation_authority=remediation_authority,
        execution_security_policy=execution_security_policy,
        authority_findings=authority_findings or {},
        consumed_records=consumed_records or {},
        verification=verification or {},
        authorization=authorization or {},
        reasons=reasons or [],
        cache_ready=cache_ready,
        executable=executable,
    ).signed()


def verify_upstream_artifact_authority_recheck_record(record: dict[str, Any]) -> bool:
    signature = str(record.get("record_signature") or "")
    if not signature:
        return False
    return hmac.compare_digest(signature, _signature(record))


def write_upstream_artifact_authority_recheck_record(
    record: dict[str, Any], output_dir: Path
) -> Path:
    if not verify_upstream_artifact_authority_recheck_record(record):
        raise ValueError("upstream artifact authority recheck record signature invalid")
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
    raw = os.environ.get("DETERMINEX_UPSTREAM_ARTIFACT_AUTHORITY_RECHECK_KEY", "").strip()
    if raw:
        try:
            key = bytes.fromhex(raw)
            if len(key) >= 32:
                return key
        except ValueError:
            pass
    return b"determinex-upstream-artifact-authority-recheck-lock-001-test-key"


def _canonical_json(record: dict[str, Any]) -> bytes:
    raw = json.dumps(record, sort_keys=True, ensure_ascii=True)
    return unicodedata.normalize("NFC", raw).encode()


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)[:160]
