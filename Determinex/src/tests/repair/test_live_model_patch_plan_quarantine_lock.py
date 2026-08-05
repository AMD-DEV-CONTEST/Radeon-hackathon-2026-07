"""Tests for LIVE_MODEL_PATCH_PLAN_QUARANTINE_LOCK_001."""

from __future__ import annotations

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

quarantine_mod = importlib.import_module("repair.live_patch_plan_quarantine")
rec_mod = importlib.import_module("repair.live_patch_plan_record")
admission_mod = importlib.import_module("models.live_model_admission")
policy_mod = importlib.import_module("models.local_model_admission_policy")
router_mod = importlib.import_module("models.model_router")
inv_mod = importlib.import_module("models.model_inventory")

LivePatchPlanQuarantine = quarantine_mod.LivePatchPlanQuarantine
LIVE_PATCH_PLAN_STATUS_TOKENS = rec_mod.LIVE_PATCH_PLAN_STATUS_TOKENS
PatchOp = rec_mod.PatchOp

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

FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "intake"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "LIVE_MODEL_PATCH_PLAN_QUARANTINE_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "live_model_patch_plan_quarantine"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(LIVE_PATCH_PLAN_STATUS_TOKENS)


def _stocked_inventory():
    return LocalModelInventory.of(sorted(CURRENT_MODEL_IDS))


def _admission_ready():
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
        _stocked_inventory(),
        ModelRouter(inventory=_stocked_inventory()).route(
            TaskClass.PATCH_GENERATION, mode=RouterMode.LIVE
        ),
    )


def _admission_blocked():
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
        _stocked_inventory(),
        ModelRouter(inventory=_stocked_inventory()).route(TaskClass.PATCH_GENERATION),
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


# ---------------------------------------------------------------------------
# Status / closed set
# ---------------------------------------------------------------------------


def test_status_tokens_match_expected_set():
    expected = {
        "PATCH_PLAN_QUARANTINED",
        "PATCH_PLAN_BLOCKED_SCHEMA_INVALID",
        "PATCH_PLAN_BLOCKED_PATH_ESCAPE",
        "PATCH_PLAN_BLOCKED_UNSUPPORTED_OPERATION",
        "PATCH_PLAN_BLOCKED_MODEL_NOT_ADMITTED",
        "PATCH_PLAN_BLOCKED_BINARY_CONTENT",
        "PATCH_PLAN_BLOCKED_OVERSIZED",
    }
    assert set(STATUS_TOKENS) == expected


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_plan_quarantined():
    q = LivePatchPlanQuarantine()
    plan = q.quarantine(
        [{"operation": "replace_file", "path": "src/x.py", "new_content": "y = 2\n"}],
        admission=_admission_ready(),
        workspace=FIXTURES / "python_broken",
        provider_name="ollama",
        model_id="determinex-engineer-v11-dsl",
    )
    assert plan.decision == "PATCH_PLAN_QUARANTINED"
    assert len(plan.entries) == 1
    assert plan.entries[0].path == "src/x.py"
    # Hard invariants
    assert plan.trusted is False
    assert plan.applied_to_source is False
    assert plan.applied_to_temp_workspace is False
    assert plan.source_mutation_authorized is False
    assert plan.corpus_write_authorized is False
    assert plan.training_eligible is False


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


def test_unadmitted_model_blocks():
    q = LivePatchPlanQuarantine()
    plan = q.quarantine(
        [{"operation": "replace_file", "path": "src/x.py", "new_content": "ok\n"}],
        admission=_admission_blocked(),
        workspace=FIXTURES / "python_broken",
    )
    assert plan.decision == "PATCH_PLAN_BLOCKED_MODEL_NOT_ADMITTED"


def test_schema_invalid_blocks():
    q = LivePatchPlanQuarantine()
    plan = q.quarantine(
        [{"not_a_valid_entry": True}],
        admission=_admission_ready(),
        workspace=FIXTURES / "python_broken",
    )
    assert plan.decision == "PATCH_PLAN_BLOCKED_UNSUPPORTED_OPERATION"


