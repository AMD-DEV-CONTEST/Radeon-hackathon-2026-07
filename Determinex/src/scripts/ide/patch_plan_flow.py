"""IDE patch plan flow.

Wraps OptInPatchPlanCommand. Returns IDEPatchPlanFlowRecord with
source_unchanged=True. Plan is quarantined, never applied.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from models.local_model_config_record import LocalModelConfigRecord  # noqa: E402
from repair.opt_in_patch_plan_command import OptInPatchPlanCommand  # noqa: E402

from .patch_plan_flow_record import (
    IDE_PATCH_PLAN_FLOW_STATUS_TOKENS,
    IDEPatchPlanFlowRecord,
)


class IDEPatchPlanFlow:
    """Stateless flow."""

    def run(
        self,
        workspace: Path,
        *,
        plan_entries: Sequence[dict[str, object]],
        config: LocalModelConfigRecord | None = None,
        opt_in: bool = False,
    ) -> IDEPatchPlanFlowRecord:
        ws = Path(workspace).resolve()
        cmd_rec = OptInPatchPlanCommand().run(
            ws,
            config=config,
            plan_entries=plan_entries,
            opt_in=opt_in,
        )

        mapping = {
            "OPT_IN_PATCH_PLAN_BLOCKED_NO_MODEL": "IDE_PATCH_PLAN_BLOCKED_NO_MODEL",
            "OPT_IN_PATCH_PLAN_BLOCKED_NOT_OPTED_IN": "IDE_PATCH_PLAN_BLOCKED_NOT_OPTED_IN",
            "OPT_IN_PATCH_PLAN_BLOCKED_SCHEMA_INVALID": "IDE_PATCH_PLAN_BLOCKED_SCHEMA_INVALID",
            "OPT_IN_PATCH_PLAN_BLOCKED_PATH_ESCAPE": "IDE_PATCH_PLAN_BLOCKED_PATH_ESCAPE",
            "OPT_IN_PATCH_PLAN_BLOCKED_PROVIDER_UNAVAILABLE": "IDE_PATCH_PLAN_BLOCKED_NO_MODEL",
            "OPT_IN_PATCH_PLAN_QUARANTINED": "IDE_PATCH_PLAN_QUARANTINED",
        }
        ide_decision = mapping.get(cmd_rec.decision, "IDE_PATCH_PLAN_BLOCKED_SCHEMA_INVALID")
        statuses = [ide_decision, "IDE_PATCH_PLAN_SOURCE_UNCHANGED"]

        return IDEPatchPlanFlowRecord(
            decision=ide_decision,
            workspace=str(ws),
            entries_quarantined=cmd_rec.entries_quarantined,
            plan_decision=cmd_rec.plan_decision,
            trusted=False,
            applied_to_source=False,
            source_mutation_authorized=False,
            training_eligible=False,
            statuses_seen=tuple(statuses),
            evidence_refs=(cmd_rec.config_path,) if cmd_rec.config_path else (),
            notes=tuple(cmd_rec.notes),
        )


__all__ = [
    "IDEPatchPlanFlow",
    "IDEPatchPlanFlowRecord",
    "IDE_PATCH_PLAN_FLOW_STATUS_TOKENS",
]
