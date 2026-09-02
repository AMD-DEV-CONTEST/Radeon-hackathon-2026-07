"""Tests for LOCAL_PROVIDER_SMOKE_TEST_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

smoke_mod = importlib.import_module("models.local_provider_smoke_test")
smoke_rec_mod = importlib.import_module("models.local_provider_smoke_record")
wizard_mod = importlib.import_module("models.local_model_config_wizard")
harness_mod = importlib.import_module("models.live_model_compat_harness")

LocalProviderSmokeTest = smoke_mod.LocalProviderSmokeTest
LOCAL_PROVIDER_SMOKE_STATUS_TOKENS = smoke_rec_mod.LOCAL_PROVIDER_SMOKE_STATUS_TOKENS

LocalModelConfigWizard = wizard_mod.LocalModelConfigWizard
WizardConfig = wizard_mod.WizardConfig

DeterministicProvider = harness_mod.DeterministicProvider
TimeoutProvider = harness_mod.TimeoutProvider
UnavailableProvider = harness_mod.UnavailableProvider
MalformedProvider = harness_mod.MalformedProvider

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "LOCAL_PROVIDER_SMOKE_TEST_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "local_provider_smoke_test"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(LOCAL_PROVIDER_SMOKE_STATUS_TOKENS)


def _config(tmp_path: Path, provider: str = "ollama"):
    w = LocalModelConfigWizard(WizardConfig(config_root=tmp_path))
    return w.write_config(
        provider=provider,
        model_id="determinex-engineer-v11-dsl",
        capabilities=("code_generation",),
        task_classes_allowed=("VERIFIER_SUMMARY",),
        enabled=True,
    )


def test_status_tokens_match_expected_set():
    expected = {
        "LOCAL_PROVIDER_SMOKE_PASSED",
        "LOCAL_PROVIDER_SMOKE_BLOCKED_NOT_CONFIGURED",
        "LOCAL_PROVIDER_SMOKE_BLOCKED_PROVIDER_UNAVAILABLE",
        "LOCAL_PROVIDER_SMOKE_BLOCKED_TIMEOUT",
        "LOCAL_PROVIDER_SMOKE_BLOCKED_NETWORK_PROVIDER",
        "LOCAL_PROVIDER_SMOKE_OUTPUT_UNTRUSTED",
        "LOCAL_PROVIDER_SMOKE_BLOCKED_MALFORMED_OUTPUT",
    }
    assert set(STATUS_TOKENS) == expected


def test_smoke_passes_with_valid_fixture(tmp_path):
    cfg = _config(tmp_path)
    p = DeterministicProvider(canned={"status": "MOCK_PASS"})
    res = LocalProviderSmokeTest().run(cfg, p)
    assert res.decision == "LOCAL_PROVIDER_SMOKE_PASSED"
    assert res.output_trusted is False


def test_provider_unavailable_blocks(tmp_path):
    cfg = _config(tmp_path)
    res = LocalProviderSmokeTest().run(cfg, UnavailableProvider())
    assert res.decision == "LOCAL_PROVIDER_SMOKE_BLOCKED_PROVIDER_UNAVAILABLE"


def test_timeout_blocks(tmp_path):
    cfg = _config(tmp_path)
    res = LocalProviderSmokeTest().run(cfg, TimeoutProvider())
    assert res.decision == "LOCAL_PROVIDER_SMOKE_BLOCKED_TIMEOUT"


def test_malformed_output_blocks(tmp_path):
    cfg = _config(tmp_path)
    res = LocalProviderSmokeTest().run(cfg, MalformedProvider())
    assert res.decision == "LOCAL_PROVIDER_SMOKE_BLOCKED_MALFORMED_OUTPUT"


def test_not_configured_blocks():
    res = LocalProviderSmokeTest().run(None, DeterministicProvider(canned={}))
    assert res.decision == "LOCAL_PROVIDER_SMOKE_BLOCKED_NOT_CONFIGURED"


def test_network_provider_blocks(tmp_path):
    w = LocalModelConfigWizard(WizardConfig(config_root=tmp_path))
    # Force a record that DECLARES network_required=True through a blocked path,
    # but for this test we need a config that passes wizard but is network. We
    # instead inject by hand:
    from models.local_model_config_record import LocalModelConfigRecord

    cfg = LocalModelConfigRecord(
        provider="ollama",
        model_id="determinex-engineer-v11-dsl",
        model_digest_or_revision="",
        capabilities=("code_generation",),
        task_classes_allowed=("VERIFIER_SUMMARY",),
        network_required=True,
        local_only=False,
        enabled=True,
        dry_run_default=True,
        created_at="2026-05-28T00:00:00+00:00",
        stale_after="2026-11-24T00:00:00+00:00",
        decision="LOCAL_MODEL_CONFIG_WRITTEN",
        config_path=str(tmp_path / "x.json"),
    )
    res = LocalProviderSmokeTest().run(cfg, DeterministicProvider(canned={"status": "X"}))
    assert res.decision == "LOCAL_PROVIDER_SMOKE_BLOCKED_NETWORK_PROVIDER"


def test_output_trusted_false_on_every_decision(tmp_path):
    cfg = _config(tmp_path)
    for p in [
        DeterministicProvider(canned={"status": "X"}),
        UnavailableProvider(),
        TimeoutProvider(),
        MalformedProvider(),
    ]:
        res = LocalProviderSmokeTest().run(cfg, p)
        assert res.output_trusted is False


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("local_provider_smoke_test.py", "local_provider_smoke_record.py"):
        src = (_REPO_ROOT / "scripts" / "models" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "from subprocess" not in src
        assert "import urllib" not in src
        assert "from urllib" not in src


def test_record_json_round_trip(tmp_path):
    cfg = _config(tmp_path)
    res = LocalProviderSmokeTest().run(cfg, DeterministicProvider(canned={"status": "X"}))
    parsed = json.loads(res.to_json())
    assert parsed["output_trusted"] is False


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "LOCAL_PROVIDER_SMOKE_TEST_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "LOCAL_PROVIDER_SMOKE_TEST_LOCK_001" in ids
