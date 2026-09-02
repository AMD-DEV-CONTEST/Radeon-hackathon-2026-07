"""IDE model-route panel — pure read of routing + admission state.

Returns a flat IDEModelRoutePanelRecord describing routing for the
selected task class, whether live opt-in is available (and if not,
which specific reason blocks it), and the config/smoke state.

Performs no model invocation. No subprocess. No network.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from models.live_model_admission import (  # noqa: E402
    _NETWORK_PROVIDER_TOKENS,
    LiveAdmissionMode,
    LiveModelAdmissionConfig,
    LiveModelAdmissionGate,
)
from models.local_model_admission_policy import (  # noqa: E402
    LocalModelCandidate,
    ModelProvider,
)
from models.local_model_config_record import LocalModelConfigRecord  # noqa: E402
from models.local_provider_smoke_record import LocalProviderSmokeRecord  # noqa: E402
from models.model_inventory import LocalModelInventory  # noqa: E402
from models.model_router import (  # noqa: E402
    CURRENT_MODEL_IDS,
    STALE_MODEL_IDS,
    ModelRouter,
    RouterMode,
    TaskClass,
)

from .model_route_panel_record import (
    IDE_MODEL_ROUTE_PANEL_STATUS_TOKENS,
    IDEModelRoutePanelRecord,
)


class IDEModelRoutePanel:
    """Stateless panel-state assembler."""

    def view(
        self,
        *,
        task_class: str = "BUILD_DIAGNOSIS",
        config: LocalModelConfigRecord | None = None,
        smoke: LocalProviderSmokeRecord | None = None,
        opt_in: bool = False,
    ) -> IDEModelRoutePanelRecord:
        # Normalize task class.
        try:
            tc = TaskClass(task_class)
        except ValueError:
            tc = TaskClass.UNKNOWN

        inv = LocalModelInventory.of(sorted(CURRENT_MODEL_IDS))
        route_dry = ModelRouter(inventory=inv).route(tc, mode=RouterMode.DRY_RUN)

        config_state = "MISSING" if config is None else config.decision
        smoke_state = "MISSING" if smoke is None else smoke.decision

        block_reason = ""
        live_opt_in_available = False
        live_call_authorized = False

        # Determine block reason in priority order.
        if config is None:
            block_reason = "MODEL_ROUTE_BLOCKED_NO_MODEL"
        elif config.provider in _NETWORK_PROVIDER_TOKENS or config.network_required:
            block_reason = "MODEL_ROUTE_BLOCKED_NETWORK_PROVIDER"
        elif config.model_id in STALE_MODEL_IDS:
            block_reason = "MODEL_ROUTE_BLOCKED_STALE_MODEL"
        else:
            # Live admission with explicit opt-in.
            gate = LiveModelAdmissionGate(
                config=LiveModelAdmissionConfig(
                    mode=LiveAdmissionMode.OPT_IN_LIVE,
                    opt_in_live=opt_in,
                )
            )
            candidate = LocalModelCandidate(
                model_id=config.model_id,
                provider=config.provider or ModelProvider.OLLAMA.value,
                capability_tags=tuple(config.capabilities) or ("diagnose",),
                supported_task_classes=tuple(config.task_classes_allowed) or (task_class,),
            )
            route_live = ModelRouter(inventory=inv).route(tc, mode=RouterMode.LIVE)
            admission = gate.evaluate(candidate, task_class, inv, route_live)
            live_opt_in_available = admission.is_ready
            live_call_authorized = admission.live_call_authorized

        if block_reason:
            decision = block_reason
        elif live_opt_in_available:
            decision = "MODEL_ROUTE_LIVE_OPT_IN_AVAILABLE"
        else:
            decision = "MODEL_ROUTE_DRY_RUN_DEFAULT"

        statuses_seen = [
            "MODEL_ROUTE_PANEL_READY",
            decision,
        ]
        if not opt_in or not live_opt_in_available:
            statuses_seen.append("MODEL_ROUTE_DRY_RUN_DEFAULT")

        return IDEModelRoutePanelRecord(
            decision=decision,
            task_class=tc.value,
            selected_route=route_dry.selected_route,
            selected_model_id=route_dry.selected_model_id,
            fallback_chain=route_dry.fallback_chain,
            dry_run_default=True,
            live_opt_in_available=live_opt_in_available,
            live_call_authorized=live_call_authorized,
            config_state=config_state,
            provider_smoke_state=smoke_state,
            block_reason=block_reason,
            statuses_seen=tuple(statuses_seen),
            notes=(),
        )


__all__ = [
    "IDEModelRoutePanel",
    "IDEModelRoutePanelRecord",
    "IDE_MODEL_ROUTE_PANEL_STATUS_TOKENS",
]
