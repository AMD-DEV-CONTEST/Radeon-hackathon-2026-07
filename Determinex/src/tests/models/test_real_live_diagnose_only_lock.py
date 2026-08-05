"""Tests for REAL_LIVE_DIAGNOSE_ONLY_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

mod = importlib.import_module("models.real_live_diagnose_only")
rec_mod = importlib.import_module("models.real_live_diagnose_only_record")
adm_mod = importlib.import_module("models.real_local_model_admission_record")

run = mod.run
TOKENS = rec_mod.REAL_LIVE_DIAGNOSE_ONLY_STATUS_TOKENS
RealLiveDiagnoseOnlyRecord = rec_mod.RealLiveDiagnoseOnlyRecord
RealLocalModelAdmissionRecord = adm_mod.RealLocalModelAdmissionRecord

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "REAL_LIVE_DIAGNOSE_ONLY_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "real_live_diagnose_only"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED = frozenset(
    {
        "REAL_LIVE_DIAGNOSE_WRITTEN",
        "REAL_LIVE_DIAGNOSE_BLOCKED_NO_MODEL",
        "REAL_LIVE_DIAGNOSE_BLOCKED_NOT_OPTED_IN",
        "REAL_LIVE_DIAGNOSE_ADVISORY_ONLY",
        "REAL_LIVE_DIAGNOSE_BLOCKED_TIMEOUT",
        "REAL_LIVE_DIAGNOSE_BLOCKED_PROVIDER_ERROR",
    }
)


def _admitted():
    return RealLocalModelAdmissionRecord(
        decision="REAL_LOCAL_MODEL_ADMITTED",
        provider="ollama",
        model_id="determinex-engineer-v11-dsl",
        task_classes_admitted=("BUILD_DIAGNOSIS",),
        dry_run_default=True,
        opt_in=True,
    )


def _blocked_admission():
    return RealLocalModelAdmissionRecord(
        decision="REAL_LOCAL_MODEL_BLOCKED_NO_PROVIDER",
        provider="ollama",
        model_id="determinex-engineer-v11-dsl",
        task_classes_admitted=(),
    )


def _gen_ok(endpoint, model_id, prompt, system, timeout):
    from models.real_live_diagnose_only import _GenResult

    return _GenResult(ok=True, timed_out=False, text="Looks like a build issue.")


def _gen_timeout(endpoint, model_id, prompt, system, timeout):
    from models.real_live_diagnose_only import _GenResult

    return _GenResult(ok=False, timed_out=True, error="timed out")


def _gen_err(endpoint, model_id, prompt, system, timeout):
    from models.real_live_diagnose_only import _GenResult

    return _GenResult(ok=False, timed_out=False, error="500")


def test_status_tokens_exact():
    assert set(TOKENS) == EXPECTED


def test_no_admission_blocked():
    r = run(workspace="/ws", admission=None, opt_in=True, transport=_gen_ok)
    assert r.decision == "REAL_LIVE_DIAGNOSE_BLOCKED_NO_MODEL"
    assert r.advisory_only is True
    assert r.patch_generated is False


def test_blocked_admission_refused():
    r = run(workspace="/ws", admission=_blocked_admission(), opt_in=True, transport=_gen_ok)
    assert r.decision == "REAL_LIVE_DIAGNOSE_BLOCKED_NO_MODEL"


def test_not_opted_in_blocked():
    r = run(workspace="/ws", admission=_admitted(), opt_in=False, transport=_gen_ok)
    assert r.decision == "REAL_LIVE_DIAGNOSE_BLOCKED_NOT_OPTED_IN"


def test_task_class_outside_admitted_set_blocked():
    r = run(
        workspace="/ws",
        admission=_admitted(),
        opt_in=True,
        task_class="PATCH_GENERATION",
        transport=_gen_ok,
    )
    assert r.decision == "REAL_LIVE_DIAGNOSE_BLOCKED_NO_MODEL"


def test_timeout_recorded():
    r = run(workspace="/ws", admission=_admitted(), opt_in=True, transport=_gen_timeout)
    assert r.decision == "REAL_LIVE_DIAGNOSE_BLOCKED_TIMEOUT"


def test_provider_error_recorded():
    r = run(workspace="/ws", admission=_admitted(), opt_in=True, transport=_gen_err)
    assert r.decision == "REAL_LIVE_DIAGNOSE_BLOCKED_PROVIDER_ERROR"


def test_success_writes_advisory_only():
    r = run(workspace="/ws", admission=_admitted(), opt_in=True, transport=_gen_ok)
    assert r.decision == "REAL_LIVE_DIAGNOSE_WRITTEN"
    assert r.advisory_only is True
    assert r.output_trusted is False
    assert r.patch_generated is False
    assert r.source_mutation_authorized is False
    assert r.training_eligible is False
    assert "REAL_LIVE_DIAGNOSE_ADVISORY_ONLY" in r.statuses_seen


def test_advisory_summary_is_bounded():
    big = "x" * 5000

    def gen_big(endpoint, model_id, prompt, system, timeout):
        from models.real_live_diagnose_only import _GenResult

        return _GenResult(ok=True, timed_out=False, text=big)

    r = run(workspace="/ws", admission=_admitted(), opt_in=True, transport=gen_big)
    assert r.decision == "REAL_LIVE_DIAGNOSE_WRITTEN"
    assert len(r.advisory_summary) <= 1024
    assert r.response_chars == 5000


def test_non_local_endpoint_blocked_when_default_transport():
    # When no transport override is given, a non-local endpoint must be
    # refused so the runner never opens an external socket.
    r = run(
        workspace="/ws",
        admission=_admitted(),
        opt_in=True,
        endpoint="http://example.com:11434",
        transport=None,
        timeout_seconds=0.1,
    )
    assert r.decision == "REAL_LIVE_DIAGNOSE_BLOCKED_PROVIDER_ERROR"


def test_module_does_not_import_requests_or_httpx():
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("import requests", "from requests", "import httpx", "from httpx"):
        assert forbidden not in src


def test_record_serializes_with_safe_flags():
    r = run(workspace="/ws", admission=_admitted(), opt_in=True, transport=_gen_ok)
    d = r.to_dict()
    json.dumps(d)
    assert d["advisory_only"] is True
    assert d["output_trusted"] is False
    assert d["patch_generated"] is False
    assert d["source_mutation_authorized"] is False
    assert d["training_eligible"] is False


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "REAL_LIVE_DIAGNOSE_ONLY_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED)
    sd = blob.get("scope_discipline", {})
    assert sd.get("source_mutation_authorized") is False
    assert sd.get("training_eligibility_opened") is False
    assert sd.get("patch_generated") is False
    assert sd.get("network_provider_admitted") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "REAL_LIVE_DIAGNOSE_ONLY_LOCK_001" in ids
