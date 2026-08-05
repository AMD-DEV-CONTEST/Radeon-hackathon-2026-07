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
class CleanroomRecipeProvenanceRecoveryRecord:
    schema_version: str
    record_type: str
    status: str
    decision: str
    image_reference: str
    image_digest: str
    provenance_gap: str
    remediation_plan: str
    recipe_recovery: str
    searched_locations: list[dict[str, Any]] = field(default_factory=list)
    recovered_provenance: list[dict[str, Any]] = field(default_factory=list)
    provenance_statuses: list[str] = field(default_factory=list)
    gap_closure: dict[str, Any] = field(default_factory=dict)
    go_remediation: dict[str, Any] = field(default_factory=dict)
    fidelity_assessment: dict[str, Any] = field(default_factory=dict)
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


def make_cleanroom_recipe_provenance_recovery_record(
    *,
    status: str,
    decision: str,
    image_reference: str,
    image_digest: str,
    provenance_gap: str,
    remediation_plan: str,
    recipe_recovery: str,
    searched_locations: list[dict[str, Any]] | None = None,
    recovered_provenance: list[dict[str, Any]] | None = None,
    provenance_statuses: list[str] | None = None,
    gap_closure: dict[str, Any] | None = None,
    go_remediation: dict[str, Any] | None = None,
    fidelity_assessment: dict[str, Any] | None = None,
    authorization: dict[str, bool] | None = None,
    reasons: list[str] | None = None,
    cache_ready: bool = False,
    executable: bool = False,
) -> dict[str, Any]:
    return CleanroomRecipeProvenanceRecoveryRecord(
        schema_version="determinex-programbench-cleanroom-recipe-provenance-recovery-v1",
        record_type="programbench_cleanroom_recipe_provenance_recovery",
        status=status,
        decision=decision,
        image_reference=image_reference,
        image_digest=image_digest,
        provenance_gap=provenance_gap,
        remediation_plan=remediation_plan,
        recipe_recovery=recipe_recovery,
        searched_locations=searched_locations or [],
        recovered_provenance=recovered_provenance or [],
        provenance_statuses=provenance_statuses or [],
        gap_closure=gap_closure or {},
        go_remediation=go_remediation or {},
        fidelity_assessment=fidelity_assessment or {},
        authorization=authorization or {},
        reasons=reasons or [],
        cache_ready=cache_ready,
        executable=executable,
    ).signed()


def verify_cleanroom_recipe_provenance_recovery_record(record: dict[str, Any]) -> bool:
    signature = str(record.get("record_signature") or "")
    if not signature:
        return False
    return hmac.compare_digest(signature, _signature(record))


def write_cleanroom_recipe_provenance_recovery_record(
    record: dict[str, Any], output_dir: Path
) -> Path:
    if not verify_cleanroom_recipe_provenance_recovery_record(record):
        raise ValueError("cleanroom recipe provenance recovery record signature invalid")
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
    raw = os.environ.get("DETERMINEX_CLEANROOM_RECIPE_PROVENANCE_RECOVERY_KEY", "").strip()
    if raw:
        try:
            key = bytes.fromhex(raw)
            if len(key) >= 32:
                return key
        except ValueError:
            pass
    return b"determinex-cleanroom-recipe-provenance-recovery-lock-001-test-key"


def _canonical_json(record: dict[str, Any]) -> bytes:
    raw = json.dumps(record, sort_keys=True, ensure_ascii=True)
    return unicodedata.normalize("NFC", raw).encode()


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)[:160]