def test_non_dict_entry_blocks_schema_invalid():
    q = LivePatchPlanQuarantine()
    plan = q.quarantine(
        ["not a dict"],
        admission=_admission_ready(),
        workspace=FIXTURES / "python_broken",
    )
    assert plan.decision == "PATCH_PLAN_BLOCKED_SCHEMA_INVALID"


@pytest.mark.parametrize(
    "bad_path",
    [
        "../etc/passwd",
        "..\\..\\system32",
        "/abs/path",
        "C:/abs",
        "foo/../bar",
    ],
)
def test_path_traversal_blocks(bad_path):
    q = LivePatchPlanQuarantine()
    plan = q.quarantine(
        [{"operation": "replace_file", "path": bad_path, "new_content": "x\n"}],
        admission=_admission_ready(),
        workspace=FIXTURES / "python_broken",
    )
    assert plan.decision == "PATCH_PLAN_BLOCKED_PATH_ESCAPE"


def test_unsupported_operation_blocks():
    q = LivePatchPlanQuarantine()
    plan = q.quarantine(
        [{"operation": "delete_file", "path": "src/x.py", "new_content": ""}],
        admission=_admission_ready(),
        workspace=FIXTURES / "python_broken",
    )
    assert plan.decision == "PATCH_PLAN_BLOCKED_UNSUPPORTED_OPERATION"


def test_binary_content_blocks():
    q = LivePatchPlanQuarantine()
    plan = q.quarantine(
        [{"operation": "replace_file", "path": "src/x.py", "new_content": "ok\x00bad"}],
        admission=_admission_ready(),
        workspace=FIXTURES / "python_broken",
    )
    assert plan.decision == "PATCH_PLAN_BLOCKED_BINARY_CONTENT"


def test_empty_plan_blocks_schema_invalid():
    q = LivePatchPlanQuarantine()
    plan = q.quarantine(
        [],
        admission=_admission_ready(),
        workspace=FIXTURES / "python_broken",
    )
    assert plan.decision == "PATCH_PLAN_BLOCKED_SCHEMA_INVALID"


# ---------------------------------------------------------------------------
# Source-preservation
# ---------------------------------------------------------------------------


def test_quarantine_does_not_mutate_workspace():
    q = LivePatchPlanQuarantine()
    ws = FIXTURES / "python_broken"
    before = _hash_tree(ws)
    q.quarantine(
        [{"operation": "replace_file", "path": "src/x.py", "new_content": "x = 1\n"}],
        admission=_admission_ready(),
        workspace=ws,
    )
    after = _hash_tree(ws)
    assert before == after


# ---------------------------------------------------------------------------
# Hygiene
# ---------------------------------------------------------------------------


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("live_patch_plan_quarantine.py", "live_patch_plan_record.py"):
        src = (_REPO_ROOT / "scripts" / "repair" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "from subprocess" not in src
        assert "import urllib" not in src
        assert "from urllib" not in src
        assert "import socket" not in src


def test_plan_json_round_trip():
    q = LivePatchPlanQuarantine()
    plan = q.quarantine(
        [{"operation": "replace_file", "path": "src/x.py", "new_content": "ok\n"}],
        admission=_admission_ready(),
        workspace=FIXTURES / "python_broken",
    )
    parsed = json.loads(plan.to_json())
    assert parsed["decision"] == "PATCH_PLAN_QUARANTINED"
    assert parsed["trusted"] is False
    assert parsed["training_eligible"] is False


# ---------------------------------------------------------------------------
# Lock + evidence + index
# ---------------------------------------------------------------------------


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "LIVE_MODEL_PATCH_PLAN_QUARANTINE_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates
    blob = json.loads(candidates[-1].read_text(encoding="utf-8"))
    assert blob["lock_id"] == "LIVE_MODEL_PATCH_PLAN_QUARANTINE_LOCK_001"


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "LIVE_MODEL_PATCH_PLAN_QUARANTINE_LOCK_001" in ids
