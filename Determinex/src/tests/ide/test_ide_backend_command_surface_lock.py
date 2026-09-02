"""Tests for IDE_BACKEND_COMMAND_SURFACE_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

surf_mod = importlib.import_module("ide.backend_command_surface")
rec_mod = importlib.import_module("ide.backend_command_record")
wizard_mod = importlib.import_module("models.local_model_config_wizard")

IDEBackendCommandSurface = surf_mod.IDEBackendCommandSurface
IDE_BACKEND_COMMAND_STATUS_TOKENS = rec_mod.IDE_BACKEND_COMMAND_STATUS_TOKENS
commands = surf_mod.commands

LocalModelConfigWizard = wizard_mod.LocalModelConfigWizard
WizardConfig = wizard_mod.WizardConfig

FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "intake"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "IDE_BACKEND_COMMAND_SURFACE_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "ide_backend_command_surface"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(IDE_BACKEND_COMMAND_STATUS_TOKENS)


def _cfg(tmp_path: Path):
    w = LocalModelConfigWizard(WizardConfig(config_root=tmp_path))
    return w.write_config(
        provider="ollama",
        model_id="determinex-engineer-v11-dsl",
        capabilities=("code_generation",),
        task_classes_allowed=("BUILD_DIAGNOSIS", "PATCH_GENERATION"),
        enabled=True,
    )


def test_status_tokens_match_expected_set():
    expected = {
        "IDE_BACKEND_COMMAND_SURFACE_READY",
        "IDE_COMMAND_BLOCKED_NOT_OPTED_IN",
        "IDE_COMMAND_BLOCKED_NO_MODEL",
        "IDE_COMMAND_SOURCE_MUTATION_BLOCKED",
        "IDE_COMMAND_TEMP_ONLY",
        "IDE_COMMAND_BLOCKED_UNKNOWN_COMMAND",
        "IDE_COMMAND_OK",
    }
    assert set(STATUS_TOKENS) == expected


def test_unknown_command_blocks():
    s = IDEBackendCommandSurface()
    r = s.call("unknown_command")
    assert r.status == "IDE_COMMAND_BLOCKED_UNKNOWN_COMMAND"


def test_inspect_workspace_supported():
    s = IDEBackendCommandSurface()
    r = s.call("inspect_workspace", workspace=FIXTURES / "python_broken")
    assert r.status == "IDE_COMMAND_OK"
    assert r.payload["supported"] is True


def test_inspect_workspace_unsupported():
    s = IDEBackendCommandSurface()
    r = s.call("inspect_workspace", workspace=FIXTURES / "unsupported_repo")
    assert r.payload["supported"] is False


def test_route_model():
    s = IDEBackendCommandSurface()
    r = s.call("route_model", task_class="PATCH_GENERATION")
    assert r.status == "IDE_COMMAND_OK"
    assert "decision" in r.payload


def test_diagnose_dry_run_is_temp_only():
    s = IDEBackendCommandSurface()
    r = s.call("diagnose_dry_run", task_class="BUILD_DIAGNOSIS")
    assert r.status == "IDE_COMMAND_TEMP_ONLY"


def test_diagnose_live_requires_opt_in(tmp_path):
    s = IDEBackendCommandSurface()
    r = s.call(
        "diagnose_live_opt_in", task_class="BUILD_DIAGNOSIS", opt_in=False, config=_cfg(tmp_path)
    )
    assert r.status == "IDE_COMMAND_BLOCKED_NOT_OPTED_IN"


def test_diagnose_live_requires_model_config():
    s = IDEBackendCommandSurface()
    r = s.call("diagnose_live_opt_in", task_class="BUILD_DIAGNOSIS", opt_in=True, config=None)
    assert r.status == "IDE_COMMAND_BLOCKED_NO_MODEL"


def test_patch_plan_requires_opt_in(tmp_path):
    s = IDEBackendCommandSurface()
    r = s.call("generate_patch_plan_opt_in", opt_in=False, config=_cfg(tmp_path))
    assert r.status == "IDE_COMMAND_BLOCKED_NOT_OPTED_IN"


def test_verify_temp_patch_is_temp_only():
    s = IDEBackendCommandSurface()
    r = s.call("verify_temp_patch")
    assert r.status == "IDE_COMMAND_TEMP_ONLY"


def test_get_repair_state_returns_conservative_defaults():
    s = IDEBackendCommandSurface()
    r = s.call("get_repair_state")
    assert r.status == "IDE_COMMAND_OK"
    assert r.payload["source_mutation"] == "BLOCKED_PENDING_HUMAN_APPROVAL"
    assert r.payload["training_eligible"] is False


def test_approval_packet_command_does_not_authorize():
    s = IDEBackendCommandSurface()
    r = s.call(
        "get_human_approval_packet",
        workspace=FIXTURES / "python_broken",
        unified_diff="--- a\n+++ b\n",
        files_changed=("src/x.py",),
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    assert r.status == "IDE_COMMAND_SOURCE_MUTATION_BLOCKED"
    assert r.source_mutation_authorized is False


def test_every_command_keeps_training_eligible_false():
    s = IDEBackendCommandSurface()
    for c in commands():
        r = s.call(c)
        assert r.training_eligible is False
        assert r.source_mutation_authorized is False


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("backend_command_surface.py", "backend_command_record.py"):
        src = (_REPO_ROOT / "scripts" / "ide" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "import urllib" not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "IDE_BACKEND_COMMAND_SURFACE_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "IDE_BACKEND_COMMAND_SURFACE_LOCK_001" in ids
