"""Tests for REAL_OLLAMA_PROVIDER_DETECTION_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

mod = importlib.import_module("models.real_ollama_provider_detection")
rec_mod = importlib.import_module("models.real_ollama_provider_detection_record")

detect = mod.detect
TOKENS = rec_mod.REAL_OLLAMA_PROVIDER_DETECTION_STATUS_TOKENS
RealOllamaProviderDetectionRecord = rec_mod.RealOllamaProviderDetectionRecord

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "REAL_OLLAMA_PROVIDER_DETECTION_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "real_ollama_provider_detection"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED = frozenset(
    {
        "REAL_OLLAMA_PROVIDER_DETECTED",
        "REAL_OLLAMA_PROVIDER_BLOCKED_NOT_INSTALLED",
        "REAL_OLLAMA_PROVIDER_BLOCKED_NOT_RUNNING",
        "REAL_OLLAMA_PROVIDER_BLOCKED_TIMEOUT",
        "REAL_OLLAMA_PROVIDER_BLOCKED_NETWORK_PROVIDER",
    }
)


def _no_binary():
    return None


def _has_binary():
    return "/usr/local/bin/ollama"


def _tags_ok(endpoint, timeout):
    from models.real_ollama_provider_detection import _TagsResult

    return _TagsResult(
        ok=True, timed_out=False, not_running=False, models=("llama3:8b", "qwen2.5-coder:7b")
    )


def _tags_not_running(endpoint, timeout):
    from models.real_ollama_provider_detection import _TagsResult

    return _TagsResult(ok=False, timed_out=False, not_running=True, error="refused")


def _tags_timeout(endpoint, timeout):
    from models.real_ollama_provider_detection import _TagsResult

    return _TagsResult(ok=False, timed_out=True, not_running=False, error="timed out")


def test_status_tokens_exact():
    assert set(TOKENS) == EXPECTED


def test_network_endpoint_refused_before_anything_else():
    # Even when binary present and tags would pass — host check first.
    r = detect(
        endpoint="http://example.com:11434", binary_locator=_has_binary, tags_transport=_tags_ok
    )
    assert r.decision == "REAL_OLLAMA_PROVIDER_BLOCKED_NETWORK_PROVIDER"
    assert r.elapsed_ms == 0, "must not have probed"
    assert r.network_provider_admitted is False


def test_not_installed_when_binary_missing():
    r = detect(binary_locator=_no_binary, tags_transport=_tags_ok)
    assert r.decision == "REAL_OLLAMA_PROVIDER_BLOCKED_NOT_INSTALLED"
    assert r.elapsed_ms == 0


def test_not_running_when_daemon_refused():
    r = detect(binary_locator=_has_binary, tags_transport=_tags_not_running)
    assert r.decision == "REAL_OLLAMA_PROVIDER_BLOCKED_NOT_RUNNING"


def test_timeout_when_daemon_hangs():
    r = detect(binary_locator=_has_binary, tags_transport=_tags_timeout)
    assert r.decision == "REAL_OLLAMA_PROVIDER_BLOCKED_TIMEOUT"


def test_detected_with_model_list_captured():
    r = detect(binary_locator=_has_binary, tags_transport=_tags_ok)
    assert r.decision == "REAL_OLLAMA_PROVIDER_DETECTED"
    assert "llama3:8b" in r.models
    assert r.live_inference_called is False
    assert r.network_provider_admitted is False


def test_module_does_not_import_requests_or_httpx():
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("import requests", "from requests", "import httpx", "from httpx"):
        assert forbidden not in src
    # Must not call any ollama subcommand or pull / run a model.
    for forbidden in (
        '"pull"',
        "'pull'",
        "ollama.pull",
        '"run"',
        "'run'",
        "ollama.run",
        "subprocess.Popen",
        "subprocess.run",
    ):
        assert forbidden not in src, f"forbidden live-inference path: {forbidden}"


def test_default_endpoint_is_localhost():
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert '"http://127.0.0.1:11434"' in src


def test_record_serializes_with_safe_flags():
    r = detect(binary_locator=_has_binary, tags_transport=_tags_ok)
    d = r.to_dict()
    json.dumps(d)
    assert d["network_provider_admitted"] is False
    assert d["live_inference_called"] is False


def test_real_run_on_this_host_blocks_or_detects_safely():
    # Default-binary, default-transport run. Acceptable outcomes:
    #   DETECTED if a real daemon is up
    #   BLOCKED_NOT_INSTALLED if ollama binary missing
    #   BLOCKED_NOT_RUNNING if daemon down
    #   BLOCKED_TIMEOUT if daemon hangs
    # Anything else is a contract violation.
    r = detect(timeout_seconds=0.5)
    assert r.decision in EXPECTED
    assert r.network_provider_admitted is False
    assert r.live_inference_called is False


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "REAL_OLLAMA_PROVIDER_DETECTION_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED)
    sd = blob.get("scope_discipline", {})
    assert sd.get("live_inference_called") is False
    assert sd.get("network_provider_admitted") is False
    assert sd.get("repo_source_inputted") is False
    assert sd.get("patch_generated") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "REAL_OLLAMA_PROVIDER_DETECTION_LOCK_001" in ids
