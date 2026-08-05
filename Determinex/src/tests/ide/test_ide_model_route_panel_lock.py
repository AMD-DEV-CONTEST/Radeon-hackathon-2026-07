"""Tests for IDE_MODEL_ROUTE_PANEL_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

panel_mod = importlib.import_module("ide.model_route_panel")
rec_mod = importlib.import_module("ide.model_route_panel_record")
wizard_mod = importlib.import_module("models.local_model_config_wizard")
smoke_mod = importlib.import_module("models.local_provider_smoke_test")
harness_mod = importlib.import_module("models.live_model_compat_harness")

IDEModelRoutePanel = panel_mod.IDEModelRoutePanel
IDE_MODEL_ROUTE_PANEL_STATUS_TOKENS = rec_mod.IDE_MODEL_ROUTE_PANEL_STATUS_TOKENS

LocalModelConfigWizard = wizard_mod.LocalModelConfigWizard
WizardConfig = wizard_mod.WizardConfig

LocalProviderSmokeTest = smoke_mod.LocalProviderSmokeTest
DeterministicProvider = harness_mod.DeterministicProvider

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "IDE_MODEL_ROUTE_PANEL_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "ide_model_route_panel"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(IDE_MODEL_ROUTE_PANEL_STATUS_TOKENS)


def _cfg(tmp_path: Path, **overrides):
    w = LocalModelConfigWizard(WizardConfig(config_root=tmp_path))
    return w.write_config(
        provider=overrides.get("provider", "ollama"),
        model_id=overrides.get("model_id", "determinex-engineer-v11-dsl"),
        capabilities=("code_generation",),
        task_classes_allowed=("BUILD_DIAGNOSIS", "PATCH_GENERATION"),
        enabled=overrides.get("enabled", True),
    )


def test_status_tokens_match_expected_set():
    expected = {
        "MODEL_ROUTE_PANEL_READY",
        "MODEL_ROUTE_DRY_RUN_DEFAULT",
        "MODEL_ROUTE_LIVE_OPT_IN_AVAILABLE",
        "MODEL_ROUTE_BLOCKED_NO_MODEL",
        "MODEL_ROUTE_BLOCKED_STALE_MODEL",
        "MODEL_ROUTE_BLOCKED_NETWORK_PROVIDER",
    }
    assert set(STATUS_TOKENS) == expected


def test_no_config_blocks_no_model():
    p = IDEModelRoutePanel().view(task_class="BUILD_DIAGNOSIS")
    assert p.decision == "MODEL_ROUTE_BLOCKED_NO_MODEL"
    assert p.live_call_authorized is False


def test_default_view_without_opt_in_is_dry_run(tmp_path):
    cfg = _cfg(tmp_path)
    p = IDEModelRoutePanel().view(config=cfg, opt_in=False)
    assert p.decision == "MODEL_ROUTE_DRY_RUN_DEFAULT"
    assert p.live_call_authorized is False
    assert p.dry_run_default is True


def test_opt_in_makes_live_available(tmp_path):
    cfg = _cfg(tmp_path)
    p = IDEModelRoutePanel().view(config=cfg, opt_in=True)
    assert p.decision == "MODEL_ROUTE_LIVE_OPT_IN_AVAILABLE"
    assert p.live_opt_in_available is True
    assert p.live_call_authorized is True


def test_stale_model_blocks(tmp_path):
    # Force a stale id directly into the record (bypassing the wizard's
    # block) since the wizard would refuse to write one.
    from models.local_model_config_record import LocalModelConfigRecord

    cfg = LocalModelConfigRecord(
        provider="ollama",
        model_id="determinex-observer-v5-dsl",
        model_digest_or_revision="",
        capabilities=("code_generation",),
        task_classes_allowed=("BUILD_DIAGNOSIS",),
        network_required=False,
        local_only=True,
        enabled=True,
        dry_run_default=True,
        created_at="2026-05-28T00:00:00+00:00",
        stale_after="2026-11-24T00:00:00+00:00",
        decision="LOCAL_MODEL_CONFIG_WRITTEN",
        config_path=str(tmp_path / "x.json"),
    )
    p = IDEModelRoutePanel().view(config=cfg, opt_in=True)
    assert p.decision == "MODEL_ROUTE_BLOCKED_STALE_MODEL"


def test_network_provider_blocks(tmp_path):
    from models.local_model_config_record import LocalModelConfigRecord

    cfg = LocalModelConfigRecord(
        provider="ollama",
        model_id="determinex-engineer-v11-dsl",
        model_digest_or_revision="",
        capabilities=("code_generation",),
        task_classes_allowed=("BUILD_DIAGNOSIS",),
        network_required=True,
        local_only=False,
        enabled=True,
        dry_run_default=True,
        created_at="2026-05-28T00:00:00+00:00",
        stale_after="2026-11-24T00:00:00+00:00",
        decision="LOCAL_MODEL_CONFIG_WRITTEN",
        config_path=str(tmp_path / "x.json"),
    )
    p = IDEModelRoutePanel().view(config=cfg, opt_in=True)
    assert p.decision == "MODEL_ROUTE_BLOCKED_NETWORK_PROVIDER"


def test_panel_reports_smoke_state(tmp_path):
    cfg = _cfg(tmp_path)
    smoke = LocalProviderSmokeTest().run(cfg, DeterministicProvider(canned={"status": "OK"}))
    p = IDEModelRoutePanel().view(config=cfg, smoke=smoke, opt_in=True)
    assert p.provider_smoke_state == "LOCAL_PROVIDER_SMOKE_PASSED"


def test_panel_json_round_trip(tmp_path):
    cfg = _cfg(tmp_path)
    p = IDEModelRoutePanel().view(config=cfg, opt_in=True)
    parsed = json.loads(p.to_json())
    assert parsed["dry_run_default"] is True


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("model_route_panel.py", "model_route_panel_record.py"):
        src = (_REPO_ROOT / "scripts" / "ide" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "import urllib" not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "IDE_MODEL_ROUTE_PANEL_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "IDE_MODEL_ROUTE_PANEL_LOCK_001" in ids
