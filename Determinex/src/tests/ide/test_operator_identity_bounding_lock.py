"""Tests for CLAUDE_OPERATOR_IDENTITY_BOUNDING_LOCK_001.

Bounded operator identity: a free-string operator_identity (without
a signing key reference and without a payload-hash binding) cannot
satisfy the bound check. Tampering with workspace, operator, or
payload fields breaks the bind. The bind never authorizes source
mutation; it only attests that the admission and the named
operator are coupled.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

oib = importlib.import_module("ide.operator_identity_bounding")
oib_rec = importlib.import_module("ide.operator_identity_bounding_record")
admission_mod = importlib.import_module("ide.real_human_approval_admission_record")

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / ("CLAUDE_OPERATOR_IDENTITY_BOUNDING_LOCK_001.json")
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / ("claude_operator_identity_bounding")
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


def _admission(operator_identity="ryan"):
    return admission_mod.RealHumanApprovalAdmissionRecord(
        decision="REAL_HUMAN_APPROVAL_ACCEPTED",
        trace_id="t-1",
        workspace_identity="/c/Users/ryan/repo",
        diff_hash="d" * 64,
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
        operator_identity=operator_identity,
        operator_signature="e" * 64,
        signature_kind="real_local_hmac",
        is_fixture=False,
        accepted_at="2026-05-28T00:00:00+00:00",
        stale_after="2099-01-01T00:00:00+00:00",
        source_mutation_authorized=False,
        training_eligible=False,
        canonical_patch_body_hash="b" * 64,
    )


def _bound_for(adm, *, signing_key_ref=None):
    return oib.bound_from_admission(
        adm,
        display_name="Ryan G.",
        signing_key_ref=signing_key_ref or ("f" * 64),
    )


# ---------------------------------------------------------------------------
# Status token surface
# ---------------------------------------------------------------------------
def test_status_tokens_exact():
    assert set(oib_rec.OPERATOR_IDENTITY_BOUNDING_STATUS_TOKENS) == {
        "OPERATOR_IDENTITY_BOUNDING_PASSED",
        "OPERATOR_IDENTITY_BLOCKED_FREE_STRING_ONLY",
        "OPERATOR_IDENTITY_BLOCKED_MISSING_SIGNING_REF",
        "OPERATOR_IDENTITY_BLOCKED_PAYLOAD_MISMATCH",
        "OPERATOR_IDENTITY_BLOCKED_WORKSPACE_MISMATCH",
        "OPERATOR_IDENTITY_BLOCKED_STALE",
        "OPERATOR_IDENTITY_BLOCKED_MALFORMED_IDENTITY",
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_bound_from_admission_well_formed():
    adm = _admission()
    bound = _bound_for(adm)
    assert bound.is_well_formed


def test_bound_check_passes_for_matching_pair():
    adm = _admission()
    bound = _bound_for(adm)
    rec = oib.check(admission=adm, bound=bound)
    assert rec.is_passed, rec.notes
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False


def test_signing_key_ref_for_returns_64_hex(tmp_path):
    p = tmp_path / "secret"
    ref = oib.signing_key_ref_for(p)
    assert len(ref) == 64
    int(ref, 16)


# ---------------------------------------------------------------------------
# Free-string-only refusal
# ---------------------------------------------------------------------------
def test_free_string_only_blocks():
    """Admission alone (without a BoundedOperatorIdentity supplied)
    is not enough — that's the residual CLAUDE-AUTH-014 risk."""
    adm = _admission()
    rec = oib.check(admission=adm, bound=None)
    assert rec.decision == "OPERATOR_IDENTITY_BLOCKED_FREE_STRING_ONLY"
    assert rec.is_blocked


def test_missing_signing_ref_blocks():
    adm = _admission()
    bound = _bound_for(adm)
    bound2 = dataclasses.replace(bound, signing_key_ref="")
    rec = oib.check(admission=adm, bound=bound2)
    assert rec.is_blocked
    # not is_well_formed either, so it lands on MALFORMED — both valid
    assert rec.decision in (
        "OPERATOR_IDENTITY_BLOCKED_MISSING_SIGNING_REF",
        "OPERATOR_IDENTITY_BLOCKED_MALFORMED_IDENTITY",
    )


