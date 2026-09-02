"""Tests for TAURI_BACKEND_COMMAND_BRIDGE_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

bridge_mod = importlib.import_module("ide.tauri_backend_bridge")
rec_mod = importlib.import_module("ide.tauri_backend_bridge_record")
wizard_mod = importlib.import_module("models.local_model_config_wizard")

TauriBackendBridge = bridge_mod.TauriBackendBridge
tauri_commands = bridge_mod.tauri_commands
tauri_app_present = bridge_mod.tauri_app_present
TAURI_BRIDGE_STATUS_TOKENS = rec_mod.TAURI_BRIDGE_STATUS_TOKENS

LocalModelConfigWizard = wizard_mod.LocalModelConfigWizard
WizardConfig = wizard_mod.WizardConfig

FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "intake"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "TAURI_BACKEND_COMMAND_BRIDGE_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "tauri_backend_command_bridge"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(TAURI_BRIDGE_STATUS_TOKENS)


REQUIRED_COMMANDS = frozenset(
    {
        "open_workspace",
        "get_workspace_status",
        "get_model_route_status",
        "diagnose_dry_run",
        "diagnose_live_opt_in",
        "generate_patch_plan",
        "verify_temp_patch",
        "get_human_approval_packet",
        "source_apply_dry_run",
        "get_repair_flow_state",
    }
)


def _cfg(tmp_path):
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
        "TAURI_BRIDGE_READY",
        "TAURI_BRIDGE_BLOCKED_NO_TAURI_APP",
        "TAURI_BRIDGE_API_STABLE",
        "TAURI_COMMAND_SOURCE_MUTATION_BLOCKED",
        "TAURI_COMMAND_TEMP_ONLY",
        "TAURI_COMMAND_OK",
        "TAURI_COMMAND_BLOCKED_NOT_OPTED_IN",
        "TAURI_COMMAND_BLOCKED_NO_MODEL",
        "TAURI_COMMAND_BLOCKED_UNKNOWN",
    }
    assert set(STATUS_TOKENS) == expected


def test_all_required_commands_present():
    assert REQUIRED_COMMANDS.issubset(set(tauri_commands()))


def test_unknown_command_blocked():
    b = TauriBackendBridge()
    r = b.call("snake_oil_command")
    assert r.status == "TAURI_COMMAND_BLOCKED_UNKNOWN"


def test_open_workspace_supported_path():
    b = TauriBackendBridge()
    r = b.call("open_workspace", workspace=FIXTURES / "python_broken")
    assert r.status == "TAURI_COMMAND_OK"
    assert r.payload["supported"] is True


def test_diagnose_live_blocked_without_opt_in():
    b = TauriBackendBridge()
    r = b.call("diagnose_live_opt_in", opt_in=False, config=None)
    assert r.status == "TAURI_COMMAND_BLOCKED_NOT_OPTED_IN"


def test_patch_plan_blocked_without_model(tmp_path):
    b = TauriBackendBridge()
    r = b.call("generate_patch_plan", opt_in=True, config=None)
    assert r.status == "TAURI_COMMAND_BLOCKED_NO_MODEL"


def test_get_repair_flow_state_returns_conservative():
    b = TauriBackendBridge()
    r = b.call("get_repair_flow_state")
    assert r.status == "TAURI_COMMAND_OK"
    assert r.payload["source_mutation"] == "BLOCKED_PENDING_HUMAN_APPROVAL"


def test_every_response_keeps_training_eligible_false():
    b = TauriBackendBridge()
    for c in tauri_commands():
        r = b.call(c)
        assert r.training_eligible is False
        assert r.source_mutation_authorized is False


def test_tauri_app_presence_probe():
    """Probe never errors. Returns whether frontend/src-tauri/Cargo.toml exists."""
    res = tauri_app_present(_REPO_ROOT)
    assert isinstance(res, bool)


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("tauri_backend_bridge.py", "tauri_backend_bridge_record.py"):
        src = (_REPO_ROOT / "scripts" / "ide" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "import urllib" not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "TAURI_BACKEND_COMMAND_BRIDGE_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "TAURI_BACKEND_COMMAND_BRIDGE_LOCK_001" in ids
