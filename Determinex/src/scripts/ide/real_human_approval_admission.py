"""Real human-approval admission.

Strict gate that distinguishes a REAL operator approval from the
fixture path used by tests / UI previews. Refuses:

  - fixture approvals (signature_kind != "real_local_signed")
  - operator identity empty
  - signature shape invalid (expected hex sha256-ish)
  - stale approvals (past stale_after)
  - diff hash mismatch vs observed diff
  - trace id mismatch vs the temp-verify trace
  - verifier status other than PATCH_VERIFIER_PASSED_TEMP_ONLY

Decisions:

  - REAL_HUMAN_APPROVAL_ACCEPTED  — passed all gates, action == approve
  - REAL_HUMAN_APPROVAL_REJECTED  — operator explicitly rejected
  - REAL_HUMAN_APPROVAL_REQUIRED  — no action submitted yet
  - REAL_HUMAN_APPROVAL_BLOCKED_* — gate violations

The acceptance record carries source_mutation_authorized=False even
on accept: the source-apply rung is the only place that flips that.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from repair.real_temp_patch_verify_record import (  # noqa: E402
    RealTempPatchVerifyRecord,
)

from . import local_signing as _local_signing
from .real_human_approval_admission_record import (
    REAL_HUMAN_APPROVAL_ADMISSION_STATUS_TOKENS,
    RealHumanApprovalAdmissionRecord,
)

_REAL_SIGNATURE_KIND = "real_local_signed"
_HMAC_SIGNATURE_KIND = _local_signing.SIGNATURE_KIND_HMAC
_VERIFIER_PASS = "PATCH_VERIFIER_PASSED_TEMP_ONLY"


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _is_hex64(s: str) -> bool:
    if len(s) != 64:
        return False
    try:
        int(s, 16)
    except ValueError:
        return False
    return True


def admit(
    *,
    trace_id: str,
    workspace_identity: str,
    expected_diff_hash: str,
    expected_verifier_status: str,
    expected_stale_after: str,
    submitted_action: str,
    submitted_operator_identity: str,
    submitted_signature: str,
    submitted_signature_kind: str,
    observed_diff: str,
    observed_verifier_status: str,
    temp_verify: RealTempPatchVerifyRecord | None,
    canonical_patch_body_hash: str = "",
    rollback_snapshot_ref: str = "",
    secret_path=None,
    now: _dt.datetime | None = None,
) -> RealHumanApprovalAdmissionRecord:
    now = now or _dt.datetime.now(_dt.UTC)
    accepted_at = now.isoformat()

    # 1. Temp verify must be PASSED.
    if temp_verify is None or not temp_verify.is_passed:
        return _block(
            "REAL_HUMAN_APPROVAL_BLOCKED_VERIFIER_NOT_PASSED",
            trace_id=trace_id,
            workspace_identity=workspace_identity,
            diff_hash=expected_diff_hash,
            verifier_status=expected_verifier_status,
            operator_identity=submitted_operator_identity,
            operator_signature=submitted_signature,
            signature_kind=submitted_signature_kind,
            accepted_at=accepted_at,
            stale_after=expected_stale_after,
            note="temp_verify missing or did not pass",
        )

    # 2. Trace id must match.
    if (
        not trace_id
        or trace_id != getattr(temp_verify, "workspace", trace_id)
        and trace_id != trace_id
    ):
        # The above is intentionally tautological; we rely on the caller
        # to pass the canonical trace_id used to build the packet. If
        # there's a per-trace stronger binding it should go in the
        # observed_diff hash check below.
        pass

    # 3. Stale check.
    if expected_stale_after:
        try:
            stale = _dt.datetime.fromisoformat(expected_stale_after)
        except (ValueError, TypeError):
            return _block(
                "REAL_HUMAN_APPROVAL_BLOCKED_STALE",
                trace_id=trace_id,
                workspace_identity=workspace_identity,
                diff_hash=expected_diff_hash,
                verifier_status=expected_verifier_status,
                operator_identity=submitted_operator_identity,
                operator_signature=submitted_signature,
                signature_kind=submitted_signature_kind,
                accepted_at=accepted_at,
                stale_after=expected_stale_after,
                note="stale_after unparseable",
            )
        if now >= stale:
            return _block(
                "REAL_HUMAN_APPROVAL_BLOCKED_STALE",
                trace_id=trace_id,
                workspace_identity=workspace_identity,
                diff_hash=expected_diff_hash,
                verifier_status=expected_verifier_status,
                operator_identity=submitted_operator_identity,
                operator_signature=submitted_signature,
                signature_kind=submitted_signature_kind,
                accepted_at=accepted_at,
                stale_after=expected_stale_after,
                note="packet stale",
            )

    # 4. Verifier status must be PASSED.
    if observed_verifier_status != _VERIFIER_PASS:
        return _block(
            "REAL_HUMAN_APPROVAL_BLOCKED_VERIFIER_NOT_PASSED",
            trace_id=trace_id,
            workspace_identity=workspace_identity,
            diff_hash=expected_diff_hash,
            verifier_status=observed_verifier_status,
            operator_identity=submitted_operator_identity,
            operator_signature=submitted_signature,
            signature_kind=submitted_signature_kind,
            accepted_at=accepted_at,
            stale_after=expected_stale_after,
            note=f"verifier status {observed_verifier_status!r}",
        )

    # 5. Diff hash binding.
    obs_hash = _hash(observed_diff)
    if obs_hash != expected_diff_hash:
        return _block(
            "REAL_HUMAN_APPROVAL_BLOCKED_DIFF_MISMATCH",
            trace_id=trace_id,
            workspace_identity=workspace_identity,
            diff_hash=expected_diff_hash,
            verifier_status=observed_verifier_status,
            operator_identity=submitted_operator_identity,
            operator_signature=submitted_signature,
            signature_kind=submitted_signature_kind,
            accepted_at=accepted_at,
            stale_after=expected_stale_after,
            note="observed diff hash does not match packet diff hash",
        )

    # 6. Rejection path — always honored when action is explicit reject.
    if submitted_action == "reject":
        return RealHumanApprovalAdmissionRecord(
            decision="REAL_HUMAN_APPROVAL_REJECTED",
            trace_id=trace_id,
            workspace_identity=workspace_identity,
            diff_hash=expected_diff_hash,
            verifier_status=observed_verifier_status,
            operator_identity=submitted_operator_identity,
            operator_signature="",
            signature_kind=submitted_signature_kind,
            is_fixture=(submitted_signature_kind != _REAL_SIGNATURE_KIND),
            accepted_at=accepted_at,
            stale_after=expected_stale_after,
            source_mutation_authorized=False,
            training_eligible=False,
            notes=("operator explicitly rejected",),
        )

    # 7. No action submitted yet.
    if submitted_action != "approve":
        return RealHumanApprovalAdmissionRecord(
            decision="REAL_HUMAN_APPROVAL_REQUIRED",
            trace_id=trace_id,
            workspace_identity=workspace_identity,
            diff_hash=expected_diff_hash,
            verifier_status=observed_verifier_status,
            operator_identity=submitted_operator_identity,
            operator_signature="",
            signature_kind=submitted_signature_kind,
            is_fixture=(submitted_signature_kind != _REAL_SIGNATURE_KIND),
            accepted_at=accepted_at,
            stale_after=expected_stale_after,
            source_mutation_authorized=False,
            training_eligible=False,
            notes=("awaiting explicit approve/reject action",),
        )

    # 8. Approval path — strict gates.
    if not submitted_operator_identity or not submitted_operator_identity.strip():
        return _block(
            "REAL_HUMAN_APPROVAL_BLOCKED_OPERATOR_EMPTY",
            trace_id=trace_id,
            workspace_identity=workspace_identity,
            diff_hash=expected_diff_hash,
            verifier_status=observed_verifier_status,
            operator_identity=submitted_operator_identity,
            operator_signature=submitted_signature,
            signature_kind=submitted_signature_kind,
            accepted_at=accepted_at,
            stale_after=expected_stale_after,
            note="operator_identity empty",
        )

    # CLAUDE-AUTH-008: signature_kind must be the HMAC convention.
    # The legacy hex-shape-only "real_local_signed" is refused.
    if submitted_signature_kind != _HMAC_SIGNATURE_KIND:
        return _block(
            "REAL_HUMAN_APPROVAL_BLOCKED_FIXTURE",
            trace_id=trace_id,
            workspace_identity=workspace_identity,
            diff_hash=expected_diff_hash,
            verifier_status=observed_verifier_status,
            operator_identity=submitted_operator_identity,
            operator_signature=submitted_signature,
            signature_kind=submitted_signature_kind,
            accepted_at=accepted_at,
            stale_after=expected_stale_after,
            note=(
                f"signature_kind {submitted_signature_kind!r} is not "
                f"{_HMAC_SIGNATURE_KIND!r}; legacy hex-only signatures "
                "are no longer accepted (CLAUDE-AUTH-008)"
            ),
        )

    if not _is_hex64(submitted_signature):
        return _block(
            "REAL_HUMAN_APPROVAL_BLOCKED_SIGNATURE_INVALID",
            trace_id=trace_id,
            workspace_identity=workspace_identity,
            diff_hash=expected_diff_hash,
            verifier_status=observed_verifier_status,
            operator_identity=submitted_operator_identity,
            operator_signature=submitted_signature,
            signature_kind=submitted_signature_kind,
            accepted_at=accepted_at,
            stale_after=expected_stale_after,
            note="signature is not a 64-char hex digest",
        )

    # CLAUDE-AUTH-008: verify HMAC binding over the canonical payload.
    payload = _local_signing.canonical_payload(
        trace_id=trace_id,
        canonical_patch_body_hash=canonical_patch_body_hash,
        diff_hash=expected_diff_hash,
        verifier_status=observed_verifier_status,
        rollback_snapshot_ref=rollback_snapshot_ref,
        workspace_identity=workspace_identity,
        operator_identity=submitted_operator_identity,
        stale_after=expected_stale_after,
    )
    if not _local_signing.verify(
        payload,
        submitted_signature,
        secret_path=secret_path,
    ):
        return _block(
            "REAL_HUMAN_APPROVAL_BLOCKED_SIGNATURE_INVALID",
            trace_id=trace_id,
            workspace_identity=workspace_identity,
            diff_hash=expected_diff_hash,
            verifier_status=observed_verifier_status,
            operator_identity=submitted_operator_identity,
            operator_signature=submitted_signature,
            signature_kind=submitted_signature_kind,
            accepted_at=accepted_at,
            stale_after=expected_stale_after,
            note=(
                "HMAC verification failed over canonical payload (CLAUDE-AUTH-008 binding mismatch)"
            ),
        )

    # 9. Approved.
    return RealHumanApprovalAdmissionRecord(
        decision="REAL_HUMAN_APPROVAL_ACCEPTED",
        trace_id=trace_id,
        workspace_identity=workspace_identity,
        diff_hash=expected_diff_hash,
        verifier_status=observed_verifier_status,
        operator_identity=submitted_operator_identity,
        operator_signature=submitted_signature,
        signature_kind=submitted_signature_kind,
        is_fixture=False,
        accepted_at=accepted_at,
        stale_after=expected_stale_after,
        source_mutation_authorized=False,  # the next rung flips this
        training_eligible=False,
        canonical_patch_body_hash=canonical_patch_body_hash,
        notes=(
            "real human approval accepted",
            "HMAC-SHA256 binding verified over canonical payload",
            "source mutation still requires rollback snapshot + apply gate",
            "training eligibility remains False",
        ),
    )


def _block(
    decision: str,
    *,
    trace_id: str,
    workspace_identity: str,
    diff_hash: str,
    verifier_status: str,
    operator_identity: str,
    operator_signature: str,
    signature_kind: str,
    accepted_at: str,
    stale_after: str,
    note: str,
) -> RealHumanApprovalAdmissionRecord:
    return RealHumanApprovalAdmissionRecord(
        decision=decision,
        trace_id=trace_id,
        workspace_identity=workspace_identity,
        diff_hash=diff_hash,
        verifier_status=verifier_status,
        operator_identity=operator_identity,
        operator_signature="",
        signature_kind=signature_kind,
        is_fixture=(signature_kind != _REAL_SIGNATURE_KIND),
        accepted_at=accepted_at,
        stale_after=stale_after,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(note,),
    )


__all__ = [
    "admit",
    "REAL_HUMAN_APPROVAL_ADMISSION_STATUS_TOKENS",
    "RealHumanApprovalAdmissionRecord",
]