def test_legacy_signature_kind_blocks_even_with_bound():
    adm = _admission()
    adm2 = dataclasses.replace(adm, signature_kind="real_local_signed")
    bound = _bound_for(adm2)
    rec = oib.check(admission=adm2, bound=bound)
    assert rec.decision == "OPERATOR_IDENTITY_BLOCKED_MISSING_SIGNING_REF"


# ---------------------------------------------------------------------------
# Tampering
# ---------------------------------------------------------------------------
def test_operator_id_mismatch_blocks():
    adm = _admission(operator_identity="ryan")
    bound = _bound_for(adm)
    bound2 = dataclasses.replace(bound, operator_id="mallory")
    rec = oib.check(admission=adm, bound=bound2)
    assert rec.decision == "OPERATOR_IDENTITY_BLOCKED_PAYLOAD_MISMATCH"


def test_workspace_hash_mismatch_blocks():
    adm = _admission()
    bound = _bound_for(adm)
    wrong = hashlib.sha256(b"different-ws").hexdigest()
    bound2 = dataclasses.replace(bound, workspace_identity_hash=wrong)
    rec = oib.check(admission=adm, bound=bound2)
    assert rec.decision == "OPERATOR_IDENTITY_BLOCKED_WORKSPACE_MISMATCH"


def test_payload_hash_mismatch_blocks():
    adm = _admission()
    bound = _bound_for(adm)
    wrong = hashlib.sha256(b"tampered").hexdigest()
    bound2 = dataclasses.replace(bound, approval_payload_hash=wrong)
    rec = oib.check(admission=adm, bound=bound2)
    assert rec.decision == "OPERATOR_IDENTITY_BLOCKED_PAYLOAD_MISMATCH"


# ---------------------------------------------------------------------------
# Refusals on admission shape
# ---------------------------------------------------------------------------
def test_none_admission_blocks():
    rec = oib.check(admission=None, bound=None)
    assert rec.decision == "OPERATOR_IDENTITY_BLOCKED_MALFORMED_IDENTITY"


def test_fixture_admission_blocks():
    adm = _admission()
    adm2 = dataclasses.replace(adm, is_fixture=True)
    bound = _bound_for(adm2)
    rec = oib.check(admission=adm2, bound=bound)
    assert rec.decision == "OPERATOR_IDENTITY_BLOCKED_MALFORMED_IDENTITY"


def test_unaccepted_admission_blocks():
    adm = _admission()
    adm2 = dataclasses.replace(adm, decision="REAL_HUMAN_APPROVAL_REQUIRED")
    rec = oib.check(admission=adm2, bound=_bound_for(adm))
    assert rec.is_blocked


# ---------------------------------------------------------------------------
# Bounded shape
# ---------------------------------------------------------------------------
def test_well_formed_rejects_nul_in_operator_id():
    adm = _admission()
    bound = _bound_for(adm)
    bad = dataclasses.replace(bound, operator_id="ry\x00an")
    assert not bad.is_well_formed


def test_well_formed_rejects_huge_operator_id():
    adm = _admission()
    bound = _bound_for(adm)
    bad = dataclasses.replace(bound, operator_id="x" * 200)
    assert not bad.is_well_formed


def test_well_formed_rejects_non_hex_signing_key_ref():
    adm = _admission()
    bound = _bound_for(adm)
    bad = dataclasses.replace(bound, signing_key_ref="not-hex" + "z" * 57)
    assert not bad.is_well_formed


def test_well_formed_rejects_short_hash():
    adm = _admission()
    bound = _bound_for(adm)
    bad = dataclasses.replace(bound, approval_payload_hash="abc123")
    assert not bad.is_well_formed


def test_does_not_authorize_source_mutation_on_pass():
    adm = _admission()
    bound = _bound_for(adm)
    rec = oib.check(admission=adm, bound=bound)
    assert rec.is_passed
    # Hard invariant: the bound check NEVER opens source mutation.
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False


# ---------------------------------------------------------------------------
# Lock / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "CLAUDE_OPERATOR_IDENTITY_BOUNDING_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "CLAUDE_OPERATOR_IDENTITY_BOUNDING_LOCK_001" in ids
