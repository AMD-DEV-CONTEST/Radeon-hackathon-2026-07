from __future__ import annotations

import hashlib
import hmac
import json
import os
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from corpus.programbench.root_cause_packet_schema import REQUIRED_PACKET_FIELDS


def make_root_cause_packet(
    *,
    packet_id: str,
    benchmark_name: str,
    candidate_id: str,
    baseline_score: str,
    candidate_score: str,
    score_delta: str,
    baseline_artifact_reference: str,
    candidate_artifact_reference: str,
    failing_tests: list[str],
    regression_diff_summary: str,
    suspected_patch_location: str,
    suspected_failure_class: str,
    repair_hypothesis: str,
    expected_score_recovery: str,
    rerun_scope: dict[str, Any],
    evidence_inputs: list[str],
    previously_passing_now_failing_tests: list[str] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    packet = {
        "packet_id": packet_id,
        "benchmark_name": benchmark_name,
        "candidate_id": candidate_id,
        "baseline_score": baseline_score,
        "candidate_score": candidate_score,
        "score_delta": score_delta,
        "baseline_artifact_reference": baseline_artifact_reference,
        "candidate_artifact_reference": candidate_artifact_reference,
        "failing_tests": failing_tests,
        "previously_passing_now_failing_tests": previously_passing_now_failing_tests or [],
        "regression_diff_summary": regression_diff_summary,
        "suspected_patch_location": suspected_patch_location,
        "suspected_failure_class": suspected_failure_class,
        "repair_hypothesis": repair_hypothesis,
        "expected_score_recovery": expected_score_recovery,
        "rerun_scope": rerun_scope,
        "evidence_inputs": evidence_inputs,
        "created_at": created_at or datetime.now(UTC).isoformat(),
    }
    return sign_packet(packet)


def sign_packet(packet: dict[str, Any]) -> dict[str, Any]:
    signed = dict(packet)
    signed["packet_signature"] = _signature(signed)
    return signed


def verify_packet_signature(packet: dict[str, Any]) -> bool:
    signature = str(packet.get("packet_signature") or "")
    if not signature:
        return False
    return hmac.compare_digest(signature, _signature(packet))


def packet_hash(packet: dict[str, Any]) -> str:
    payload = {k: v for k, v in packet.items() if k != "packet_signature"}
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def missing_required_fields(packet: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field in REQUIRED_PACKET_FIELDS:
        value = packet.get(field)
        if value is None or value == "" or value == [] or value == {}:
            missing.append(field)
    return missing


@dataclass(slots=True)
class EvidenceReference:
    path: str
    expected_sha256: str = ""
    expected_score: str = ""
    superseded_by: str = ""


@dataclass(slots=True)
class EvidenceCheckResult:
    conflicts: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.conflicts and not self.stale and not self.missing


def check_evidence_references(packet: dict[str, Any], root: Path) -> EvidenceCheckResult:
    result = EvidenceCheckResult()
    refs = [
        _reference(packet.get("baseline_artifact_reference")),
        _reference(packet.get("candidate_artifact_reference")),
    ]
    for ref in refs:
        if ref is None:
            result.missing.append("artifact_reference_missing")
            continue
        if ref.superseded_by:
            result.stale.append(f"superseded:{ref.path}->{ref.superseded_by}")
        path = root / ref.path
        if not path.is_file():
            result.missing.append(f"artifact_not_found:{ref.path}")
            continue
        if ref.expected_sha256:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != ref.expected_sha256:
                result.conflicts.append(f"sha256_mismatch:{ref.path}")
        if ref.expected_score:
            score = _score_from_artifact(path)
            if score and score != ref.expected_score:
                result.conflicts.append(f"score_mismatch:{ref.path}:{score}!={ref.expected_score}")
    return result


def write_packet(packet: dict[str, Any], output_dir: Path) -> Path:
    if not verify_packet_signature(packet):
        raise ValueError("root-cause packet signature invalid")
    output_dir.mkdir(parents=True, exist_ok=True)
    packet_id = _safe_name(str(packet.get("packet_id") or "packet"))
    path = output_dir / f"{packet_id}.json"
    path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _reference(raw: Any) -> EvidenceReference | None:
    if isinstance(raw, str):
        return EvidenceReference(path=raw)
    if not isinstance(raw, dict):
        return None
    return EvidenceReference(
        path=str(raw.get("path") or ""),
        expected_sha256=str(raw.get("sha256") or ""),
        expected_score=str(raw.get("score") or ""),
        superseded_by=str(raw.get("superseded_by") or ""),
    )


def _score_from_artifact(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return ""
    for key in ("score", "passed", "candidate_score", "baseline_score"):
        if data.get(key) is not None:
            return str(data[key])
    return ""


def _signature(packet: dict[str, Any]) -> str:
    payload = {k: v for k, v in packet.items() if k != "packet_signature"}
    return hmac.new(_packet_key(), _canonical_json(payload), hashlib.blake2b).hexdigest()


def _packet_key() -> bytes:
    raw = os.environ.get("DETERMINEX_ROOT_CAUSE_PACKET_KEY", "").strip()
    if raw:
        try:
            key = bytes.fromhex(raw)
            if len(key) >= 32:
                return key
        except ValueError:
            pass
    return b"determinex-root-cause-packet-lock-001-test-key"


def _canonical_json(packet: dict[str, Any]) -> bytes:
    raw = json.dumps(packet, sort_keys=True, ensure_ascii=True)
    return unicodedata.normalize("NFC", raw).encode()


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)[:160]
