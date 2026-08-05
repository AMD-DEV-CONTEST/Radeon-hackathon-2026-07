"""Tests for IDE_LIVE_MODEL_REPAIR_FLOW_STATE_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

flow_mod = importlib.import_module("ide.live_model_repair_flow_state")
rec_mod = importlib.import_module("ide.live_model_repair_flow_record")

build_live_flow_state = flow_mod.build_live_flow_state
IDE_LIVE_MODEL_REPAIR_FLOW_STATE_TOKENS = rec_mod.IDE_LIVE_MODEL_REPAIR_FLOW_STATE_TOKENS

# Reuse admission + diagnose + quarantine + temp-patch test helpers.
admission_mod = importlib.import_module("models.live_model_admission")
policy_mod = importlib.import_module("models.local_model_admission_policy")
router_mod = importlib.import_module("models.model_router")
inv_mod = importlib.import_module("models.model_inventory")
trace_mod = importlib.import_module("repair.live_diagnose_trace")
harness_mod = importlib.import_module("models.live_model_compat_harness")
quarantine_mod = importlib.import_module("repair.live_patch_plan_quarantine")
verifier_gate_mod = importlib.import_module("repair.live_temp_patch_verifier_gate")
sp_mod = importlib.import_module("repair.safe_patch_workspace")

LiveModelAdmissionGate = admission_mod.LiveModelAdmissionGate
LiveModelAdmissionConfig = admission_mod.LiveModelAdmissionConfig
LiveAdmissionMode = admission_mod.LiveAdmissionMode
LocalModelCandidate = policy_mod.LocalModelCandidate
ModelProvider = policy_mod.ModelProvider
ModelRouter = router_mod.ModelRouter
RouterMode = router_mod.RouterMode
TaskClass = router_mod.TaskClass
CURRENT_MODEL_IDS = router_mod.CURRENT_MODEL_IDS
LocalModelInventory = inv_mod.LocalModelInventory
LiveDiagnoseTraceRunner = trace_mod.LiveDiagnoseTraceRunner
DeterministicProvider = harness_mod.DeterministicProvider
LivePatchPlanQuarantine = quarantine_mod.LivePatchPlanQuarantine
LiveTempPatchVerifierGate = verifier_gate_mod.LiveTempPatchVerifierGate
stub_verifier_pass = sp_mod.stub_verifier_pass
stub_verifier_fail = sp_mod.stub_verifier_fail

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "IDE_LIVE_MODEL_REPAIR_FLOW_STATE_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "ide_live_model_repair_flow_state"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(IDE_LIVE_MODEL_REPAIR_FLOW_STATE_TOKENS)
FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "intake"


def _admission_ready():
    inv = LocalModelInventory.of(sorted(CURRENT_MODEL_IDS))
    gate = LiveModelAdmissionGate(
        config=LiveModelAdmissionConfig(
            mode=LiveAdmissionMode.OPT_IN_LIVE,
            opt_in_live=True,
        )
    )
    candidate = LocalModelCandidate(
        model_id="determinex-engineer-v11-dsl",
        provider=ModelProvider.OLLAMA.value,
        capability_tags=("code_generation",),
        supported_task_classes=(TaskClass.PATCH_GENERATION.value,),
    )
    return gate.evaluate(
        candidate,
        TaskClass.PATCH_GENERATION,
        inv,
        ModelRouter(inventory=inv).route(TaskClass.PATCH_GENERATION, mode=RouterMode.LIVE),
    )


def _admission_blocked():
    inv = LocalModelInventory.of(sorted(CURRENT_MODEL_IDS))
    gate = LiveModelAdmissionGate()
    candidate = LocalModelCandidate(
        model_id="determinex-engineer-v11-dsl",
        provider=ModelProvider.OLLAMA.value,
        capability_tags=("code_generation",),
        supported_task_classes=(TaskClass.PATCH_GENERATION.value,),
    )
    return gate.evaluate(
        candidate,
        TaskClass.PATCH_GENERATION,
        inv,
        ModelRouter(inventory=inv).route(TaskClass.PATCH_GENERATION),
    )


# ---------------------------------------------------------------------------
# Status / closed set
# ---------------------------------------------------------------------------


def test_status_tokens_match_expected_set():
    expected = {
        "LIVE_MODEL_NOT_ADMITTED",
        "LIVE_MODEL_ADMITTED",
        "DIAGNOSIS_ADVISORY_AVAILABLE",
        "PATCH_PLAN_QUARANTINED",
        "TEMP_PATCH_VERIFIER_FAILED",
        "TEMP_PATCH_VERIFIER_PASSED",
        "HUMAN_APPROVAL_REQUIRED",
        "SOURCE_MUTATION_BLOCKED",
        "TRAINING_ELIGIBLE_FALSE",
        "EVIDENCE_AVAILABLE",
    }
    assert set(STATUS_TOKENS) == expected


# ---------------------------------------------------------------------------
# Admission only
# ---------------------------------------------------------------------------


def test_admitted_minimal_state():
    state = build_live_flow_state(FIXTURES / "python_broken", admission=_admission_ready())
    d = state.to_dict()
    assert d["live_admission"] == "LIVE_MODEL_ADMITTED"
    assert d["human_approval"] == "HUMAN_APPROVAL_REQUIRED"
    assert d["source_mutation"] == "SOURCE_MUTATION_BLOCKED"
    assert d["training_eligibility"] == "TRAINING_ELIGIBLE_FALSE"


def test_unadmitted_minimal_state():
    state = build_live_flow_state(FIXTURES / "python_broken", admission=_admission_blocked())
    assert state.live_admission == "LIVE_MODEL_NOT_ADMITTED"
    assert state.human_approval == "HUMAN_APPROVAL_REQUIRED"
    assert state.source_mutation == "SOURCE_MUTATION_BLOCKED"


# ---------------------------------------------------------------------------
# Composed states
# ---------------------------------------------------------------------------


def test_admitted_plus_diagnosis_plus_quarantined_plan(tmp_path):
    admission = _admission_ready()
    runner = LiveDiagnoseTraceRunner()
    diagnose = runner.run(
        FIXTURES / "python_broken",
        task_class="BUILD_DIAGNOSIS",
        admission=admission,
        provider=DeterministicProvider(canned={"summary": "ok"}),
    )
    q = LivePatchPlanQuarantine()
    plan = q.quarantine(
        [{"operation": "replace_file", "path": "src/x.py", "new_content": "ok\n"}],
        admission=admission,
        workspace=FIXTURES / "python_broken",
    )
    state = build_live_flow_state(
        FIXTURES / "python_broken",
        admission=admission,
        diagnose=diagnose,
        plan=plan,
    )
    assert state.diagnosis_advisory == "DIAGNOSIS_ADVISORY_AVAILABLE"
    assert state.patch_plan == "PATCH_PLAN_QUARANTINED"
    assert state.source_mutation == "SOURCE_MUTATION_BLOCKED"
    assert state.training_eligibility == "TRAINING_ELIGIBLE_FALSE"


def test_temp_patch_passed_does_not_open_source_mutation(tmp_path):
    """Even with TEMP_PATCH_VERIFIER_PASSED, source mutation stays blocked."""
    admission = _admission_ready()
    (tmp_path / "orig" / "src").mkdir(parents=True)
    (tmp_path / "orig" / "src" / "lib.py").write_text("x = 0\n", encoding="utf-8")
    q = LivePatchPlanQuarantine()
    plan = q.quarantine(
        [{"operation": "replace_file", "path": "src/lib.py", "new_content": "x = 1\n"}],
        admission=admission,
        workspace=tmp_path / "orig",
    )
    g = LiveTempPatchVerifierGate()
    vr = g.apply_and_verify(plan, temp_root=tmp_path / "tmp", verifier=stub_verifier_pass)

    state = build_live_flow_state(
        tmp_path / "orig",
        admission=admission,
        plan=plan,
        verifier_result=vr,
    )
    assert state.temp_patch_verifier == "TEMP_PATCH_VERIFIER_PASSED"
    assert state.source_mutation == "SOURCE_MUTATION_BLOCKED"
    assert state.human_approval == "HUMAN_APPROVAL_REQUIRED"
    assert state.training_eligibility == "TRAINING_ELIGIBLE_FALSE"


def test_temp_patch_failed_state(tmp_path):
    admission = _admission_ready()
    (tmp_path / "orig" / "src").mkdir(parents=True)
    (tmp_path / "orig" / "src" / "lib.py").write_text("x = 0\n", encoding="utf-8")
    q = LivePatchPlanQuarantine()
    plan = q.quarantine(
        [{"operation": "replace_file", "path": "src/lib.py", "new_content": "x = 2\n"}],
        admission=admission,
        workspace=tmp_path / "orig",
    )
    g = LiveTempPatchVerifierGate()
    vr = g.apply_and_verify(plan, temp_root=tmp_path / "tmp", verifier=stub_verifier_fail)
    state = build_live_flow_state(
        tmp_path / "orig",
        admission=admission,
        plan=plan,
        verifier_result=vr,
    )
    assert state.temp_patch_verifier == "TEMP_PATCH_VERIFIER_FAILED"
    assert state.source_mutation == "SOURCE_MUTATION_BLOCKED"


# ---------------------------------------------------------------------------
# Conservative defaults — always
# ---------------------------------------------------------------------------


def test_human_approval_required_and_source_mutation_blocked_always():
    admission = _admission_ready()
    state = build_live_flow_state(FIXTURES / "python_broken", admission=admission)
    assert state.human_approval == "HUMAN_APPROVAL_REQUIRED"
    assert state.source_mutation == "SOURCE_MUTATION_BLOCKED"
    assert state.training_eligibility == "TRAINING_ELIGIBLE_FALSE"


# ---------------------------------------------------------------------------
# Evidence pointers
# ---------------------------------------------------------------------------


def test_evidence_pointers_surface():
    state = build_live_flow_state(
        FIXTURES / "python_broken",
        admission=_admission_ready(),
        evidence_locks=("locks/sentinel/LOCAL_MODEL_LIVE_ADMISSION_LOCK_001.json",),
        evidence_files=("assurance/evidence/local_model_live_admission/run_20260527.json",),
    )
    assert "EVIDENCE_AVAILABLE" in state.statuses_seen


# ---------------------------------------------------------------------------
# Hygiene
# ---------------------------------------------------------------------------


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("live_model_repair_flow_state.py", "live_model_repair_flow_record.py"):
        src = (_REPO_ROOT / "scripts" / "ide" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "from subprocess" not in src
        assert "import urllib" not in src
        assert "from urllib" not in src


def test_state_json_round_trip():
    state = build_live_flow_state(FIXTURES / "python_broken", admission=_admission_ready())
    parsed = json.loads(state.to_json())
    assert parsed["training_eligibility"] == "TRAINING_ELIGIBLE_FALSE"
    assert parsed["source_mutation"] == "SOURCE_MUTATION_BLOCKED"


# ---------------------------------------------------------------------------
# Lock + evidence + index
# ---------------------------------------------------------------------------


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "IDE_LIVE_MODEL_REPAIR_FLOW_STATE_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates
    blob = json.loads(candidates[-1].read_text(encoding="utf-8"))
    assert blob["lock_id"] == "IDE_LIVE_MODEL_REPAIR_FLOW_STATE_LOCK_001"


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "IDE_LIVE_MODEL_REPAIR_FLOW_STATE_LOCK_001" in ids
