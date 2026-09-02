"""Tests for REAL_LOCAL_MODEL_PROVIDER_CONFIG_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

mod = importlib.import_module("models.real_local_model_provider_config")
rec_mod = importlib.import_module("models.real_local_model_provider_config_record")

save_config = mod.save_config
DEFAULT_CONFIG_ROOT = mod.DEFAULT_CONFIG_ROOT
RealLocalModelProviderConfigRecord = rec_mod.RealLocalModelProviderConfigRecord
TOKENS = rec_mod.REAL_LOCAL_MODEL_PROVIDER_CONFIG_STATUS_TOKENS

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "REAL_LOCAL_MODEL_PROVIDER_CONFIG_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "real_local_model_provider_config"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


EXPECTED_TOKENS = frozenset(
    {
        "REAL_LOCAL_MODEL_CONFIG_READY",
        "REAL_LOCAL_MODEL_CONFIG_DRY_RUN_DEFAULT",
        "REAL_LOCAL_MODEL_CONFIG_BLOCKED_NETWORK_PROVIDER",
        "REAL_LOCAL_MODEL_CONFIG_BLOCKED_UNPINNED_MODEL",
        "REAL_LOCAL_MODEL_CONFIG_BLOCKED_UNKNOWN_PROVIDER",
        "REAL_LOCAL_MODEL_CONFIG_BLOCKED_STALE_MODEL_ID",
        "REAL_LOCAL_MODEL_CONFIG_BLOCKED_INVALID_LOCATION",
        "REAL_LOCAL_MODEL_CONFIG_SAVE_NO_LIVE_CALL",
    }
)


def test_status_tokens_exact():
    assert set(TOKENS) == EXPECTED_TOKENS


def test_no_model_default_dry_run(tmp_path):
    rec = save_config(provider="no_model", model_id="", config_root=tmp_path)
    assert isinstance(rec, RealLocalModelProviderConfigRecord)
    assert rec.decision == "REAL_LOCAL_MODEL_CONFIG_DRY_RUN_DEFAULT"
    assert rec.dry_run_default is True
    assert rec.live_model_called_on_save is False
    assert rec.network_provider_admitted is False
    assert rec.is_ready


def test_network_provider_blocked(tmp_path):
    for p in ("anthropic", "openai", "deepseek", "google"):
        rec = save_config(provider=p, model_id="any-id", config_root=tmp_path)
        assert rec.decision == "REAL_LOCAL_MODEL_CONFIG_BLOCKED_NETWORK_PROVIDER", p
        assert rec.is_blocked
        assert rec.network_provider_admitted is False


def test_unknown_provider_blocked(tmp_path):
    rec = save_config(provider="quantum-cloud", model_id="x", config_root=tmp_path)
    assert rec.decision in {
        "REAL_LOCAL_MODEL_CONFIG_BLOCKED_UNKNOWN_PROVIDER",
        "REAL_LOCAL_MODEL_CONFIG_BLOCKED_NETWORK_PROVIDER",
    }
    assert rec.is_blocked


def test_stale_model_id_blocked(tmp_path):
    rec = save_config(
        provider="ollama",
        model_id="determinex-engineer-v10-dsl",  # stale id
        config_root=tmp_path,
    )
    assert rec.decision == "REAL_LOCAL_MODEL_CONFIG_BLOCKED_STALE_MODEL_ID"
    assert rec.is_blocked


def test_unpinned_model_id_blocked(tmp_path):
    rec = save_config(
        provider="ollama",
        model_id="totally-not-a-real-model-id",
        config_root=tmp_path,
    )
    assert rec.decision == "REAL_LOCAL_MODEL_CONFIG_BLOCKED_UNPINNED_MODEL"
    assert rec.is_blocked


def test_current_ollama_model_writes_save_no_live_call(tmp_path):
    from models.model_router import CURRENT_MODEL_IDS

    current = sorted(CURRENT_MODEL_IDS)[0]
    rec = save_config(
        provider="ollama",
        model_id=current,
        digest="sha256:abc",
        capabilities=("code_generation",),
        config_root=tmp_path,
    )
    assert rec.decision == "REAL_LOCAL_MODEL_CONFIG_SAVE_NO_LIVE_CALL"
    assert rec.live_model_called_on_save is False
    assert rec.config_path  # disk path filled
    assert Path(rec.config_path).is_file()


def test_save_does_not_open_network(tmp_path, monkeypatch):
    # No socket/urllib usage is allowed at module level.
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("requests", "httpx", "urllib.request", "socket.connect"):
        assert forbidden not in src


def test_record_serializes_to_json(tmp_path):
    rec = save_config(provider="no_model", model_id="", config_root=tmp_path)
    d = rec.to_dict()
    json.dumps(d)  # round-trips
    assert d["live_model_called_on_save"] is False
    assert d["network_provider_admitted"] is False


def test_default_config_root_is_inside_repo():
    assert DEFAULT_CONFIG_ROOT.is_absolute()
    assert "assurance" in str(DEFAULT_CONFIG_ROOT)
    assert "local_model_configs" in str(DEFAULT_CONFIG_ROOT)


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "REAL_LOCAL_MODEL_PROVIDER_CONFIG_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED_TOKENS)
    sd = blob.get("scope_discipline", {})
    assert sd.get("live_model_called_on_save") is False
    assert sd.get("network_provider_admitted") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "REAL_LOCAL_MODEL_PROVIDER_CONFIG_LOCK_001" in ids
