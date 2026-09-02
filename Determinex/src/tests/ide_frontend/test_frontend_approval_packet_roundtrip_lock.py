"""Tests for FRONTEND_APPROVAL_PACKET_ROUNDTRIP_LOCK_001."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ide.frontend_approval_packet_roundtrip import (
    FRONTEND_APPROVAL_PACKET_ROUNDTRIP_TOKENS,
    FrontendApprovalPacketRoundtripTrace,
    run_roundtrip,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "FRONTEND_APPROVAL_PACKET_ROUNDTRIP_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "frontend_approval_packet_roundtrip"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED = frozenset(
    {
        "APPROVAL_PACKET_ROUNDTRIP_READY",
        "APPROVAL_REJECT_PATH_READY",
        "APPROVAL_FIXTURE_ONLY",
        "APPROVAL_SOURCE_MUTATION_BLOCKED",
        "APPROVAL_STALE_VISIBLE",
        "APPROVAL_DIFF_MISMATCH_VISIBLE",
        "APPROVAL_VERIFIER_FAILED_VISIBLE",
    }
)


def test_status_tokens_exact():
    assert set(FRONTEND_APPROVAL_PACKET_ROUNDTRIP_TOKENS) == EXPECTED


def test_approve_fixture_path_works():
    t = run_roundtrip()
    assert t.approve_stage.signing_decision == "IDE_APPROVAL_FIXTURE_ONLY"
    assert t.approve_stage.apply_gate_decision == "IDE_SOURCE_APPLY_DRY_RUN_READY"
    assert t.approve_stage.fixture_only is True
    # Even the "approved" stage must not authorize source mutation.
    assert t.approve_stage.source_mutation_authorized is False


def test_reject_path_blocked_apply():
    t = run_roundtrip()
    assert t.reject_stage.signing_decision == "IDE_APPROVAL_REJECTED"
    assert "BLOCKED" in t.reject_stage.apply_gate_decision


def test_stale_packet_visible():
    t = run_roundtrip()
    assert t.stale_stage.signing_decision == "IDE_APPROVAL_BLOCKED_STALE_PACKET"


def test_diff_mismatch_visible():
    t = run_roundtrip()
    assert t.diff_mismatch_stage.signing_decision == "IDE_APPROVAL_BLOCKED_DIFF_MISMATCH"


def test_verifier_failed_visible():
    t = run_roundtrip()
    assert t.verifier_failed_stage.signing_decision == "IDE_APPROVAL_BLOCKED_VERIFIER_NOT_PASSED"


def test_no_source_mutation_anywhere():
    t = run_roundtrip()
    assert t.source_mutation_authorized_anywhere is False
    assert t.training_eligible_anywhere is False


def test_trace_invariant_shape():
    t = run_roundtrip()
    assert isinstance(t, FrontendApprovalPacketRoundtripTrace)
    d = t.to_dict()
    json.dumps(d)
    assert d["source_mutation_authorized_anywhere"] is False
    assert d["training_eligible_anywhere"] is False


def test_module_does_not_spawn_subprocess_or_open_network():
    import scripts.ide.frontend_approval_packet_roundtrip as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "requests",
        "httpx",
        "urllib.request",
        "socket.connect",
        "subprocess.Popen",
        "subprocess.run",
    ):
        assert forbidden not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "FRONTEND_APPROVAL_PACKET_ROUNDTRIP_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED)
    sd = blob.get("scope_discipline", {})
    assert sd.get("user_source_mutated") is False
    assert sd.get("training_eligibility_opened") is False
    assert sd.get("network_called") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "FRONTEND_APPROVAL_PACKET_ROUNDTRIP_LOCK_001" in ids
