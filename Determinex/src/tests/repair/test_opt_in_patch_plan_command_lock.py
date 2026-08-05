"""Tests for OPT_IN_PATCH_PLAN_COMMAND_LOCK_001."""

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

cmd_mod = importlib.import_module("repair.opt_in_patch_plan_command")
rec_mod = importlib.import_module("repair.opt_in_patch_plan_record")
wizard_mod = importlib.import_module("models.local_model_config_wizard")

OptInPatchPlanCommand = cmd_mod.OptInPatchPlanCommand
OPT_IN_PATCH_PLAN_STATUS_TOKENS = rec_mod.OPT_IN_PATCH_PLAN_STATUS_TOKENS

LocalModelConfigWizard = wizard_mod.LocalModelConfigWizard
WizardConfig = wizard_mod.WizardConfig

FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "intake"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "OPT_IN_PATCH_PLAN_COMMAND_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "opt_in_patch_plan_command"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(OPT_IN_PATCH_PLAN_STATUS_TOKENS)


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


def _cfg(tmp_path: Path):
    w = LocalModelConfigWizard(WizardConfig(config_root=tmp_path))
    return w.write_config(
        provider="ollama",
        model_id="determinex-engineer-v11-dsl",
        capabilities=("code_generation",),
        task_classes_allowed=("PATCH_GENERATION",),
        enabled=True,
    )


def test_status_tokens_match_expected_set():
    expected = {
        "OPT_IN_PATCH_PLAN_QUARANTINED",
        "OPT_IN_PATCH_PLAN_BLOCKED_NO_MODEL",
        "OPT_IN_PATCH_PLAN_BLOCKED_NOT_OPTED_IN",
        "OPT_IN_PATCH_PLAN_BLOCKED_SCHEMA_INVALID",
        "OPT_IN_PATCH_PLAN_BLOCKED_PATH_ESCAPE",
        "OPT_IN_PATCH_PLAN_BLOCKED_PROVIDER_UNAVAILABLE",
    }
    assert set(STATUS_TOKENS) == expected


def test_no_opt_in_blocks(tmp_path):
    cfg = _cfg(tmp_path)
    rec = OptInPatchPlanCommand().run(
        FIXTURES / "python_broken",
        config=cfg,
        plan_entries=[{"operation": "replace_file", "path": "src/x.py", "new_content": "ok\n"}],
        opt_in=False,
    )
    assert rec.decision == "OPT_IN_PATCH_PLAN_BLOCKED_NOT_OPTED_IN"


def test_no_model_blocks():
    rec = OptInPatchPlanCommand().run(
        FIXTURES / "python_broken",
        config=None,
        plan_entries=[{"operation": "replace_file", "path": "x", "new_content": "x"}],
        opt_in=True,
    )
    assert rec.decision == "OPT_IN_PATCH_PLAN_BLOCKED_NO_MODEL"


def test_happy_path_quarantines(tmp_path):
    cfg = _cfg(tmp_path)
    rec = OptInPatchPlanCommand().run(
        FIXTURES / "python_broken",
        config=cfg,
        plan_entries=[{"operation": "replace_file", "path": "src/x.py", "new_content": "ok\n"}],
        opt_in=True,
    )
    assert rec.decision == "OPT_IN_PATCH_PLAN_QUARANTINED"
    assert rec.entries_quarantined == 1
    assert rec.trusted is False
    assert rec.applied_to_source is False
    assert rec.training_eligible is False


def test_path_escape_blocks(tmp_path):
    cfg = _cfg(tmp_path)
    rec = OptInPatchPlanCommand().run(
        FIXTURES / "python_broken",
        config=cfg,
        plan_entries=[{"operation": "replace_file", "path": "../etc/passwd", "new_content": "x"}],
        opt_in=True,
    )
    assert rec.decision == "OPT_IN_PATCH_PLAN_BLOCKED_PATH_ESCAPE"


def test_unsupported_op_blocks_schema_invalid(tmp_path):
    cfg = _cfg(tmp_path)
    rec = OptInPatchPlanCommand().run(
        FIXTURES / "python_broken",
        config=cfg,
        plan_entries=[{"operation": "delete_file", "path": "x", "new_content": ""}],
        opt_in=True,
    )
    assert rec.decision == "OPT_IN_PATCH_PLAN_BLOCKED_SCHEMA_INVALID"


def test_command_does_not_mutate_workspace(tmp_path):
    cfg = _cfg(tmp_path)
    ws = FIXTURES / "python_broken"
    before = _hash_tree(ws)
    OptInPatchPlanCommand().run(
        ws,
        config=cfg,
        plan_entries=[{"operation": "replace_file", "path": "src/x.py", "new_content": "ok\n"}],
        opt_in=True,
    )
    assert _hash_tree(ws) == before


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("opt_in_patch_plan_command.py", "opt_in_patch_plan_record.py"):
        src = (_REPO_ROOT / "scripts" / "repair" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "import urllib" not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "OPT_IN_PATCH_PLAN_COMMAND_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "OPT_IN_PATCH_PLAN_COMMAND_LOCK_001" in ids
