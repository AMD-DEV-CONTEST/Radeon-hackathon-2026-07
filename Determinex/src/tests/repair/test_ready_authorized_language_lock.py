"""Tests for CLAUDE_AUTH_005_READY_AUTHORIZED_LANGUAGE_LOCK_001.

Locks the rule: a ``READY`` token (capability_available) NEVER
means ``AUTHORIZED``. Backend and frontend status tokens are
classified into an 8-class disjoint vocabulary, and the lock
fails if any token violates the precision rules.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

vocab = importlib.import_module("repair.ready_authorized_vocabulary")
vocab_rec = importlib.import_module("repair.ready_authorized_vocabulary_record")

LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / ("CLAUDE_AUTH_005_READY_AUTHORIZED_LANGUAGE_LOCK_001.json")
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / ("claude_auth_005_ready_authorized_language")
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


# ---------------------------------------------------------------------------
# Class set
# ---------------------------------------------------------------------------
def test_eight_classes_exact():
    assert set(vocab.classes()) == {
        "capability_available",
        "evidence_present",
        "request_pending",
        "admission_present",
        "approval_present",
        "execution_authorized",
        "source_mutation_authorized",
        "training_eligible",
    }


def test_authorization_classes_set():
    assert vocab_rec.CLASSES_THAT_IMPLY_AUTHORIZATION == frozenset(
        {
            "execution_authorized",
            "source_mutation_authorized",
            "training_eligible",
        }
    )


# ---------------------------------------------------------------------------
# Hard invariants
# ---------------------------------------------------------------------------
def test_no_ready_token_implies_authorization():
    for tok in vocab.known_tokens():
        if "READY" not in tok:
            continue
        c = vocab.classify(tok)
        assert c is not None
        assert c.vocabulary_class not in vocab_rec.CLASSES_THAT_IMPLY_AUTHORIZATION, (
            f"{tok!r} READY token classified as {c.vocabulary_class!r} — "
            "READY must never imply authorization"
        )


def test_no_fixture_token_classifies_as_source_mutation_authorized():
    for tok in vocab.known_tokens():
        if "FIXTURE" not in tok:
            continue
        c = vocab.classify(tok)
        assert c is not None
        assert c.vocabulary_class != "source_mutation_authorized", (
            f"fixture token {tok!r} must never classify as source_mutation_authorized"
        )
        # Fixture-only approvals should classify as approval_present
        # but the apply gate refuses them — the classification only
        # says "there is some approval"; the gate says "but not a real
        # one".
        assert c.vocabulary_class == "approval_present"


def test_no_frontend_token_classifies_into_authorization_class():
    for tok in vocab.known_tokens():
        c = vocab.classify(tok)
        assert c is not None
        if c.surface != "frontend":
            continue
        assert c.vocabulary_class not in vocab_rec.CLASSES_THAT_IMPLY_AUTHORIZATION, (
            f"frontend token {tok!r} classifies into "
            f"{c.vocabulary_class!r} — UI must not carry authorization signal"
        )


def test_no_token_classifies_as_training_eligible():
    """Until a separate training-eligibility gate exists, NO existing
    backend/frontend status token should classify as training_eligible.
    That keeps training_eligible default-false at the vocabulary level."""
    for tok in vocab.known_tokens():
        c = vocab.classify(tok)
        assert c is not None
        assert c.vocabulary_class != "training_eligible", (
            f"{tok!r} classified as training_eligible — no token may yet"
            " imply training eligibility; this is the negative-default rule"
        )


def test_only_one_token_classifies_as_source_mutation_authorized():
    """The whole point of the campaign: there must be exactly ONE
    token that means 'source mutation has happened' — the post-fact
    record emitted by the apply gate. Any expansion of this set
    requires a new lock."""
    sm = [
        tok
        for tok in vocab.known_tokens()
        if vocab.classify(tok).vocabulary_class == "source_mutation_authorized"
    ]
    assert sm == ["SOURCE_MUTATION_APPLIED_AFTER_APPROVAL"], (
        f"unexpected source_mutation_authorized tokens: {sm!r}"
    )


def test_classify_unknown_returns_none():
    assert vocab.classify("TOTALLY_MADE_UP_TOKEN") is None
    cs, unknown = vocab.classify_many(["MADE_UP", "IDE_BACKEND_COMMAND_SURFACE_READY"])
    assert unknown == ["MADE_UP"]
    assert len(cs) == 1
    assert cs[0].token == "IDE_BACKEND_COMMAND_SURFACE_READY"


def test_assert_ready_does_not_imply_authorized_passes():
    rec = vocab.assert_ready_does_not_imply_authorized()
    assert rec.is_passed, (
        f"language audit failed: {rec.ambiguous_labels!r}, "
        f"ui_confusions={rec.ui_authority_confusions!r}"
    )
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False
    assert rec.tokens_classified, "expected at least one classification"


# ---------------------------------------------------------------------------
# Coverage — every known token in repo status enums is classified
# ---------------------------------------------------------------------------
def test_classifier_covers_audited_backend_tokens():
    """Spot-check: the known_tokens map must include every backend
    surface token raised in the audit. If a new token is added but
    not classified, this fails as a forcing function."""
    required = {
        "IDE_BACKEND_COMMAND_SURFACE_READY",
        "IDE_DIAGNOSE_DRY_RUN_READY",
        "IDE_DIAGNOSE_LIVE_OPT_IN_READY",
        "MODEL_ROUTE_PANEL_READY",
        "INTAKE_READY",
        "IDE_SOURCE_APPLY_DRY_RUN_READY",
        "SOURCE_APPLY_DRY_RUN_READY",
        "LOCAL_MODEL_LIVE_ADMISSION_READY",
        "REAL_LOCAL_MODEL_CONFIG_READY",
        "LIVE_MODEL_ADMITTED",
        "LIVE_MODEL_NOT_ADMITTED",
        "LOCAL_MODEL_METADATA_ADMITTED",
        "REAL_LOCAL_MODEL_ADMITTED",
        "REAL_HUMAN_APPROVAL_ACCEPTED",
        "SOURCE_APPROVAL_ACCEPTED_FIXTURE",
        "SOURCE_MUTATION_APPROVAL_ACCEPTED_FIXTURE",
        "SOURCE_MUTATION_APPLIED_AFTER_APPROVAL",
        "POST_APPLY_VERIFIER_PASSED",
        "ROLLBACK_SNAPSHOT_WRITTEN",
        "REAL_TEMP_PATCH_VERIFIER_PASSED",
    }
    missing = required - set(vocab.known_tokens())
    assert not missing, f"audited tokens missing from classifier: {missing!r}"


def test_classifier_covers_audited_frontend_tokens():
    required = {
        "FRONTEND_COMMAND_INVOKE_CLIENT_READY",
        "TAURI_RUST_COMMAND_BRIDGE_READY",
        "FRONTEND_PANEL_COMMAND_WIRING_READY",
        "WORKSPACE_STATUS_PANEL_READY",
        "REPAIR_PANEL_SHELL_READY",
        "FRONTEND_DIAGNOSE_DRY_RUN_READY",
        "TEMP_VERIFY_PANEL_READY",
        "HUMAN_APPROVAL_PANEL_READY",
        "SOURCE_APPLY_DRY_RUN_PANEL_READY",
        "EVIDENCE_VIEWER_READY",
        "LOCAL_MODEL_SETTINGS_PANEL_READY",
    }
    missing = required - set(vocab.known_tokens())
    assert not missing, f"frontend tokens missing from classifier: {missing!r}"


def test_apply_gate_post_fact_token_only_source_mutation_class():
    """The SOURCE_MUTATION_APPLIED_AFTER_APPROVAL token is what the
    apply gate emits AFTER all checks pass. Nothing else in the
    vocabulary may share that class."""
    cs = [
        c
        for c in (vocab.classify(t) for t in vocab.known_tokens())
        if c and c.vocabulary_class == "source_mutation_authorized"
    ]
    assert len(cs) == 1
    assert cs[0].token == "SOURCE_MUTATION_APPLIED_AFTER_APPROVAL"
    assert cs[0].surface == "backend"


# ---------------------------------------------------------------------------
# Lock / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "CLAUDE_AUTH_005_READY_AUTHORIZED_LANGUAGE_LOCK_001"
    sd = blob.get("scope_discipline", {})
    assert sd.get("source_mutation_authorized") is False
    assert sd.get("training_eligible") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "CLAUDE_AUTH_005_READY_AUTHORIZED_LANGUAGE_LOCK_001" in ids
