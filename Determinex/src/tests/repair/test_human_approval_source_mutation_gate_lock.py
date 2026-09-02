"""Tests for HUMAN_APPROVAL_SOURCE_MUTATION_GATE_LOCK_001.

Source mutation is blocked by default. The gate accepts only if every
required check passes:

  * operator + approval_token non-empty
  * trace_id matches
  * workspace identity matches
  * diff_sha256 matches the trace's safe_patch_result.unified_diff
  * verifier_status is PATCH_VERIFIER_PASSED_TEMP_ONLY
  * trace.final_status is TRACE_VERIFIER_PASSED_TEMP_ONLY
  * source_unchanged_confirmed is True

Any failure → specific blocked status. The gate is pure: it never
performs the actual original-repo write.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

gate_mod = importlib.import_module("repair.human_approval_gate")
rec_mod = importlib.import_module("repair.human_approval_record")
trace_mod = importlib.import_module("repair.verified_repair_trace")
sp_mod = importlib.import_module("repair.safe_patch_workspace")
router_mod = importlib.import_module("models.model_router")
inv_mod = importlib.import_module("models.model_inventory")

HumanApprovalGate = gate_mod.HumanApprovalGate
ApprovalPacket = rec_mod.ApprovalPacket
ApprovalGateDecision = rec_mod.ApprovalGateDecision
HUMAN_APPROVAL_STATUS_TOKENS = rec_mod.HUMAN_APPROVAL_STATUS_TOKENS
diff_hash = rec_mod.diff_hash

VerifiedRepairTraceRunner = trace_mod.VerifiedRepairTraceRunner
FilePatch = sp_mod.FilePatch
stub_verifier_pass = sp_mod.stub_verifier_pass
stub_verifier_fail = sp_mod.stub_verifier_fail

ModelRouter = router_mod.ModelRouter
LocalModelInventory = inv_mod.LocalModelInventory
CURRENT_MODEL_IDS = router_mod.CURRENT_MODEL_IDS

FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "intake"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "HUMAN_APPROVAL_SOURCE_MUTATION_GATE_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "human_approval_source_mutation_gate"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


STATUS_TOKENS = frozenset(
    {
        "SOURCE_MUTATION_APPROVAL_REQUIRED",
        "SOURCE_MUTATION_APPROVAL_ACCEPTED_FIXTURE",
        "SOURCE_MUTATION_BLOCKED_MISSING_APPROVAL",
        "SOURCE_MUTATION_BLOCKED_DIFF_MISMATCH",
        "SOURCE_MUTATION_BLOCKED_STALE_TRACE",
        "SOURCE_MUTATION_BLOCKED_VERIFIER_NOT_PASSED",
        "SOURCE_MUTATION_BLOCKED_REPO_MISMATCH",
        "SOURCE_MUTATION_BLOCKED_TRACE_ID_MISMATCH",
        "SOURCE_MUTATION_BLOCKED_OPERATOR_EMPTY",
    }
)


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


def _stocked_router() -> ModelRouter:
    inv = LocalModelInventory.of(sorted(CURRENT_MODEL_IDS))
    return ModelRouter(inventory=inv)


def _make_passing_trace(tmp_path: Path):
    """Produce a TRACE_VERIFIER_PASSED_TEMP_ONLY trace against python_broken."""
    runner = VerifiedRepairTraceRunner(router=_stocked_router(), salt="approval")
    return runner.run(
        FIXTURES / "python_broken",
        temp_root=tmp_path,
        patches=[FilePatch("src/calc.py", "x = 1\n")],
        verifier=stub_verifier_pass,
        workspace_id="approval_pass",
    )


def _make_packet(
    trace,
    *,
    operator="ryan",
    token="ok",
    diff_override=None,
    trace_id_override=None,
    workspace_override=None,
) -> ApprovalPacket:
    spr = trace.safe_patch_result or {}
    observed_diff = str(spr.get("unified_diff") or "")
    return ApprovalPacket(
        trace_id=trace_id_override if trace_id_override is not None else trace.trace_id,
        workspace_identity=workspace_override
        if workspace_override is not None
        else trace.workspace,
        diff_sha256=diff_override if diff_override is not None else diff_hash(observed_diff),
        verifier_status=str(spr.get("verifier_status") or ""),
        timestamp_utc=_dt.datetime.now(_dt.UTC).isoformat(),
        operator=operator,
        approval_token=token,
        fixture=True,
    )


# ---------------------------------------------------------------------------
# Status / closed set
# ---------------------------------------------------------------------------


def test_status_tokens_match_expected_set():
    assert set(HUMAN_APPROVAL_STATUS_TOKENS) == STATUS_TOKENS


# ---------------------------------------------------------------------------
# Required (UI default)
# ---------------------------------------------------------------------------


def test_required_emits_required_status_for_clean_trace(tmp_path):
    trace = _make_passing_trace(tmp_path)
    decision = HumanApprovalGate.required(trace)
    assert decision.decision == "SOURCE_MUTATION_APPROVAL_REQUIRED"
    assert decision.source_mutation_authorized is False


# ---------------------------------------------------------------------------
# Happy path (fixture acceptance)
# ---------------------------------------------------------------------------


def test_clean_packet_accepted_in_fixture_mode(tmp_path):
    trace = _make_passing_trace(tmp_path)
    gate = HumanApprovalGate()
    packet = _make_packet(trace)
    decision = gate.evaluate(packet, trace)
    assert decision.decision == "SOURCE_MUTATION_APPROVAL_ACCEPTED_FIXTURE"
    assert decision.source_mutation_authorized is True
    assert decision.is_accepted


# ---------------------------------------------------------------------------
# Empty operator / token
# ---------------------------------------------------------------------------


def test_empty_operator_blocks(tmp_path):
    trace = _make_passing_trace(tmp_path)
    gate = HumanApprovalGate()
    packet = _make_packet(trace, operator="")
    decision = gate.evaluate(packet, trace)
    assert decision.decision == "SOURCE_MUTATION_BLOCKED_OPERATOR_EMPTY"
    assert decision.source_mutation_authorized is False


def test_empty_token_blocks(tmp_path):
    trace = _make_passing_trace(tmp_path)
    gate = HumanApprovalGate()
    packet = _make_packet(trace, token="")
    decision = gate.evaluate(packet, trace)
    assert decision.decision == "SOURCE_MUTATION_BLOCKED_MISSING_APPROVAL"
    assert decision.source_mutation_authorized is False


# ---------------------------------------------------------------------------
# Mismatched fields
# ---------------------------------------------------------------------------


def test_trace_id_mismatch_blocks(tmp_path):
    trace = _make_passing_trace(tmp_path)
    gate = HumanApprovalGate()
    packet = _make_packet(trace, trace_id_override="0" * 64)
    decision = gate.evaluate(packet, trace)
    assert decision.decision == "SOURCE_MUTATION_BLOCKED_TRACE_ID_MISMATCH"


def test_workspace_identity_mismatch_blocks(tmp_path):
    trace = _make_passing_trace(tmp_path)
    gate = HumanApprovalGate()
    packet = _make_packet(trace, workspace_override="/wrong/path")
    decision = gate.evaluate(packet, trace)
    assert decision.decision == "SOURCE_MUTATION_BLOCKED_REPO_MISMATCH"


def test_diff_hash_mismatch_blocks(tmp_path):
    trace = _make_passing_trace(tmp_path)
    gate = HumanApprovalGate()
    packet = _make_packet(trace, diff_override="f" * 64)
    decision = gate.evaluate(packet, trace)
    assert decision.decision == "SOURCE_MUTATION_BLOCKED_DIFF_MISMATCH"


# ---------------------------------------------------------------------------
# Verifier not passed
# ---------------------------------------------------------------------------


def test_verifier_failed_trace_blocks_even_with_valid_packet(tmp_path):
    runner = VerifiedRepairTraceRunner(router=_stocked_router(), salt="approval")
    trace = runner.run(
        FIXTURES / "rust_broken",
        temp_root=tmp_path,
        patches=[FilePatch("src/lib.rs", "x\n")],
        verifier=stub_verifier_fail,
        workspace_id="approval_fail",
    )
    # Even if the operator constructs a "valid-looking" packet, the
    # verifier didn't pass — so the gate must refuse.
    gate = HumanApprovalGate()
    spr = trace.safe_patch_result or {}
    packet = ApprovalPacket(
        trace_id=trace.trace_id,
        workspace_identity=trace.workspace,
        diff_sha256=diff_hash(str(spr.get("unified_diff") or "")),
        verifier_status=str(spr.get("verifier_status") or ""),
        timestamp_utc=_dt.datetime.now(_dt.UTC).isoformat(),
        operator="ryan",
        approval_token="ok",
        fixture=True,
    )
    decision = gate.evaluate(packet, trace)
    # The diff is empty because PATCH_ROLLED_BACK clears the temp tree;
    # we land on diff_mismatch first OR verifier_not_passed — both are
    # acceptable refusals.
    assert decision.decision in (
        "SOURCE_MUTATION_BLOCKED_DIFF_MISMATCH",
        "SOURCE_MUTATION_BLOCKED_VERIFIER_NOT_PASSED",
        "SOURCE_MUTATION_BLOCKED_STALE_TRACE",
    )
    assert decision.source_mutation_authorized is False


def test_unsupported_repo_trace_blocks(tmp_path):
    runner = VerifiedRepairTraceRunner(router=_stocked_router(), salt="approval")
    trace = runner.run(
        FIXTURES / "unsupported_repo",
        temp_root=tmp_path,
        patches=[FilePatch("x.txt", "y\n")],
        verifier=stub_verifier_pass,
        workspace_id="approval_unsup",
    )
    assert trace.final_status == "TRACE_BLOCKED_UNSUPPORTED_REPO"
    gate = HumanApprovalGate()
    packet = ApprovalPacket(
        trace_id=trace.trace_id,
        workspace_identity=trace.workspace,
        diff_sha256="0" * 64,
        verifier_status="",
        timestamp_utc=_dt.datetime.now(_dt.UTC).isoformat(),
        operator="ryan",
        approval_token="ok",
    )
    decision = gate.evaluate(packet, trace)
    assert decision.is_blocked
    assert decision.source_mutation_authorized is False


# ---------------------------------------------------------------------------
# Source-preservation invariant under approval flow
# ---------------------------------------------------------------------------


def test_gate_call_does_not_mutate_original(tmp_path):
    """The gate is pure; calling it with any packet must not touch the
    original fixture tree."""
    ws = FIXTURES / "python_broken"
    before = _hash_tree(ws)
    trace = _make_passing_trace(tmp_path)
    gate = HumanApprovalGate()
    for op in ("", "ryan"):
        for tok in ("", "ok"):
            packet = _make_packet(trace, operator=op, token=tok)
            gate.evaluate(packet, trace)
    after = _hash_tree(ws)
    assert before == after


# ---------------------------------------------------------------------------
# Module hygiene
# ---------------------------------------------------------------------------


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("human_approval_gate.py", "human_approval_record.py"):
        src = (_REPO_ROOT / "scripts" / "repair" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "from subprocess" not in src
        assert "import urllib" not in src
        assert "from urllib" not in src
        assert "import socket" not in src
        assert "import http" not in src


def test_records_json_serializable(tmp_path):
    trace = _make_passing_trace(tmp_path)
    gate = HumanApprovalGate()
    packet = _make_packet(trace)
    decision = gate.evaluate(packet, trace)
    pj = json.loads(packet.to_json())
    dj = json.loads(decision.to_json())
    assert pj["trace_id"] == trace.trace_id
    assert dj["decision"] == "SOURCE_MUTATION_APPROVAL_ACCEPTED_FIXTURE"


# ---------------------------------------------------------------------------
# Lock + evidence + index
# ---------------------------------------------------------------------------


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "HUMAN_APPROVAL_SOURCE_MUTATION_GATE_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)
    assert blob["scope_discipline"]["user_source_mutated"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates
    blob = json.loads(candidates[-1].read_text(encoding="utf-8"))
    assert blob["lock_id"] == "HUMAN_APPROVAL_SOURCE_MUTATION_GATE_LOCK_001"


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "HUMAN_APPROVAL_SOURCE_MUTATION_GATE_LOCK_001" in ids
