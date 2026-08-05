"""Tests for LOCAL_MODEL_SETTINGS_PANEL_LOCK_001."""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
PANEL = (
    _REPO_ROOT / "frontend" / "src" / "components" / "ide-repair" / "LocalModelSettingsPanel.tsx"
)
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "LOCAL_MODEL_SETTINGS_PANEL_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "local_model_settings_panel"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(
    {
        "LOCAL_MODEL_SETTINGS_PANEL_READY",
        "LOCAL_MODEL_CONFIG_DRY_RUN_DEFAULT",
        "LOCAL_MODEL_NETWORK_PROVIDER_BLOCKED",
        "LOCAL_MODEL_SAVE_NO_LIVE_CALL",
        "LOCAL_MODEL_STALE_ID_WARNING_VISIBLE",
    }
)


def test_panel_exists():
    assert PANEL.is_file()


def test_status_tokens_exact():
    src = PANEL.read_text(encoding="utf-8")
    m = re.search(r"LOCAL_MODEL_SETTINGS_PANEL_STATUS_TOKENS\s*=\s*\[([^\]]+)\]\s*as\s*const", src)
    assert m
    declared = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert declared == STATUS_TOKENS


def test_provider_options_present():
    src = PANEL.read_text(encoding="utf-8")
    for value in ("no_model", "ollama", "local_hf", "executable_adapter"):
        assert f'value: "{value}"' in src


def test_required_input_testids_present():
    src = PANEL.read_text(encoding="utf-8")
    for needle in (
        'data-testid="local-model-settings-panel"',
        'data-testid="local-model-provider-select"',
        'data-testid="local-model-id-input"',
        'data-testid="local-model-digest-input"',
        'data-testid="local-model-capabilities-input"',
        'data-testid="local-model-task-classes-input"',
        'data-testid="local-model-dry-run-default-toggle"',
        'data-testid="local-model-live-opt-in-warning-checkbox"',
        'data-testid="local-model-save-button"',
    ):
        assert needle in src, f"Missing testid: {needle}"


def test_dry_run_default_is_true():
    src = PANEL.read_text(encoding="utf-8")
    assert "useState<boolean>(true)" in src
    assert 'data-testid="local-model-dry-run-default-note"' in src


def test_network_provider_tokens_blocked():
    src = PANEL.read_text(encoding="utf-8")
    for token in (
        "anthropic",
        "openai",
        "google",
        "deepseek",
        "gemini",
        "openrouter",
        "cloud",
        "network",
    ):
        assert f'"{token}"' in src
    assert 'data-testid="local-model-network-blocked-note"' in src


def test_stale_model_ids_mirrored():
    src = PANEL.read_text(encoding="utf-8")
    # Sample of stale ids that must be present
    for sid in (
        "determinex-engineer-v10-dsl",
        "determinex-observer-v5-dsl",
        "determinex-sentinel-v4",
    ):
        assert f'"{sid}"' in src
    assert 'data-testid="local-model-stale-id-warning"' in src


def test_save_button_disabled_when_blocked():
    src = PANEL.read_text(encoding="utf-8")
    assert "disabled={!canSave}" in src
    assert "canSave = !networkBlocked && !isStale" in src


def test_save_does_not_perform_live_model_call():
    src = PANEL.read_text(encoding="utf-8")
    # The save flow goes through invokeIdeCommand("get_repair_flow_state"),
    # NOT a live model invocation command.
    assert 'data-testid="local-model-save-no-live-note"' in src
    assert "no live model call performed on save" in src
    # Forbid any obvious "run model" call sites.
    for forbidden in (
        '"run_model"',
        '"invoke_live_model"',
        '"call_model"',
        '"chat_completion"',
    ):
        assert forbidden not in src, f"Forbidden live-call command: {forbidden}"


def test_live_opt_in_copy_states_output_remains_untrusted():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="local-model-live-opt-in-warning"' in src
    lowered = src.lower()
    assert "advisory" in lowered
    assert "untrusted" in lowered
    assert "source mutation" in lowered


def test_no_source_apply_or_training_controls():
    src = PANEL.read_text(encoding="utf-8")
    for n in (
        "Apply to Source",
        "source_apply",
        "training_eligible",
        "source_mutation_authorized",
    ):
        assert n not in src, f"Forbidden control/field: {n}"


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "LOCAL_MODEL_SETTINGS_PANEL_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)
    sd = blob.get("scope_discipline", {})
    assert sd.get("user_source_mutated") is False
    assert sd.get("training_eligibility_opened") is False
    assert sd.get("live_model_called_on_save") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "LOCAL_MODEL_SETTINGS_PANEL_LOCK_001" in ids
