"""Human approval gate for source mutation.

This gate is the *only* place the apparatus says "yes, this verified
temp-workspace patch may be applied to the original repo." It does NOT
perform the apply itself — the IDE/CLI layer downstream consumes a
``SOURCE_MUTATION_APPROVAL_ACCEPTED_FIXTURE`` decision and is responsible
for the actual write (under its own audited path).

Rule: source mutation remains blocked by default. To open the gate, the
caller must supply an :class:`ApprovalPacket` that:

  1. References the exact trace_id of a previously-emitted
     :class:`VerifiedRepairTrace`.
  2. Carries the sha256 of the temp-workspace unified diff that matches
     the trace's safe_patch_result.unified_diff.
  3. Matches the trace's workspace identity bit-for-bit.
  4. Reports the verifier as having passed on the temp workspace
     (``PATCH_VERIFIER_PASSED_TEMP_ONLY``).
  5. Carries a non-empty operator id and an approval_token.

Anything missing → blocked, with a specific status token explaining
which check failed.

The gate is a pure function. It performs no I/O. It does not write to
the original repo.
"""

from __future__ import annotations

from collections.abc import Mapping

from .human_approval_record import (
    HUMAN_APPROVAL_STATUS_TOKENS,
    ApprovalGateDecision,
    ApprovalPacket,
    diff_hash,
)
from .verified_repair_trace_record import VerifiedRepairTrace


class HumanApprovalGate:
    """Stateless approval-decision surface."""

    def evaluate(
        self,
        packet: ApprovalPacket,
        trace: VerifiedRepairTrace,
    ) -> ApprovalGateDecision:
        # 0. Trivial requirement — empty packet → REQUIRED.
        if not packet.operator or not packet.operator.strip():
            return self._blocked(
                packet,
                trace,
                "SOURCE_MUTATION_BLOCKED_OPERATOR_EMPTY",
                "approval_packet.operator is empty",
            )
        if not packet.approval_token or not packet.approval_token.strip():
            return self._blocked(
                packet,
                trace,
                "SOURCE_MUTATION_BLOCKED_MISSING_APPROVAL",
                "approval_packet.approval_token is empty",
            )

        # 1. trace_id must match.
        if packet.trace_id != trace.trace_id:
            return self._blocked(
                packet,
                trace,
                "SOURCE_MUTATION_BLOCKED_TRACE_ID_MISMATCH",
                f"packet.trace_id={packet.trace_id!r} != trace.trace_id={trace.trace_id!r}",
            )

        # 2. workspace identity must match.
        if packet.workspace_identity != trace.workspace:
            return self._blocked(
                packet,
                trace,
                "SOURCE_MUTATION_BLOCKED_REPO_MISMATCH",
                "packet.workspace_identity != trace.workspace",
            )

        # 3. diff sha256 must match the trace's recorded diff.
        spr = trace.safe_patch_result or {}
        observed_diff = str(spr.get("unified_diff") or "")
        observed_hash = diff_hash(observed_diff) if observed_diff else ""
        if not observed_hash:
            return self._blocked(
                packet,
                trace,
                "SOURCE_MUTATION_BLOCKED_DIFF_MISMATCH",
                "trace.safe_patch_result has no unified_diff to compare against",
            )
        if packet.diff_sha256 != observed_hash:
            return self._blocked(
                packet,
                trace,
                "SOURCE_MUTATION_BLOCKED_DIFF_MISMATCH",
                f"packet.diff_sha256={packet.diff_sha256[:12]}... != observed={observed_hash[:12]}...",
            )

        # 4. Verifier must have passed on the temp workspace.
        observed_verifier = str(spr.get("verifier_status") or "")
        if observed_verifier != "PATCH_VERIFIER_PASSED_TEMP_ONLY":
            return self._blocked(
                packet,
                trace,
                "SOURCE_MUTATION_BLOCKED_VERIFIER_NOT_PASSED",
                f"trace.safe_patch_result.verifier_status={observed_verifier!r}",
            )

        # 5. Trace must declare final_status TRACE_VERIFIER_PASSED_TEMP_ONLY
        #    — anything else is a stale or wrong trace.
        if trace.final_status != "TRACE_VERIFIER_PASSED_TEMP_ONLY":
            return self._blocked(
                packet,
                trace,
                "SOURCE_MUTATION_BLOCKED_STALE_TRACE",
                f"trace.final_status={trace.final_status!r}",
            )

        # 6. Trace's source-preservation must have been confirmed at trace time.
        if trace.source_unchanged_confirmed is not True:
            return self._blocked(
                packet,
                trace,
                "SOURCE_MUTATION_BLOCKED_STALE_TRACE",
                "trace.source_unchanged_confirmed != True",
            )

        # All checks passed → accept (fixture-only at this rung).
        return ApprovalGateDecision(
            decision="SOURCE_MUTATION_APPROVAL_ACCEPTED_FIXTURE",
            reason="all checks passed (fixture mode)",
            trace_id=packet.trace_id,
            workspace_identity=packet.workspace_identity,
            diff_sha256=packet.diff_sha256,
            verifier_status=observed_verifier,
            operator=packet.operator,
            fixture=packet.fixture,
            source_mutation_authorized=True,
            notes=(
                "fixture acceptance — IDE/CLI consumer is still responsible "
                "for the actual write under its own audited path",
            ),
        )

    @staticmethod
    def required(trace: VerifiedRepairTrace) -> ApprovalGateDecision:
        """Convenience: emit the "required" status for a UI to render."""
        return ApprovalGateDecision(
            decision="SOURCE_MUTATION_APPROVAL_REQUIRED",
            reason="trace ready for review; awaiting approval packet",
            trace_id=trace.trace_id,
            workspace_identity=trace.workspace,
            diff_sha256=diff_hash(str((trace.safe_patch_result or {}).get("unified_diff") or "")),
            verifier_status=str((trace.safe_patch_result or {}).get("verifier_status") or ""),
            operator="",
            fixture=True,
            source_mutation_authorized=False,
        )

    @staticmethod
    def _blocked(
        packet: ApprovalPacket,
        trace: VerifiedRepairTrace,
        decision: str,
        reason: str,
    ) -> ApprovalGateDecision:
        spr: Mapping[str, object] = trace.safe_patch_result or {}
        return ApprovalGateDecision(
            decision=decision,
            reason=reason,
            trace_id=packet.trace_id,
            workspace_identity=packet.workspace_identity,
            diff_sha256=packet.diff_sha256,
            verifier_status=str(spr.get("verifier_status") or ""),
            operator=packet.operator,
            fixture=packet.fixture,
            source_mutation_authorized=False,
            notes=(reason,),
        )


__all__ = [
    "HumanApprovalGate",
    "ApprovalPacket",
    "ApprovalGateDecision",
    "HUMAN_APPROVAL_STATUS_TOKENS",
    "diff_hash",
]
