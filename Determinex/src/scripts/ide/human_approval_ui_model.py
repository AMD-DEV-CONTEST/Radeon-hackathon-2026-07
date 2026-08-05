"""Human approval packet UI model.

Builds an IDE-displayable HumanApprovalPacket from a verified
temp-patch result. Validates packet consistency.
"""

from __future__ import annotations

import datetime as _dt
import hashlib

from .human_approval_ui_record import (
    HUMAN_APPROVAL_PACKET_UI_STATUS_TOKENS,
    HumanApprovalPacket,
)

_DEFAULT_STALE_HOURS = 24


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def build_packet(
    *,
    trace_id: str,
    workspace_identity: str,
    unified_diff: str,
    files_changed: tuple[str, ...],
    verifier_status: str,
    model_route_ref: str = "",
    patch_plan_ref: str = "",
    temp_patch_ref: str = "",
    risk_summary: str = "",
    operator_identity: str = "",
) -> HumanApprovalPacket:
    now = _dt.datetime.now(_dt.UTC)
    stale_after = now + _dt.timedelta(hours=_DEFAULT_STALE_HOURS)
    diff_hash = _hash(unified_diff)
    # First 200 chars of the diff for the IDE summary.
    diff_summary = unified_diff[:200]

    return HumanApprovalPacket(
        trace_id=trace_id,
        workspace_identity=workspace_identity,
        diff_hash=diff_hash,
        diff_summary=diff_summary,
        files_changed=tuple(files_changed),
        verifier_result=verifier_status,
        model_route_ref=model_route_ref,
        patch_plan_ref=patch_plan_ref,
        temp_patch_ref=temp_patch_ref,
        risk_summary=risk_summary or "temp-only patch verified; source mutation requires approval",
        approval_required=True,
        approval_status="REQUIRED",
        operator_identity=operator_identity,
        operator_signature="",
        timestamp=now.isoformat(),
        stale_after=stale_after.isoformat(),
        decision="HUMAN_APPROVAL_PACKET_WRITTEN",
        notes=("packet is REQUIRED; operator must sign to approve",),
    )


def evaluate_submitted(
    packet: HumanApprovalPacket | None,
    *,
    observed_diff: str,
    observed_verifier_status: str,
    now: _dt.datetime | None = None,
) -> str:
    """Return one of HUMAN_APPROVAL_PACKET_UI_STATUS_TOKENS based on the
    submitted packet.

    This does not apply source mutation; the caller is responsible.
    """
    if packet is None:
        return "HUMAN_APPROVAL_BLOCKED_MISSING_PACKET"
    now = now or _dt.datetime.now(_dt.UTC)
    try:
        stale = _dt.datetime.fromisoformat(packet.stale_after)
    except (ValueError, TypeError):
        return "HUMAN_APPROVAL_BLOCKED_STALE_PACKET"
    if now >= stale:
        return "HUMAN_APPROVAL_BLOCKED_STALE_PACKET"
    if _hash(observed_diff) != packet.diff_hash:
        return "HUMAN_APPROVAL_BLOCKED_DIFF_MISMATCH"
    if observed_verifier_status != "PATCH_VERIFIER_PASSED_TEMP_ONLY":
        return "HUMAN_APPROVAL_BLOCKED_VERIFIER_NOT_PASSED"
    if packet.approval_status not in ("REQUIRED", "ACCEPTED_FIXTURE"):
        return "HUMAN_APPROVAL_REQUIRED"
    return "HUMAN_APPROVAL_REQUIRED"


__all__ = [
    "build_packet",
    "evaluate_submitted",
    "HumanApprovalPacket",
    "HUMAN_APPROVAL_PACKET_UI_STATUS_TOKENS",
]
