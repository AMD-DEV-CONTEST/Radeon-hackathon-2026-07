"""Tests for LIVE_MODEL_MOCK_COMPATIBILITY_HARNESS_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

harness_mod = importlib.import_module("models.live_model_compat_harness")
rec_mod = importlib.import_module("models.live_model_response_record")

LiveModelCompatHarness = harness_mod.LiveModelCompatHarness
DeterministicProvider = harness_mod.DeterministicProvider
TimeoutProvider = harness_mod.TimeoutProvider
UnavailableProvider = harness_mod.UnavailableProvider
MalformedProvider = harness_mod.MalformedProvider
OversizedProvider = harness_mod.OversizedProvider
EmptyProvider = harness_mod.EmptyProvider
LIVE_MODEL_RESPONSE_STATUS_TOKENS = harness_mod.LIVE_MODEL_RESPONSE_STATUS_TOKENS

LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "LIVE_MODEL_MOCK_COMPATIBILITY_HARNESS_LOCK_001.json"
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "live_model_mock_compatibility_harness"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(LIVE_MODEL_RESPONSE_STATUS_TOKENS)


def test_status_tokens_match_expected_set():
    expected = {
        "MODEL_COMPAT_HARNESS_PASSED",
        "MODEL_COMPAT_HARNESS_BLOCKED_PROVIDER_UNAVAILABLE",
        "MODEL_COMPAT_HARNESS_BLOCKED_BAD_RESPONSE",
        "MODEL_COMPAT_HARNESS_BLOCKED_TIMEOUT",
        "MODEL_COMPAT_HARNESS_BLOCKED_SCHEMA_INVALID",
        "MODEL_COMPAT_HARNESS_BLOCKED_OVERSIZED",
        "MODEL_COMPAT_HARNESS_BLOCKED_EMPTY",
    }
    assert set(STATUS_TOKENS) == expected


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_deterministic_provider_with_valid_schema_passes():
    h = LiveModelCompatHarness()
    p = DeterministicProvider(canned={"summary": "fixture diagnose", "extra": "ok"})
    r = h.invoke(p, task_class="BUILD_DIAGNOSIS", schema_id="diagnose_v1")
    assert r.status == "MODEL_COMPAT_HARNESS_PASSED"
    assert r.payload["summary"] == "fixture diagnose"
    # Hard invariant — never trusted.
    assert r.trusted is False


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


def test_unavailable_provider_blocks():
    r = LiveModelCompatHarness().invoke(
        UnavailableProvider(),
        task_class="BUILD_DIAGNOSIS",
        schema_id="diagnose_v1",
    )
    assert r.status == "MODEL_COMPAT_HARNESS_BLOCKED_PROVIDER_UNAVAILABLE"
    assert r.trusted is False


def test_timeout_provider_blocks():
    r = LiveModelCompatHarness().invoke(
        TimeoutProvider(),
        task_class="BUILD_DIAGNOSIS",
        schema_id="diagnose_v1",
    )
    assert r.status == "MODEL_COMPAT_HARNESS_BLOCKED_TIMEOUT"


def test_malformed_provider_blocks_bad_response():
    r = LiveModelCompatHarness().invoke(
        MalformedProvider(bad_value="not a dict"),
        task_class="BUILD_DIAGNOSIS",
        schema_id="diagnose_v1",
    )
    assert r.status == "MODEL_COMPAT_HARNESS_BLOCKED_BAD_RESPONSE"


def test_malformed_provider_with_unencodable_value_blocks():
    r = LiveModelCompatHarness().invoke(
        MalformedProvider(bad_value={"k": object()}),
        task_class="BUILD_DIAGNOSIS",
        schema_id="diagnose_v1",
    )
    assert r.status == "MODEL_COMPAT_HARNESS_BLOCKED_BAD_RESPONSE"


def test_oversized_provider_blocks():
    r = LiveModelCompatHarness().invoke(
        OversizedProvider(),
        task_class="BUILD_DIAGNOSIS",
        schema_id="diagnose_v1",
    )
    assert r.status == "MODEL_COMPAT_HARNESS_BLOCKED_OVERSIZED"


def test_empty_provider_blocks():
    r = LiveModelCompatHarness().invoke(
        EmptyProvider(),
        task_class="BUILD_DIAGNOSIS",
        schema_id="diagnose_v1",
    )
    assert r.status == "MODEL_COMPAT_HARNESS_BLOCKED_EMPTY"


def test_schema_validation_missing_keys_blocks():
    p = DeterministicProvider(canned={"some_other_field": "irrelevant"})
    r = LiveModelCompatHarness().invoke(
        p,
        task_class="PATCH_PLANNING",
        schema_id="patch_plan_v1",
    )
    assert r.status == "MODEL_COMPAT_HARNESS_BLOCKED_SCHEMA_INVALID"


def test_patch_plan_schema_passes_with_required_keys():
    p = DeterministicProvider(canned={"kind": "MOCK", "steps": ["x", "y"]})
    r = LiveModelCompatHarness().invoke(
        p,
        task_class="PATCH_PLANNING",
        schema_id="patch_plan_v1",
    )
    assert r.status == "MODEL_COMPAT_HARNESS_PASSED"


def test_verifier_schema_passes_with_required_key():
    p = DeterministicProvider(canned={"status": "MOCK_PASS"})
    r = LiveModelCompatHarness().invoke(
        p,
        task_class="VERIFIER_SUMMARY",
        schema_id="verifier_v1",
    )
    assert r.status == "MODEL_COMPAT_HARNESS_PASSED"


# ---------------------------------------------------------------------------
# Trust + state invariants
# ---------------------------------------------------------------------------


def test_response_trusted_false_on_every_status():
    h = LiveModelCompatHarness()
    fixtures = [
        DeterministicProvider(canned={"summary": "ok"}),
        UnavailableProvider(),
        TimeoutProvider(),
        MalformedProvider(),
        OversizedProvider(),
        EmptyProvider(),
    ]
    for p in fixtures:
        r = h.invoke(p, task_class="BUILD_DIAGNOSIS", schema_id="diagnose_v1")
        assert r.trusted is False


def test_response_json_round_trip():
    r = LiveModelCompatHarness().invoke(
        DeterministicProvider(canned={"summary": "ok"}),
        task_class="BUILD_DIAGNOSIS",
        schema_id="diagnose_v1",
    )
    parsed = json.loads(r.to_json())
    assert parsed["status"] == "MODEL_COMPAT_HARNESS_PASSED"
    assert parsed["trusted"] is False


# ---------------------------------------------------------------------------
# Hygiene
# ---------------------------------------------------------------------------


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("live_model_compat_harness.py", "live_model_response_record.py"):
        src = (_REPO_ROOT / "scripts" / "models" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "from subprocess" not in src
        assert "import urllib" not in src
        assert "from urllib" not in src
        assert "import socket" not in src
        assert "import http" not in src


# ---------------------------------------------------------------------------
# Lock + evidence + index
# ---------------------------------------------------------------------------


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "LIVE_MODEL_MOCK_COMPATIBILITY_HARNESS_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates
    blob = json.loads(candidates[-1].read_text(encoding="utf-8"))
    assert blob["lock_id"] == "LIVE_MODEL_MOCK_COMPATIBILITY_HARNESS_LOCK_001"


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "LIVE_MODEL_MOCK_COMPATIBILITY_HARNESS_LOCK_001" in ids
