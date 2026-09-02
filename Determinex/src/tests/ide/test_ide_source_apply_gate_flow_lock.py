"""Tests for IDE_SOURCE_APPLY_GATE_FLOW_LOCK_001."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

gate_mod = importlib.import_module("ide.source_apply_gate_flow")
rec_mod = importlib.import_module("ide.source_apply_gate_record")
signing_mod = importlib.import_module("ide.human_approval_signing_flow")
ui_mod = importlib.import_module("ide.human_approval_ui_model")

IDESourceApplyGateFlow = gate_mod.IDESourceApplyGateFlow
workspace_hash = gate_mod.workspace_hash
IDE_SOURCE_APPLY_GATE_STATUS_TOKENS = rec_mod.IDE_SOURCE_APPLY_GATE_STATUS_TOKENS
IDEHumanApprovalSigningFlow = signing_mod.IDEHumanApprovalSigningFlow
build_packet = ui_mod.build_packet

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "IDE_SOURCE_APPLY_GATE_FLOW_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "ide_source_apply_gate_flow"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(IDE_SOURCE_APPLY_GATE_STATUS_TOKENS)


def _seed(tmp_path: Path) -> Path:
    ws = tmp_path / "orig"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "lib.py").write_text("x = 0\n", encoding="utf-8")
    return ws


def _hash_tree(root: Path):
    out = {}
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        try:
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
        except (OSError, PermissionError):
            continue
    return out


def _packet_and_signing(ws, diff="--- a\n+++ b\n"):
    packet = build_packet(
        trace_id="t1",
        workspace_identity=str(ws),
        unified_diff=diff,
        files_changed=("src/lib.py",),
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    signing = IDEHumanApprovalSigningFlow().submit(
        packet,
        action="approve",
        operator_identity="ryan",
        observed_diff=diff,
        observed_verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
        fixture=True,
    )
    return packet, signing


def test_status_tokens_match_expected_set():
    expected = {
        "IDE_SOURCE_APPLY_BLOCKED_NO_APPROVAL",
        "IDE_SOURCE_APPLY_BLOCKED_STALE_SOURCE",
        "IDE_SOURCE_APPLY_BLOCKED_DIFF_MISMATCH",
        "IDE_SOURCE_APPLY_BLOCKED_VERIFIER_NOT_PASSED",
        "IDE_SOURCE_APPLY_DRY_RUN_READY",
        "IDE_SOURCE_APPLY_SOURCE_UNCHANGED",
        "IDE_SOURCE_APPLY_FIXTURE_ONLY",
        "IDE_SOURCE_APPLY_BLOCKED_NOT_SIGNED",
    }
    assert set(STATUS_TOKENS) == expected


def test_fixture_only_signing_yields_dry_run_ready(tmp_path):
    ws = _seed(tmp_path)
    diff = "--- a/src/lib.py\n+++ b/src/lib.py\n@@ -1 +1 @@\n-x = 0\n+x = 1\n"
    packet, signing = _packet_and_signing(ws, diff=diff)
    before = _hash_tree(ws)
    rec = IDESourceApplyGateFlow().evaluate(
        ws,
        signing=signing,
        packet=packet,
        observed_diff=diff,
        observed_source_hash_at_packet_time=workspace_hash(ws),
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    assert rec.decision == "IDE_SOURCE_APPLY_DRY_RUN_READY"
    assert "IDE_SOURCE_APPLY_FIXTURE_ONLY" in rec.statuses_seen
    assert rec.source_mutation_authorized is False
    assert _hash_tree(ws) == before


def test_no_approval_blocks(tmp_path):
    ws = _seed(tmp_path)
    rec = IDESourceApplyGateFlow().evaluate(
        ws,
        signing=None,
        packet=None,
        observed_diff="x",
        observed_source_hash_at_packet_time=workspace_hash(ws),
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    assert rec.decision == "IDE_SOURCE_APPLY_BLOCKED_NO_APPROVAL"


def test_rejected_signing_blocks(tmp_path):
    ws = _seed(tmp_path)
    diff = "x"
    packet = build_packet(
        trace_id="t1",
        workspace_identity=str(ws),
        unified_diff=diff,
        files_changed=("src/lib.py",),
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    signing = IDEHumanApprovalSigningFlow().submit(
        packet,
        action="reject",
        operator_identity="ryan",
        observed_diff=diff,
        observed_verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    rec = IDESourceApplyGateFlow().evaluate(
        ws,
        signing=signing,
        packet=packet,
        observed_diff=diff,
        observed_source_hash_at_packet_time=workspace_hash(ws),
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    assert rec.decision == "IDE_SOURCE_APPLY_BLOCKED_NOT_SIGNED"


def test_stale_source_blocks(tmp_path):
    ws = _seed(tmp_path)
    diff = "x"
    packet, signing = _packet_and_signing(ws, diff=diff)
    rec = IDESourceApplyGateFlow().evaluate(
        ws,
        signing=signing,
        packet=packet,
        observed_diff=diff,
        observed_source_hash_at_packet_time="stale",
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    assert rec.decision == "IDE_SOURCE_APPLY_BLOCKED_STALE_SOURCE"


def test_verifier_not_passed_blocks(tmp_path):
    ws = _seed(tmp_path)
    diff = "x"
    packet, signing = _packet_and_signing(ws, diff=diff)
    rec = IDESourceApplyGateFlow().evaluate(
        ws,
        signing=signing,
        packet=packet,
        observed_diff=diff,
        observed_source_hash_at_packet_time=workspace_hash(ws),
        verifier_status="PATCH_VERIFIER_FAILED",
    )
    assert rec.decision == "IDE_SOURCE_APPLY_BLOCKED_VERIFIER_NOT_PASSED"


def test_diff_mismatch_blocks(tmp_path):
    ws = _seed(tmp_path)
    packet, signing = _packet_and_signing(ws, diff="aaaa")
    rec = IDESourceApplyGateFlow().evaluate(
        ws,
        signing=signing,
        packet=packet,
        observed_diff="bbbb",
        observed_source_hash_at_packet_time=workspace_hash(ws),
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    assert rec.decision == "IDE_SOURCE_APPLY_BLOCKED_DIFF_MISMATCH"


def test_gate_never_mutates_workspace(tmp_path):
    ws = _seed(tmp_path)
    before = _hash_tree(ws)
    diff = "x"
    packet, signing = _packet_and_signing(ws, diff=diff)
    IDESourceApplyGateFlow().evaluate(
        ws,
        signing=signing,
        packet=packet,
        observed_diff=diff,
        observed_source_hash_at_packet_time=workspace_hash(ws),
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    assert _hash_tree(ws) == before


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("source_apply_gate_flow.py", "source_apply_gate_record.py"):
        src = (_REPO_ROOT / "scripts" / "ide" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "import urllib" not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "IDE_SOURCE_APPLY_GATE_FLOW_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "IDE_SOURCE_APPLY_GATE_FLOW_LOCK_001" in ids
