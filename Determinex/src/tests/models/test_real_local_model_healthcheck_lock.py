"""Tests for REAL_LOCAL_MODEL_HEALTHCHECK_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

mod = importlib.import_module("models.real_local_model_healthcheck")
rec_mod = importlib.import_module("models.real_local_model_healthcheck_record")
sel_mod = importlib.import_module("models.canonical_local_model_id_selection_record")

run = mod.run
TOKENS = rec_mod.REAL_LOCAL_MODEL_HEALTHCHECK_STATUS_TOKENS
RealLocalModelHealthcheckRecord = rec_mod.RealLocalModelHealthcheckRecord
CanonicalLocalModelIdSelectionRecord = sel_mod.CanonicalLocalModelIdSelectionRecord

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "REAL_LOCAL_MODEL_HEALTHCHECK_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "real_local_model_healthcheck"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED = frozenset(
    {
        "REAL_LOCAL_MODEL_HEALTHCHECK_PASSED",
        "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_MODEL_NOT_PULLED",
        "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_TIMEOUT",
        "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_PROVIDER_UNAVAILABLE",
        "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_NOT_SELECTED",
        "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_PROVIDER_ERROR",
        "REAL_LOCAL_MODEL_HEALTHCHECK_OUTPUT_UNTRUSTED",
    }
)


def _selected(model_id="determinex-engineer-v11-dsl"):
    return CanonicalLocalModelIdSelectionRecord(
        decision="CANONICAL_LOCAL_MODEL_SELECTED",
        selected_model_id=model_id,
        provider="ollama",
        candidate_model_ids=(model_id,),
        daemon_models_available=(model_id,),
        host_state="MODEL_AVAILABLE",
        operator_action="",
    )


def _blocked_selection():
    return CanonicalLocalModelIdSelectionRecord(
        decision="CANONICAL_LOCAL_MODEL_BLOCKED_NOT_PULLED",
        selected_model_id="",
        provider="ollama",
        candidate_model_ids=("determinex-engineer-v11-dsl",),
        daemon_models_available=(),
        host_state="MODEL_NOT_PULLED",
        operator_action="ollama pull ...",
    )


def _ok(endpoint, model_id, prompt, system, timeout):
    from models.real_local_model_healthcheck import _GenResult

    return _GenResult(ok=True, timed_out=False, not_pulled=False, not_reachable=False, text="OK")


def _timeout(endpoint, model_id, prompt, system, timeout):
    from models.real_local_model_healthcheck import _GenResult

    return _GenResult(
        ok=False, timed_out=True, not_pulled=False, not_reachable=False, error="timed out"
    )


def _not_pulled(endpoint, model_id, prompt, system, timeout):
    from models.real_local_model_healthcheck import _GenResult

    return _GenResult(
        ok=False, timed_out=False, not_pulled=True, not_reachable=False, error="model not found"
    )


def _not_reachable(endpoint, model_id, prompt, system, timeout):
    from models.real_local_model_healthcheck import _GenResult

    return _GenResult(
        ok=False, timed_out=False, not_pulled=False, not_reachable=True, error="connection refused"
    )


def _err(endpoint, model_id, prompt, system, timeout):
    from models.real_local_model_healthcheck import _GenResult

    return _GenResult(
        ok=False, timed_out=False, not_pulled=False, not_reachable=False, error="malformed json"
    )


def test_status_tokens_exact():
    assert set(TOKENS) == EXPECTED


def test_not_selected_blocks():
    r = run(selection=None, transport=_ok)
    assert r.decision == "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_NOT_SELECTED"


def test_blocked_selection_blocks():
    r = run(selection=_blocked_selection(), transport=_ok)
    assert r.decision == "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_NOT_SELECTED"


def test_non_local_endpoint_blocks_without_transport_override():
    r = run(
        selection=_selected(),
        endpoint="http://example.com:11434",
        transport=None,
        timeout_seconds=0.1,
    )
    assert r.decision == "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_PROVIDER_UNAVAILABLE"


def test_timeout_recorded():
    r = run(selection=_selected(), transport=_timeout)
    assert r.decision == "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_TIMEOUT"


def test_not_pulled_recorded():
    r = run(selection=_selected(), transport=_not_pulled)
    assert r.decision == "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_MODEL_NOT_PULLED"


def test_not_reachable_recorded():
    r = run(selection=_selected(), transport=_not_reachable)
    assert r.decision == "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_PROVIDER_UNAVAILABLE"


def test_provider_error_recorded():
    r = run(selection=_selected(), transport=_err)
    assert r.decision == "REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_PROVIDER_ERROR"


def test_pass_records_untrusted_output():
    r = run(selection=_selected(), transport=_ok)
    assert r.decision == "REAL_LOCAL_MODEL_HEALTHCHECK_PASSED"
    assert r.output_trusted is False
    assert r.patch_generated is False
    assert r.repo_source_inputted is False
    assert r.training_eligible is False
    assert r.source_mutation_authorized is False
    assert r.network_provider_admitted is False
    assert "REAL_LOCAL_MODEL_HEALTHCHECK_OUTPUT_UNTRUSTED" in r.statuses_seen


def test_prompt_does_not_contain_repo_source():
    # The healthcheck prompt is a fixed trivial string. Verify by
    # inspecting the module-level constant via the record.
    r = run(selection=_selected(), transport=_ok)
    assert "ok" in r.prompt.lower() or "reply" in r.prompt.lower()
    # No suggestion of file contents / paths.
    for forbidden in ("src/", "diff", "@@", "<<<<<", "src\\"):
        assert forbidden not in r.prompt.lower()


def test_module_does_not_import_requests_or_httpx():
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("import requests", "from requests", "import httpx", "from httpx"):
        assert forbidden not in src


def test_record_serializes_safely():
    r = run(selection=_selected(), transport=_ok)
    d = r.to_dict()
    json.dumps(d)
    assert d["output_trusted"] is False
    assert d["patch_generated"] is False
    assert d["repo_source_inputted"] is False
    assert d["training_eligible"] is False
    assert d["source_mutation_authorized"] is False


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "REAL_LOCAL_MODEL_HEALTHCHECK_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED)
    sd = blob.get("scope_discipline", {})
    assert sd.get("network_provider_admitted") is False
    assert sd.get("patch_generated") is False
    assert sd.get("repo_source_inputted") is False
    assert sd.get("training_eligibility_opened") is False
    assert sd.get("source_mutation_authorized") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "REAL_LOCAL_MODEL_HEALTHCHECK_LOCK_001" in ids
