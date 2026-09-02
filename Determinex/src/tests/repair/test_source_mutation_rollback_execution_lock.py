"""Tests for SOURCE_MUTATION_ROLLBACK_EXECUTION_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

mod = importlib.import_module("repair.source_mutation_rollback_execution")
rec_mod = importlib.import_module("repair.source_mutation_rollback_execution_record")
snap_mod = importlib.import_module("repair.source_mutation_rollback_snapshot_record")
take_snap = importlib.import_module("repair.source_mutation_rollback_snapshot").take_snapshot
apply_mod = importlib.import_module("repair.source_mutation_apply_after_approval_record")
post_mod = importlib.import_module("repair.post_apply_verifier_record")
adm_mod = importlib.import_module("ide.real_human_approval_admission_record")
tv_mod = importlib.import_module("repair.real_temp_patch_verify_record")

execute_rollback = mod.execute_rollback
TOKENS = rec_mod.SOURCE_MUTATION_ROLLBACK_EXECUTION_STATUS_TOKENS
SourceMutationRollbackExecutionRecord = rec_mod.SourceMutationRollbackExecutionRecord
SourceMutationApplyAfterApprovalRecord = apply_mod.SourceMutationApplyAfterApprovalRecord
PostApplyVerifierRecord = post_mod.PostApplyVerifierRecord
RealHumanApprovalAdmissionRecord = adm_mod.RealHumanApprovalAdmissionRecord
RealTempPatchVerifyRecord = tv_mod.RealTempPatchVerifyRecord

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "SOURCE_MUTATION_ROLLBACK_EXECUTION_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "source_mutation_rollback_execution"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED = frozenset(
    {
        "SOURCE_ROLLBACK_EXECUTED",
        "SOURCE_ROLLBACK_NOT_REQUIRED",
        "SOURCE_ROLLBACK_BLOCKED_MISSING_SNAPSHOT",
        "SOURCE_ROLLBACK_BLOCKED_SNAPSHOT_HASH_MISMATCH",
        "SOURCE_ROLLBACK_BLOCKED_SYMLINKS_UNSUPPORTED",
    }
)


def _approval():
    return RealHumanApprovalAdmissionRecord(
        decision="REAL_HUMAN_APPROVAL_ACCEPTED",
        trace_id="trace-1",
        workspace_identity="/ws",
        diff_hash="d" * 64,
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
        operator_identity="ryan",
        operator_signature="a" * 64,
        signature_kind="real_local_signed",
        is_fixture=False,
        accepted_at="x",
        stale_after="2026-05-29T00:00:00+00:00",
    )


def _verify_passed():
    return RealTempPatchVerifyRecord(
        decision="REAL_TEMP_PATCH_VERIFIER_PASSED",
        workspace="/ws",
        temp_workspace="/tmp/x",
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
        unified_diff="",
        applied_paths=(),
        original_unchanged=True,
        original_sha256_before="a" * 64,
        original_sha256_after="a" * 64,
        human_approval_required=True,
    )


def _apply(applied=True):
    return SourceMutationApplyAfterApprovalRecord(
        decision="SOURCE_MUTATION_APPLIED_AFTER_APPROVAL" if applied else "X",
        workspace_identity="/ws",
        pre_apply_source_hash="a" * 64,
        post_apply_source_hash="b" * 64,
        applied_paths=("src/lib.py",),
        diff_hash="d" * 64,
        approval_ref="x",
        verifier_ref="x",
        rollback_snapshot_ref="x",
        source_mutation_applied=applied,
        post_apply_verifier_required=True,
    )


def _post_apply(rollback=True):
    return PostApplyVerifierRecord(
        decision="POST_APPLY_VERIFIER_FAILED" if rollback else "POST_APPLY_VERIFIER_PASSED",
        workspace_identity="/ws",
        verifier_status="PATCH_VERIFIER_FAILED" if rollback else "PATCH_VERIFIER_PASSED",
        verifier_output="x",
        post_apply_source_hash="b" * 64,
        apply_ref="x",
        rollback_snapshot_ref="x",
        rollback_recommended=rollback,
    )


def _ws_with_modifications(tmp_path):
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "lib.py").write_text("x = 1\n", encoding="utf-8")
    return ws


def _take_real_snap(tmp_path, ws):
    return take_snap(
        workspace=ws,
        snapshot_root=tmp_path / "snaps",
        snapshot_id="rb_t",
        approval=_approval(),
        temp_verify=_verify_passed(),
    )


def test_status_tokens_exact():
    assert set(TOKENS) == EXPECTED


def test_not_required_when_verifier_passed(tmp_path):
    ws = _ws_with_modifications(tmp_path)
    snap = _take_real_snap(tmp_path, ws)
    # Now mutate the workspace so we can prove rollback is NOT executed.
    (ws / "src" / "lib.py").write_text("MUTATED\n", encoding="utf-8")
    r = execute_rollback(
        workspace=ws,
        rollback_snapshot=snap,
        apply_record=_apply(),
        post_apply=_post_apply(rollback=False),
    )
    assert r.decision == "SOURCE_ROLLBACK_NOT_REQUIRED"
    # Mutation preserved — we did not restore.
    assert (ws / "src" / "lib.py").read_text(encoding="utf-8") == "MUTATED\n"


def test_missing_snapshot_blocks_rollback(tmp_path):
    ws = _ws_with_modifications(tmp_path)
    r = execute_rollback(
        workspace=ws,
        rollback_snapshot=None,
        apply_record=_apply(),
        post_apply=_post_apply(rollback=True),
    )
    assert r.decision == "SOURCE_ROLLBACK_BLOCKED_MISSING_SNAPSHOT"


def test_snapshot_dir_missing_blocks_rollback(tmp_path):
    ws = _ws_with_modifications(tmp_path)
    snap = _take_real_snap(tmp_path, ws)
    # Delete the snapshot directory on disk.
    import shutil as _sh

    _sh.rmtree(snap.snapshot_path)
    r = execute_rollback(
        workspace=ws,
        rollback_snapshot=snap,
        apply_record=_apply(),
        post_apply=_post_apply(rollback=True),
    )
    assert r.decision == "SOURCE_ROLLBACK_BLOCKED_MISSING_SNAPSHOT"


def test_snapshot_hash_drift_blocks_rollback(tmp_path):
    ws = _ws_with_modifications(tmp_path)
    snap = _take_real_snap(tmp_path, ws)
    # Mutate snapshot after creation.
    (Path(snap.snapshot_path) / "src" / "lib.py").write_text("TAINTED\n", encoding="utf-8")
    r = execute_rollback(
        workspace=ws,
        rollback_snapshot=snap,
        apply_record=_apply(),
        post_apply=_post_apply(rollback=True),
    )
    assert r.decision == "SOURCE_ROLLBACK_BLOCKED_SNAPSHOT_HASH_MISMATCH"


def test_happy_path_restores_workspace(tmp_path):
    ws = _ws_with_modifications(tmp_path)
    snap = _take_real_snap(tmp_path, ws)
    # Simulate a "bad apply" — corrupt the workspace.
    (ws / "src" / "lib.py").write_text("BROKEN\n", encoding="utf-8")
    (ws / "extra.py").write_text("introduced by bad apply\n", encoding="utf-8")
    r = execute_rollback(
        workspace=ws,
        rollback_snapshot=snap,
        apply_record=_apply(),
        post_apply=_post_apply(rollback=True),
    )
    assert r.decision == "SOURCE_ROLLBACK_EXECUTED"
    # Original content restored.
    assert (ws / "src" / "lib.py").read_text(encoding="utf-8") == "x = 1\n"
    # File not present in snapshot got removed.
    assert not (ws / "extra.py").exists()
    # Hashes recorded.
    assert r.pre_rollback_source_hash
    assert r.post_rollback_source_hash
    assert r.snapshot_verified_tree_hash
    assert r.training_eligible is False


def test_record_serializes_safely(tmp_path):
    ws = _ws_with_modifications(tmp_path)
    snap = _take_real_snap(tmp_path, ws)
    r = execute_rollback(
        workspace=ws,
        rollback_snapshot=snap,
        apply_record=_apply(),
        post_apply=_post_apply(rollback=False),
    )
    d = r.to_dict()
    json.dumps(d)
    assert d["training_eligible"] is False


def test_module_does_not_open_network():
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
    assert blob["lock_id"] == "SOURCE_MUTATION_ROLLBACK_EXECUTION_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED)
    sd = blob.get("scope_discipline", {})
    assert sd.get("training_eligibility_opened") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "SOURCE_MUTATION_ROLLBACK_EXECUTION_LOCK_001" in ids
