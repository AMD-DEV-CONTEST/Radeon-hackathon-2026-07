"""Opt-in live diagnose command.

CLI/API entry that runs diagnose-only against an admitted local model
config. Requires explicit ``opt_in=True`` flag. Routes through the
model router, captures the response as advisory (verifier remains
source of truth). No patch, no source mutation, no corpus, no
training eligibility.
"""

from __future__ import annotations

import sys
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
from models.live_model_compat_harness import FixtureProvider  # noqa: E402
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

from .live_diagnose_trace import LiveDiagnoseTraceRunner
from .opt_in_live_diagnose_record import (
    OPT_IN_LIVE_DIAGNOSE_STATUS_TOKENS,
    OptInLiveDiagnoseRecord,
)

_DIAGNOSE_TASKS = frozenset(
    {
        TaskClass.BUILD_DIAGNOSIS.value,
        TaskClass.TEST_FAILURE_LOCALIZATION.value,
    }
)


class OptInLiveDiagnoseCommand:
    """Stateless command. Returns OptInLiveDiagnoseRecord."""

    def run(
        self,
        workspace: Path,
        *,
        task_class: str,
        config: LocalModelConfigRecord | None,
        provider: FixtureProvider,
        opt_in: bool = False,
    ) -> OptInLiveDiagnoseRecord:
        ws = Path(workspace).resolve()
        statuses_seen: list[str] = []

        # 1. Config must be admitted.
        if (
            config is None
            or not config.is_written
            and not (config and config.decision == "LOCAL_MODEL_CONFIG_DRY_RUN_ONLY")
        ):
            return self._blocked(
                ws,
                task_class,
                config,
                provider,
                "OPT_IN_LIVE_DIAGNOSE_BLOCKED_NO_MODEL_CONFIG",
                "config missing or not written",
            )

        # 2. Explicit opt-in.
        if not opt_in:
            return self._blocked(
                ws,
                task_class,
                config,
                provider,
                "OPT_IN_LIVE_DIAGNOSE_BLOCKED_NOT_OPTED_IN",
                "opt_in=False; explicit caller opt-in required",
            )

        # 3. Task class allowed.
        if task_class not in _DIAGNOSE_TASKS:
            return self._blocked(
                ws,
                task_class,
                config,
                provider,
                "OPT_IN_LIVE_DIAGNOSE_BLOCKED_UNSUPPORTED_TASK",
                f"task_class {task_class!r} not in {sorted(_DIAGNOSE_TASKS)}",
            )

        # 4. Build admission via the existing gate.
        inv = LocalModelInventory.of(sorted(CURRENT_MODEL_IDS))
        admission_cfg = LiveModelAdmissionConfig(
            mode=LiveAdmissionMode.OPT_IN_LIVE,
            opt_in_live=True,
        )
        gate = LiveModelAdmissionGate(config=admission_cfg)
        candidate = LocalModelCandidate(
            model_id=config.model_id,
            provider=config.provider or ModelProvider.OLLAMA.value,
            capability_tags=tuple(config.capabilities) or ("diagnose",),
            supported_task_classes=(task_class,),
        )
        route = ModelRouter(inventory=inv).route(task_class, mode=RouterMode.LIVE)
        admission = gate.evaluate(candidate, task_class, inv, route)
        if not admission.is_ready:
            return self._blocked(
                ws,
                task_class,
                config,
                provider,
                "OPT_IN_LIVE_DIAGNOSE_BLOCKED_PROVIDER_UNAVAILABLE",
                f"live admission not ready: {admission.decision}",
            )

        # 5. Run diagnose trace.
        runner = LiveDiagnoseTraceRunner()
        trace = runner.run(
            ws,
            task_class=task_class,
            admission=admission,
            provider=provider,
        )
        if not trace.is_written:
            return self._blocked(
                ws,
                task_class,
                config,
                provider,
                "OPT_IN_LIVE_DIAGNOSE_BLOCKED_PROVIDER_UNAVAILABLE",
                f"diagnose trace blocked: {trace.decision}",
            )

        statuses_seen = [
            "OPT_IN_LIVE_DIAGNOSE_READY",
            "OPT_IN_LIVE_DIAGNOSE_ADVISORY_WRITTEN",
        ]
        return OptInLiveDiagnoseRecord(
            decision="OPT_IN_LIVE_DIAGNOSE_READY",
            workspace=str(ws),
            task_class=task_class,
            config_path=config.config_path,
            provider=provider.name,
            model_id=provider.model_id,
            advisory_payload=dict(trace.advisory_payload),
            advisory_only=True,
            patch_generated=False,
            source_mutation_authorized=False,
            training_eligible=False,
            statuses_seen=tuple(statuses_seen),
            notes=("opt-in live diagnose; verifier remains source of truth",),
        )

    @staticmethod
    def _blocked(
        ws: Path,
        task_class: str,
        config: LocalModelConfigRecord | None,
        provider: FixtureProvider,
        decision: str,
        note: str,
    ) -> OptInLiveDiagnoseRecord:
        return OptInLiveDiagnoseRecord(
            decision=decision,
            workspace=str(ws),
            task_class=task_class,
            config_path=(config.config_path if config else ""),
            provider=getattr(provider, "name", ""),
            model_id=getattr(provider, "model_id", ""),
            advisory_payload={},
            advisory_only=True,
            patch_generated=False,
            source_mutation_authorized=False,
            training_eligible=False,
            statuses_seen=(decision,),
            notes=(note,),
        )


__all__ = [
    "OptInLiveDiagnoseCommand",
    "OptInLiveDiagnoseRecord",
    "OPT_IN_LIVE_DIAGNOSE_STATUS_TOKENS",
]
