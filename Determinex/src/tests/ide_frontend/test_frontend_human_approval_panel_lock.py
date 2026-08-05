"""Tests for FRONTEND_HUMAN_APPROVAL_PANEL_LOCK_001."""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
PANEL = _REPO_ROOT / "frontend" / "src" / "components" / "ide-repair" / "HumanApprovalPanel.tsx"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "FRONTEND_HUMAN_APPROVAL_PANEL_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "frontend_human_approval_panel"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(
    {
        "HUMAN_APPROVAL_PANEL_READY",
        "HUMAN_APPROVAL_RISK_COPY_VISIBLE",
        "HUMAN_APPROVAL_REJECT_AVAILABLE",
        "HUMAN_APPROVAL_SOURCE_MUTATION_STILL_GATED",
        "HUMAN_APPROVAL_BLOCKERS_VISIBLE",
    }
)

REQUIRED_COPY_KEYS = (
    "diagnosis_advisory",
    "patch_plan_untrusted",
    "verifier_result_explanation",
    "temp_workspace_explanation",
    "source_mutation_warning",
    "approval_consequences",
    "reject_option",
    "evidence_trail_explanation",
    "training_eligibility_notice",
    "live_model_disclaimer",
    "no_blind_approval",
)

FORBIDDEN_HYPE = (
    "always correct",
    "guaranteed to work",
    "risk-free",
    "trust the AI",
    "blindly approve",
    "no need to read",
)


def test_panel_exists():
    assert PANEL.is_file()


def test_status_tokens_exact():
    src = PANEL.read_text(encoding="utf-8")
    m = re.search(r"HUMAN_APPROVAL_PANEL_STATUS_TOKENS\s*=\s*\[([^\]]+)\]\s*as\s*const", src)
    assert m
    declared = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert declared == STATUS_TOKENS


def test_all_required_copy_keys_present():
    src = PANEL.read_text(encoding="utf-8")
    for key in REQUIRED_COPY_KEYS:
        assert f"{key}:" in src, f"copy key {key!r} missing"


def test_no_forbidden_hype():
    src = PANEL.read_text(encoding="utf-8").lower()
    for phrase in FORBIDDEN_HYPE:
        assert phrase.lower() not in src, f"Forbidden phrase: {phrase}"


def test_calls_get_human_approval_packet():
    src = PANEL.read_text(encoding="utf-8")
    assert '"get_human_approval_packet"' in src


def test_renders_diff_files_verifier_trace():
    src = PANEL.read_text(encoding="utf-8")
    for tid in (
        "human-approval-diff-summary",
        "human-approval-files-changed",
        "human-approval-verifier-result",
        "human-approval-trace-id",
    ):
        assert f'data-testid="{tid}"' in src


def test_approve_reject_buttons_present():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="human-approval-approve-button"' in src
    assert 'data-testid="human-approval-reject-button"' in src
    # Approve button must be disabled until operator id is non-empty.
    assert "disabled={!canApprove" in src


def test_operator_input_required():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="human-approval-operator-input"' in src


def test_source_mutation_still_gated_note():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="human-approval-source-mutation-still-gated"' in src
    assert "Source mutation is still gated" in src


def test_fixture_only_approve_label_present():
    src = PANEL.read_text(encoding="utf-8")
    assert "Approve (fixture only)" in src
    assert 'data-testid="human-approval-fixture-recorded"' in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "FRONTEND_HUMAN_APPROVAL_PANEL_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "FRONTEND_HUMAN_APPROVAL_PANEL_LOCK_001" in ids
