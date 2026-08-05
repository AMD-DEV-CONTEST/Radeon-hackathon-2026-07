"""Temp patch verify command.

Applies a quarantined patch plan ONLY to a temp workspace via
LiveTempPatchVerifierGate. Runs the verifier. Source remains immutable.
Human approval still required.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .live_patch_plan_record import QuarantinedPatchPlan
from .live_temp_patch_verifier_gate import LiveTempPatchVerifierGate
from .safe_patch_workspace import VerifierResult, stub_verifier_pass
from .temp_patch_verify_record import (
    TEMP_PATCH_VERIFY_STATUS_TOKENS,
    TempPatchVerifyRecord,
)


class TempPatchVerifyCommand:
    """Stateless command."""

    def run(
        self,
        plan: QuarantinedPatchPlan,
        *,
        temp_root: Path,
        verifier: Callable[[Path], VerifierResult] | None = None,
        workspace_id: str = "tpv",
    ) -> TempPatchVerifyRecord:
        if not plan.is_quarantined:
            return TempPatchVerifyRecord(
                decision="TEMP_PATCH_VERIFY_BLOCKED_NO_PLAN",
                workspace=plan.workspace,
                temp_workspace="",
                verifier_status="",
                unified_diff="",
                source_unchanged_confirmed=True,
                human_approval_required=True,
                training_eligible=False,
                statuses_seen=(
                    "TEMP_PATCH_VERIFY_BLOCKED_NO_PLAN",
                    "TEMP_PATCH_VERIFY_HUMAN_APPROVAL_REQUIRED",
                ),
                notes=(f"plan.decision={plan.decision}",),
            )

        gate = LiveTempPatchVerifierGate()
        result = gate.apply_and_verify(
            plan,
            temp_root=Path(temp_root),
            verifier=verifier or stub_verifier_pass,
            workspace_id=workspace_id,
        )

        if result.decision == "LIVE_PATCH_VERIFIER_PASSED_TEMP_ONLY":
            decision = "TEMP_PATCH_VERIFY_PASSED_TEMP_ONLY"
        elif result.decision == "LIVE_PATCH_VERIFIER_FAILED":
            decision = "TEMP_PATCH_VERIFY_FAILED"
        elif result.decision == "LIVE_PATCH_BLOCKED_SOURCE_MUTATION":
            decision = "TEMP_PATCH_VERIFY_BLOCKED_PATH_ESCAPE"
        else:
            decision = "TEMP_PATCH_VERIFY_FAILED"

        statuses = [
            decision,
            "TEMP_PATCH_VERIFY_SOURCE_UNCHANGED"
            if result.source_unchanged_confirmed
            else "TEMP_PATCH_VERIFY_FAILED",
            "TEMP_PATCH_VERIFY_HUMAN_APPROVAL_REQUIRED",
        ]
        return TempPatchVerifyRecord(
            decision=decision,
            workspace=plan.workspace,
            temp_workspace=result.temp_workspace,
            verifier_status=result.verifier_status,
            unified_diff=result.unified_diff,
            source_unchanged_confirmed=bool(result.source_unchanged_confirmed),
            human_approval_required=True,
            training_eligible=False,
            statuses_seen=tuple(statuses),
            notes=tuple(result.notes),
        )


__all__ = ["TempPatchVerifyCommand", "TempPatchVerifyRecord", "TEMP_PATCH_VERIFY_STATUS_TOKENS"]
