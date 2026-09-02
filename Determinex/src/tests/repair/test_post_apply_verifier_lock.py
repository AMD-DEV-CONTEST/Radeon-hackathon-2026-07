"""Tests for POST_APPLY_VERIFIER_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

mod = importlib.import_module("repair.post_apply_verifier")
rec_mod = importlib.import_module("repair.post_apply_verifier_record")
apply_mod = importlib.import_module("repair.source_mutation_apply_after_approval_record")
spw = importlib.import_module("repair.safe_patch_workspace")

run = mod.run
TOKENS = rec_mod.POST_APPLY_VERIFIER_STATUS_TOKENS
PostApplyVerifierRecord = rec_mod.PostApplyVerifierRecord
SourceMutationApplyAfterApprovalRecord = apply_mod.SourceMutationApplyAfterApprovalRecord

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "POST_APPLY_VERIFIER_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "post_apply_verifier"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED = frozenset(
    {
        "POST_APPLY_VERIFIER_PASSED",
        "POST_APPLY_VERIFIER_FAILED",
        "POST_APPLY_ROLLBACK_RECOMMENDED",
        "POST_APPLY_VERIFIER_BLOCKED_NO_APPLY",
        "POST_APPLY_VERIFIER_BLOCKED_MISSING_VERIFIER",
        "POST_APPLY_VERIFIER_BLOCKED_FIXTURE_VERIFIER_IN_LIVE_PATH",
        "POST_APPLY_VERIFIER_EXPLICIT_REQUIRED",
    }
)


def _ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "lib.py").write_text("x = 2\n", encoding="utf-8")
    return ws


def _apply_record_applied():
    return SourceMutationApplyAfterApprovalRecord(
        decision="SOURCE_MUTATION_APPLIED_AFTER_APPROVAL",
        workspace_identity="/ws",
        pre_apply_source_hash="a" * 64,
        post_apply_source_hash="b" * 64,
        applied_paths=("src/lib.py",),
        diff_hash="d" * 64,
        approval_ref="REAL_HUMAN_APPROVAL_ACCEPTED",
        verifier_ref="PATCH_VERIFIER_PASSED_TEMP_ONLY",
        rollback_snapshot_ref="/tmp/snaps/rollback_t",
        source_mutation_applied=True,
        post_apply_verifier_required=True,
    )


def _apply_record_blocked():
    return SourceMutationApplyAfterApprovalRecord(
        decision="SOURCE_MUTATION_BLOCKED_NO_APPROVAL",
        workspace_identity="/ws",
        pre_apply_source_hash="a" * 64,
        post_apply_source_hash="a" * 64,
        applied_paths=(),
        diff_hash="d" * 64,
        approval_ref="x",
        verifier_ref="x",
        rollback_snapshot_ref="x",
        source_mutation_applied=False,
        post_apply_verifier_required=False,
    )


def test_status_tokens_exact():
    assert set(TOKENS) == EXPECTED


def test_no_apply_blocks(tmp_path):
    r = run(workspace=_ws(tmp_path), apply_record=None, verifier=spw.stub_verifier_pass)
    assert r.decision == "POST_APPLY_VERIFIER_BLOCKED_NO_APPLY"


def test_apply_blocked_blocks_post(tmp_path):
    r = run(
        workspace=_ws(tmp_path),
        apply_record=_apply_record_blocked(),
        verifier=spw.stub_verifier_pass,
    )
    assert r.decision == "POST_APPLY_VERIFIER_BLOCKED_NO_APPLY"


def test_verifier_pass_records_passed(tmp_path):
    # CLAUDE-AUTH-003: stub verifier requires explicit fixture_mode=True
    r = run(
        workspace=_ws(tmp_path),
        apply_record=_apply_record_applied(),
        verifier=spw.stub_verifier_pass,
        fixture_mode=True,
    )
    assert r.decision == "POST_APPLY_VERIFIER_PASSED"
    assert r.is_passed
    assert r.rollback_recommended is False
    assert r.training_eligible is False, (
        "passing verifier must not auto-create training eligibility"
    )


def test_verifier_fail_records_rollback_recommended(tmp_path):
    r = run(
        workspace=_ws(tmp_path),
        apply_record=_apply_record_applied(),
        verifier=spw.stub_verifier_fail,
        fixture_mode=True,
    )
    assert r.decision == "POST_APPLY_VERIFIER_FAILED"
    assert r.is_failed
    assert r.rollback_recommended is True
    assert "POST_APPLY_ROLLBACK_RECOMMENDED" in r.statuses_seen
    assert r.training_eligible is False


def test_post_apply_hash_recorded(tmp_path):
    r = run(
        workspace=_ws(tmp_path),
        apply_record=_apply_record_applied(),
        verifier=spw.stub_verifier_pass,
        fixture_mode=True,
    )
    assert r.post_apply_source_hash  # non-empty


def test_record_serializes_safely(tmp_path):
    r = run(
        workspace=_ws(tmp_path),
        apply_record=_apply_record_applied(),
        verifier=spw.stub_verifier_pass,
        fixture_mode=True,
    )
    d = r.to_dict()
    json.dumps(d)
    assert d["training_eligible"] is False


def test_claude_auth_003_no_default_pass_when_verifier_missing(tmp_path):
    """CLAUDE-AUTH-003: verifier=None must NOT silently pass."""
    r = run(workspace=_ws(tmp_path), apply_record=_apply_record_applied(), verifier=None)
    assert r.decision == "POST_APPLY_VERIFIER_BLOCKED_MISSING_VERIFIER"
    assert "POST_APPLY_VERIFIER_EXPLICIT_REQUIRED" in r.statuses_seen
    assert r.rollback_recommended is False
    assert r.is_passed is False


def test_claude_auth_003_stub_verifier_refused_in_live_path(tmp_path):
    """CLAUDE-AUTH-003: stub verifier without fixture_mode is refused."""
    r = run(
        workspace=_ws(tmp_path),
        apply_record=_apply_record_applied(),
        verifier=spw.stub_verifier_pass,
    )  # no fixture_mode
    assert r.decision == "POST_APPLY_VERIFIER_BLOCKED_FIXTURE_VERIFIER_IN_LIVE_PATH"
    assert "POST_APPLY_VERIFIER_EXPLICIT_REQUIRED" in r.statuses_seen
    assert r.is_passed is False


def test_claude_auth_003_stub_verifier_fail_also_refused_in_live_path(tmp_path):
    """Even stub_verifier_fail is refused in live path (fixture is fixture)."""
    r = run(
        workspace=_ws(tmp_path),
        apply_record=_apply_record_applied(),
        verifier=spw.stub_verifier_fail,
    )
    assert r.decision == "POST_APPLY_VERIFIER_BLOCKED_FIXTURE_VERIFIER_IN_LIVE_PATH"


def test_real_verifier_callable_accepted_without_fixture_mode(tmp_path):
    """A real (non-stub) verifier callable passes through fine."""
    from scripts.repair.safe_patch_workspace import VerifierResult

    def real_verifier(_ws):
        return VerifierResult(passed=True, output="real verifier ran")

    r = run(workspace=_ws(tmp_path), apply_record=_apply_record_applied(), verifier=real_verifier)
    assert r.decision == "POST_APPLY_VERIFIER_PASSED"


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
    assert blob["lock_id"] == "POST_APPLY_VERIFIER_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED)
    sd = blob.get("scope_discipline", {})
    assert sd.get("training_eligibility_opened") is False
    assert sd.get("training_row_written") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "POST_APPLY_VERIFIER_LOCK_001" in ids
