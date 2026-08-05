"""IDE human approval signing flow.

Displays the approval packet, accepts explicit approve/reject action,
validates stale/diff/verifier state. Source mutation NOT authorized
even when accepted — that's the next rung.
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

from .human_approval_signing_record import (
    IDE_HUMAN_APPROVAL_SIGNING_STATUS_TOKENS,
    ApprovalAction,
    IDEHumanApprovalSigningRecord,
)
from .human_approval_ui_record import HumanApprovalPacket


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class IDEHumanApprovalSigningFlow:
    """Stateless flow. Accepts approve/reject actions and validates the packet."""

    def submit(
        self,
        packet: HumanApprovalPacket,
        *,
        action: str,
        operator_identity: str,
        observed_diff: str,
        observed_verifier_status: str,
        fixture: bool = True,
        now: _dt.datetime | None = None,
    ) -> IDEHumanApprovalSigningRecord:
        now = now or _dt.datetime.now(_dt.UTC)

        if not operator_identity or not operator_identity.strip():
            return self._refuse(
                packet,
                action,
                "",
                "IDE_APPROVAL_BLOCKED_OPERATOR_EMPTY",
                "operator_identity empty",
                now,
            )

        # Stale check.
        try:
            stale = _dt.datetime.fromisoformat(packet.stale_after)
        except (ValueError, TypeError):
            return self._refuse(
                packet,
                action,
                operator_identity,
                "IDE_APPROVAL_BLOCKED_STALE_PACKET",
                "stale_after unparseable",
                now,
            )
        if now >= stale:
            return self._refuse(
                packet,
                action,
                operator_identity,
                "IDE_APPROVAL_BLOCKED_STALE_PACKET",
                "packet stale",
                now,
            )

        # Diff hash check.
        if _hash(observed_diff) != packet.diff_hash:
            return self._refuse(
                packet,
                action,
                operator_identity,
                "IDE_APPROVAL_BLOCKED_DIFF_MISMATCH",
                "diff hash mismatch",
                now,
            )

        # Verifier check.
        if observed_verifier_status != "PATCH_VERIFIER_PASSED_TEMP_ONLY":
            return self._refuse(
                packet,
                action,
                operator_identity,
                "IDE_APPROVAL_BLOCKED_VERIFIER_NOT_PASSED",
                f"verifier status={observed_verifier_status!r}",
                now,
            )

        # Rejection path.
        if action == ApprovalAction.REJECT.value:
            return IDEHumanApprovalSigningRecord(
                decision="IDE_APPROVAL_REJECTED",
                action=action,
                operator_identity=operator_identity,
                operator_signature="",
                trace_id=packet.trace_id,
                workspace_identity=packet.workspace_identity,
                diff_hash=packet.diff_hash,
                verifier_status=observed_verifier_status,
                timestamp=now.isoformat(),
                fixture_only=fixture,
                source_mutation_authorized=False,
                training_eligible=False,
                statuses_seen=("IDE_APPROVAL_REJECTED",),
                notes=("operator rejected",),
            )

        # Approve path — fixture only at this rung.
        if action == ApprovalAction.APPROVE.value:
            sig = _hash(f"{operator_identity}|{packet.diff_hash}|{packet.trace_id}")
            statuses_seen = ["IDE_APPROVAL_PACKET_READY"]
            if fixture:
                statuses_seen.append("IDE_APPROVAL_FIXTURE_ONLY")
            return IDEHumanApprovalSigningRecord(
                decision="IDE_APPROVAL_FIXTURE_ONLY" if fixture else "IDE_APPROVAL_PACKET_READY",
                action=action,
                operator_identity=operator_identity,
                operator_signature=sig,
                trace_id=packet.trace_id,
                workspace_identity=packet.workspace_identity,
                diff_hash=packet.diff_hash,
                verifier_status=observed_verifier_status,
                timestamp=now.isoformat(),
                fixture_only=fixture,
                source_mutation_authorized=False,  # source mutation is the NEXT rung's call
                training_eligible=False,
                statuses_seen=tuple(statuses_seen),
                notes=("fixture-only approval; source mutation gate is separate",)
                if fixture
                else ("approval recorded; source mutation gate is separate",),
            )

        # Default: REQUIRED.
        return IDEHumanApprovalSigningRecord(
            decision="IDE_APPROVAL_REQUIRED",
            action=action,
            operator_identity=operator_identity,
            operator_signature="",
            trace_id=packet.trace_id,
            workspace_identity=packet.workspace_identity,
            diff_hash=packet.diff_hash,
            verifier_status=observed_verifier_status,
            timestamp=now.isoformat(),
            fixture_only=fixture,
            source_mutation_authorized=False,
            training_eligible=False,
            statuses_seen=("IDE_APPROVAL_REQUIRED",),
            notes=("awaiting operator approve/reject",),
        )

    @staticmethod
    def _refuse(
        packet: HumanApprovalPacket,
        action: str,
        operator_identity: str,
        decision: str,
        reason: str,
        now: _dt.datetime,
    ) -> IDEHumanApprovalSigningRecord:
        return IDEHumanApprovalSigningRecord(
            decision=decision,
            action=action,
            operator_identity=operator_identity,
            operator_signature="",
            trace_id=packet.trace_id,
            workspace_identity=packet.workspace_identity,
            diff_hash=packet.diff_hash,
            verifier_status="",
            timestamp=now.isoformat(),
            fixture_only=True,
            source_mutation_authorized=False,
            training_eligible=False,
            statuses_seen=(decision,),
            notes=(reason,),
        )


__all__ = [
    "IDEHumanApprovalSigningFlow",
    "IDEHumanApprovalSigningRecord",
    "ApprovalAction",
    "IDE_HUMAN_APPROVAL_SIGNING_STATUS_TOKENS",
]
