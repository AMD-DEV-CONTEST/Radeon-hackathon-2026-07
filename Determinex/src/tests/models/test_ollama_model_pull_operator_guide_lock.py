"""Tests for OLLAMA_MODEL_PULL_OPERATOR_GUIDE_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

mod = importlib.import_module("models.ollama_model_pull_operator_guide")
rec_mod = importlib.import_module("models.ollama_model_pull_operator_guide_record")
sel_mod = importlib.import_module("models.canonical_local_model_id_selection_record")

guide = mod.guide
TOKENS = rec_mod.OLLAMA_MODEL_PULL_OPERATOR_GUIDE_STATUS_TOKENS
OllamaModelPullOperatorGuideRecord = rec_mod.OllamaModelPullOperatorGuideRecord
CanonicalLocalModelIdSelectionRecord = sel_mod.CanonicalLocalModelIdSelectionRecord

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "OLLAMA_MODEL_PULL_OPERATOR_GUIDE_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "ollama_model_pull_operator_guide"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED = frozenset(
    {
        "OPERATOR_GUIDE_WRITTEN",
        "OPERATOR_GUIDE_NOT_NEEDED_MODEL_AVAILABLE",
        "OPERATOR_GUIDE_BLOCKED_NETWORK_PROVIDER",
        "OPERATOR_GUIDE_BLOCKED_PROVIDER_UNAVAILABLE",
        "OPERATOR_GUIDE_BLOCKED_STALE_ID",
        "OPERATOR_GUIDE_BLOCKED_UNPINNED",
    }
)


def _sel(
    decision,
    selected_id="determinex-engineer-v11-dsl",
    candidates=("determinex-engineer-v11-dsl",),
    host_state="MODEL_AVAILABLE",
    provider="ollama",
    operator_action="",
):
    return CanonicalLocalModelIdSelectionRecord(
        decision=decision,
        selected_model_id=selected_id if decision == "CANONICAL_LOCAL_MODEL_SELECTED" else "",
        provider=provider,
        candidate_model_ids=candidates,
        daemon_models_available=(),
        host_state=host_state,
        operator_action=operator_action,
    )


def test_status_tokens_exact():
    assert set(TOKENS) == EXPECTED


def test_selection_missing_blocks():
    r = guide(selection=None)
    assert r.decision == "OPERATOR_GUIDE_BLOCKED_PROVIDER_UNAVAILABLE"
    assert r.auto_pull_performed is False


def test_selection_selected_means_no_guide_needed():
    r = guide(selection=_sel("CANONICAL_LOCAL_MODEL_SELECTED"))
    assert r.decision == "OPERATOR_GUIDE_NOT_NEEDED_MODEL_AVAILABLE"
    assert r.expected_command == ""
    assert r.auto_pull_performed is False


def test_network_provider_selection_blocks_guide():
    r = guide(
        selection=_sel(
            "CANONICAL_LOCAL_MODEL_BLOCKED_NETWORK_PROVIDER",
            host_state="NETWORK_PROVIDER",
            provider="anthropic",
        )
    )
    assert r.decision == "OPERATOR_GUIDE_BLOCKED_NETWORK_PROVIDER"


def test_stale_selection_blocks_guide():
    r = guide(
        selection=_sel(
            "CANONICAL_LOCAL_MODEL_BLOCKED_STALE_ID",
            host_state="PREFERRED_STALE",
        )
    )
    assert r.decision == "OPERATOR_GUIDE_BLOCKED_STALE_ID"


def test_unpinned_selection_blocks_guide():
    r = guide(
        selection=_sel(
            "CANONICAL_LOCAL_MODEL_BLOCKED_UNPINNED",
            host_state="PREFERRED_UNPINNED",
        )
    )
    assert r.decision == "OPERATOR_GUIDE_BLOCKED_UNPINNED"


def test_provider_unavailable_blocks_guide():
    r = guide(
        selection=_sel(
            "CANONICAL_LOCAL_MODEL_BLOCKED_PROVIDER_UNAVAILABLE",
            host_state="PROVIDER_NOT_RUNNING",
        )
    )
    assert r.decision == "OPERATOR_GUIDE_BLOCKED_PROVIDER_UNAVAILABLE"


def test_not_pulled_writes_guide_with_exact_command():
    r = guide(
        selection=_sel(
            "CANONICAL_LOCAL_MODEL_BLOCKED_NOT_PULLED",
            host_state="MODEL_NOT_PULLED",
        )
    )
    assert r.decision == "OPERATOR_GUIDE_WRITTEN"
    assert r.expected_command == "ollama pull determinex-engineer-v11-dsl"
    assert r.safety_warning  # non-empty
    assert "pytest" in r.next_validation_command
    assert r.auto_pull_performed is False
    assert r.training_eligibility_opened is False
    assert r.network_provider_admitted is False


def test_guide_refuses_malformed_candidate_id():
    sel = CanonicalLocalModelIdSelectionRecord(
        decision="CANONICAL_LOCAL_MODEL_BLOCKED_NOT_PULLED",
        selected_model_id="",
        provider="ollama",
        candidate_model_ids=("name with space",),
        daemon_models_available=(),
        host_state="MODEL_NOT_PULLED",
        operator_action="x",
    )
    r = guide(selection=sel)
    assert r.decision == "OPERATOR_GUIDE_BLOCKED_UNPINNED"


def test_module_does_not_pull_or_call_a_model():
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "subprocess.Popen",
        "subprocess.run",
        "urllib.request.urlopen",
        "requests.get",
        "httpx",
        "ollama.pull",
        "ollama.run",
    ):
        assert forbidden not in src
    # Sanity: the file never imports any execution primitive.
    for forbidden in ("import subprocess", "import urllib.request"):
        assert forbidden not in src


def test_record_serializes_safely():
    r = guide(
        selection=_sel("CANONICAL_LOCAL_MODEL_BLOCKED_NOT_PULLED", host_state="MODEL_NOT_PULLED")
    )
    d = r.to_dict()
    json.dumps(d)
    assert d["auto_pull_performed"] is False
    assert d["training_eligibility_opened"] is False
    assert d["network_provider_admitted"] is False


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "OLLAMA_MODEL_PULL_OPERATOR_GUIDE_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED)
    sd = blob.get("scope_discipline", {})
    assert sd.get("auto_pull_performed") is False
    assert sd.get("network_provider_admitted") is False
    assert sd.get("training_eligibility_opened") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "OLLAMA_MODEL_PULL_OPERATOR_GUIDE_LOCK_001" in ids
