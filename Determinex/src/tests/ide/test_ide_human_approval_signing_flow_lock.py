"""Tests for IDE_HUMAN_APPROVAL_SIGNING_FLOW_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

flow_mod = importlib.import_module("ide.human_approval_signing_flow")
rec_mod = importlib.import_module("ide.human_approval_signing_record")
ui_mod = importlib.import_module("ide.human_approval_ui_model")
ui_rec = importlib.import_module("ide.human_approval_ui_record")

IDEHumanApprovalSigningFlow = flow_mod.IDEHumanApprovalSigningFlow
ApprovalAction = rec_mod.ApprovalAction
IDE_HUMAN_APPROVAL_SIGNING_STATUS_TOKENS = rec_mod.IDE_HUMAN_APPROVAL_SIGNING_STATUS_TOKENS
build_packet = ui_mod.build_packet
HumanApprovalPacket = ui_rec.HumanApprovalPacket

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "IDE_HUMAN_APPROVAL_SIGNING_FLOW_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "ide_human_approval_signing_flow"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(IDE_HUMAN_APPROVAL_SIGNING_STATUS_TOKENS)


def _pkt(diff: str = "--- a\n+++ b\n"):
    return build_packet(
        trace_id="t1",
        workspace_identity="/ws",
        unified_diff=diff,
        files_changed=("src/x.py",),
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )


def test_status_tokens_match_expected_set():
    expected = {
        "IDE_APPROVAL_PACKET_READY",
        "IDE_APPROVAL_REQUIRED",
        "IDE_APPROVAL_REJECTED",
        "IDE_APPROVAL_BLOCKED_STALE_PACKET",
        "IDE_APPROVAL_BLOCKED_DIFF_MISMATCH",
        "IDE_APPROVAL_BLOCKED_VERIFIER_NOT_PASSED",
        "IDE_APPROVAL_FIXTURE_ONLY",
        "IDE_APPROVAL_BLOCKED_OPERATOR_EMPTY",
    }
    assert set(STATUS_TOKENS) == expected


def test_empty_operator_blocked():
    p = _pkt()
    r = IDEHumanApprovalSigningFlow().submit(
        p,
        action="approve",
        operator_identity="",
        observed_diff="--- a\n+++ b\n",
        observed_verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    assert r.decision == "IDE_APPROVAL_BLOCKED_OPERATOR_EMPTY"
    assert r.source_mutation_authorized is False


def test_fixture_approve_signs_but_does_not_authorize():
    diff = "--- a\n+++ b\n"
    p = _pkt(diff)
    r = IDEHumanApprovalSigningFlow().submit(
        p,
        action="approve",
        operator_identity="ryan",
        observed_diff=diff,
        observed_verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
        fixture=True,
    )
    assert r.decision == "IDE_APPROVAL_FIXTURE_ONLY"
    assert r.operator_signature != ""
    # Source mutation NEVER opened by signing.
    assert r.source_mutation_authorized is False
    assert r.training_eligible is False


def test_reject_clean():
    diff = "--- a\n+++ b\n"
    p = _pkt(diff)
    r = IDEHumanApprovalSigningFlow().submit(
        p,
        action="reject",
        operator_identity="ryan",
        observed_diff=diff,
        observed_verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    assert r.decision == "IDE_APPROVAL_REJECTED"
    assert r.source_mutation_authorized is False


def test_stale_packet_blocked():
    diff = "--- a\n+++ b\n"
    p = _pkt(diff)
    p2 = HumanApprovalPacket(
        **{
            **p.to_dict(),
            "stale_after": "2000-01-01T00:00:00+00:00",
            "files_changed": tuple(p.files_changed),
            "notes": tuple(p.notes),
        }
    )
    r = IDEHumanApprovalSigningFlow().submit(
        p2,
        action="approve",
        operator_identity="ryan",
        observed_diff=diff,
        observed_verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    assert r.decision == "IDE_APPROVAL_BLOCKED_STALE_PACKET"


def test_diff_mismatch_blocked():
    p = _pkt("aaaa")
    r = IDEHumanApprovalSigningFlow().submit(
        p,
        action="approve",
        operator_identity="ryan",
        observed_diff="bbbb",
        observed_verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    assert r.decision == "IDE_APPROVAL_BLOCKED_DIFF_MISMATCH"


def test_verifier_not_passed_blocked():
    diff = "--- a\n+++ b\n"
    p = _pkt(diff)
    r = IDEHumanApprovalSigningFlow().submit(
        p,
        action="approve",
        operator_identity="ryan",
        observed_diff=diff,
        observed_verifier_status="PATCH_VERIFIER_FAILED",
    )
    assert r.decision == "IDE_APPROVAL_BLOCKED_VERIFIER_NOT_PASSED"


def test_deferred_action_required():
    diff = "--- a\n+++ b\n"
    p = _pkt(diff)
    r = IDEHumanApprovalSigningFlow().submit(
        p,
        action="deferred",
        operator_identity="ryan",
        observed_diff=diff,
        observed_verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    assert r.decision == "IDE_APPROVAL_REQUIRED"


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("human_approval_signing_flow.py", "human_approval_signing_record.py"):
        src = (_REPO_ROOT / "scripts" / "ide" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "import urllib" not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "IDE_HUMAN_APPROVAL_SIGNING_FLOW_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "IDE_HUMAN_APPROVAL_SIGNING_FLOW_LOCK_001" in ids
