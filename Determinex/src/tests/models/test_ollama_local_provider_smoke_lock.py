"""Tests for OLLAMA_LOCAL_PROVIDER_SMOKE_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

mod = importlib.import_module("models.ollama_local_provider_smoke")
rec_mod = importlib.import_module("models.ollama_local_provider_smoke_record")

smoke = mod.smoke
TOKENS = rec_mod.OLLAMA_LOCAL_PROVIDER_SMOKE_STATUS_TOKENS
OllamaLocalProviderSmokeRecord = rec_mod.OllamaLocalProviderSmokeRecord

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "OLLAMA_LOCAL_PROVIDER_SMOKE_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "ollama_local_provider_smoke"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED = frozenset(
    {
        "OLLAMA_PROVIDER_SMOKE_PASSED",
        "OLLAMA_PROVIDER_SMOKE_BLOCKED_NOT_CONFIGURED",
        "OLLAMA_PROVIDER_SMOKE_BLOCKED_UNAVAILABLE",
        "OLLAMA_PROVIDER_SMOKE_BLOCKED_TIMEOUT",
        "OLLAMA_PROVIDER_OUTPUT_UNTRUSTED",
    }
)


def _ok_transport(endpoint, timeout):
    from models.ollama_local_provider_smoke import _ProbeResult

    return _ProbeResult(status_code=200, ok=True, timed_out=False)


def _timeout_transport(endpoint, timeout):
    from models.ollama_local_provider_smoke import _ProbeResult

    return _ProbeResult(status_code=0, ok=False, timed_out=True, error="timed out")


def _unavailable_transport(endpoint, timeout):
    from models.ollama_local_provider_smoke import _ProbeResult

    return _ProbeResult(status_code=0, ok=False, timed_out=False, error="connection refused")


def test_status_tokens_exact():
    assert set(TOKENS) == EXPECTED


def test_default_returns_blocked_not_configured():
    rec = smoke()
    assert rec.decision == "OLLAMA_PROVIDER_SMOKE_BLOCKED_NOT_CONFIGURED"
    assert rec.output_trusted is False
    assert rec.network_provider_admitted is False


def test_non_local_endpoint_refused_without_probe():
    # Even with an "ok" transport — the host check must refuse first.
    rec = smoke(endpoint="http://example.com:11434", transport=_ok_transport)
    assert rec.decision == "OLLAMA_PROVIDER_SMOKE_BLOCKED_NOT_CONFIGURED"
    assert rec.elapsed_ms == 0, "must not have probed"


def test_localhost_endpoint_passes_with_ok_transport():
    rec = smoke(endpoint="http://127.0.0.1:11434", transport=_ok_transport)
    assert rec.decision == "OLLAMA_PROVIDER_SMOKE_PASSED"
    assert rec.is_passed is True
    assert rec.output_trusted is False
    assert "OLLAMA_PROVIDER_OUTPUT_UNTRUSTED" in rec.statuses_seen


def test_localhost_endpoint_passes_with_localhost_name():
    rec = smoke(endpoint="http://localhost:11434", transport=_ok_transport)
    assert rec.decision == "OLLAMA_PROVIDER_SMOKE_PASSED"


def test_timeout_transport_returns_blocked_timeout():
    rec = smoke(endpoint="http://127.0.0.1:11434", transport=_timeout_transport)
    assert rec.decision == "OLLAMA_PROVIDER_SMOKE_BLOCKED_TIMEOUT"
    assert rec.is_blocked is True


def test_unavailable_transport_returns_blocked_unavailable():
    rec = smoke(endpoint="http://127.0.0.1:11434", transport=_unavailable_transport)
    assert rec.decision == "OLLAMA_PROVIDER_SMOKE_BLOCKED_UNAVAILABLE"
    assert rec.is_blocked is True


def test_module_does_not_import_requests_or_httpx():
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("import requests", "import httpx", "from requests", "from httpx"):
        assert forbidden not in src


def test_record_serializes_with_safe_flags():
    rec = smoke(endpoint="http://127.0.0.1:11434", transport=_ok_transport)
    d = rec.to_dict()
    json.dumps(d)
    assert d["output_trusted"] is False
    assert d["network_provider_admitted"] is False


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "OLLAMA_LOCAL_PROVIDER_SMOKE_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED)
    sd = blob.get("scope_discipline", {})
    assert sd.get("network_provider_admitted") is False
    assert sd.get("repo_source_inputted") is False
    assert sd.get("patch_generated") is False
    assert sd.get("training_eligibility_opened") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "OLLAMA_LOCAL_PROVIDER_SMOKE_LOCK_001" in ids
