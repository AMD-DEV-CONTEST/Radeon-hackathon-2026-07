"""Tests for CANONICAL_LOCAL_MODEL_ID_SELECTION_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

mod = importlib.import_module("models.canonical_local_model_id_selection")
rec_mod = importlib.import_module("models.canonical_local_model_id_selection_record")
det_mod = importlib.import_module("models.real_ollama_provider_detection_record")

select = mod.select
TOKENS = rec_mod.CANONICAL_LOCAL_MODEL_ID_SELECTION_STATUS_TOKENS
RealOllamaProviderDetectionRecord = det_mod.RealOllamaProviderDetectionRecord

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "CANONICAL_LOCAL_MODEL_ID_SELECTION_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "canonical_local_model_id_selection"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED = frozenset(
    {
        "CANONICAL_LOCAL_MODEL_SELECTED",
        "CANONICAL_LOCAL_MODEL_BLOCKED_NOT_PULLED",
        "CANONICAL_LOCAL_MODEL_BLOCKED_STALE_ID",
        "CANONICAL_LOCAL_MODEL_BLOCKED_UNPINNED",
        "CANONICAL_LOCAL_MODEL_BLOCKED_PROVIDER_UNAVAILABLE",
        "CANONICAL_LOCAL_MODEL_BLOCKED_NETWORK_PROVIDER",
    }
)


def _detected_with(models=("determinex-engineer-v11-dsl",)):
    return RealOllamaProviderDetectionRecord(
        decision="REAL_OLLAMA_PROVIDER_DETECTED",
        endpoint="http://127.0.0.1:11434",
        elapsed_ms=10,
        models=tuple(models),
    )


def _not_detected():
    return RealOllamaProviderDetectionRecord(
        decision="REAL_OLLAMA_PROVIDER_BLOCKED_NOT_RUNNING",
        endpoint="http://127.0.0.1:11434",
        elapsed_ms=5,
    )


def test_status_tokens_exact():
    assert set(TOKENS) == EXPECTED


def test_network_provider_blocked():
    r = select(detection=_detected_with(), provider="openai", preferred_model_id="claude-3")
    assert r.decision == "CANONICAL_LOCAL_MODEL_BLOCKED_NETWORK_PROVIDER"
    assert r.network_provider_admitted is False


def test_stale_preferred_id_blocked():
    r = select(
        detection=_detected_with(),
        provider="ollama",
        preferred_model_id="determinex-engineer-v10-dsl",
    )
    assert r.decision == "CANONICAL_LOCAL_MODEL_BLOCKED_STALE_ID"
    assert "stale" in r.operator_action.lower()


def test_unpinned_preferred_id_blocked():
    r = select(
        detection=_detected_with(), provider="ollama", preferred_model_id="totally-not-a-real-id"
    )
    assert r.decision == "CANONICAL_LOCAL_MODEL_BLOCKED_UNPINNED"


def test_unknown_provider_blocked():
    r = select(detection=_detected_with(), provider="quantum-cloud")
    assert r.decision == "CANONICAL_LOCAL_MODEL_BLOCKED_PROVIDER_UNAVAILABLE"


def test_no_model_provider_blocked():
    r = select(detection=None, provider="no_model")
    assert r.decision == "CANONICAL_LOCAL_MODEL_BLOCKED_PROVIDER_UNAVAILABLE"


def test_provider_not_running_blocked():
    r = select(detection=_not_detected(), provider="ollama")
    assert r.decision == "CANONICAL_LOCAL_MODEL_BLOCKED_PROVIDER_UNAVAILABLE"
    assert "ollama serve" in r.operator_action


def test_model_not_pulled_blocks_with_operator_command():
    r = select(detection=_detected_with(models=("some-other-model:tag",)), provider="ollama")
    assert r.decision == "CANONICAL_LOCAL_MODEL_BLOCKED_NOT_PULLED"
    # Operator action contains the exact pull command.
    assert "ollama pull " in r.operator_action


def test_pulled_model_selected_with_tagged_form():
    # Daemon often returns "name:tag"; selection should tolerate that.
    r = select(
        detection=_detected_with(models=("determinex-engineer-v11-dsl:latest",)), provider="ollama"
    )
    assert r.decision == "CANONICAL_LOCAL_MODEL_SELECTED"
    assert r.selected_model_id == "determinex-engineer-v11-dsl"


def test_pulled_model_selected_with_bare_form():
    from models.model_router import CURRENT_MODEL_IDS

    canonical = sorted(CURRENT_MODEL_IDS)[0]
    r = select(detection=_detected_with(models=(canonical,)), provider="ollama")
    assert r.decision == "CANONICAL_LOCAL_MODEL_SELECTED"
    assert r.selected_model_id == canonical


def test_candidate_overrides_with_unpinned_id_refused():
    r = select(
        detection=_detected_with(), provider="ollama", candidate_overrides=("not-canonical",)
    )
    assert r.decision == "CANONICAL_LOCAL_MODEL_BLOCKED_UNPINNED"


def test_module_does_not_call_or_pull_a_model():
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "subprocess.Popen",
        "subprocess.run",
        "urllib.request.urlopen",
        "requests.get",
        "httpx",
        "/api/generate",
        "/api/pull",
    ):
        assert forbidden not in src


def test_record_serializes_safely():
    r = select(detection=_detected_with(), provider="ollama")
    d = r.to_dict()
    json.dumps(d)
    assert d["network_provider_admitted"] is False
    assert d["live_model_called"] is False


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "CANONICAL_LOCAL_MODEL_ID_SELECTION_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED)
    sd = blob.get("scope_discipline", {})
    assert sd.get("network_provider_admitted") is False
    assert sd.get("live_model_called") is False
    assert sd.get("model_pulled") is False
    assert sd.get("source_mutation_authorized") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "CANONICAL_LOCAL_MODEL_ID_SELECTION_LOCK_001" in ids
