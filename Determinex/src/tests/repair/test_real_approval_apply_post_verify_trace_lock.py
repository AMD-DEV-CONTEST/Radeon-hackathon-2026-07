"""Tests for REAL_APPROVAL_APPLY_POST_VERIFY_TRACE_LOCK_001."""

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

mod = importlib.import_module("repair.real_approval_apply_post_verify_trace")
rec_mod = importlib.import_module("repair.real_approval_apply_post_verify_trace_record")
adm_mod = importlib.import_module("ide.real_human_approval_admission_record")
tv_mod = importlib.import_module("repair.real_temp_patch_verify_record")
sel_mod = importlib.import_module("repair.build_adapter_backed_verifier_selection_record")

trace = mod.trace
TOKENS = rec_mod.REAL_APPROVAL_APPLY_POST_VERIFY_TRACE_STATUS_TOKENS
RealApprovalApplyPostVerifyTraceRecord = rec_mod.RealApprovalApplyPostVerifyTraceRecord
RealHumanApprovalAdmissionRecord = adm_mod.RealHumanApprovalAdmissionRecord
RealTempPatchVerifyRecord = tv_mod.RealTempPatchVerifyRecord
BuildAdapterBackedVerifierSelectionRecord = sel_mod.BuildAdapterBackedVerifierSelectionRecord

LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "REAL_APPROVAL_APPLY_POST_VERIFY_TRACE_LOCK_001.json"
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "real_approval_apply_post_verify_trace"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED = frozenset(
    {
        "REAL_APPROVAL_REQUIRED",
        "REAL_APPROVAL_APPLY_POST_VERIFY_PASSED",
        "REAL_APPROVAL_APPLY_POST_VERIFY_FAILED_ROLLBACK_REQUIRED",
        "REAL_APPROVAL_APPLY_BLOCKED_NO_APPROVAL",
        "REAL_APPROVAL_APPLY_BLOCKED_MISMATCH",
        "REAL_APPROVAL_APPLY_BLOCKED_NO_TEMP_VERIFY",
        "REAL_APPROVAL_APPLY_BLOCKED_NO_VERIFIER",
    }
)


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "lib.py").write_text("x = 1\n", encoding="utf-8")
    (ws / "tests").mkdir()
    (ws / "tests" / "test_x.py").write_text(
        "from src.lib import x\ndef test_x():\n    assert x == 2\n",
        encoding="utf-8",
    )
    # Sanity init.
    (ws / "src" / "__init__.py").write_text("", encoding="utf-8")
    (ws / "conftest.py").write_text(
        "import sys, os\nsys.path.insert(0, os.path.dirname(__file__))\n",
        encoding="utf-8",
    )
    return ws


def _approval(diff, *, kind="real_local_signed", accepted=True, entries=None):
    from repair.patch_body_hash import compute as _compute

    if entries is None:
        entries = ({"operation": "replace_file", "path": "src/lib.py", "new_content": "x = 2\n"},)
    body_hash = _compute(list(entries)).hex_digest
    return RealHumanApprovalAdmissionRecord(
        decision="REAL_HUMAN_APPROVAL_ACCEPTED"
        if accepted
        else "REAL_HUMAN_APPROVAL_BLOCKED_FIXTURE",
        trace_id="trace-1",
        workspace_identity="/ws",
        diff_hash=_sha(diff),
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
        operator_identity="ryan",
        operator_signature="a" * 64,
        signature_kind=kind,
        is_fixture=(kind != "real_local_signed"),
        accepted_at="x",
        stale_after="2026-05-29T00:00:00+00:00",
        canonical_patch_body_hash=body_hash,
    )


def _tv_passed():
    return RealTempPatchVerifyRecord(
        decision="REAL_TEMP_PATCH_VERIFIER_PASSED",
        workspace="/ws",
        temp_workspace="/tmp/x",
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
        unified_diff="",
        applied_paths=("src/lib.py",),
        original_unchanged=True,
        original_sha256_before="a" * 64,
        original_sha256_after="a" * 64,
        human_approval_required=True,
    )


def _tv_failed():
    return RealTempPatchVerifyRecord(
        decision="REAL_TEMP_PATCH_VERIFIER_FAILED",
        workspace="/ws",
        temp_workspace="/tmp/x",
        verifier_status="PATCH_VERIFIER_FAILED",
        unified_diff="",
        applied_paths=(),
        original_unchanged=True,
        original_sha256_before="a" * 64,
        original_sha256_after="a" * 64,
        human_approval_required=False,
    )


def _sel_selected():
    return BuildAdapterBackedVerifierSelectionRecord(
        decision="BUILD_ADAPTER_VERIFIER_SELECTED",
        workspace="/ws",
        adapter_name="Python",
        build_system_id="pip",
        test_framework_id="pytest -q",
        verifier_command=("pytest", "-q"),
        hardened_runner="intake.hardened_runner",
        multi_match=False,
        matched_adapters=("Python",),
    )


def _sel_blocked():
    return BuildAdapterBackedVerifierSelectionRecord(
        decision="BUILD_ADAPTER_VERIFIER_BLOCKED_UNSUPPORTED_REPO",
        workspace="/ws",
        adapter_name="",
        build_system_id="",
        test_framework_id="",
        verifier_command=(),
        hardened_runner="intake.hardened_runner",
        multi_match=False,
        matched_adapters=(),
    )


