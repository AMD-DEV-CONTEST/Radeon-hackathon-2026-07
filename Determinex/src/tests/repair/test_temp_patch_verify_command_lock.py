"""Tests for TEMP_PATCH_VERIFY_COMMAND_LOCK_001."""

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

cmd_mod = importlib.import_module("repair.temp_patch_verify_command")
rec_mod = importlib.import_module("repair.temp_patch_verify_record")
quarantine_mod = importlib.import_module("repair.live_patch_plan_quarantine")
admission_mod = importlib.import_module("models.live_model_admission")
policy_mod = importlib.import_module("models.local_model_admission_policy")
router_mod = importlib.import_module("models.model_router")
inv_mod = importlib.import_module("models.model_inventory")
sp_mod = importlib.import_module("repair.safe_patch_workspace")

TempPatchVerifyCommand = cmd_mod.TempPatchVerifyCommand
TEMP_PATCH_VERIFY_STATUS_TOKENS = rec_mod.TEMP_PATCH_VERIFY_STATUS_TOKENS

LivePatchPlanQuarantine = quarantine_mod.LivePatchPlanQuarantine
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
stub_verifier_pass = sp_mod.stub_verifier_pass
stub_verifier_fail = sp_mod.stub_verifier_fail

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "TEMP_PATCH_VERIFY_COMMAND_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "temp_patch_verify_command"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(TEMP_PATCH_VERIFY_STATUS_TOKENS)


def _hash_tree(root: Path) -> dict[str, str]:
    out = {}
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


def _seed(tmp_path: Path) -> Path:
    ws = tmp_path / "orig"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "lib.py").write_text("x = 0\n", encoding="utf-8")
    return ws


def _admission():
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


def _quarantine(ws: Path, content: str):
    return LivePatchPlanQuarantine().quarantine(
        [{"operation": "replace_file", "path": "src/lib.py", "new_content": content}],
        admission=_admission(),
        workspace=ws,
    )


def test_status_tokens_match_expected_set():
    expected = {
        "TEMP_PATCH_VERIFY_PASSED_TEMP_ONLY",
        "TEMP_PATCH_VERIFY_FAILED",
        "TEMP_PATCH_VERIFY_BLOCKED_NO_PLAN",
        "TEMP_PATCH_VERIFY_BLOCKED_PATH_ESCAPE",
        "TEMP_PATCH_VERIFY_SOURCE_UNCHANGED",
        "TEMP_PATCH_VERIFY_HUMAN_APPROVAL_REQUIRED",
    }
    assert set(STATUS_TOKENS) == expected


def test_passing_verifier(tmp_path):
    ws = _seed(tmp_path)
    plan = _quarantine(ws, "x = 1\n")
    before = _hash_tree(ws)
    rec = TempPatchVerifyCommand().run(
        plan, temp_root=tmp_path / "tmp", verifier=stub_verifier_pass
    )
    assert rec.decision == "TEMP_PATCH_VERIFY_PASSED_TEMP_ONLY"
    assert rec.human_approval_required is True
    assert rec.source_unchanged_confirmed is True
    assert rec.training_eligible is False
    assert _hash_tree(ws) == before


def test_failing_verifier(tmp_path):
    ws = _seed(tmp_path)
    plan = _quarantine(ws, "x = 2\n")
    rec = TempPatchVerifyCommand().run(
        plan, temp_root=tmp_path / "tmp", verifier=stub_verifier_fail
    )
    assert rec.decision == "TEMP_PATCH_VERIFY_FAILED"
    assert rec.training_eligible is False


def test_no_plan_blocks(tmp_path):
    ws = _seed(tmp_path)
    # Construct a BLOCKED quarantine.
    plan = LivePatchPlanQuarantine().quarantine(
        [{"operation": "delete_file", "path": "x", "new_content": ""}],
        admission=_admission(),
        workspace=ws,
    )
    rec = TempPatchVerifyCommand().run(plan, temp_root=tmp_path / "tmp")
    assert rec.decision == "TEMP_PATCH_VERIFY_BLOCKED_NO_PLAN"


def test_human_approval_required_always(tmp_path):
    ws = _seed(tmp_path)
    plan = _quarantine(ws, "x = 1\n")
    for v in (stub_verifier_pass, stub_verifier_fail):
        rec = TempPatchVerifyCommand().run(plan, temp_root=tmp_path / f"t_{id(v)}", verifier=v)
        assert rec.human_approval_required is True


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("temp_patch_verify_command.py", "temp_patch_verify_record.py"):
        src = (_REPO_ROOT / "scripts" / "repair" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "import urllib" not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "TEMP_PATCH_VERIFY_COMMAND_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "TEMP_PATCH_VERIFY_COMMAND_LOCK_001" in ids
