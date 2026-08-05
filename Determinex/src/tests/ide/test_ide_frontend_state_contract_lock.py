"""Tests for IDE_FRONTEND_STATE_CONTRACT_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

contract_mod = importlib.import_module("ide.frontend_state_contract")
rec_mod = importlib.import_module("ide.frontend_state_contract_record")

validate_state = contract_mod.validate_state
sample_ready_state = contract_mod.sample_ready_state
default_risk_warnings = contract_mod.default_risk_warnings
FRONTEND_STATE_CONTRACT_STATUS_TOKENS = rec_mod.FRONTEND_STATE_CONTRACT_STATUS_TOKENS
REQUIRED_SECTIONS = rec_mod.REQUIRED_SECTIONS

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "IDE_FRONTEND_STATE_CONTRACT_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "ide_frontend_state_contract"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(FRONTEND_STATE_CONTRACT_STATUS_TOKENS)


def test_status_tokens_match_expected_set():
    expected = {
        "FRONTEND_STATE_CONTRACT_READY",
        "FRONTEND_STATE_BLOCKED_FIELDS_MISSING",
        "FRONTEND_STATE_RISK_WARNINGS_PRESENT",
        "FRONTEND_STATE_SOURCE_MUTATION_BLOCKED_VISIBLE",
    }
    assert set(STATUS_TOKENS) == expected


def test_required_sections_present():
    required = {
        "workspace",
        "adapter",
        "verifier",
        "model_route",
        "diagnosis",
        "patch_plan",
        "temp_verifier",
        "human_approval",
        "source_apply",
        "corpus_eligibility",
        "evidence",
        "risk_warnings",
    }
    assert set(REQUIRED_SECTIONS) == required


def test_sample_ready_state_validates():
    rec = validate_state(sample_ready_state())
    assert rec.decision == "FRONTEND_STATE_CONTRACT_READY"
    assert rec.sections_missing == ()
    assert "FRONTEND_STATE_RISK_WARNINGS_PRESENT" in rec.statuses_seen
    assert "FRONTEND_STATE_SOURCE_MUTATION_BLOCKED_VISIBLE" in rec.statuses_seen


def test_missing_section_blocks():
    state = sample_ready_state()
    del state["model_route"]
    rec = validate_state(state)
    assert rec.decision == "FRONTEND_STATE_BLOCKED_FIELDS_MISSING"
    assert "model_route" in rec.sections_missing


def test_risk_warnings_always_present():
    state = sample_ready_state()
    rec = validate_state(state)
    assert "TRAINING_ELIGIBILITY_FALSE" in rec.risk_warnings
    assert "VERIFIER_REMAINS_SOURCE_OF_TRUTH" in rec.risk_warnings
    assert "SOURCE_MUTATION_REQUIRES_HUMAN_APPROVAL" in rec.risk_warnings


def test_source_mutation_visible_blocked():
    rec = validate_state(sample_ready_state())
    assert "BLOCKED" in rec.source_mutation.upper()


def test_default_risk_warnings_set():
    warns = default_risk_warnings()
    assert "DIAGNOSIS_IS_ADVISORY" in warns
    assert "PATCH_PLAN_IS_UNTRUSTED" in warns


def test_record_json_round_trip():
    rec = validate_state(sample_ready_state())
    parsed = json.loads(rec.to_json())
    assert parsed["decision"] == "FRONTEND_STATE_CONTRACT_READY"


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("frontend_state_contract.py", "frontend_state_contract_record.py"):
        src = (_REPO_ROOT / "scripts" / "ide" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "import urllib" not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "IDE_FRONTEND_STATE_CONTRACT_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "IDE_FRONTEND_STATE_CONTRACT_LOCK_001" in ids