def _entries(content="x = 2\n"):
    return ({"operation": "replace_file", "path": "src/lib.py", "new_content": content},)


def test_status_tokens_exact():
    assert set(TOKENS) == EXPECTED


def test_no_temp_verify_blocks(tmp_path):
    diff = "diff body"
    r = trace(
        workspace=_ws(tmp_path),
        snapshot_root=tmp_path / "snaps",
        snapshot_id="t1",
        approval=_approval(diff),
        temp_verify=_tv_failed(),
        verifier_selection=_sel_selected(),
        plan_entries=_entries(),
        observed_diff=diff,
    )
    assert r.decision == "REAL_APPROVAL_APPLY_BLOCKED_NO_TEMP_VERIFY"


def test_no_verifier_blocks(tmp_path):
    diff = "diff body"
    r = trace(
        workspace=_ws(tmp_path),
        snapshot_root=tmp_path / "snaps",
        snapshot_id="t1",
        approval=_approval(diff),
        temp_verify=_tv_passed(),
        verifier_selection=_sel_blocked(),
        plan_entries=_entries(),
        observed_diff=diff,
    )
    assert r.decision == "REAL_APPROVAL_APPLY_BLOCKED_NO_VERIFIER"


def test_no_approval_returns_required(tmp_path):
    diff = "diff body"
    r = trace(
        workspace=_ws(tmp_path),
        snapshot_root=tmp_path / "snaps",
        snapshot_id="t1",
        approval=None,
        temp_verify=_tv_passed(),
        verifier_selection=_sel_selected(),
        plan_entries=_entries(),
        observed_diff=diff,
    )
    assert r.decision == "REAL_APPROVAL_REQUIRED"
    assert r.source_mutation_applied is False


def test_fixture_approval_blocks(tmp_path):
    diff = "diff body"
    r = trace(
        workspace=_ws(tmp_path),
        snapshot_root=tmp_path / "snaps",
        snapshot_id="t1",
        approval=_approval(diff, kind="fixture"),
        temp_verify=_tv_passed(),
        verifier_selection=_sel_selected(),
        plan_entries=_entries(),
        observed_diff=diff,
    )
    assert r.decision == "REAL_APPROVAL_APPLY_BLOCKED_NO_APPROVAL"


def test_real_pass_path_applies_and_post_verifies(tmp_path):
    diff = "diff body"
    ws = _ws(tmp_path)
    r = trace(
        workspace=ws,
        snapshot_root=tmp_path / "snaps",
        snapshot_id="t1",
        approval=_approval(diff),
        temp_verify=_tv_passed(),
        verifier_selection=_sel_selected(),
        plan_entries=_entries(),
        observed_diff=diff,
        verifier_timeout_seconds=120,
    )
    assert r.decision == "REAL_APPROVAL_APPLY_POST_VERIFY_PASSED"
    assert r.source_mutation_applied is True
    assert r.rollback_executed is False
    assert r.training_eligible is False, (
        "passing post-apply verifier must not auto-promote training"
    )
    # Source actually updated.
    assert (ws / "src" / "lib.py").read_text(encoding="utf-8") == "x = 2\n"


def test_real_fail_path_triggers_rollback(tmp_path):
    diff = "diff body"
    ws = _ws(tmp_path)
    # Use a body that breaks the test fixture (test asserts x == 2).
    bad_entries = ({"operation": "replace_file", "path": "src/lib.py", "new_content": "x = 99\n"},)
    # Approval must be bound to the bad bodies; otherwise the
    # CLAUDE-AUTH-001 body-hash gate blocks before apply.
    r = trace(
        workspace=ws,
        snapshot_root=tmp_path / "snaps",
        snapshot_id="t2",
        approval=_approval(diff, entries=bad_entries),
        temp_verify=_tv_passed(),
        verifier_selection=_sel_selected(),
        plan_entries=bad_entries,
        observed_diff=diff,
        verifier_timeout_seconds=120,
    )
    assert r.decision == "REAL_APPROVAL_APPLY_POST_VERIFY_FAILED_ROLLBACK_REQUIRED"
    assert r.source_mutation_applied is True
    assert r.rollback_executed is True
    assert r.training_eligible is False
    # Source restored to original.
    assert (ws / "src" / "lib.py").read_text(encoding="utf-8") == "x = 1\n"


def test_record_serializes_safely(tmp_path):
    diff = "diff body"
    r = trace(
        workspace=_ws(tmp_path),
        snapshot_root=tmp_path / "snaps",
        snapshot_id="ser",
        approval=_approval(diff),
        temp_verify=_tv_passed(),
        verifier_selection=_sel_selected(),
        plan_entries=_entries(),
        observed_diff=diff,
        verifier_timeout_seconds=120,
    )
    d = r.to_dict()
    json.dumps(d)
    assert d["training_eligible"] is False


def test_module_does_not_open_network():
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("requests", "httpx", "urllib.request", "socket.connect"):
        assert forbidden not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "REAL_APPROVAL_APPLY_POST_VERIFY_TRACE_LOCK_001"
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
    assert "REAL_APPROVAL_APPLY_POST_VERIFY_TRACE_LOCK_001" in ids
