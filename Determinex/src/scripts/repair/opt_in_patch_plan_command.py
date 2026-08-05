"""Opt-in patch-plan command.

Takes a list of model-produced patch entries and quarantines them via
LivePatchPlanQuarantine. Does NOT apply the patch. Requires opt_in=True.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from models.live_model_admission import (  # noqa: E402
    LiveAdmissionMode,
    LiveModelAdmissionConfig,
    LiveModelAdmissionGate,
)
from models.local_model_admission_policy import (  # noqa: E402
    LocalModelCandidate,
    ModelProvider,
)
from models.local_model_config_record import LocalModelConfigRecord  # noqa: E402
from models.model_inventory import LocalModelInventory  # noqa: E402
from models.model_router import (  # noqa: E402
    CURRENT_MODEL_IDS,
    ModelRouter,
    RouterMode,
    TaskClass,
)

from .live_patch_plan_quarantine import LivePatchPlanQuarantine
from .opt_in_patch_plan_record import (
    OPT_IN_PATCH_PLAN_STATUS_TOKENS,
    OptInPatchPlanRecord,
)


class OptInPatchPlanCommand:
    """Stateless command."""

    def run(
        self,
        workspace: Path,
        *,
        config: LocalModelConfigRecord | None,
        plan_entries: Sequence[dict[str, object]],
        opt_in: bool = False,
    ) -> OptInPatchPlanRecord:
        ws = Path(workspace).resolve()

        if config is None or not (
            config.is_written or config.decision == "LOCAL_MODEL_CONFIG_DRY_RUN_ONLY"
        ):
            return self._blocked(ws, config, "OPT_IN_PATCH_PLAN_BLOCKED_NO_MODEL", "config missing")

        if not opt_in:
            return self._blocked(
                ws, config, "OPT_IN_PATCH_PLAN_BLOCKED_NOT_OPTED_IN", "opt_in=False"
            )

        # Build admission via live gate.
        inv = LocalModelInventory.of(sorted(CURRENT_MODEL_IDS))
        gate = LiveModelAdmissionGate(
            config=LiveModelAdmissionConfig(
                mode=LiveAdmissionMode.OPT_IN_LIVE,
                opt_in_live=True,
            )
        )
        candidate = LocalModelCandidate(
            model_id=config.model_id,
            provider=config.provider or ModelProvider.OLLAMA.value,
            capability_tags=tuple(config.capabilities) or ("code_generation",),
            supported_task_classes=(TaskClass.PATCH_GENERATION.value,),
        )
        route = ModelRouter(inventory=inv).route(TaskClass.PATCH_GENERATION, mode=RouterMode.LIVE)
        admission = gate.evaluate(candidate, TaskClass.PATCH_GENERATION, inv, route)
        if not admission.is_ready:
            return self._blocked(
                ws,
                config,
                "OPT_IN_PATCH_PLAN_BLOCKED_PROVIDER_UNAVAILABLE",
                f"admission not ready: {admission.decision}",
            )

        # Quarantine.
        q = LivePatchPlanQuarantine()
        plan = q.quarantine(
            plan_entries,
            admission=admission,
            workspace=ws,
            provider_name=config.provider,
            model_id=config.model_id,
        )
        if plan.decision == "PATCH_PLAN_BLOCKED_PATH_ESCAPE":
            cmd_dec = "OPT_IN_PATCH_PLAN_BLOCKED_PATH_ESCAPE"
        elif plan.is_blocked:
            cmd_dec = "OPT_IN_PATCH_PLAN_BLOCKED_SCHEMA_INVALID"
        else:
            cmd_dec = "OPT_IN_PATCH_PLAN_QUARANTINED"

        return OptInPatchPlanRecord(
            decision=cmd_dec,
            workspace=str(ws),
            config_path=config.config_path,
            provider=config.provider,
            model_id=config.model_id,
            plan_decision=plan.decision,
            entries_quarantined=len(plan.entries),
            trusted=False,
            applied_to_source=False,
            source_mutation_authorized=False,
            training_eligible=False,
            statuses_seen=(cmd_dec,),
            notes=tuple(plan.notes),
        )

    @staticmethod
    def _blocked(
        ws: Path, config: LocalModelConfigRecord | None, decision: str, note: str
    ) -> OptInPatchPlanRecord:
        return OptInPatchPlanRecord(
            decision=decision,
            workspace=str(ws),
            config_path=(config.config_path if config else ""),
            provider=(config.provider if config else ""),
            model_id=(config.model_id if config else ""),
            plan_decision="",
            entries_quarantined=0,
            trusted=False,
            applied_to_source=False,
            source_mutation_authorized=False,
            training_eligible=False,
            statuses_seen=(decision,),
            notes=(note,),
        )


__all__ = ["OptInPatchPlanCommand", "OptInPatchPlanRecord", "OPT_IN_PATCH_PLAN_STATUS_TOKENS"]
