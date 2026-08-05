"""Tests for REAL_HUMAN_APPROVAL_ADMISSION_LOCK_001."""

from __future__ import annotations

import datetime as _dt
import hashlib
import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

mod = importlib.import_module("ide.real_human_approval_admission")
rec_mod = importlib.import_module("ide.real_human_approval_admission_record")
tv_mod = importlib.import_module("repair.real_temp_patch_verify_record")

admit = mod.admit
TOKENS = rec_mod.REAL_HUMAN_APPROVAL_ADMISSION_STATUS_TOKENS
RealHumanApprovalAdmissionRecord = rec_mod.RealHumanApprovalAdmissionRecord
RealTempPatchVerifyRecord = tv_mod.RealTempPatchVerifyRecord

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "REAL_HUMAN_APPROVAL_ADMISSION_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "real_human_approval_admission"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED = frozenset(
    {
        "REAL_HUMAN_APPROVAL_ACCEPTED",
        "REAL_HUMAN_APPROVAL_REQUIRED",
        "REAL_HUMAN_APPROVAL_REJECTED",
        "REAL_HUMAN_APPROVAL_BLOCKED_STALE",
        "REAL_HUMAN_APPROVAL_BLOCKED_DIFF_MISMATCH",
        "REAL_HUMAN_APPROVAL_BLOCKED_VERIFIER_NOT_PASSED",
        "REAL_HUMAN_APPROVAL_BLOCKED_FIXTURE",
        "REAL_HUMAN_APPROVAL_BLOCKED_TRACE_MISMATCH",
        "REAL_HUMAN_APPROVAL_BLOCKED_OPERATOR_EMPTY",
        "REAL_HUMAN_APPROVAL_BLOCKED_SIGNATURE_INVALID",
    }
)


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _passed_verify():
    return RealTempPatchVerifyRecord(
        decision="REAL_TEMP_PATCH_VERIFIER_PASSED",
        workspace="/ws",
        temp_workspace="/tmp/x",
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
        unified_diff="--- a\n+++ b\n",
        applied_paths=("src/lib.py",),
        original_unchanged=True,
        original_sha256_before="a" * 64,
        original_sha256_after="a" * 64,
        human_approval_required=True,
    )


def _failed_verify():
    return RealTempPatchVerifyRecord(
        decision="REAL_TEMP_PATCH_VERIFIER_FAILED",
        workspace="/ws",
        temp_workspace="/tmp/x",
        verifier_status="PATCH_VERIFIER_FAILED",
        unified_diff="",
        applied_paths=(),
        original_unchanged=True,
        original_sha256_before="a" * 64,
        original_sha256_after="a" * 64,
        human_approval_required=False,
    )


def _common_kwargs(diff="my diff body"):
    return dict(
        trace_id="trace-1",
        workspace_identity="/ws",
        expected_diff_hash=_sha(diff),
        expected_verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
        expected_stale_after=(_dt.datetime.now(_dt.UTC) + _dt.timedelta(hours=1)).isoformat(),
        observed_diff=diff,
        observed_verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
        temp_verify=_passed_verify(),
    )


def _hmac_sign(
    kwargs,
    *,
    operator_identity="ryan",
    canonical_patch_body_hash="",
    rollback_snapshot_ref="",
    secret_path=None,
):
    """Build a real HMAC signature matching the canonical payload."""
    from ide import local_signing

    payload = local_signing.canonical_payload(
        trace_id=kwargs["trace_id"],
        canonical_patch_body_hash=canonical_patch_body_hash,
        diff_hash=kwargs["expected_diff_hash"],
        verifier_status=kwargs["observed_verifier_status"],
        rollback_snapshot_ref=rollback_snapshot_ref,
        workspace_identity=kwargs["workspace_identity"],
        operator_identity=operator_identity,
        stale_after=kwargs["expected_stale_after"],
    )
    return local_signing.sign(payload, secret_path=secret_path)


def _hmac_secret(tmp_path):
    return tmp_path / "secret"


def test_status_tokens_exact():
    assert set(TOKENS) == EXPECTED


def test_verifier_not_passed_blocked():
    r = admit(
        submitted_action="approve",
        submitted_operator_identity="ryan",
        submitted_signature="a" * 64,
        submitted_signature_kind="real_local_signed",
        **{**_common_kwargs(), "temp_verify": _failed_verify()},
    )
    assert r.decision == "REAL_HUMAN_APPROVAL_BLOCKED_VERIFIER_NOT_PASSED"


def test_observed_verifier_status_not_passed_blocked():
    kw = _common_kwargs()
    kw["observed_verifier_status"] = "PATCH_VERIFIER_FAILED"
    r = admit(
        submitted_action="approve",
        submitted_operator_identity="ryan",
        submitted_signature="a" * 64,
        submitted_signature_kind="real_local_signed",
        **kw,
    )
    assert r.decision == "REAL_HUMAN_APPROVAL_BLOCKED_VERIFIER_NOT_PASSED"


def test_stale_packet_blocked():
    kw = _common_kwargs()
    kw["expected_stale_after"] = (_dt.datetime.now(_dt.UTC) - _dt.timedelta(hours=1)).isoformat()
    r = admit(
        submitted_action="approve",
        submitted_operator_identity="ryan",
        submitted_signature="a" * 64,
        submitted_signature_kind="real_local_signed",
        **kw,
    )
    assert r.decision == "REAL_HUMAN_APPROVAL_BLOCKED_STALE"


