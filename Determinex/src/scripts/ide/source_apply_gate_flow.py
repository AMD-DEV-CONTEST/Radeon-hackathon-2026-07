"""IDE source apply gate flow.

Pure decision surface. Consumes a signing record + observed source
state. Returns whether source application is blocked, dry-run-ready, or
fixture-only. NEVER mutates the original repo.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from repair.source_mutation_apply_dry_run import (  # noqa: E402
    SourceMutationApplyDryRun,
    workspace_hash,
)

from .human_approval_signing_record import IDEHumanApprovalSigningRecord
from .human_approval_ui_record import HumanApprovalPacket
from .source_apply_gate_record import (
    IDE_SOURCE_APPLY_GATE_STATUS_TOKENS,
    IDESourceApplyGateRecord,
)


class IDESourceApplyGateFlow:
    """Stateless gate decision."""

    def evaluate(
        self,
        workspace: Path,
        *,
        signing: IDEHumanApprovalSigningRecord | None,
        packet: HumanApprovalPacket | None,
        observed_diff: str,
        observed_source_hash_at_packet_time: str,
        verifier_status: str,
    ) -> IDESourceApplyGateRecord:
        ws = Path(workspace).resolve()

        # 1. Signing must be present.
        if signing is None or packet is None:
            return self._blocked(
                ws, "IDE_SOURCE_APPLY_BLOCKED_NO_APPROVAL", "signing or packet missing"
            )

        # 2. Signing must have produced a signature (FIXTURE_ONLY or PACKET_READY).
        if signing.decision in ("IDE_APPROVAL_REJECTED",) or not signing.operator_signature:
            return self._blocked(
                ws, "IDE_SOURCE_APPLY_BLOCKED_NOT_SIGNED", f"signing decision={signing.decision}"
            )

        # 3. Compose the dry-run check.
        dry = SourceMutationApplyDryRun().run(
            ws,
            approval=packet,
            observed_diff=observed_diff,
            observed_source_hash_at_packet_time=observed_source_hash_at_packet_time,
            verifier_status=verifier_status,
        )

        mapping = {
            "SOURCE_APPLY_DRY_RUN_READY": "IDE_SOURCE_APPLY_DRY_RUN_READY",
            "SOURCE_APPLY_DRY_RUN_BLOCKED_NO_APPROVAL": "IDE_SOURCE_APPLY_BLOCKED_NO_APPROVAL",
            "SOURCE_APPLY_DRY_RUN_BLOCKED_STALE_SOURCE": "IDE_SOURCE_APPLY_BLOCKED_STALE_SOURCE",
            "SOURCE_APPLY_DRY_RUN_BLOCKED_DIFF_MISMATCH": "IDE_SOURCE_APPLY_BLOCKED_DIFF_MISMATCH",
            "SOURCE_APPLY_DRY_RUN_BLOCKED_VERIFIER_NOT_PASSED": "IDE_SOURCE_APPLY_BLOCKED_VERIFIER_NOT_PASSED",
        }
        decision = mapping.get(dry.decision, "IDE_SOURCE_APPLY_BLOCKED_NO_APPROVAL")

        # If signing was FIXTURE_ONLY and the dry-run is otherwise READY,
        # surface FIXTURE_ONLY so the IDE knows real source mutation is
        # still gated.
        statuses = [decision, "IDE_SOURCE_APPLY_SOURCE_UNCHANGED"]
        if decision == "IDE_SOURCE_APPLY_DRY_RUN_READY" and signing.fixture_only:
            statuses.append("IDE_SOURCE_APPLY_FIXTURE_ONLY")

        return IDESourceApplyGateRecord(
            decision=decision,
            workspace=str(ws),
            files_would_change=tuple(dry.files_would_change),
            source_unchanged=True,
            fixture_only=signing.fixture_only,
            source_mutation_authorized=False,
            training_eligible=False,
            statuses_seen=tuple(statuses),
            notes=tuple(dry.notes),
        )

    @staticmethod
    def _blocked(
        ws: Path,
        decision: str,
        note: str,
    ) -> IDESourceApplyGateRecord:
        return IDESourceApplyGateRecord(
            decision=decision,
            workspace=str(ws),
            files_would_change=(),
            source_unchanged=True,
            fixture_only=True,
            source_mutation_authorized=False,
            training_eligible=False,
            statuses_seen=(decision, "IDE_SOURCE_APPLY_SOURCE_UNCHANGED"),
            notes=(note,),
        )


__all__ = [
    "IDESourceApplyGateFlow",
    "IDESourceApplyGateRecord",
    "IDE_SOURCE_APPLY_GATE_STATUS_TOKENS",
    "workspace_hash",
]
