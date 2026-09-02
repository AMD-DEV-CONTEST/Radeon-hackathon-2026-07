"""Tests for REAL_MODEL_DIAGNOSE_WITH_BUILD_VERIFIER_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

mod = importlib.import_module("models.real_model_diagnose_with_build_verifier")
rec_mod = importlib.import_module("models.real_model_diagnose_with_build_verifier_record")
hc_mod = importlib.import_module("models.real_local_model_healthcheck_record")
sel_mod = importlib.import_module("repair.build_adapter_backed_verifier_selection_record")

diagnose = mod.diagnose
TOKENS = rec_mod.REAL_MODEL_DIAGNOSE_WITH_BUILD_VERIFIER_STATUS_TOKENS
RealModelDiagnoseWithBuildVerifierRecord = rec_mod.RealModelDiagnoseWithBuildVerifierRecord
RealLocalModelHealthcheckRecord = hc_mod.RealLocalModelHealthcheckRecord
BuildAdapterBackedVerifierSelectionRecord = sel_mod.BuildAdapterBackedVerifierSelectionRecord

LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "REAL_MODEL_DIAGNOSE_WITH_BUILD_VERIFIER_LOCK_001.json"
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "real_model_diagnose_with_build_verifier"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED = frozenset(
    {
        "REAL_MODEL_DIAGNOSE_WITH_VERIFIER_WRITTEN",
        "REAL_MODEL_DIAGNOSE_BLOCKED_NO_MODEL",
        "REAL_MODEL_DIAGNOSE_BLOCKED_HEALTHCHECK_FAILED",
        "REAL_MODEL_DIAGNOSE_BLOCKED_NO_VERIFIER",
        "REAL_MODEL_DIAGNOSE_BLOCKED_NOT_OPTED_IN",
        "REAL_MODEL_DIAGNOSE_BLOCKED_TIMEOUT",
        "REAL_MODEL_DIAGNOSE_BLOCKED_PROVIDER_ERROR",
        "REAL_MODEL_DIAGNOSE_ADVISORY_ONLY",
    }
)


def _hc_passed():
    return RealLocalModelHealthcheckRecord(
        decision="REAL_LOCAL_MODEL_HEALTHCHECK_PASSED",
        model_id="determinex-engineer-v11-dsl",
        provider="ollama",
        endpoint="http://127.0.0.1:11434",
        prompt="trivial",
        response_chars=2,
        elapsed_ms=200,
    )


def _hc_failed():
    return RealLocalModelHealthcheckRecord(
        decision="REAL_LOCAL_MODEL_HEALTHCHECK_BLOCKED_TIMEOUT",
        model_id="determinex-engineer-v11-dsl",
        provider="ollama",
        endpoint="http://127.0.0.1:11434",
        prompt="trivial",
        response_chars=0,
        elapsed_ms=5000,
    )


def _sel_selected():
    return BuildAdapterBackedVerifierSelectionRecord(
        decision="BUILD_ADAPTER_VERIFIER_SELECTED",
        workspace="/ws",
        adapter_name="Python",
        build_system_id="pip",
        test_framework_id="pytest",
        verifier_command=("pytest",),
        hardened_runner="intake.hardened_runner",
        multi_match=False,
        matched_adapters=("Python",),
    )


def _sel_blocked():
    return BuildAdapterBackedVerifierSelectionRecord(
        decision="BUILD_ADAPTER_VERIFIER_BLOCKED_UNSUPPORTED_REPO",
        workspace="/ws",
        adapter_name="",
        build_system_id="",
        test_framework_id="",
        verifier_command=(),
        hardened_runner="intake.hardened_runner",
        multi_match=False,
        matched_adapters=(),
    )


def _ok(endpoint, model_id, prompt, system, timeout):
    from models.real_model_diagnose_with_build_verifier import _GenResult

    return _GenResult(ok=True, timed_out=False, text="Likely a test runner config drift.")


def _timeout(endpoint, model_id, prompt, system, timeout):
    from models.real_model_diagnose_with_build_verifier import _GenResult

    return _GenResult(ok=False, timed_out=True, error="timed out")


def _err(endpoint, model_id, prompt, system, timeout):
    from models.real_model_diagnose_with_build_verifier import _GenResult

    return _GenResult(ok=False, timed_out=False, error="500")


def test_status_tokens_exact():
    assert set(TOKENS) == EXPECTED


def test_healthcheck_failed_blocks():
    r = diagnose(
        workspace_identity="ws",
        healthcheck=_hc_failed(),
        verifier_selection=_sel_selected(),
        opt_in=True,
        transport=_ok,
    )
    assert r.decision == "REAL_MODEL_DIAGNOSE_BLOCKED_HEALTHCHECK_FAILED"


def test_missing_healthcheck_blocks():
    r = diagnose(
        workspace_identity="ws",
        healthcheck=None,
        verifier_selection=_sel_selected(),
        opt_in=True,
        transport=_ok,
    )
    assert r.decision == "REAL_MODEL_DIAGNOSE_BLOCKED_HEALTHCHECK_FAILED"


def test_verifier_not_selected_blocks():
    r = diagnose(
        workspace_identity="ws",
        healthcheck=_hc_passed(),
        verifier_selection=_sel_blocked(),
        opt_in=True,
        transport=_ok,
    )
    assert r.decision == "REAL_MODEL_DIAGNOSE_BLOCKED_NO_VERIFIER"


def test_not_opted_in_blocks():
    r = diagnose(
        workspace_identity="ws",
        healthcheck=_hc_passed(),
        verifier_selection=_sel_selected(),
        opt_in=False,
        transport=_ok,
    )
    assert r.decision == "REAL_MODEL_DIAGNOSE_BLOCKED_NOT_OPTED_IN"


def test_timeout_recorded():
    r = diagnose(
        workspace_identity="ws",
        healthcheck=_hc_passed(),
        verifier_selection=_sel_selected(),
        opt_in=True,
        transport=_timeout,
    )
    assert r.decision == "REAL_MODEL_DIAGNOSE_BLOCKED_TIMEOUT"


def test_provider_error_recorded():
    r = diagnose(
        workspace_identity="ws",
        healthcheck=_hc_passed(),
        verifier_selection=_sel_selected(),
        opt_in=True,
        transport=_err,
    )
    assert r.decision == "REAL_MODEL_DIAGNOSE_BLOCKED_PROVIDER_ERROR"


def test_pass_writes_advisory_only():
    r = diagnose(
        workspace_identity="ws",
        healthcheck=_hc_passed(),
        verifier_selection=_sel_selected(),
        opt_in=True,
        transport=_ok,
    )
    assert r.decision == "REAL_MODEL_DIAGNOSE_WITH_VERIFIER_WRITTEN"
    assert r.advisory_only is True
    assert r.output_trusted is False
    assert r.patch_generated is False
    assert r.source_mutation_authorized is False
    assert r.training_eligible is False
    assert r.verifier_remains_source_of_truth is True
    assert "REAL_MODEL_DIAGNOSE_ADVISORY_ONLY" in r.statuses_seen


def test_advisory_summary_is_bounded():
    big = "x" * 8000

    def gen_big(endpoint, model_id, prompt, system, timeout):
        from models.real_model_diagnose_with_build_verifier import _GenResult

        return _GenResult(ok=True, timed_out=False, text=big)

    r = diagnose(
        workspace_identity="ws",
        healthcheck=_hc_passed(),
        verifier_selection=_sel_selected(),
        opt_in=True,
        transport=gen_big,
    )
    assert r.decision == "REAL_MODEL_DIAGNOSE_WITH_VERIFIER_WRITTEN"
    assert len(r.advisory_summary) <= 2048


def test_prompt_does_not_include_source_text():
    # The prompt must never reach the model with workspace source.
    # We capture the prompt by intercepting in the transport.
    captured = {}

    def capture(endpoint, model_id, prompt, system, timeout):
        from models.real_model_diagnose_with_build_verifier import _GenResult

        captured["prompt"] = prompt
        captured["system"] = system
        return _GenResult(ok=True, timed_out=False, text="ok")

    diagnose(
        workspace_identity="opaque-id-1",
        healthcheck=_hc_passed(),
        verifier_selection=_sel_selected(),
        opt_in=True,
        transport=capture,
    )
    p = captured["prompt"]
    # Sanity: verifier context references present
    assert "pip" in p
    assert "pytest" in p
    # No code-like content from a real source tree. The trigger
    # forbiddens are language tokens that would only appear if we
    # had inlined a Python/Rust/Go file body into the prompt.
    for forbidden in (
        "def test_",
        "import os",
        "fn main(",
        "package main",
        "class Foo",
        "@@",
        "---",
        "+++",
    ):
        assert forbidden not in p
    # System reinforces advisory-only
    assert "untrusted" in captured["system"].lower()


def test_module_does_not_import_requests_or_httpx():
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("import requests", "from requests", "import httpx", "from httpx"):
        assert forbidden not in src


def test_record_serializes_safely():
    r = diagnose(
        workspace_identity="ws",
        healthcheck=_hc_passed(),
        verifier_selection=_sel_selected(),
        opt_in=True,
        transport=_ok,
    )
    d = r.to_dict()
    json.dumps(d)
    assert d["advisory_only"] is True
    assert d["output_trusted"] is False
    assert d["patch_generated"] is False
    assert d["training_eligible"] is False
    assert d["verifier_remains_source_of_truth"] is True


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "REAL_MODEL_DIAGNOSE_WITH_BUILD_VERIFIER_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED)
    sd = blob.get("scope_discipline", {})
    assert sd.get("source_mutation_authorized") is False
    assert sd.get("training_eligibility_opened") is False
    assert sd.get("patch_generated") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "REAL_MODEL_DIAGNOSE_WITH_BUILD_VERIFIER_LOCK_001" in ids
