"""Tests for SOURCE_MUTATION_APPLY_AFTER_APPROVAL_LOCK_001."""

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

mod = importlib.import_module("repair.source_mutation_apply_after_approval")
rec_mod = importlib.import_module("repair.source_mutation_apply_after_approval_record")
adm_mod = importlib.import_module("ide.real_human_approval_admission_record")
tv_mod = importlib.import_module("repair.real_temp_patch_verify_record")
snap_mod = importlib.import_module("repair.source_mutation_rollback_snapshot_record")
plan_rec_mod = importlib.import_module("repair.real_patch_plan_quarantine_record")
plan_mod = importlib.import_module("repair.real_patch_plan_quarantine")
admin_mod = importlib.import_module("models.real_local_model_admission_record")
take_snap = importlib.import_module("repair.source_mutation_rollback_snapshot").take_snapshot

apply_after_approval = mod.apply_after_approval
TOKENS = rec_mod.SOURCE_MUTATION_APPLY_AFTER_APPROVAL_STATUS_TOKENS
RealHumanApprovalAdmissionRecord = adm_mod.RealHumanApprovalAdmissionRecord
RealTempPatchVerifyRecord = tv_mod.RealTempPatchVerifyRecord
SourceMutationRollbackSnapshotRecord = snap_mod.SourceMutationRollbackSnapshotRecord
RealLocalModelAdmissionRecord = admin_mod.RealLocalModelAdmissionRecord
quarantine = plan_mod.quarantine

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "SOURCE_MUTATION_APPLY_AFTER_APPROVAL_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "source_mutation_apply_after_approval"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED = frozenset(
    {
        "SOURCE_MUTATION_APPLIED_AFTER_APPROVAL",
        "SOURCE_MUTATION_BLOCKED_NO_APPROVAL",
        "SOURCE_MUTATION_BLOCKED_NO_ROLLBACK",
        "SOURCE_MUTATION_BLOCKED_SOURCE_HASH_MISMATCH",
        "SOURCE_MUTATION_BLOCKED_DIFF_MISMATCH",
        "SOURCE_MUTATION_BLOCKED_VERIFIER_NOT_PASSED",
        "SOURCE_MUTATION_BLOCKED_PLAN_BODY_MISSING",
        "SOURCE_MUTATION_BLOCKED_PATH_ESCAPE",
        "SOURCE_MUTATION_BLOCKED_MISSING_BODY_HASH",
        "SOURCE_MUTATION_BLOCKED_BODY_HASH_MISMATCH",
        "SOURCE_MUTATION_BLOCKED_FIXTURE_APPROVAL",
        "SOURCE_MUTATION_BLOCKED_INVALID_SIGNATURE_KIND",
        "SOURCE_MUTATION_BLOCKED_SYMLINKS_UNSUPPORTED",
    }
)


def _ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "lib.py").write_text("x = 1\n", encoding="utf-8")
    return ws


def _admission():
    return RealLocalModelAdmissionRecord(
        decision="REAL_LOCAL_MODEL_ADMITTED",
        provider="ollama",
        model_id="determinex-engineer-v11-dsl",
        task_classes_admitted=("PATCH_GENERATION",),
        opt_in=True,
    )


def _entries():
    return ({"operation": "replace_file", "path": "src/lib.py", "new_content": "x = 2\n"},)


def _body_hash_for(entries):
    from repair.patch_body_hash import compute as _compute

    return _compute(list(entries)).hex_digest


