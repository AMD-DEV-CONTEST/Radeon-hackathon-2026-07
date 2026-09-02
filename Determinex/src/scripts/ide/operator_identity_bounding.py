"""Operator identity bounding for Claude source-mutation approvals.

CLAUDE_OPERATOR_IDENTITY_BOUNDING_LOCK_001 — rung 2 of the IDE
authority and claims hygiene campaign.

Computes a ``BoundedOperatorIdentity`` from an approval admission
record + a local signing-key-ref, then verifies the bound check.

This module is purely a validator. It does NOT mutate the
admission, does NOT relax the HMAC gate, does NOT issue new
signatures. A free-string-only operator_identity (without a
signing key/ref binding and without a payload hash binding) is
refused.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from .operator_identity_bounding_record import (
    OPERATOR_IDENTITY_BOUNDING_STATUS_TOKENS,
    BoundedOperatorIdentity,
    OperatorIdentityBoundingRecord,
)
from .real_human_approval_admission_record import (
    RealHumanApprovalAdmissionRecord,
)


def signing_key_ref_for(secret_path: Path) -> str:
    """Compute the per-host signing key reference.

    The reference is sha256(absolute path of the secret file).
    Two hosts with different secret paths produce different refs;
    two hosts using the same path-but-different-bytes are still
    distinguished by the HMAC check at the strict admission gate.
    The ref is identity-level metadata, not a substitute for the
    signature.
    """
    sp = Path(secret_path).resolve()
    return hashlib.sha256(str(sp).encode("utf-8")).hexdigest()


def payload_hash_for(
    *,
    trace_id: str,
    canonical_patch_body_hash: str,
    diff_hash: str,
    verifier_status: str,
    rollback_snapshot_ref: str,
    workspace_identity_hash: str,
    operator_identity: str,
    stale_after: str,
) -> str:
    """Hash of the canonical payload fields. Identical to the
    fields the HMAC binds — gives the bound check a payload-level
    binding without requiring access to the secret."""
    lines = [
        "v1",
        f"trace_id={trace_id}",
        f"canonical_patch_body_hash={canonical_patch_body_hash}",
        f"diff_hash={diff_hash}",
        f"verifier_status={verifier_status}",
        f"rollback_snapshot_ref={rollback_snapshot_ref}",
        f"workspace_identity_hash={workspace_identity_hash}",
        f"operator_identity={operator_identity}",
        f"stale_after={stale_after}",
    ]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def bound_from_admission(
    admission: RealHumanApprovalAdmissionRecord,
    *,
    display_name: str,
    signing_key_ref: str,
) -> BoundedOperatorIdentity:
    """Construct a BoundedOperatorIdentity from a strict admission
    record. The caller supplies a display_name (UI-only) and the
    per-host signing key ref."""
    ws_hash = hashlib.sha256(
        (admission.workspace_identity or "").encode("utf-8", errors="replace")
    ).hexdigest()
    payload_hash = payload_hash_for(
        trace_id=admission.trace_id,
        canonical_patch_body_hash=admission.canonical_patch_body_hash,
        diff_hash=admission.diff_hash,
        verifier_status=admission.verifier_status,
        rollback_snapshot_ref="",  # apply-time field; not in admission record
        workspace_identity_hash=ws_hash,
        operator_identity=admission.operator_identity,
        stale_after=admission.stale_after,
    )
    return BoundedOperatorIdentity(
        operator_id=admission.operator_identity,
        display_name=display_name,
        signing_key_ref=signing_key_ref,
        timestamp=admission.accepted_at,
        workspace_identity_hash=ws_hash,
        approval_payload_hash=payload_hash,
    )


def check(
    *,
    admission: RealHumanApprovalAdmissionRecord | None,
    bound: BoundedOperatorIdentity | None,
) -> OperatorIdentityBoundingRecord:
    """Verify the bounded identity matches the admission.

    Returns OPERATOR_IDENTITY_BOUNDING_PASSED iff:
      - admission is accepted, not fixture, signature_kind real_local_hmac
      - bound is well-formed
      - bound.operator_id == admission.operator_identity
      - bound.workspace_identity_hash matches sha256(admission.workspace_identity)
      - bound.approval_payload_hash matches the recomputed payload hash
    """
    if admission is None or not admission.is_accepted:
        return _block(
            "OPERATOR_IDENTITY_BLOCKED_MALFORMED_IDENTITY",
            admission=admission,
            bound=bound,
            note="admission missing or not accepted",
        )

    if getattr(admission, "is_fixture", False):
        return _block(
            "OPERATOR_IDENTITY_BLOCKED_MALFORMED_IDENTITY",
            admission=admission,
            bound=bound,
            note="fixture admissions cannot be bound to a real operator identity",
        )

    if admission.signature_kind != "real_local_hmac":
        return _block(
            "OPERATOR_IDENTITY_BLOCKED_MISSING_SIGNING_REF",
            admission=admission,
            bound=bound,
            note=(
                f"admission.signature_kind={admission.signature_kind!r}; "
                "operator identity binding requires real_local_hmac"
            ),
        )

    if bound is None:
        return _block(
            "OPERATOR_IDENTITY_BLOCKED_FREE_STRING_ONLY",
            admission=admission,
            bound=bound,
            note=(
                "no BoundedOperatorIdentity supplied; admission has "
                f"free-string operator_identity={admission.operator_identity!r}"
            ),
        )

    if not bound.is_well_formed:
        return _block(
            "OPERATOR_IDENTITY_BLOCKED_MALFORMED_IDENTITY",
            admission=admission,
            bound=bound,
            note="BoundedOperatorIdentity is not well-formed",
        )

    if not bound.signing_key_ref:
        return _block(
            "OPERATOR_IDENTITY_BLOCKED_MISSING_SIGNING_REF",
            admission=admission,
            bound=bound,
            note="bound.signing_key_ref is empty",
        )

    if bound.operator_id != admission.operator_identity:
        return _block(
            "OPERATOR_IDENTITY_BLOCKED_PAYLOAD_MISMATCH",
            admission=admission,
            bound=bound,
            note=(
                f"bound.operator_id={bound.operator_id!r} != "
                f"admission.operator_identity={admission.operator_identity!r}"
            ),
        )

    expected_ws_hash = hashlib.sha256(
        (admission.workspace_identity or "").encode("utf-8", errors="replace")
    ).hexdigest()
    if bound.workspace_identity_hash != expected_ws_hash:
        return _block(
            "OPERATOR_IDENTITY_BLOCKED_WORKSPACE_MISMATCH",
            admission=admission,
            bound=bound,
            note="bound.workspace_identity_hash does not match admission.workspace_identity",
        )

    expected_payload_hash = payload_hash_for(
        trace_id=admission.trace_id,
        canonical_patch_body_hash=admission.canonical_patch_body_hash,
        diff_hash=admission.diff_hash,
        verifier_status=admission.verifier_status,
        rollback_snapshot_ref="",
        workspace_identity_hash=expected_ws_hash,
        operator_identity=admission.operator_identity,
        stale_after=admission.stale_after,
    )
    if bound.approval_payload_hash != expected_payload_hash:
        return _block(
            "OPERATOR_IDENTITY_BLOCKED_PAYLOAD_MISMATCH",
            admission=admission,
            bound=bound,
            note="bound.approval_payload_hash != recomputed canonical payload hash",
        )

    return OperatorIdentityBoundingRecord(
        decision="OPERATOR_IDENTITY_BOUNDING_PASSED",
        operator_id=bound.operator_id,
        workspace_identity_hash=bound.workspace_identity_hash,
        approval_payload_hash=bound.approval_payload_hash,
        signing_key_ref=bound.signing_key_ref,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(
            "operator identity bound to admission via canonical payload hash",
            "signing key ref recorded but does not replace HMAC verification",
            "does not authorize source mutation; downstream gate decides",
        ),
    )


def _block(
    decision: str,
    *,
    admission: RealHumanApprovalAdmissionRecord | None,
    bound: BoundedOperatorIdentity | None,
    note: str,
) -> OperatorIdentityBoundingRecord:
    return OperatorIdentityBoundingRecord(
        decision=decision,
        operator_id=getattr(bound, "operator_id", "")
        if bound
        else (getattr(admission, "operator_identity", "") if admission else ""),
        workspace_identity_hash=getattr(bound, "workspace_identity_hash", "") if bound else "",
        approval_payload_hash=getattr(bound, "approval_payload_hash", "") if bound else "",
        signing_key_ref=getattr(bound, "signing_key_ref", "") if bound else "",
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(note,),
    )


__all__ = [
    "signing_key_ref_for",
    "payload_hash_for",
    "bound_from_admission",
    "check",
    "OPERATOR_IDENTITY_BOUNDING_STATUS_TOKENS",
    "OperatorIdentityBoundingRecord",
    "BoundedOperatorIdentity",
]
