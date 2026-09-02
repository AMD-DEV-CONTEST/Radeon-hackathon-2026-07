"""Tests for IDE_REPAIR_STATE_MODEL_LOCK_001.

The IDE state model assembles a flat JSON record from a
VerifiedRepairTrace (and optionally an ApprovalGateDecision). Tests:

  * supported repo + verifier pass → INTAKE_READY + VERIFIER_AVAILABLE
    + PATCH_VERIFIED_TEMP_ONLY + SOURCE_APPROVAL_REQUIRED
  * supported repo + verifier fail → PATCH_VERIFIER_FAILED +
    SOURCE_MUTATION_BLOCKED
  * unsupported repo → INTAKE_UNSUPPORTED with no patch states
  * with accepted ApprovalGateDecision → SOURCE_APPROVAL_ACCEPTED_FIXTURE
    + source_mutation_authorized=True
  * blocked ApprovalGateDecision → SOURCE_MUTATION_BLOCKED
  * corpus eligibility + training_eligible always False
  * no source mutation by state assembly
  * record JSON round-trip
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

model_mod = importlib.import_module("ide.repair_state_model")
rec_mod = importlib.import_module("ide.repair_state_record")
trace_mod = importlib.import_module("repair.verified_repair_trace")
sp_mod = importlib.import_module("repair.safe_patch_workspace")
approval_mod = importlib.import_module("repair.human_approval_gate")
approval_rec_mod = importlib.import_module("repair.human_approval_record")
router_mod = importlib.import_module("models.model_router")
inv_mod = importlib.import_module("models.model_inventory")

build_ide_state = model_mod.build_ide_state
IDERepairState = rec_mod.IDERepairState
IDE_REPAIR_STATE_TOKENS = rec_mod.IDE_REPAIR_STATE_TOKENS

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
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "IDE_REPAIR_STATE_MODEL_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "ide_repair_state_model"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


STATUS_TOKENS = frozenset(IDE_REPAIR_STATE_TOKENS)


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
    return VerifiedRepairTraceRunner(router=ModelRouter(inventory=inv), salt="ide")


def _pass_trace(tmp_path):
    return _runner().run(
        FIXTURES / "python_broken",
        tmp_path,
        patches=[FilePatch("src/calc.py", "x = 1\n")],
        verifier=stub_verifier_pass,
        workspace_id="ide_pass",
    )


def _fail_trace(tmp_path):
    return _runner().run(
        FIXTURES / "rust_broken",
        tmp_path,
        patches=[FilePatch("src/lib.rs", "x\n")],
        verifier=stub_verifier_fail,
        workspace_id="ide_fail",
    )


def _unsupported_trace(tmp_path):
    return _runner().run(
        FIXTURES / "unsupported_repo",
        tmp_path,
        patches=[FilePatch("x.txt", "y\n")],
        verifier=stub_verifier_pass,
        workspace_id="ide_unsup",
    )


# ---------------------------------------------------------------------------
# Status / closed set
# ---------------------------------------------------------------------------


def test_state_tokens_match_expected_set():
    expected = {
        "INTAKE_READY",
        "INTAKE_UNSUPPORTED",
        "VERIFIER_AVAILABLE",
        "VERIFIER_MISSING",
        "MODEL_ROUTE_SELECTED",
        "MODEL_ROUTE_BLOCKED",
        "MODEL_ROUTE_NO_MODEL",
        "PATCH_PLAN_AVAILABLE",
        "PATCH_PLAN_UNAVAILABLE",
        "PATCH_TEMP_APPLIED",
        "PATCH_TEMP_FAILED",
        "PATCH_VERIFIED_TEMP_ONLY",
        "PATCH_VERIFIER_FAILED",
        "SOURCE_APPROVAL_REQUIRED",
        "SOURCE_APPROVAL_ACCEPTED_FIXTURE",
        "SOURCE_MUTATION_BLOCKED",
        "CORPUS_ELIGIBILITY_FALSE",
        "EVIDENCE_AVAILABLE",
    }
    assert set(STATUS_TOKENS) == expected


# ---------------------------------------------------------------------------
# Supported pass path
# ---------------------------------------------------------------------------


def test_supported_pass_trace_yields_ready_passed(tmp_path):
    trace = _pass_trace(tmp_path)
    state = build_ide_state(trace)
    d = state.to_dict()
    assert d["intake"] == "INTAKE_READY"
    assert d["verifier"] == "VERIFIER_AVAILABLE"
    assert d["model_route"] == "MODEL_ROUTE_SELECTED"
    assert d["selected_model_id"] in CURRENT_MODEL_IDS
    assert d["patch_plan"] == "PATCH_PLAN_AVAILABLE"
    assert d["patch_temp"] == "PATCH_TEMP_APPLIED"
    assert d["patch_verifier"] == "PATCH_VERIFIED_TEMP_ONLY"
    # No approval supplied → REQUIRED.
    assert d["source_approval"] == "SOURCE_APPROVAL_REQUIRED"
    assert d["source_mutation_authorized"] is False
    assert d["corpus_eligibility"] == "CORPUS_ELIGIBILITY_FALSE"
    assert d["training_eligible"] is False


# ---------------------------------------------------------------------------
# Supported fail path
# ---------------------------------------------------------------------------


def test_supported_fail_trace_yields_verifier_failed(tmp_path):
    trace = _fail_trace(tmp_path)
    state = build_ide_state(trace)
    d = state.to_dict()
    assert d["intake"] == "INTAKE_READY"
    # Verifier ran but didn't pass — VERIFIER_AVAILABLE captures the
    # presence of a verifier; patch_verifier captures the outcome.
    assert d["patch_verifier"] == "PATCH_VERIFIER_FAILED"
    assert d["source_mutation_authorized"] is False
    assert d["training_eligible"] is False


# ---------------------------------------------------------------------------
# Unsupported repo
# ---------------------------------------------------------------------------


def test_unsupported_trace_yields_unsupported(tmp_path):
    trace = _unsupported_trace(tmp_path)
    state = build_ide_state(trace)
    d = state.to_dict()
    assert d["intake"] == "INTAKE_UNSUPPORTED"
    assert d["source_mutation_authorized"] is False
    assert d["training_eligible"] is False


# ---------------------------------------------------------------------------
# Approval interactions
# ---------------------------------------------------------------------------


def test_accepted_approval_flips_source_authorized(tmp_path):
    trace = _pass_trace(tmp_path)
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
    assert decision.is_accepted
    state = build_ide_state(trace, approval=decision)
    d = state.to_dict()
    assert d["source_approval"] == "SOURCE_APPROVAL_ACCEPTED_FIXTURE"
    assert d["source_mutation_authorized"] is True


def test_blocked_approval_yields_source_mutation_blocked(tmp_path):
    trace = _pass_trace(tmp_path)
    gate = HumanApprovalGate()
    bad_packet = ApprovalPacket(
        trace_id="0" * 64,
        workspace_identity=trace.workspace,
        diff_sha256="0" * 64,
        verifier_status="",
        timestamp_utc=_dt.datetime.now(_dt.UTC).isoformat(),
        operator="ryan",
        approval_token="ok",
    )
    decision = gate.evaluate(bad_packet, trace)
    state = build_ide_state(trace, approval=decision)
    d = state.to_dict()
    assert d["source_approval"] == "SOURCE_MUTATION_BLOCKED"
    assert d["source_mutation_authorized"] is False


def test_required_approval_keeps_required_status(tmp_path):
    trace = _pass_trace(tmp_path)
    decision = HumanApprovalGate.required(trace)
    state = build_ide_state(trace, approval=decision)
    d = state.to_dict()
    assert d["source_approval"] == "SOURCE_APPROVAL_REQUIRED"
    assert d["source_mutation_authorized"] is False


# ---------------------------------------------------------------------------
# Evidence pointers
# ---------------------------------------------------------------------------


def test_evidence_pointers_surface_in_state(tmp_path):
    trace = _pass_trace(tmp_path)
    state = build_ide_state(
        trace,
        lock_paths=("locks/sentinel/MODEL_ROUTER_LOCK_001.json",),
        evidence_paths=("assurance/evidence/model_router/run_20260527.json",),
    )
    d = state.to_dict()
    assert "EVIDENCE_AVAILABLE" in d["statuses_seen"]
    assert "locks/sentinel/MODEL_ROUTER_LOCK_001.json" in d["evidence"]["locks"]


# ---------------------------------------------------------------------------
# Corpus eligibility / training eligibility invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", ["pass", "fail", "unsupported"])
def test_corpus_eligibility_always_false_and_training_eligible_false(scenario, tmp_path):
    if scenario == "pass":
        trace = _pass_trace(tmp_path)
    elif scenario == "fail":
        trace = _fail_trace(tmp_path)
    else:
        trace = _unsupported_trace(tmp_path)
    state = build_ide_state(trace)
    d = state.to_dict()
    assert d["corpus_eligibility"] == "CORPUS_ELIGIBILITY_FALSE"
    assert d["training_eligible"] is False


# ---------------------------------------------------------------------------
# Source-preservation under state assembly
# ---------------------------------------------------------------------------


def test_state_assembly_does_not_touch_workspace(tmp_path):
    ws = FIXTURES / "python_broken"
    before = _hash_tree(ws)
    trace = _pass_trace(tmp_path)
    build_ide_state(trace)
    after = _hash_tree(ws)
    assert before == after


# ---------------------------------------------------------------------------
# Module hygiene
# ---------------------------------------------------------------------------


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("repair_state_model.py", "repair_state_record.py"):
        src = (_REPO_ROOT / "scripts" / "ide" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "from subprocess" not in src
        assert "import urllib" not in src
        assert "from urllib" not in src
        assert "import socket" not in src
        assert "import http" not in src


def test_state_json_round_trip(tmp_path):
    trace = _pass_trace(tmp_path)
    state = build_ide_state(trace)
    parsed = json.loads(state.to_json())
    assert parsed["trace_id"] == trace.trace_id
    assert parsed["training_eligible"] is False


# ---------------------------------------------------------------------------
# Lock + evidence + index
# ---------------------------------------------------------------------------


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "IDE_REPAIR_STATE_MODEL_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates
    blob = json.loads(candidates[-1].read_text(encoding="utf-8"))
    assert blob["lock_id"] == "IDE_REPAIR_STATE_MODEL_LOCK_001"


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "IDE_REPAIR_STATE_MODEL_LOCK_001" in ids