def _approval_accepted(
    diff_hash,
    *,
    canonical_patch_body_hash=None,
    entries=None,
    signature_kind="real_local_signed",
    is_fixture=False,
):
    if canonical_patch_body_hash is None:
        canonical_patch_body_hash = _body_hash_for(entries or _entries())
    return RealHumanApprovalAdmissionRecord(
        decision="REAL_HUMAN_APPROVAL_ACCEPTED",
        trace_id="trace-1",
        workspace_identity="/ws",
        diff_hash=diff_hash,
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
        operator_identity="ryan",
        operator_signature="a" * 64,
        signature_kind=signature_kind,
        is_fixture=is_fixture,
        accepted_at="2026-05-28T00:00:00+00:00",
        stale_after="2026-05-29T00:00:00+00:00",
        canonical_patch_body_hash=canonical_patch_body_hash,
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


def _setup(tmp_path, diff="my diff body"):
    ws = _ws(tmp_path)
    diff_hash = hashlib.sha256(diff.encode("utf-8")).hexdigest()
    approval = _approval_accepted(diff_hash)
    tv = _verify_passed()
    snap = take_snap(
        workspace=ws,
        snapshot_root=tmp_path / "snaps",
        snapshot_id="apply_t",
        approval=approval,
        temp_verify=tv,
    )
    plan = quarantine(_entries(), admission=_admission(), workspace=ws, opt_in=True)
    return ws, approval, tv, snap, plan, diff


def test_status_tokens_exact():
    assert set(TOKENS) == EXPECTED


def test_no_approval_blocks(tmp_path):
    ws, approval, tv, snap, plan, diff = _setup(tmp_path)
    r = apply_after_approval(
        workspace=ws,
        approval=None,
        temp_verify=tv,
        rollback_snapshot=snap,
        plan=plan,
        plan_entries=_entries(),
        observed_diff=diff,
    )
    assert r.decision == "SOURCE_MUTATION_BLOCKED_NO_APPROVAL"
    # Source unchanged.
    assert (ws / "src" / "lib.py").read_text(encoding="utf-8") == "x = 1\n"


def test_no_verify_blocks(tmp_path):
    ws, approval, tv, snap, plan, diff = _setup(tmp_path)
    r = apply_after_approval(
        workspace=ws,
        approval=approval,
        temp_verify=None,
        rollback_snapshot=snap,
        plan=plan,
        plan_entries=_entries(),
        observed_diff=diff,
    )
    assert r.decision == "SOURCE_MUTATION_BLOCKED_VERIFIER_NOT_PASSED"
    assert (ws / "src" / "lib.py").read_text(encoding="utf-8") == "x = 1\n"


def test_no_rollback_blocks(tmp_path):
    ws, approval, tv, snap, plan, diff = _setup(tmp_path)
    r = apply_after_approval(
        workspace=ws,
        approval=approval,
        temp_verify=tv,
        rollback_snapshot=None,
        plan=plan,
        plan_entries=_entries(),
        observed_diff=diff,
    )
    assert r.decision == "SOURCE_MUTATION_BLOCKED_NO_ROLLBACK"
    assert (ws / "src" / "lib.py").read_text(encoding="utf-8") == "x = 1\n"


def test_source_drift_blocks(tmp_path):
    ws, approval, tv, snap, plan, diff = _setup(tmp_path)
    # Drift the workspace AFTER snapshot.
    (ws / "src" / "lib.py").write_text("DRIFTED\n", encoding="utf-8")
    r = apply_after_approval(
        workspace=ws,
        approval=approval,
        temp_verify=tv,
        rollback_snapshot=snap,
        plan=plan,
        plan_entries=_entries(),
        observed_diff=diff,
    )
    assert r.decision == "SOURCE_MUTATION_BLOCKED_SOURCE_HASH_MISMATCH"
    # Drift preserved; we did not write a clean apply.
    assert (ws / "src" / "lib.py").read_text(encoding="utf-8") == "DRIFTED\n"


def test_diff_mismatch_blocks(tmp_path):
    ws, approval, tv, snap, plan, diff = _setup(tmp_path)
    r = apply_after_approval(
        workspace=ws,
        approval=approval,
        temp_verify=tv,
        rollback_snapshot=snap,
        plan=plan,
        plan_entries=_entries(),
        observed_diff=diff + " MUTATED",
    )
    assert r.decision == "SOURCE_MUTATION_BLOCKED_DIFF_MISMATCH"
    assert (ws / "src" / "lib.py").read_text(encoding="utf-8") == "x = 1\n"


def test_plan_body_mismatch_blocks_via_body_hash_gate(tmp_path):
    # When plan_entries differ from what approval was bound to, the
    # body-hash binding gate (CLAUDE-AUTH-001 remediation) fires FIRST
    # — more specific than the older PLAN_BODY_MISSING decision.
    ws, approval, tv, snap, plan, diff = _setup(tmp_path)
    r = apply_after_approval(
        workspace=ws,
        approval=approval,
        temp_verify=tv,
        rollback_snapshot=snap,
        plan=plan,
        plan_entries=({"operation": "replace_file", "path": "src/other.py", "new_content": "y\n"},),
        observed_diff=diff,
    )
    assert r.decision == "SOURCE_MUTATION_BLOCKED_BODY_HASH_MISMATCH"
    assert (ws / "src" / "lib.py").read_text(encoding="utf-8") == "x = 1\n"


def test_path_escape_blocks_via_body_hash_gate(tmp_path):
    # Path-escape entries are rejected during body_hash.compute, so
    # the binding gate refuses with MISSING_BODY_HASH (no valid hash
    # could be derived from the malicious entries).
    ws, approval, tv, snap, plan, diff = _setup(tmp_path)
    r = apply_after_approval(
        workspace=ws,
        approval=approval,
        temp_verify=tv,
        rollback_snapshot=snap,
        plan=plan,
        plan_entries=({"operation": "replace_file", "path": "../escape", "new_content": "x"},),
        observed_diff=diff,
    )
    assert r.decision == "SOURCE_MUTATION_BLOCKED_MISSING_BODY_HASH"
    assert (ws / "src" / "lib.py").read_text(encoding="utf-8") == "x = 1\n"


def test_claude_auth_001_attack_scenario_blocked(tmp_path):
    """CLAUDE-AUTH-001: clean diff narrative + tampered bodies.

    The attacker constructs an approval bound to a clean diff
    (observed_diff matches approval.diff_hash) and supplies
    tampered plan_entries.new_content for the same path. The
    binding gate must refuse with BODY_HASH_MISMATCH.
    """
    ws, approval, tv, snap, plan, diff = _setup(tmp_path)
    # Approval was bound to canonical hash of _entries() (x = 2).
    # Attacker supplies the same path but malicious content.
    tampered = (
        {
            "operation": "replace_file",
            "path": "src/lib.py",
            "new_content": "import os; os.system('rm -rf /')\n",
        },
    )
    r = apply_after_approval(
        workspace=ws,
        approval=approval,
        temp_verify=tv,
        rollback_snapshot=snap,
        plan=plan,
        plan_entries=tampered,
        observed_diff=diff,  # matches approval.diff_hash
    )
    assert r.decision == "SOURCE_MUTATION_BLOCKED_BODY_HASH_MISMATCH"
    # Source untouched.
    assert (ws / "src" / "lib.py").read_text(encoding="utf-8") == "x = 1\n"


def test_missing_canonical_body_hash_blocks(tmp_path):
    """Approval lacks canonical_patch_body_hash → BLOCKED_MISSING_BODY_HASH."""
    ws, approval, tv, snap, plan, diff = _setup(tmp_path)
    # Strip the binding from the approval.
    from dataclasses import replace as _replace

    bad_approval = _replace(approval, canonical_patch_body_hash="")
    r = apply_after_approval(
        workspace=ws,
        approval=bad_approval,
        temp_verify=tv,
        rollback_snapshot=snap,
        plan=plan,
        plan_entries=_entries(),
        observed_diff=diff,
    )
    assert r.decision == "SOURCE_MUTATION_BLOCKED_MISSING_BODY_HASH"
    assert (ws / "src" / "lib.py").read_text(encoding="utf-8") == "x = 1\n"


def test_claude_auth_002_fixture_approval_blocked(tmp_path):
    """CLAUDE-AUTH-002: fixture-ACCEPTED approval must be refused at apply gate."""
    ws, approval, tv, snap, plan, diff = _setup(tmp_path)
    from dataclasses import replace as _replace

    fixture_approval = _replace(approval, is_fixture=True, signature_kind="fixture")
    r = apply_after_approval(
        workspace=ws,
        approval=fixture_approval,
        temp_verify=tv,
        rollback_snapshot=snap,
        plan=plan,
        plan_entries=_entries(),
        observed_diff=diff,
    )
    assert r.decision == "SOURCE_MUTATION_BLOCKED_FIXTURE_APPROVAL"
    assert (ws / "src" / "lib.py").read_text(encoding="utf-8") == "x = 1\n"


def test_claude_auth_002_invalid_signature_kind_blocked(tmp_path):
    """CLAUDE-AUTH-002: signature_kind outside the production set is refused."""
    ws, approval, tv, snap, plan, diff = _setup(tmp_path)
    from dataclasses import replace as _replace

    bad_approval = _replace(approval, is_fixture=False, signature_kind="some_other_thing")
    r = apply_after_approval(
        workspace=ws,
        approval=bad_approval,
        temp_verify=tv,
        rollback_snapshot=snap,
        plan=plan,
        plan_entries=_entries(),
        observed_diff=diff,
    )
    assert r.decision == "SOURCE_MUTATION_BLOCKED_INVALID_SIGNATURE_KIND"
    assert (ws / "src" / "lib.py").read_text(encoding="utf-8") == "x = 1\n"


def test_happy_path_applies_and_records_post_apply_required(tmp_path):
    ws, approval, tv, snap, plan, diff = _setup(tmp_path)
    pre = (ws / "src" / "lib.py").read_text(encoding="utf-8")
    assert pre == "x = 1\n"
    r = apply_after_approval(
        workspace=ws,
        approval=approval,
        temp_verify=tv,
        rollback_snapshot=snap,
        plan=plan,
        plan_entries=_entries(),
        observed_diff=diff,
    )
    assert r.decision == "SOURCE_MUTATION_APPLIED_AFTER_APPROVAL"
    assert r.is_applied
    assert r.source_mutation_applied is True
    assert r.post_apply_verifier_required is True
    assert r.training_eligible is False
    # Source NOW updated.
    assert (ws / "src" / "lib.py").read_text(encoding="utf-8") == "x = 2\n"
    # Hashes differ.
    assert r.pre_apply_source_hash != r.post_apply_source_hash


def test_record_serializes_safely(tmp_path):
    ws, approval, tv, snap, plan, diff = _setup(tmp_path)
    r = apply_after_approval(
        workspace=ws,
        approval=approval,
        temp_verify=tv,
        rollback_snapshot=snap,
        plan=plan,
        plan_entries=_entries(),
        observed_diff=diff,
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
    assert blob["lock_id"] == "SOURCE_MUTATION_APPLY_AFTER_APPROVAL_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED)
    sd = blob.get("scope_discipline", {})
    assert sd.get("training_eligibility_opened") is False
    # source_mutation_applied is True at this rung *for the apply path*.
    # The scope_discipline reports the rung's intent boundary.
    assert "training_row_written" in sd
    assert sd.get("training_row_written") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "SOURCE_MUTATION_APPLY_AFTER_APPROVAL_LOCK_001" in ids
