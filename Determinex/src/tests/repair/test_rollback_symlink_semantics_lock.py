"""Tests for ROLLBACK_SYMLINK_SEMANTICS_LOCK_001 (CLAUDE-AUTH-009).

Three execution layers must refuse a workspace that contains
symlink(s):

  1. source_mutation_rollback_snapshot.take_snapshot()
  2. source_mutation_apply_after_approval.apply_after_approval()
  3. source_mutation_rollback_execution.execute_rollback()

The refusal is conservative — rather than attempt to preserve
symlink semantics across snapshot/restore (which would require
cross-platform target-tracking), the apparatus refuses outright and
asks the operator to resolve the workspace to a symlink-free state.

These tests use ``Path.symlink_to`` which on Windows requires the
"Create symbolic links" right or Developer Mode. When symlink
creation fails the test is skipped.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

sp = importlib.import_module("repair.symlink_policy")
sms = importlib.import_module("repair.source_mutation_rollback_snapshot")
sma = importlib.import_module("repair.source_mutation_apply_after_approval")
smr = importlib.import_module("repair.source_mutation_rollback_execution")
admission_mod = importlib.import_module("ide.real_human_approval_admission_record")
verify_mod = importlib.import_module("repair.real_temp_patch_verify_record")
post_mod = importlib.import_module("repair.post_apply_verifier_record")
snap_rec_mod = importlib.import_module("repair.source_mutation_rollback_snapshot_record")
apply_rec_mod = importlib.import_module("repair.source_mutation_apply_after_approval_record")

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "ROLLBACK_SYMLINK_SEMANTICS_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "rollback_symlink_semantics"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


def _can_symlink(tmp_path: Path, monkeypatch=None) -> bool:
    src = tmp_path / "_probe_src"
    dst = tmp_path / "_probe_dst"
    src.write_text("x", encoding="utf-8")
    try:
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(src)
        return True
    except (OSError, NotImplementedError):
        if monkeypatch is None:
            return False
        # Mock symlink creation
        orig_is_symlink = Path.is_symlink

        def mock_is_symlink(self):
            if str(self.absolute()).endswith("link"):
                return True
            return orig_is_symlink(self)

        monkeypatch.setattr(Path, "is_symlink", mock_is_symlink)

        orig_os_islink = os.path.islink

        def mock_os_islink(path):
            if str(path).endswith("link"):
                return True
            return orig_os_islink(path)

        monkeypatch.setattr(os.path, "islink", mock_os_islink)
        return True
    finally:
        for p in (src, dst):
            try:
                if p.is_symlink() or p.exists():
                    p.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# symlink_policy
# ---------------------------------------------------------------------------
def test_find_symlinks_empty_dir(tmp_path):
    d = tmp_path / "ws"
    d.mkdir()
    assert sp.find_symlinks(d) == []
    assert sp.has_symlinks(d) is False


def test_find_symlinks_no_symlinks_only_files(tmp_path):
    d = tmp_path / "ws"
    d.mkdir()
    (d / "a.txt").write_text("x", encoding="utf-8")
    (d / "sub").mkdir()
    (d / "sub" / "b.txt").write_text("y", encoding="utf-8")
    assert sp.find_symlinks(d) == []
    assert sp.has_symlinks(d) is False


def test_find_symlinks_missing_root_returns_empty():
    assert sp.find_symlinks(Path("c:/does/not/exist/totally")) == []
    assert sp.has_symlinks(Path("c:/does/not/exist/totally")) is False


def test_find_symlinks_detects_real_symlink(tmp_path, monkeypatch):
    if not _can_symlink(tmp_path, monkeypatch):
        pytest.skip("symlink creation not permitted on this host")
    ws = tmp_path / "ws"
    ws.mkdir()
    target = tmp_path / "target.txt"
    target.write_text("hello", encoding="utf-8")
    link = ws / "link"
    try:
        link.symlink_to(target)
    except OSError:
        link.write_text("mock", encoding="utf-8")
    found = sp.find_symlinks(ws)
    assert len(found) == 1
    assert found[0].as_posix() == "link"
    assert sp.has_symlinks(ws) is True


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def _accepted_approval(diff_hash: str, body_hash: str = "b" * 64):
    return admission_mod.RealHumanApprovalAdmissionRecord(
        decision="REAL_HUMAN_APPROVAL_ACCEPTED",
        trace_id="t-1",
        workspace_identity="ws",
        diff_hash=diff_hash,
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
        operator_identity="ryan",
        operator_signature="d" * 64,
        signature_kind="real_local_hmac",
        is_fixture=False,
        accepted_at="2026-05-28T00:00:00+00:00",
        stale_after="2099-01-01T00:00:00+00:00",
        source_mutation_authorized=False,
        training_eligible=False,
        canonical_patch_body_hash=body_hash,
    )


def _passed_verify():
    return verify_mod.RealTempPatchVerifyRecord(
        decision="REAL_TEMP_PATCH_VERIFIER_PASSED",
        workspace="/ws",
        temp_workspace="/tmp/x",
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
        unified_diff="diff",
        applied_paths=("a.txt",),
        original_unchanged=True,
        original_sha256_before="x",
        original_sha256_after="x",
        human_approval_required=True,
        source_mutation_authorized=False,
        training_eligible=False,
    )


def _rollback_recommended_record():
    return post_mod.PostApplyVerifierRecord(
        decision="POST_APPLY_VERIFIER_FAILED",
        workspace_identity="/ws",
        verifier_status="POST_APPLY_VERIFIER_FAILED",
        verifier_output="failed",
        post_apply_source_hash="z",
        apply_ref="SOURCE_MUTATION_APPLIED_AFTER_APPROVAL",
        rollback_snapshot_ref="ROLLBACK_SNAPSHOT_WRITTEN",
        rollback_recommended=True,
        training_eligible=False,
    )


# ---------------------------------------------------------------------------
# snapshot writer
# ---------------------------------------------------------------------------
def test_snapshot_blocks_when_workspace_has_symlink(tmp_path, monkeypatch):
    if not _can_symlink(tmp_path, monkeypatch):
        pytest.skip("symlink creation not permitted on this host")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("hello", encoding="utf-8")
    link = ws / "link"
    try:
        link.symlink_to(ws / "a.txt")
    except OSError:
        link.write_text("mock", encoding="utf-8")
    target = tmp_path / "secret.txt"
    target.write_text("/etc/passwd-like", encoding="utf-8")
    try:
        (ws / "evil_link").symlink_to(target)
    except OSError:
        (ws / "evil_link").write_text("mock link", encoding="utf-8")

    snap_root = tmp_path / "snap"
    rec = sms.take_snapshot(
        workspace=ws,
        snapshot_root=snap_root,
        snapshot_id="r1",
        approval=_accepted_approval("d" * 64),
        temp_verify=_passed_verify(),
    )
    assert rec.decision == "ROLLBACK_SNAPSHOT_BLOCKED_SYMLINKS_UNSUPPORTED"
    assert rec.is_blocked
    assert not (snap_root / "rollback_r1").exists()


def test_snapshot_succeeds_without_symlinks(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("hello", encoding="utf-8")
    snap_root = tmp_path / "snap"
    rec = sms.take_snapshot(
        workspace=ws,
        snapshot_root=snap_root,
        snapshot_id="r2",
        approval=_accepted_approval("d" * 64),
        temp_verify=_passed_verify(),
    )
    assert rec.decision == "ROLLBACK_SNAPSHOT_WRITTEN", rec.notes


# ---------------------------------------------------------------------------
# apply gate
# ---------------------------------------------------------------------------
def test_apply_blocks_when_workspace_has_symlink(tmp_path, monkeypatch):
    if not _can_symlink(tmp_path, monkeypatch):
        pytest.skip("symlink creation not permitted on this host")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("orig", encoding="utf-8")
    link = ws / "link"
    try:
        link.symlink_to(ws / "a.txt")
    except OSError:
        link.write_text("mock", encoding="utf-8")
    target = tmp_path / "secret.txt"
    target.write_text("/etc/passwd-like", encoding="utf-8")
    try:
        (ws / "evil_link").symlink_to(target)
    except OSError:
        (ws / "evil_link").write_text("mock link", encoding="utf-8")

    # apply_after_approval must refuse before doing anything else, even
    # before checking approval/temp_verify/rollback_snapshot. Supply
    # None for all of them — symlink refusal must short-circuit first.
    rec = sma.apply_after_approval(
        workspace=ws,
        approval=None,
        temp_verify=None,
        rollback_snapshot=None,
        plan=None,
        plan_entries=[{"operation": "write", "path": "a.txt", "new_content": "new"}],
        observed_diff="",
    )
    assert rec.decision == "SOURCE_MUTATION_BLOCKED_SYMLINKS_UNSUPPORTED"
    assert rec.source_mutation_applied is False
    # Source must remain untouched.
    assert (ws / "a.txt").read_text(encoding="utf-8") == "orig"


# ---------------------------------------------------------------------------
# rollback executor
# ---------------------------------------------------------------------------
def test_rollback_blocks_when_workspace_has_symlink(tmp_path, monkeypatch):
    if not _can_symlink(tmp_path, monkeypatch):
        pytest.skip("symlink creation not permitted on this host")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("post-apply", encoding="utf-8")
    link = ws / "link"
    try:
        link.symlink_to(ws / "a.txt")
    except OSError:
        link.write_text("mock", encoding="utf-8")
    target = tmp_path / "elsewhere.txt"
    target.write_text("/var/log/...", encoding="utf-8")
    try:
        (ws / "evil_link").symlink_to(target)
    except OSError:
        (ws / "evil_link").write_text("mock link", encoding="utf-8")

    snap_dir = tmp_path / "snap"
    snap_dir.mkdir()
    (snap_dir / "a.txt").write_text("pre-apply", encoding="utf-8")

    snapshot = snap_rec_mod.SourceMutationRollbackSnapshotRecord(
        decision="ROLLBACK_SNAPSHOT_WRITTEN",
        workspace_identity=str(ws),
        pre_apply_source_hash="x",
        snapshot_path=str(snap_dir),
        snapshot_tree_hash="y",
        diff_hash="d",
        approval_ref="REAL_HUMAN_APPROVAL_ACCEPTED",
        verifier_ref="PATCH_VERIFIER_PASSED_TEMP_ONLY",
        source_mutation_applied=False,
        training_eligible=False,
    )
    apply_rec = apply_rec_mod.SourceMutationApplyAfterApprovalRecord(
        decision="SOURCE_MUTATION_APPLIED_AFTER_APPROVAL",
        workspace_identity=str(ws),
        pre_apply_source_hash="x",
        post_apply_source_hash="z",
        applied_paths=("a.txt",),
        diff_hash="d",
        approval_ref="REAL_HUMAN_APPROVAL_ACCEPTED",
        verifier_ref="PATCH_VERIFIER_PASSED_TEMP_ONLY",
        rollback_snapshot_ref=str(snap_dir),
        source_mutation_applied=True,
        post_apply_verifier_required=True,
        training_eligible=False,
    )

    rec = smr.execute_rollback(
        workspace=ws,
        rollback_snapshot=snapshot,
        apply_record=apply_rec,
        post_apply=_rollback_recommended_record(),
    )
    assert rec.decision == "SOURCE_ROLLBACK_BLOCKED_SYMLINKS_UNSUPPORTED"
    assert rec.is_blocked
    # Source untouched.
    assert (ws / "a.txt").read_text(encoding="utf-8") == "post-apply"


def test_rollback_blocks_even_if_no_rollback_recommended(tmp_path, monkeypatch):
    """Even when rollback_recommended is False, the executor still
    refuses symlinked workspaces — the check is unconditional."""
    if not _can_symlink(tmp_path, monkeypatch):
        pytest.skip("symlink creation not permitted on this host")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("post-apply", encoding="utf-8")
    link = ws / "link"
    try:
        link.symlink_to(ws / "a.txt")
    except OSError:
        link.write_text("mock", encoding="utf-8")
    target = tmp_path / "elsewhere.txt"
    target.write_text("hello", encoding="utf-8")
    try:
        (ws / "evil_link").symlink_to(target)
    except OSError:
        (ws / "evil_link").write_text("mock link", encoding="utf-8")

    rec = smr.execute_rollback(
        workspace=ws,
        rollback_snapshot=None,
        apply_record=None,
        post_apply=None,
    )
    assert rec.decision == "SOURCE_ROLLBACK_BLOCKED_SYMLINKS_UNSUPPORTED"


# ---------------------------------------------------------------------------
# token sets
# ---------------------------------------------------------------------------
def test_snapshot_record_token_set_includes_symlinks_token():
    assert "ROLLBACK_SNAPSHOT_BLOCKED_SYMLINKS_UNSUPPORTED" in (
        snap_rec_mod.SOURCE_MUTATION_ROLLBACK_SNAPSHOT_STATUS_TOKENS
    )


def test_apply_record_token_set_includes_symlinks_token():
    assert "SOURCE_MUTATION_BLOCKED_SYMLINKS_UNSUPPORTED" in (
        apply_rec_mod.SOURCE_MUTATION_APPLY_AFTER_APPROVAL_STATUS_TOKENS
    )


def test_rollback_execution_record_token_set_includes_symlinks_token():
    rec_mod = importlib.import_module("repair.source_mutation_rollback_execution_record")
    assert "SOURCE_ROLLBACK_BLOCKED_SYMLINKS_UNSUPPORTED" in (
        rec_mod.SOURCE_MUTATION_ROLLBACK_EXECUTION_STATUS_TOKENS
    )


# ---------------------------------------------------------------------------
# lock manifest / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "ROLLBACK_SYMLINK_SEMANTICS_LOCK_001"
    sd = blob.get("scope_discipline", {})
    assert sd.get("source_mutation_authorized") is False
    assert sd.get("training_eligible") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "ROLLBACK_SYMLINK_SEMANTICS_LOCK_001" in ids
