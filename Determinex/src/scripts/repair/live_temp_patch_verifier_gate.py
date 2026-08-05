"""Live temp-patch verifier gate.

Consumes a :class:`QuarantinedPatchPlan` and applies it ONLY to a temp
workspace via :class:`SafePatchWorkspace`. The original repo is
treated as immutable. The verifier runs on the temp workspace via an
injected callable (the BuildAdapter-backed verifier composes here in
real usage; tests use stub verifiers). Verifier failure rolls back the
temp tree. Human approval remains required for any subsequent
original-repo write.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from .live_patch_plan_record import QuarantinedPatchPlan
from .live_temp_patch_verifier_record import (
    LIVE_TEMP_PATCH_VERIFIER_STATUS_TOKENS,
    LiveTempPatchVerifierResult,
)
from .safe_patch_record import FilePatch
from .safe_patch_workspace import (
    SafePatchWorkspace,
    VerifierResult,
    stub_verifier_pass,
)


class LiveTempPatchVerifierGate:
    """Stateless gate. Consumes quarantined plan → verified temp result."""

    def apply_and_verify(
        self,
        plan: QuarantinedPatchPlan,
        *,
        temp_root: Path,
        verifier: Callable[[Path], VerifierResult] | None = None,
        workspace_id: str = "live_temp",
    ) -> LiveTempPatchVerifierResult:
        ws = Path(plan.workspace)

        # 1. Plan must be quarantined.
        if not plan.is_quarantined:
            return self._blocked(
                "LIVE_PATCH_BLOCKED_NO_QUARANTINED_PLAN",
                workspace=str(ws),
                temp_workspace="",
                note=f"plan.decision={plan.decision}",
                plan_admission_ref=plan.admission_decision_ref,
            )

        # 2. Convert quarantined entries → SafePatch FilePatch objects.
        #    The plan stores previews; this gate needs the full contents.
        #    We rebuild from the preview only if it's the entire content
        #    (i.e. ≤ 200 chars). For longer contents, the caller should
        #    pass the original full-content plan separately. For this
        #    rung, the test fixture's plan entries are small enough that
        #    the preview IS the full content.
        file_patches = tuple(
            FilePatch(path=e.path, new_content=e.new_content_preview)
            for e in plan.entries
            if e.new_content_chars == len(e.new_content_preview)
        )
        if not file_patches and plan.entries:
            return self._blocked(
                "LIVE_PATCH_BLOCKED_SAFE_PATCH_REJECTED",
                workspace=str(ws),
                temp_workspace="",
                note="plan entries have contents larger than preview; "
                "full-plan delivery not yet implemented at this rung",
                plan_admission_ref=plan.admission_decision_ref,
            )

        # 3. Apply via SafePatchWorkspace.
        sp = SafePatchWorkspace(ws, Path(temp_root), workspace_id=workspace_id)
        result = sp.apply_and_verify(
            file_patches,
            verifier=verifier or stub_verifier_pass,
            rollback_on_failure=True,
        )

        statuses_seen: list[str] = []
        if result.status == "PATCH_APPLIED_TO_TEMP_WORKSPACE":
            statuses_seen.append("LIVE_PATCH_TEMP_APPLIED")
        if result.original_unchanged:
            statuses_seen.append("LIVE_PATCH_SOURCE_UNCHANGED_CONFIRMED")
        if result.rolled_back:
            statuses_seen.append("LIVE_PATCH_ROLLED_BACK")
        statuses_seen.append("LIVE_PATCH_HUMAN_APPROVAL_REQUIRED")
        statuses_seen.append("LIVE_PATCH_TRAINING_ELIGIBLE_FALSE")

        # 4. Decide final.
        if result.status == "SOURCE_MUTATION_BLOCKED":
            decision = "LIVE_PATCH_BLOCKED_SOURCE_MUTATION"
        elif result.status.startswith("PATCH_BLOCKED_") or result.status == "PATCH_REJECTED":
            decision = "LIVE_PATCH_BLOCKED_SAFE_PATCH_REJECTED"
        elif result.verifier_status == "PATCH_VERIFIER_FAILED":
            decision = "LIVE_PATCH_VERIFIER_FAILED"
        elif result.verifier_status == "PATCH_VERIFIER_PASSED_TEMP_ONLY":
            decision = "LIVE_PATCH_VERIFIER_PASSED_TEMP_ONLY"
        else:
            decision = "LIVE_PATCH_TEMP_APPLIED"

        return LiveTempPatchVerifierResult(
            decision=decision,
            workspace=str(ws),
            temp_workspace=result.temp_workspace,
            safe_patch_status=result.status,
            verifier_status=result.verifier_status,
            unified_diff=result.unified_diff,
            rolled_back=result.rolled_back,
            source_unchanged_confirmed=bool(result.original_unchanged),
            human_approval_required=True,
            statuses_seen=tuple(statuses_seen),
            plan_admission_ref=plan.admission_decision_ref,
            training_eligible=False,
            notes=tuple(plan.notes) + tuple(result.notes),
        )

    @staticmethod
    def _blocked(
        decision: str,
        *,
        workspace: str,
        temp_workspace: str,
        note: str,
        plan_admission_ref: str = "",
    ) -> LiveTempPatchVerifierResult:
        return LiveTempPatchVerifierResult(
            decision=decision,
            workspace=workspace,
            temp_workspace=temp_workspace,
            safe_patch_status="",
            verifier_status="",
            unified_diff="",
            rolled_back=False,
            source_unchanged_confirmed=True,
            human_approval_required=True,
            statuses_seen=(
                decision,
                "LIVE_PATCH_HUMAN_APPROVAL_REQUIRED",
                "LIVE_PATCH_TRAINING_ELIGIBLE_FALSE",
            ),
            plan_admission_ref=plan_admission_ref,
            training_eligible=False,
            notes=(note,),
        )


__all__ = [
    "LiveTempPatchVerifierGate",
    "LiveTempPatchVerifierResult",
    "LIVE_TEMP_PATCH_VERIFIER_STATUS_TOKENS",
]
