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
class DockerHubManifestProvenanceRecord:
    schema_version: str
    record_type: str
    status: str
    triage_record: str
    image_reference: str
    registry: str
    repository: str
    tag: str
    manifest_digest: str
    target: dict[str, Any]
    provenance_statuses: list[str] = field(default_factory=list)
    lookup_method: str = "manifest/digest metadata only"
    metadata: dict[str, Any] = field(default_factory=dict)
    operator_claim_path: str = ""
    pulled_layers: bool = False
    executed: bool = False
    hydration_authorized: bool = False
    execution_authorized: bool = False
    record_status: str = "active_eval_evidence"
    training_eligible: bool = False
    reasons: list[str] = field(default_factory=list)
    created_at: str = ""
    record_signature: str = ""

    def signed(self) -> dict[str, Any]:
        row = asdict(self)
        if not row["created_at"]:
            row["created_at"] = datetime.now(UTC).isoformat()
        row["record_signature"] = _signature(row)
        return row


def make_dockerhub_manifest_provenance_record(
    *,
    status: str,
    triage_record: str,
    image_reference: str,
    registry: str,
    repository: str,
    tag: str,
    manifest_digest: str,
    target: dict[str, Any],
    provenance_statuses: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    operator_claim_path: str = "",
    reasons: list[str] | None = None,
) -> dict[str, Any]:
    return DockerHubManifestProvenanceRecord(
        schema_version="determinex-programbench-dockerhub-manifest-provenance-v1",
        record_type="programbench_dockerhub_manifest_provenance",
        status=status,
        triage_record=triage_record,
        image_reference=image_reference,
        registry=registry,
        repository=repository,
        tag=tag,
        manifest_digest=manifest_digest,
        target=target,
        provenance_statuses=provenance_statuses or [],
        metadata=metadata or {},
        operator_claim_path=operator_claim_path,
        reasons=reasons or [],
    ).signed()


def verify_dockerhub_manifest_provenance_record(record: dict[str, Any]) -> bool:
    signature = str(record.get("record_signature") or "")
    if not signature:
        return False
    return hmac.compare_digest(signature, _signature(record))


def write_dockerhub_manifest_provenance_record(record: dict[str, Any], output_dir: Path) -> Path:
    if not verify_dockerhub_manifest_provenance_record(record):
        raise ValueError("dockerhub manifest provenance record signature invalid")
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
    raw = os.environ.get("DETERMINEX_DOCKERHUB_MANIFEST_PROVENANCE_KEY", "").strip()
    if raw:
        try:
            key = bytes.fromhex(raw)
            if len(key) >= 32:
                return key
        except ValueError:
            pass
    return b"determinex-dockerhub-manifest-provenance-lock-001-test-key"


def _canonical_json(record: dict[str, Any]) -> bytes:
    raw = json.dumps(record, sort_keys=True, ensure_ascii=True)
    return unicodedata.normalize("NFC", raw).encode()


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)[:160]
