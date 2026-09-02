"""Tests for HUMAN_APPROVAL_PACKET_UI_MODEL_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

ui_mod = importlib.import_module("ide.human_approval_ui_model")
rec_mod = importlib.import_module("ide.human_approval_ui_record")

build_packet = ui_mod.build_packet
evaluate_submitted = ui_mod.evaluate_submitted
HumanApprovalPacket = rec_mod.HumanApprovalPacket
HUMAN_APPROVAL_PACKET_UI_STATUS_TOKENS = rec_mod.HUMAN_APPROVAL_PACKET_UI_STATUS_TOKENS

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "HUMAN_APPROVAL_PACKET_UI_MODEL_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "human_approval_packet_ui_model"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(HUMAN_APPROVAL_PACKET_UI_STATUS_TOKENS)


def _sample_packet(diff: str = "--- a\n+++ b\n@@ -1 +1 @@\n-x\n+y\n"):
    return build_packet(
        trace_id="trace-abc",
        workspace_identity="/some/workspace",
        unified_diff=diff,
        files_changed=("src/lib.py",),
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
        model_route_ref="ROUTE_SELECTED",
        patch_plan_ref="PATCH_PLAN_QUARANTINED",
        temp_patch_ref="LIVE_PATCH_VERIFIER_PASSED_TEMP_ONLY",
        risk_summary="risk: low",
    )


def test_status_tokens_match_expected_set():
    expected = {
        "HUMAN_APPROVAL_PACKET_WRITTEN",
        "HUMAN_APPROVAL_REQUIRED",
        "HUMAN_APPROVAL_BLOCKED_MISSING_PACKET",
        "HUMAN_APPROVAL_BLOCKED_STALE_PACKET",
        "HUMAN_APPROVAL_BLOCKED_DIFF_MISMATCH",
        "HUMAN_APPROVAL_BLOCKED_VERIFIER_NOT_PASSED",
    }
    assert set(STATUS_TOKENS) == expected


def test_build_packet_writes_packet():
    p = _sample_packet()
    assert p.decision == "HUMAN_APPROVAL_PACKET_WRITTEN"
    assert p.approval_required is True
    assert p.approval_status == "REQUIRED"


def test_evaluate_missing_packet():
    res = evaluate_submitted(
        None,
        observed_diff="x",
        observed_verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    assert res == "HUMAN_APPROVAL_BLOCKED_MISSING_PACKET"


def test_evaluate_stale_packet():
    p = _sample_packet()
    # Force stale by setting stale_after to a past timestamp.
    p2 = HumanApprovalPacket(
        **{
            **p.to_dict(),
            "stale_after": "2000-01-01T00:00:00+00:00",
            "files_changed": tuple(p.files_changed),
            "notes": tuple(p.notes),
        }
    )
    res = evaluate_submitted(
        p2, observed_diff="x", observed_verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY"
    )
    assert res == "HUMAN_APPROVAL_BLOCKED_STALE_PACKET"


def test_evaluate_diff_mismatch():
    p = _sample_packet(diff="aaaa")
    res = evaluate_submitted(
        p, observed_diff="bbbb", observed_verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY"
    )
    assert res == "HUMAN_APPROVAL_BLOCKED_DIFF_MISMATCH"


def test_evaluate_verifier_not_passed():
    diff = "--- a\n+++ b\n"
    p = _sample_packet(diff=diff)
    res = evaluate_submitted(
        p, observed_diff=diff, observed_verifier_status="PATCH_VERIFIER_FAILED"
    )
    assert res == "HUMAN_APPROVAL_BLOCKED_VERIFIER_NOT_PASSED"


def test_evaluate_required_when_all_match():
    diff = "--- a\n+++ b\n"
    p = _sample_packet(diff=diff)
    res = evaluate_submitted(
        p, observed_diff=diff, observed_verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY"
    )
    assert res == "HUMAN_APPROVAL_REQUIRED"


def test_packet_json_round_trip():
    p = _sample_packet()
    parsed = json.loads(p.to_json())
    assert parsed["approval_required"] is True
    assert parsed["decision"] == "HUMAN_APPROVAL_PACKET_WRITTEN"


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("human_approval_ui_model.py", "human_approval_ui_record.py"):
        src = (_REPO_ROOT / "scripts" / "ide" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "import urllib" not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "HUMAN_APPROVAL_PACKET_UI_MODEL_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "HUMAN_APPROVAL_PACKET_UI_MODEL_LOCK_001" in ids
