"""Tests for LOCAL_MODEL_CONFIG_WIZARD_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

wizard_mod = importlib.import_module("models.local_model_config_wizard")
rec_mod = importlib.import_module("models.local_model_config_record")

LocalModelConfigWizard = wizard_mod.LocalModelConfigWizard
WizardConfig = wizard_mod.WizardConfig
LOCAL_MODEL_CONFIG_STATUS_TOKENS = rec_mod.LOCAL_MODEL_CONFIG_STATUS_TOKENS

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "LOCAL_MODEL_CONFIG_WIZARD_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "local_model_config_wizard"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(LOCAL_MODEL_CONFIG_STATUS_TOKENS)


def _wiz(tmp_path: Path) -> LocalModelConfigWizard:
    return LocalModelConfigWizard(WizardConfig(config_root=tmp_path))


def test_status_tokens_match_expected_set():
    expected = {
        "LOCAL_MODEL_CONFIG_WRITTEN",
        "LOCAL_MODEL_CONFIG_BLOCKED_NETWORK_PROVIDER",
        "LOCAL_MODEL_CONFIG_BLOCKED_UNPINNED_MODEL",
        "LOCAL_MODEL_CONFIG_BLOCKED_UNKNOWN_PROVIDER",
        "LOCAL_MODEL_CONFIG_BLOCKED_UNSUPPORTED_TASK_CLASS",
        "LOCAL_MODEL_CONFIG_BLOCKED_STALE_MODEL_ID",
        "LOCAL_MODEL_CONFIG_BLOCKED_INVALID_LOCATION",
        "LOCAL_MODEL_CONFIG_DRY_RUN_ONLY",
    }
    assert set(STATUS_TOKENS) == expected


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_default_write_is_dry_run_only(tmp_path):
    rec = _wiz(tmp_path).write_config(
        provider="ollama",
        model_id="determinex-engineer-v11-dsl",
        capabilities=("code_generation",),
        task_classes_allowed=("PATCH_GENERATION",),
    )
    assert rec.decision == "LOCAL_MODEL_CONFIG_DRY_RUN_ONLY"
    assert rec.enabled is False
    assert rec.dry_run_default is True
    # File written under config_root
    assert Path(rec.config_path).is_file()


def test_explicit_enabled_writes_normally(tmp_path):
    rec = _wiz(tmp_path).write_config(
        provider="ollama",
        model_id="determinex-engineer-v11-dsl",
        capabilities=("code_generation",),
        task_classes_allowed=("PATCH_GENERATION",),
        enabled=True,
    )
    assert rec.decision == "LOCAL_MODEL_CONFIG_WRITTEN"
    assert rec.enabled is True
    # Even when enabled=True, dry_run_default stays True until caller
    # explicitly disables it.
    assert rec.dry_run_default is True


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


def test_network_provider_blocked(tmp_path):
    rec = _wiz(tmp_path).write_config(
        provider="anthropic",
        model_id="claude-sonnet-4-6",
        capabilities=("code_generation",),
        task_classes_allowed=("PATCH_GENERATION",),
        network_required=True,
    )
    assert rec.decision == "LOCAL_MODEL_CONFIG_BLOCKED_NETWORK_PROVIDER"
    assert rec.config_path == ""


def test_unknown_provider_blocked(tmp_path):
    rec = _wiz(tmp_path).write_config(
        provider="exotic_provider",
        model_id="determinex-engineer-v11-dsl",
        capabilities=("code_generation",),
        task_classes_allowed=("PATCH_GENERATION",),
    )
    assert rec.decision == "LOCAL_MODEL_CONFIG_BLOCKED_UNKNOWN_PROVIDER"


def test_stale_model_id_blocked(tmp_path):
    rec = _wiz(tmp_path).write_config(
        provider="ollama",
        model_id="determinex-engineer-v10-dsl",  # stale
        capabilities=("code_generation",),
        task_classes_allowed=("PATCH_GENERATION",),
    )
    assert rec.decision == "LOCAL_MODEL_CONFIG_BLOCKED_STALE_MODEL_ID"


def test_unpinned_model_id_blocked(tmp_path):
    rec = _wiz(tmp_path).write_config(
        provider="ollama",
        model_id="some-unverified-model",
        capabilities=("code_generation",),
        task_classes_allowed=("PATCH_GENERATION",),
    )
    assert rec.decision == "LOCAL_MODEL_CONFIG_BLOCKED_UNPINNED_MODEL"


def test_unsupported_task_class_blocked(tmp_path):
    rec = _wiz(tmp_path).write_config(
        provider="ollama",
        model_id="determinex-engineer-v11-dsl",
        capabilities=("code_generation",),
        task_classes_allowed=("NOT_A_TASK_CLASS",),
    )
    assert rec.decision == "LOCAL_MODEL_CONFIG_BLOCKED_UNSUPPORTED_TASK_CLASS"


def test_no_model_provider_admits_minimal_config(tmp_path):
    rec = _wiz(tmp_path).write_config(
        provider="no_model",
        model_id="",
        capabilities=(),
        task_classes_allowed=(),
    )
    assert rec.decision == "LOCAL_MODEL_CONFIG_DRY_RUN_ONLY"


# ---------------------------------------------------------------------------
# Boundary
# ---------------------------------------------------------------------------


def test_config_written_only_under_config_root(tmp_path):
    rec = _wiz(tmp_path).write_config(
        provider="ollama",
        model_id="determinex-engineer-v11-dsl",
        capabilities=("code_generation",),
        task_classes_allowed=("PATCH_GENERATION",),
    )
    written = Path(rec.config_path)
    assert written.is_file()
    assert tmp_path in written.parents or tmp_path == written.parent


# ---------------------------------------------------------------------------
# Hygiene
# ---------------------------------------------------------------------------


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("local_model_config_wizard.py", "local_model_config_record.py"):
        src = (_REPO_ROOT / "scripts" / "models" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "from subprocess" not in src
        assert "import urllib" not in src
        assert "from urllib" not in src
        assert "import socket" not in src


def test_record_json_round_trip(tmp_path):
    rec = _wiz(tmp_path).write_config(
        provider="ollama",
        model_id="determinex-engineer-v11-dsl",
        capabilities=("code_generation",),
        task_classes_allowed=("PATCH_GENERATION",),
    )
    parsed = json.loads(rec.to_json())
    assert parsed["enabled"] is False
    assert parsed["dry_run_default"] is True


# ---------------------------------------------------------------------------
# Lock + evidence + index
# ---------------------------------------------------------------------------


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "LOCAL_MODEL_CONFIG_WIZARD_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates
    blob = json.loads(candidates[-1].read_text(encoding="utf-8"))
    assert blob["lock_id"] == "LOCAL_MODEL_CONFIG_WIZARD_LOCK_001"


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "LOCAL_MODEL_CONFIG_WIZARD_LOCK_001" in ids
