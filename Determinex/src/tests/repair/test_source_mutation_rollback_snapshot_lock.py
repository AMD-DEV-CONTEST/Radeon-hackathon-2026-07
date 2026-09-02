"""Tests for SOURCE_MUTATION_ROLLBACK_SNAPSHOT_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

mod = importlib.import_module("repair.source_mutation_rollback_snapshot")
rec_mod = importlib.import_module("repair.source_mutation_rollback_snapshot_record")
adm_mod = importlib.import_module("ide.real_human_approval_admission_record")
tv_mod = importlib.import_module("repair.real_temp_patch_verify_record")

take_snapshot = mod.take_snapshot
TOKENS = rec_mod.SOURCE_MUTATION_ROLLBACK_SNAPSHOT_STATUS_TOKENS
SourceMutationRollbackSnapshotRecord = rec_mod.SourceMutationRollbackSnapshotRecord
RealHumanApprovalAdmissionRecord = adm_mod.RealHumanApprovalAdmissionRecord
RealTempPatchVerifyRecord = tv_mod.RealTempPatchVerifyRecord

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "SOURCE_MUTATION_ROLLBACK_SNAPSHOT_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "source_mutation_rollback_snapshot"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED = frozenset(
    {
        "ROLLBACK_SNAPSHOT_WRITTEN",
        "ROLLBACK_SNAPSHOT_BLOCKED_NO_APPROVAL",
        "ROLLBACK_SNAPSHOT_BLOCKED_SOURCE_HASH_MISMATCH",
        "ROLLBACK_SNAPSHOT_BLOCKED_NO_VERIFY",
        "ROLLBACK_SNAPSHOT_BLOCKED_INVALID_LOCATION",
        "ROLLBACK_SNAPSHOT_BLOCKED_SYMLINKS_UNSUPPORTED",
    }
)


def _approval_accepted():
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
        accepted_at="2026-05-28T00:00:00+00:00",
        stale_after="2026-05-29T00:00:00+00:00",
    )


def _approval_blocked():
    return RealHumanApprovalAdmissionRecord(
        decision="REAL_HUMAN_APPROVAL_BLOCKED_FIXTURE",
        trace_id="trace-1",
        workspace_identity="/ws",
        diff_hash="d" * 64,
        verifier_status="x",
        operator_identity="ryan",
        operator_signature="",
        signature_kind="fixture",
        is_fixture=True,
        accepted_at="0",
        stale_after="0",
    )


def _verify_passed():
    return RealTempPatchVerifyRecord(
        decision="REAL_TEMP_PATCH_VERIFIER_PASSED",
        workspace="/ws",
        temp_workspace="/tmp/x",
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
        unified_diff="--- a\n+++ b\n",
        applied_paths=("src/lib.py",),
        original_unchanged=True,
        original_sha256_before="a" * 64,
        original_sha256_after="a" * 64,
        human_approval_required=True,
    )


def _ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "lib.py").write_text("x = 1\n", encoding="utf-8")
    return ws


def test_status_tokens_exact():
    assert set(TOKENS) == EXPECTED


def test_no_approval_blocked(tmp_path):
    ws = _ws(tmp_path)
    r = take_snapshot(
        workspace=ws,
        snapshot_root=tmp_path / "snaps",
        snapshot_id="t1",
        approval=None,
        temp_verify=_verify_passed(),
    )
    assert r.decision == "ROLLBACK_SNAPSHOT_BLOCKED_NO_APPROVAL"


def test_blocked_approval_refused(tmp_path):
    ws = _ws(tmp_path)
    r = take_snapshot(
        workspace=ws,
        snapshot_root=tmp_path / "snaps",
        snapshot_id="t1",
        approval=_approval_blocked(),
        temp_verify=_verify_passed(),
    )
    assert r.decision == "ROLLBACK_SNAPSHOT_BLOCKED_NO_APPROVAL"


def test_no_verify_blocked(tmp_path):
    ws = _ws(tmp_path)
    r = take_snapshot(
        workspace=ws,
        snapshot_root=tmp_path / "snaps",
        snapshot_id="t1",
        approval=_approval_accepted(),
        temp_verify=None,
    )
    assert r.decision == "ROLLBACK_SNAPSHOT_BLOCKED_NO_VERIFY"


def test_source_hash_mismatch_blocked(tmp_path):
    ws = _ws(tmp_path)
    r = take_snapshot(
        workspace=ws,
        snapshot_root=tmp_path / "snaps",
        snapshot_id="t1",
        approval=_approval_accepted(),
        temp_verify=_verify_passed(),
        expected_pre_apply_source_hash="z" * 64,
    )
    assert r.decision == "ROLLBACK_SNAPSHOT_BLOCKED_SOURCE_HASH_MISMATCH"


def test_existing_snapshot_path_refused(tmp_path):
    ws = _ws(tmp_path)
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    (snaps / "rollback_t1").mkdir()
    r = take_snapshot(
        workspace=ws,
        snapshot_root=snaps,
        snapshot_id="t1",
        approval=_approval_accepted(),
        temp_verify=_verify_passed(),
    )
    assert r.decision == "ROLLBACK_SNAPSHOT_BLOCKED_INVALID_LOCATION"


def test_happy_path_writes_snapshot(tmp_path):
    ws = _ws(tmp_path)
    r = take_snapshot(
        workspace=ws,
        snapshot_root=tmp_path / "snaps",
        snapshot_id="happy",
        approval=_approval_accepted(),
        temp_verify=_verify_passed(),
    )
    assert r.decision == "ROLLBACK_SNAPSHOT_WRITTEN"
    assert r.snapshot_path
    assert Path(r.snapshot_path).is_dir()
    # Snapshot contains the original content.
    assert (Path(r.snapshot_path) / "src" / "lib.py").read_text(encoding="utf-8") == "x = 1\n"
    # Source unchanged.
    assert (ws / "src" / "lib.py").read_text(encoding="utf-8") == "x = 1\n"
    # Source mutation not applied here.
    assert r.source_mutation_applied is False
    assert r.training_eligible is False
    assert r.pre_apply_source_hash
    assert r.snapshot_tree_hash


def test_record_serializes_safely(tmp_path):
    ws = _ws(tmp_path)
    r = take_snapshot(
        workspace=ws,
        snapshot_root=tmp_path / "snaps",
        snapshot_id="ser",
        approval=_approval_accepted(),
        temp_verify=_verify_passed(),
    )
    d = r.to_dict()
    json.dumps(d)
    assert d["source_mutation_applied"] is False
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
    assert blob["lock_id"] == "SOURCE_MUTATION_ROLLBACK_SNAPSHOT_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED)
    sd = blob.get("scope_discipline", {})
    assert sd.get("source_mutation_applied") is False
    assert sd.get("training_eligibility_opened") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "SOURCE_MUTATION_ROLLBACK_SNAPSHOT_LOCK_001" in ids
