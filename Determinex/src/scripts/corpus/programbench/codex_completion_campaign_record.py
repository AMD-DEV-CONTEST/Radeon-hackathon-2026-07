from __future__ import annotations

import hashlib
import hmac
import json
import os
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def make_campaign_record(
    *,
    record_type: str,
    schema_version: str,
    status: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    record = {
        "schema_version": schema_version,
        "record_type": record_type,
        "status": status,
        "record_status": "active_eval_evidence",
        "created_at": datetime.now(UTC).isoformat(),
        **payload,
    }
    record["record_signature"] = _signature(record)
    return record


def verify_campaign_record(record: dict[str, Any]) -> bool:
    signature = str(record.get("record_signature") or "")
    if not signature:
        return False
    return hmac.compare_digest(signature, _signature(record))


def write_campaign_record(
    record: dict[str, Any], output_dir: Path, *, name_key: str = "image_reference"
) -> Path:
    if not verify_campaign_record(record):
        raise ValueError(f"{record.get('record_type', 'campaign')} record signature invalid")
    output_dir = _test_redirected_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    name = _safe(
        str(
            record.get(name_key)
            or record.get("instance_id")
            or record.get("record_type")
            or "record"
        )
    )
    status = _safe(str(record.get("status") or "status"))
    path = output_dir / f"{name}.{status}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _test_redirected_output_dir(output_dir: Path) -> Path:
    override = os.environ.get("DETERMINEX_PROGRAMBENCH_EVIDENCE_WRITE_ROOT", "").strip()
    if not override:
        return output_dir

    parts = output_dir.parts
    lowered = [part.lower() for part in parts]
    try:
        evidence_idx = lowered.index("evidence")
    except ValueError:
        return output_dir

    if evidence_idx == 0 or lowered[evidence_idx - 1] != "assurance":
        return output_dir

    rel_parts = parts[evidence_idx + 1 :]
    return Path(override).joinpath(*rel_parts)


def _signature(record: dict[str, Any]) -> str:
    payload = {k: v for k, v in record.items() if k != "record_signature"}
    return hmac.new(_record_key(), _canonical_json(payload), hashlib.blake2b).hexdigest()


def _record_key() -> bytes:
    raw = os.environ.get("DETERMINEX_PROGRAMBENCH_CODEX_COMPLETION_CAMPAIGN_KEY", "").strip()
    if raw:
        try:
            key = bytes.fromhex(raw)
            if len(key) >= 32:
                return key
        except ValueError:
            pass
    return b"determinex-programbench-codex-completion-campaign-lock-001-test-key"


def _canonical_json(record: dict[str, Any]) -> bytes:
    raw = json.dumps(record, sort_keys=True, ensure_ascii=True)
    return unicodedata.normalize("NFC", raw).encode()


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)[:160]
