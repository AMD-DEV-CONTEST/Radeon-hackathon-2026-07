"""Tests for CORPUS_ELIGIBILITY_REPAIR_TRACE_GUARD_LOCK_001.

The guard refuses to admit any repair trace produced by the current
campaign as a training corpus row. Tests:

  * BLOCKED_MOCKED_MODEL_OUTPUT fires on every trace (always, in this
    campaign).
  * BLOCKED_TEMP_WORKSPACE_ONLY fires on every trace.
  * BLOCKED_NO_LIVE_MODEL_CALL fires on every trace.
  * BLOCKED_POLICY fires under default policy.
  * BLOCKED_UNSUPPORTED_REPO fires on unsupported_repo trace only.
  * BLOCKED_VERIFIER_FAILED fires when stub_verifier_fail used.
  * BLOCKED_SOURCE_NOT_APPROVED fires when no approval supplied OR
    approval was blocked.
  * BLOCKED_HUMAN_APPROVAL_REQUIRED fires when no approval supplied
    or approval is REQUIRED.
  * Even with FIXTURE-accepted approval, eligibility remains BLOCKED
    (mocked output + temp workspace + no live model + policy still apply).
  * training_eligible is False on every decision.
  * Guard call does not mutate workspace.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

guard_mod = importlib.import_module("corpus.repair_trace_eligibility_guard")
rec_mod = importlib.import_module("corpus.repair_trace_eligibility_record")
trace_mod = importlib.import_module("repair.verified_repair_trace")
sp_mod = importlib.import_module("repair.safe_patch_workspace")
approval_mod = importlib.import_module("repair.human_approval_gate")
approval_rec_mod = importlib.import_module("repair.human_approval_record")
router_mod = importlib.import_module("models.model_router")
inv_mod = importlib.import_module("models.model_inventory")

RepairTraceEligibilityGuard = guard_mod.RepairTraceEligibilityGuard
CorpusEligibilityBlockReason = rec_mod.CorpusEligibilityBlockReason
CORPUS_ELIGIBILITY_STATUS_TOKENS = rec_mod.CORPUS_ELIGIBILITY_STATUS_TOKENS

VerifiedRepairTraceRunner = trace_mod.VerifiedRepairTraceRunner
FilePatch = sp_mod.FilePatch
stub_verifier_pass = sp_mod.stub_verifier_pass
stub_verifier_fail = sp_mod.stub_verifier_fail

HumanApprovalGate = approval_mod.HumanApprovalGate
ApprovalPacket = approval_rec_mod.ApprovalPacket
diff_hash = approval_rec_mod.diff_hash

ModelRouter = router_mod.ModelRouter
LocalModelInventory = inv_mod.LocalModelInventory
CURRENT_MODEL_IDS = router_mod.CURRENT_MODEL_IDS

FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "intake"
LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "CORPUS_ELIGIBILITY_REPAIR_TRACE_GUARD_LOCK_001.json"
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "corpus_eligibility_repair_trace_guard"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


STATUS_TOKENS = frozenset(CORPUS_ELIGIBILITY_STATUS_TOKENS)


def _hash_tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
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


def _runner() -> VerifiedRepairTraceRunner:
    inv = LocalModelInventory.of(sorted(CURRENT_MODEL_IDS))
    return VerifiedRepairTraceRunner(router=ModelRouter(inventory=inv), salt="elig")


def _pass_trace(tmp_path):
    return _runner().run(
        FIXTURES / "python_broken",
        tmp_path,
        patches=[FilePatch("src/calc.py", "x = 1\n")],
        verifier=stub_verifier_pass,
        workspace_id="elig_pass",
    )


def _fail_trace(tmp_path):
    return _runner().run(
        FIXTURES / "rust_broken",
        tmp_path,
        patches=[FilePatch("src/lib.rs", "x\n")],
        verifier=stub_verifier_fail,
        workspace_id="elig_fail",
    )


def _unsupported_trace(tmp_path):
    return _runner().run(
        FIXTURES / "unsupported_repo",
        tmp_path,
        patches=[FilePatch("x.txt", "y\n")],
        verifier=stub_verifier_pass,
        workspace_id="elig_unsup",
    )


def _accepted_approval(trace):
    spr = trace.safe_patch_result or {}
    return HumanApprovalGate().evaluate(
        ApprovalPacket(
            trace_id=trace.trace_id,
            workspace_identity=trace.workspace,
            diff_sha256=diff_hash(str(spr.get("unified_diff") or "")),
            verifier_status=str(spr.get("verifier_status") or ""),
            timestamp_utc=_dt.datetime.now(_dt.UTC).isoformat(),
            operator="ryan",
            approval_token="ok",
        ),
        trace,
    )


# ---------------------------------------------------------------------------
# Status / closed set
# ---------------------------------------------------------------------------


def test_status_tokens_match_expected_set():
    expected = {
        "CORPUS_ELIGIBILITY_BLOCKED",
        "CORPUS_ELIGIBILITY_EVIDENCE_ONLY",
        "BLOCKED_MOCKED_MODEL_OUTPUT",
        "BLOCKED_TEMP_WORKSPACE_ONLY",
        "BLOCKED_SOURCE_NOT_APPROVED",
        "BLOCKED_VERIFIER_FAILED",
        "BLOCKED_UNSUPPORTED_REPO",
        "BLOCKED_NO_LIVE_MODEL_CALL",
        "BLOCKED_HUMAN_APPROVAL_REQUIRED",
        "BLOCKED_POLICY",
    }
    assert set(STATUS_TOKENS) == expected


# ---------------------------------------------------------------------------
# Every default-policy decision is BLOCKED
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", ["pass", "fail", "unsupported"])
def test_every_trace_blocked_under_default_policy(scenario, tmp_path):
    if scenario == "pass":
        trace = _pass_trace(tmp_path)
    elif scenario == "fail":
        trace = _fail_trace(tmp_path)
    else:
        trace = _unsupported_trace(tmp_path)
    g = RepairTraceEligibilityGuard()
    dec = g.evaluate(trace)
    assert dec.is_blocked
    assert dec.training_eligible is False
    assert "BLOCKED_POLICY" in dec.blocked_reasons


# ---------------------------------------------------------------------------
# Per-reason firing
# ---------------------------------------------------------------------------


def test_mocked_model_output_reason_fires_for_every_trace(tmp_path):
    g = RepairTraceEligibilityGuard()
    for fname in ("python_broken", "rust_broken", "unsupported_repo"):
        trace = _runner().run(
            FIXTURES / fname,
            tmp_path / f"r_{fname}",
            patches=[FilePatch("x.txt", "y\n")],
            verifier=stub_verifier_pass,
            workspace_id=f"mock_{fname}",
        )
        dec = g.evaluate(trace)
        assert "BLOCKED_MOCKED_MODEL_OUTPUT" in dec.blocked_reasons


def test_temp_workspace_only_reason_fires_for_every_trace(tmp_path):
    g = RepairTraceEligibilityGuard()
    trace = _pass_trace(tmp_path)
    dec = g.evaluate(trace)
    assert "BLOCKED_TEMP_WORKSPACE_ONLY" in dec.blocked_reasons


def test_no_live_model_call_reason_fires(tmp_path):
    g = RepairTraceEligibilityGuard()
    trace = _pass_trace(tmp_path)
    dec = g.evaluate(trace)
    assert "BLOCKED_NO_LIVE_MODEL_CALL" in dec.blocked_reasons


def test_unsupported_repo_reason_fires_only_for_unsupported(tmp_path):
    g = RepairTraceEligibilityGuard()
    pass_dec = g.evaluate(_pass_trace(tmp_path / "p"))
    unsup_dec = g.evaluate(_unsupported_trace(tmp_path / "u"))
    assert "BLOCKED_UNSUPPORTED_REPO" not in pass_dec.blocked_reasons
    assert "BLOCKED_UNSUPPORTED_REPO" in unsup_dec.blocked_reasons


def test_verifier_failed_reason_fires_only_on_failure(tmp_path):
    g = RepairTraceEligibilityGuard()
    pass_dec = g.evaluate(_pass_trace(tmp_path / "p"))
    fail_dec = g.evaluate(_fail_trace(tmp_path / "f"))
    assert "BLOCKED_VERIFIER_FAILED" not in pass_dec.blocked_reasons
    assert "BLOCKED_VERIFIER_FAILED" in fail_dec.blocked_reasons


def test_source_not_approved_reason_fires_without_approval(tmp_path):
    g = RepairTraceEligibilityGuard()
    trace = _pass_trace(tmp_path)
    dec = g.evaluate(trace)
    assert "BLOCKED_SOURCE_NOT_APPROVED" in dec.blocked_reasons


def test_human_approval_required_reason_fires_without_packet(tmp_path):
    g = RepairTraceEligibilityGuard()
    trace = _pass_trace(tmp_path)
    dec = g.evaluate(trace)
    assert "BLOCKED_HUMAN_APPROVAL_REQUIRED" in dec.blocked_reasons


def test_accepted_approval_clears_source_not_approved_reason(tmp_path):
    g = RepairTraceEligibilityGuard()
    trace = _pass_trace(tmp_path)
    approval = _accepted_approval(trace)
    dec = g.evaluate(trace, approval=approval)
    assert "BLOCKED_SOURCE_NOT_APPROVED" not in dec.blocked_reasons
    # But still blocked overall — other reasons still apply.
    assert dec.is_blocked


# ---------------------------------------------------------------------------
# Even FIXTURE-accepted approval keeps the trace BLOCKED at this rung
# ---------------------------------------------------------------------------


def test_even_full_acceptance_keeps_trace_blocked_at_this_rung(tmp_path):
    g = RepairTraceEligibilityGuard()
    trace = _pass_trace(tmp_path)
    approval = _accepted_approval(trace)
    dec = g.evaluate(trace, approval=approval)
    assert dec.is_blocked, "Mocked output + temp workspace + no live model + policy still apply"
    assert "BLOCKED_MOCKED_MODEL_OUTPUT" in dec.blocked_reasons
    assert "BLOCKED_TEMP_WORKSPACE_ONLY" in dec.blocked_reasons
    assert "BLOCKED_NO_LIVE_MODEL_CALL" in dec.blocked_reasons
    assert "BLOCKED_POLICY" in dec.blocked_reasons


# ---------------------------------------------------------------------------
# Policy hypothetical — all flags True → EVIDENCE_ONLY decision
# ---------------------------------------------------------------------------


def test_hypothetical_all_open_policy_still_emits_evidence_only(tmp_path):
    """If every policy flag is True (a future rung would do this only
    after admitting live models and live operators), the decision is
    CORPUS_ELIGIBILITY_EVIDENCE_ONLY — still NOT training_eligible."""
    g = RepairTraceEligibilityGuard(
        policy={
            "mocked_outputs_are_corpus_eligible": True,
            "temp_only_patches_are_corpus_eligible": True,
            "unapproved_source_traces_are_corpus_eligible": True,
            "failed_verifier_traces_are_corpus_eligible": True,
            "unsupported_repo_traces_are_corpus_eligible": True,
            "no_live_model_traces_are_corpus_eligible": True,
            "policy_default_allow": True,
        }
    )
    trace = _pass_trace(tmp_path)
    approval = _accepted_approval(trace)
    dec = g.evaluate(trace, approval=approval)
    assert dec.decision == "CORPUS_ELIGIBILITY_EVIDENCE_ONLY"
    # Crucial: training_eligible is STILL False, even with open policy.
    # Eligibility requires a future rung's positive admission step.
    assert dec.training_eligible is False


# ---------------------------------------------------------------------------
# Source / I/O hygiene
# ---------------------------------------------------------------------------


def test_guard_call_does_not_mutate_workspace(tmp_path):
    ws = FIXTURES / "python_broken"
    before = _hash_tree(ws)
    g = RepairTraceEligibilityGuard()
    trace = _pass_trace(tmp_path)
    g.evaluate(trace)
    after = _hash_tree(ws)
    assert before == after


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("repair_trace_eligibility_guard.py", "repair_trace_eligibility_record.py"):
        src = (_REPO_ROOT / "scripts" / "corpus" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "from subprocess" not in src
        assert "import urllib" not in src
        assert "from urllib" not in src
        assert "import socket" not in src
        assert "import http" not in src


def test_decision_json_round_trip(tmp_path):
    g = RepairTraceEligibilityGuard()
    trace = _pass_trace(tmp_path)
    dec = g.evaluate(trace)
    parsed = json.loads(dec.to_json())
    assert parsed["training_eligible"] is False
    assert parsed["decision"] in ("CORPUS_ELIGIBILITY_BLOCKED", "CORPUS_ELIGIBILITY_EVIDENCE_ONLY")


# ---------------------------------------------------------------------------
# Lock + evidence + index
# ---------------------------------------------------------------------------


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "CORPUS_ELIGIBILITY_REPAIR_TRACE_GUARD_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)
    assert blob["scope_discipline"]["corpus_row_written"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates
    blob = json.loads(candidates[-1].read_text(encoding="utf-8"))
    assert blob["lock_id"] == "CORPUS_ELIGIBILITY_REPAIR_TRACE_GUARD_LOCK_001"


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "CORPUS_ELIGIBILITY_REPAIR_TRACE_GUARD_LOCK_001" in ids
