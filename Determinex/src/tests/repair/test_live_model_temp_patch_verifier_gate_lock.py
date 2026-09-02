"""Tests for LIVE_MODEL_TEMP_PATCH_VERIFIER_GATE_LOCK_001."""

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

gate_mod = importlib.import_module("repair.live_temp_patch_verifier_gate")
rec_mod = importlib.import_module("repair.live_temp_patch_verifier_record")
quarantine_mod = importlib.import_module("repair.live_patch_plan_quarantine")
admission_mod = importlib.import_module("models.live_model_admission")
policy_mod = importlib.import_module("models.local_model_admission_policy")
router_mod = importlib.import_module("models.model_router")
inv_mod = importlib.import_module("models.model_inventory")
sp_mod = importlib.import_module("repair.safe_patch_workspace")

LiveTempPatchVerifierGate = gate_mod.LiveTempPatchVerifierGate
LIVE_TEMP_PATCH_VERIFIER_STATUS_TOKENS = rec_mod.LIVE_TEMP_PATCH_VERIFIER_STATUS_TOKENS

LivePatchPlanQuarantine = quarantine_mod.LivePatchPlanQuarantine
stub_verifier_pass = sp_mod.stub_verifier_pass
stub_verifier_fail = sp_mod.stub_verifier_fail

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

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "LIVE_MODEL_TEMP_PATCH_VERIFIER_GATE_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "live_model_temp_patch_verifier_gate"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(LIVE_TEMP_PATCH_VERIFIER_STATUS_TOKENS)


def _seed_original(tmp_path: Path) -> Path:
    """Create a minimal source repo under tmp_path."""
    original = tmp_path / "original"
    (original / "src").mkdir(parents=True)
    (original / "src" / "lib.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    return original


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


def _admission_ready():
    gate = LiveModelAdmissionGate(
        config=LiveModelAdmissionConfig(
            mode=LiveAdmissionMode.OPT_IN_LIVE,
            opt_in_live=True,
        )
    )
    inv = LocalModelInventory.of(sorted(CURRENT_MODEL_IDS))
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


def _quarantine(content: str, original: Path):
    q = LivePatchPlanQuarantine()
    return q.quarantine(
        [{"operation": "replace_file", "path": "src/lib.py", "new_content": content}],
        admission=_admission_ready(),
        workspace=original,
        provider_name="ollama",
        model_id="determinex-engineer-v11-dsl",
    )


# ---------------------------------------------------------------------------
# Status / closed set
# ---------------------------------------------------------------------------


def test_status_tokens_match_expected_set():
    expected = {
        "LIVE_PATCH_TEMP_APPLIED",
        "LIVE_PATCH_VERIFIER_FAILED",
        "LIVE_PATCH_VERIFIER_PASSED_TEMP_ONLY",
        "LIVE_PATCH_BLOCKED_NO_QUARANTINED_PLAN",
        "LIVE_PATCH_BLOCKED_SOURCE_MUTATION",
        "LIVE_PATCH_BLOCKED_SAFE_PATCH_REJECTED",
        "LIVE_PATCH_ROLLED_BACK",
        "LIVE_PATCH_SOURCE_UNCHANGED_CONFIRMED",
        "LIVE_PATCH_HUMAN_APPROVAL_REQUIRED",
        "LIVE_PATCH_TRAINING_ELIGIBLE_FALSE",
    }
    assert set(STATUS_TOKENS) == expected


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_temp_patch_with_passing_verifier(tmp_path):
    original = _seed_original(tmp_path)
    before = _hash_tree(original)
    plan = _quarantine("def add(a, b):\n    return a + b + 0\n", original)
    g = LiveTempPatchVerifierGate()
    res = g.apply_and_verify(plan, temp_root=tmp_path / "tmp", verifier=stub_verifier_pass)
    assert res.decision == "LIVE_PATCH_VERIFIER_PASSED_TEMP_ONLY"
    assert res.source_unchanged_confirmed is True
    assert res.human_approval_required is True
    assert res.training_eligible is False
    assert _hash_tree(original) == before


def test_temp_patch_with_failing_verifier_rolls_back(tmp_path):
    original = _seed_original(tmp_path)
    before = _hash_tree(original)
    plan = _quarantine("x = 1\n", original)
    g = LiveTempPatchVerifierGate()
    res = g.apply_and_verify(plan, temp_root=tmp_path / "tmp", verifier=stub_verifier_fail)
    assert res.decision == "LIVE_PATCH_VERIFIER_FAILED"
    assert res.rolled_back is True
    assert res.source_unchanged_confirmed is True
    assert _hash_tree(original) == before


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


def test_non_quarantined_plan_blocks(tmp_path):
    """A plan that itself is BLOCKED cannot be applied."""
    original = _seed_original(tmp_path)
    q = LivePatchPlanQuarantine()
    plan = q.quarantine(
        [{"operation": "delete_file", "path": "src/lib.py", "new_content": ""}],
        admission=_admission_ready(),
        workspace=original,
    )
    assert plan.is_blocked
    g = LiveTempPatchVerifierGate()
    res = g.apply_and_verify(plan, temp_root=tmp_path / "tmp")
    assert res.decision == "LIVE_PATCH_BLOCKED_NO_QUARANTINED_PLAN"


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


def test_human_approval_required_on_every_path(tmp_path):
    original = _seed_original(tmp_path)
    plan = _quarantine("ok\n", original)
    g = LiveTempPatchVerifierGate()
    for v in (stub_verifier_pass, stub_verifier_fail, None):
        res = g.apply_and_verify(plan, temp_root=tmp_path / f"tmp_{id(v)}", verifier=v)
        assert res.human_approval_required is True


def test_training_eligible_false_on_every_path(tmp_path):
    original = _seed_original(tmp_path)
    plan = _quarantine("ok\n", original)
    g = LiveTempPatchVerifierGate()
    for v in (stub_verifier_pass, stub_verifier_fail):
        res = g.apply_and_verify(plan, temp_root=tmp_path / f"tmp_{id(v)}_train", verifier=v)
        assert res.training_eligible is False


# ---------------------------------------------------------------------------
# Hygiene
# ---------------------------------------------------------------------------


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("live_temp_patch_verifier_gate.py", "live_temp_patch_verifier_record.py"):
        src = (_REPO_ROOT / "scripts" / "repair" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "from subprocess" not in src
        assert "import urllib" not in src
        assert "from urllib" not in src


def test_result_json_round_trip(tmp_path):
    original = _seed_original(tmp_path)
    plan = _quarantine("ok\n", original)
    g = LiveTempPatchVerifierGate()
    res = g.apply_and_verify(plan, temp_root=tmp_path / "tmp", verifier=stub_verifier_pass)
    parsed = json.loads(res.to_json())
    assert parsed["training_eligible"] is False
    assert parsed["human_approval_required"] is True


# ---------------------------------------------------------------------------
# Lock + evidence + index
# ---------------------------------------------------------------------------


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "LIVE_MODEL_TEMP_PATCH_VERIFIER_GATE_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates
    blob = json.loads(candidates[-1].read_text(encoding="utf-8"))
    assert blob["lock_id"] == "LIVE_MODEL_TEMP_PATCH_VERIFIER_GATE_LOCK_001"


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "LIVE_MODEL_TEMP_PATCH_VERIFIER_GATE_LOCK_001" in ids