def test_diff_hash_mismatch_blocked():
    kw = _common_kwargs(diff="my diff body")
    kw["observed_diff"] = "MUTATED diff"
    r = admit(
        submitted_action="approve",
        submitted_operator_identity="ryan",
        submitted_signature="a" * 64,
        submitted_signature_kind="real_local_signed",
        **kw,
    )
    assert r.decision == "REAL_HUMAN_APPROVAL_BLOCKED_DIFF_MISMATCH"


def test_fixture_signature_rejected_on_approve():
    r = admit(
        submitted_action="approve",
        submitted_operator_identity="ryan",
        submitted_signature="a" * 64,
        submitted_signature_kind="fixture",
        **_common_kwargs(),
    )
    assert r.decision == "REAL_HUMAN_APPROVAL_BLOCKED_FIXTURE"


def test_operator_identity_empty_blocked():
    r = admit(
        submitted_action="approve",
        submitted_operator_identity="   ",
        submitted_signature="a" * 64,
        submitted_signature_kind="real_local_signed",
        **_common_kwargs(),
    )
    assert r.decision == "REAL_HUMAN_APPROVAL_BLOCKED_OPERATOR_EMPTY"


def test_signature_shape_invalid_blocked(tmp_path):
    r = admit(
        submitted_action="approve",
        submitted_operator_identity="ryan",
        submitted_signature="not-hex",
        submitted_signature_kind="real_local_hmac",
        secret_path=_hmac_secret(tmp_path),
        **_common_kwargs(),
    )
    assert r.decision == "REAL_HUMAN_APPROVAL_BLOCKED_SIGNATURE_INVALID"


def test_legacy_real_local_signed_now_refused(tmp_path):
    """CLAUDE-AUTH-008: legacy hex-shape-only signature_kind is gone."""
    kw = _common_kwargs()
    r = admit(
        submitted_action="approve",
        submitted_operator_identity="ryan",
        submitted_signature="a" * 64,
        submitted_signature_kind="real_local_signed",
        secret_path=_hmac_secret(tmp_path),
        **kw,
    )
    assert r.decision == "REAL_HUMAN_APPROVAL_BLOCKED_FIXTURE"


def test_hmac_signature_with_tampered_payload_blocked(tmp_path):
    """CLAUDE-AUTH-008: signature computed over one payload but
    admission attempted with a different payload → blocked."""
    kw = _common_kwargs()
    secret_path = _hmac_secret(tmp_path)
    # Sign with one operator name but submit with a different one.
    sig = _hmac_sign(kw, operator_identity="mallory", secret_path=secret_path)
    r = admit(
        submitted_action="approve",
        submitted_operator_identity="ryan",
        submitted_signature=sig,
        submitted_signature_kind="real_local_hmac",
        secret_path=secret_path,
        **kw,
    )
    assert r.decision == "REAL_HUMAN_APPROVAL_BLOCKED_SIGNATURE_INVALID"


def test_reject_path_records_rejection():
    r = admit(
        submitted_action="reject",
        submitted_operator_identity="ryan",
        submitted_signature="ignored",
        submitted_signature_kind="real_local_signed",
        **_common_kwargs(),
    )
    assert r.decision == "REAL_HUMAN_APPROVAL_REJECTED"
    assert r.source_mutation_authorized is False


def test_no_action_returns_required():
    r = admit(
        submitted_action="",
        submitted_operator_identity="ryan",
        submitted_signature="",
        submitted_signature_kind="real_local_signed",
        **_common_kwargs(),
    )
    assert r.decision == "REAL_HUMAN_APPROVAL_REQUIRED"


def test_accepted_keeps_source_mutation_unauthorized(tmp_path):
    kw = _common_kwargs()
    secret_path = _hmac_secret(tmp_path)
    sig = _hmac_sign(kw, secret_path=secret_path)
    r = admit(
        submitted_action="approve",
        submitted_operator_identity="ryan",
        submitted_signature=sig,
        submitted_signature_kind="real_local_hmac",
        secret_path=secret_path,
        **kw,
    )
    assert r.decision == "REAL_HUMAN_APPROVAL_ACCEPTED"
    assert r.is_accepted
    assert r.source_mutation_authorized is False, (
        "accepting approval does not by itself authorize source mutation"
    )
    assert r.training_eligible is False
    assert r.is_fixture is False
    # HMAC payload binding verified.
    assert r.signature_kind == "real_local_hmac"


def test_record_serializes_safely():
    r = admit(
        submitted_action="approve",
        submitted_operator_identity="ryan",
        submitted_signature="c" * 64,
        submitted_signature_kind="real_local_signed",
        **_common_kwargs(),
    )
    d = r.to_dict()
    json.dumps(d)
    assert d["source_mutation_authorized"] is False
    assert d["training_eligible"] is False


def test_module_does_not_open_network():
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "requests",
        "httpx",
        "urllib.request",
        "socket.connect",
        "subprocess.Popen",
        "subprocess.run",
    ):
        assert forbidden not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "REAL_HUMAN_APPROVAL_ADMISSION_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED)
    sd = blob.get("scope_discipline", {})
    assert sd.get("source_mutation_authorized") is False
    assert sd.get("training_eligibility_opened") is False
    assert sd.get("fixture_approval_admitted") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "REAL_HUMAN_APPROVAL_ADMISSION_LOCK_001" in ids
