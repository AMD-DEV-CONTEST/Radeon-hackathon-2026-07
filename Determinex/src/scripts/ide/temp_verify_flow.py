"""IDE temp verify flow.

Wraps TempPatchVerifyCommand. Applies to temp only. Source unchanged.
Human approval still required.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from repair.live_patch_plan_record import QuarantinedPatchPlan  # noqa: E402
from repair.safe_patch_workspace import VerifierResult, stub_verifier_pass  # noqa: E402
from repair.temp_patch_verify_command import TempPatchVerifyCommand  # noqa: E402

from .temp_verify_flow_record import (
    IDE_TEMP_VERIFY_FLOW_STATUS_TOKENS,
    IDETempVerifyFlowRecord,
)


class IDETempVerifyFlow:
    """Stateless flow."""

    def run(
        self,
        plan: QuarantinedPatchPlan,
        *,
        temp_root: Path,
        verifier: Callable[[Path], VerifierResult] | None = None,
        workspace_id: str = "ide_tv",
    ) -> IDETempVerifyFlowRecord:
        cmd_rec = TempPatchVerifyCommand().run(
            plan,
            temp_root=Path(temp_root),
            verifier=verifier or stub_verifier_pass,
            workspace_id=workspace_id,
        )

        mapping = {
            "TEMP_PATCH_VERIFY_PASSED_TEMP_ONLY": "IDE_TEMP_VERIFY_PASSED_TEMP_ONLY",
            "TEMP_PATCH_VERIFY_FAILED": "IDE_TEMP_VERIFY_FAILED",
            "TEMP_PATCH_VERIFY_BLOCKED_NO_PLAN": "IDE_TEMP_VERIFY_BLOCKED_NO_PLAN",
            "TEMP_PATCH_VERIFY_BLOCKED_PATH_ESCAPE": "IDE_TEMP_VERIFY_FAILED",
        }
        ide_decision = mapping.get(cmd_rec.decision, "IDE_TEMP_VERIFY_FAILED")
        statuses = [
            "IDE_TEMP_VERIFY_RUNNING",
            ide_decision,
            "IDE_TEMP_VERIFY_SOURCE_UNCHANGED"
            if cmd_rec.source_unchanged_confirmed
            else "IDE_TEMP_VERIFY_FAILED",
            "IDE_TEMP_VERIFY_HUMAN_APPROVAL_REQUIRED",
        ]
        return IDETempVerifyFlowRecord(
            decision=ide_decision,
            workspace=cmd_rec.workspace,
            temp_workspace=cmd_rec.temp_workspace,
            verifier_status=cmd_rec.verifier_status,
            unified_diff=cmd_rec.unified_diff,
            source_unchanged=bool(cmd_rec.source_unchanged_confirmed),
            human_approval_required=True,
            training_eligible=False,
            statuses_seen=tuple(statuses),
            notes=tuple(cmd_rec.notes),
        )


__all__ = [
    "IDETempVerifyFlow",
    "IDETempVerifyFlowRecord",
    "IDE_TEMP_VERIFY_FLOW_STATUS_TOKENS",
]
