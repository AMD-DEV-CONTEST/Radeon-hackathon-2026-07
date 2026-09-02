"""Tests for DETERMINEX_IDE_BACKEND_FINAL_STATE_LOCK_001.

The final-state assembly is the campaign-end roll-up. Tests:

  * Every upstream lock in the apparatus chain is present.
  * The state fields hold the documented closed-set values.
  * Live model calls NOT_ADMITTED.
  * Training eligibility BLOCKED_BY_DEFAULT.
  * Release readiness NOT_RELEASED.
  * Source mutation BLOCKED_PENDING_HUMAN_APPROVAL.
  * The next_unblocker is declared.
  * Assembly performs no I/O beyond lock-file presence checks.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

final_mod = importlib.import_module("dev.determinex_ide_backend_final_state")
rec_mod = importlib.import_module("dev.determinex_ide_backend_final_state_record")

assemble_final_state = final_mod.assemble_final_state
upstream_locks = final_mod.upstream_locks
FinalBackendState = rec_mod.FinalBackendState
DETERMINEX_IDE_BACKEND_FINAL_STATE_TOKENS = rec_mod.DETERMINEX_IDE_BACKEND_FINAL_STATE_TOKENS

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "DETERMINEX_IDE_BACKEND_FINAL_STATE_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "determinex_ide_backend_final_state"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"
LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"


STATUS_TOKENS = frozenset(DETERMINEX_IDE_BACKEND_FINAL_STATE_TOKENS)


def test_status_tokens_match_expected_set():
    expected = {
        "DETERMINEX_IDE_BACKEND_FINAL_STATE_WRITTEN",
        "EXECUTION_SURFACE_CLEAN",
        "MODEL_ROUTING_READY_DRY_RUN",
        "REPO_INTAKE_READY_FIXTURES",
        "VERIFIER_MATRIX_PARTIAL_BACKED",
        "MOCKED_REPAIR_LOOP_READY",
        "SAFE_PATCH_WORKSPACE_READY_TEMP_ONLY",
        "SOURCE_MUTATION_BLOCKED_PENDING_HUMAN_APPROVAL",
        "IDE_BACKEND_STATE_READY",
        "LIVE_MODEL_CALLS_NOT_ADMITTED",
        "TRAINING_ELIGIBILITY_BLOCKED_BY_DEFAULT",
        "RELEASE_READINESS_NOT_RELEASED",
        "NEXT_UNBLOCKER_DECLARED",
    }
    assert set(STATUS_TOKENS) == expected


# ---------------------------------------------------------------------------
# Upstream locks present
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lock_name", upstream_locks())
def test_every_upstream_lock_is_present(lock_name):
    """All locks the final state references must exist on disk."""
    assert (LOCKS_DIR / f"{lock_name}.json").is_file(), f"Missing upstream lock: {lock_name}"


def test_assembly_reports_no_missing_locks():
    state = assemble_final_state()
    assert state.upstream_locks_missing == (), (
        f"Final state reports missing upstream locks: {state.upstream_locks_missing}"
    )


def test_assembly_includes_all_campaign_locks_in_present_set():
    state = assemble_final_state()
    present = set(state.upstream_locks_present)
    must_be_present = {
        "MODEL_ROUTER_LOCK_001",
        "LLM_MOCKED_INTAKE_REPAIR_LOCK_001",
        "SAFE_PATCH_DIFF_ROLLBACK_LOCK_001",
        "VERIFIED_REPAIR_TRACE_LOCK_001",
        "HUMAN_APPROVAL_SOURCE_MUTATION_GATE_LOCK_001",
        "IDE_REPAIR_STATE_MODEL_LOCK_001",
        "CORPUS_ELIGIBILITY_REPAIR_TRACE_GUARD_LOCK_001",
        "LOCAL_MODEL_ADMISSION_POLICY_LOCK_001",
        "ARBITRARY_REPO_READINESS_MATRIX_LOCK_001",
    }
    assert must_be_present.issubset(present), (
        f"Campaign locks missing from present set: {must_be_present - present}"
    )


# ---------------------------------------------------------------------------
# State field values (closed set)
# ---------------------------------------------------------------------------


def test_final_state_field_values():
    state = assemble_final_state()
    assert state.execution_surface == "CLEAN"
    assert state.model_routing == "READY_DRY_RUN"
    assert state.repo_intake == "READY_FIXTURES"
    assert state.verifier_matrix == "PARTIAL_BACKED"
    assert state.mocked_repair_loop == "READY"
    assert state.safe_patch_workspace == "READY_TEMP_ONLY"
    assert state.source_mutation == "BLOCKED_PENDING_HUMAN_APPROVAL"
    assert state.ide_backend_state == "READY"
    assert state.live_model_calls == "NOT_ADMITTED"
    assert state.training_eligibility == "BLOCKED_BY_DEFAULT"
    assert state.release_readiness == "NOT_RELEASED"
    assert state.next_unblocker == "LOCAL_MODEL_LIVE_ADMISSION_AND_IDE_UI_FLOW"


def test_state_json_round_trip():
    state = assemble_final_state()
    parsed = json.loads(state.to_json())
    assert parsed["execution_surface"] == "CLEAN"
    assert parsed["live_model_calls"] == "NOT_ADMITTED"
    assert parsed["training_eligibility"] == "BLOCKED_BY_DEFAULT"


# ---------------------------------------------------------------------------
# Hygiene
# ---------------------------------------------------------------------------


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in (
        "determinex_ide_backend_final_state.py",
        "determinex_ide_backend_final_state_record.py",
    ):
        src = (_REPO_ROOT / "scripts" / "dev" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "from subprocess" not in src
        assert "import urllib" not in src
        assert "from urllib" not in src
        assert "import socket" not in src
        assert "import http" not in src


def test_assembly_does_not_run_subprocess(monkeypatch):
    import subprocess as _sp

    called = {"count": 0}
    original_run = _sp.run

    def _spy(*args, **kwargs):  # pragma: no cover — should never fire
        called["count"] += 1
        return original_run(*args, **kwargs)

    monkeypatch.setattr(_sp, "run", _spy)
    assemble_final_state()
    assert called["count"] == 0


# ---------------------------------------------------------------------------
# Lock + evidence + index
# ---------------------------------------------------------------------------


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_IDE_BACKEND_FINAL_STATE_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates
    blob = json.loads(candidates[-1].read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_IDE_BACKEND_FINAL_STATE_LOCK_001"


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_IDE_BACKEND_FINAL_STATE_LOCK_001" in ids
