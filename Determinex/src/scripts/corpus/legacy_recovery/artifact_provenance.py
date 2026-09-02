from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from corpus.corpus_manager import hmac_key_scope, resign_record, verify_signature
from corpus.legacy_recovery.artifact_security_scan import security_scan


def provenance_record(
    candidate: dict[str, Any], *, allowed_use: list[str] | None = None
) -> dict[str, Any]:
    scan = security_scan(candidate)
    digest = str(candidate.get("resolved_digest") or candidate.get("digest") or "")
    record = {
        "schema_version": "determinex-artifact-provenance-v1",
        "artifact_id": str(
            candidate.get("artifact_id") or candidate.get("image") or candidate.get("repo_id") or ""
        ),
        "artifact_type": str(candidate.get("artifact_type") or ""),
        "source": str(candidate.get("source") or ""),
        "resolved_digest": digest,
        "revision": str(candidate.get("revision") or ""),
        "tag": str(candidate.get("tag") or ""),
        "retrieved_at": datetime.now(UTC).isoformat(),
        "trust_level": str(candidate.get("trust_level") or ""),
        "license": candidate.get("license"),
        "security_scan": {
            "scanner": scan.scanner,
            "critical": scan.critical,
            "high": scan.high,
            "policy": scan.policy,
        },
        "allowed_use": allowed_use or ["programbench_replay"],
        "signature_key_scope": hmac_key_scope(),
    }
    return resign_record(record)


def write_provenance_record(record: dict[str, Any], root: Path) -> Path:
    if not verify_signature(record):
        raise ValueError("provenance record signature invalid")
    root.mkdir(parents=True, exist_ok=True)
    artifact_id = _safe_name(str(record.get("artifact_id") or "artifact"))
    pin = _safe_name(str(record.get("resolved_digest") or record.get("revision") or "unpinned"))
    path = root / f"{artifact_id}.{pin}.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != record:
            raise FileExistsError(f"refusing to replace existing pinned provenance: {path}")
        return path
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)[:160]
