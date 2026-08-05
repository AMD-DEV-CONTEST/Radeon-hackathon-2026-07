"""IDE diagnose flow.

Wraps the existing OptInLiveDiagnoseCommand. Two paths: dry_run and
live_opt_in. Advisory only. Source unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from models.live_model_compat_harness import DeterministicProvider, FixtureProvider  # noqa: E402
from models.local_model_config_record import LocalModelConfigRecord  # noqa: E402
from repair.opt_in_live_diagnose_command import OptInLiveDiagnoseCommand  # noqa: E402

from .diagnose_flow_record import (
    IDE_DIAGNOSE_FLOW_STATUS_TOKENS,
    IDEDiagnoseFlowRecord,
)

_ALLOWED_TASKS = frozenset({"BUILD_DIAGNOSIS", "TEST_FAILURE_LOCALIZATION"})


class IDEDiagnoseFlow:
    """Stateless flow."""

    def run(
        self,
        workspace: Path,
        *,
        task_class: str = "BUILD_DIAGNOSIS",
        mode: str = "dry_run",
        config: LocalModelConfigRecord | None = None,
        provider: FixtureProvider | None = None,
    ) -> IDEDiagnoseFlowRecord:
        ws = Path(workspace).resolve()

        if task_class not in _ALLOWED_TASKS:
            return IDEDiagnoseFlowRecord(
                decision="IDE_DIAGNOSE_BLOCKED_UNSUPPORTED_TASK",
                workspace=str(ws),
                task_class=task_class,
                mode=mode,
                advisory_payload={},
                advisory_only=True,
                patch_generated=False,
                source_mutation_authorized=False,
                training_eligible=False,
                statuses_seen=("IDE_DIAGNOSE_BLOCKED_UNSUPPORTED_TASK",),
                notes=(f"task_class {task_class!r} not in {sorted(_ALLOWED_TASKS)}",),
            )

        if mode == "dry_run":
            # No live model call. We still record the flow as ready.
            return IDEDiagnoseFlowRecord(
                decision="IDE_DIAGNOSE_DRY_RUN_READY",
                workspace=str(ws),
                task_class=task_class,
                mode="dry_run",
                advisory_payload={"kind": "DRY_RUN", "summary": "dry-run mode"},
                advisory_only=True,
                patch_generated=False,
                source_mutation_authorized=False,
                training_eligible=False,
                statuses_seen=(
                    "IDE_DIAGNOSE_DRY_RUN_READY",
                    "IDE_DIAGNOSE_SOURCE_UNCHANGED",
                ),
                notes=("dry-run; no model invocation",),
            )

        # live_opt_in path.
        if config is None:
            return IDEDiagnoseFlowRecord(
                decision="IDE_DIAGNOSE_BLOCKED_NO_MODEL",
                workspace=str(ws),
                task_class=task_class,
                mode=mode,
                advisory_payload={},
                advisory_only=True,
                patch_generated=False,
                source_mutation_authorized=False,
                training_eligible=False,
                statuses_seen=("IDE_DIAGNOSE_BLOCKED_NO_MODEL",),
                notes=("config missing",),
            )

        # Live requires explicit opt_in flag inside the command.
        prov = provider or DeterministicProvider(canned={"summary": "fixture diagnose"})
        cmd_rec = OptInLiveDiagnoseCommand().run(
            ws,
            task_class=task_class,
            config=config,
            provider=prov,
            opt_in=True,
        )
        if cmd_rec.decision == "OPT_IN_LIVE_DIAGNOSE_BLOCKED_NO_MODEL_CONFIG":
            return IDEDiagnoseFlowRecord(
                decision="IDE_DIAGNOSE_BLOCKED_NO_MODEL",
                workspace=str(ws),
                task_class=task_class,
                mode=mode,
                advisory_payload={},
                advisory_only=True,
                patch_generated=False,
                source_mutation_authorized=False,
                training_eligible=False,
                statuses_seen=("IDE_DIAGNOSE_BLOCKED_NO_MODEL",),
                notes=tuple(cmd_rec.notes),
            )
        if not cmd_rec.is_ready:
            # Provider unavailable / other.
            return IDEDiagnoseFlowRecord(
                decision="IDE_DIAGNOSE_BLOCKED_NOT_OPTED_IN",
                workspace=str(ws),
                task_class=task_class,
                mode=mode,
                advisory_payload={},
                advisory_only=True,
                patch_generated=False,
                source_mutation_authorized=False,
                training_eligible=False,
                statuses_seen=("IDE_DIAGNOSE_BLOCKED_NOT_OPTED_IN",),
                notes=tuple(cmd_rec.notes),
            )

        return IDEDiagnoseFlowRecord(
            decision="IDE_DIAGNOSE_LIVE_OPT_IN_READY",
            workspace=str(ws),
            task_class=task_class,
            mode=mode,
            advisory_payload=dict(cmd_rec.advisory_payload),
            advisory_only=True,
            patch_generated=False,
            source_mutation_authorized=False,
            training_eligible=False,
            statuses_seen=(
                "IDE_DIAGNOSE_LIVE_OPT_IN_READY",
                "IDE_DIAGNOSE_ADVISORY_AVAILABLE",
                "IDE_DIAGNOSE_SOURCE_UNCHANGED",
            ),
            evidence_refs=(cmd_rec.config_path,),
            notes=("advisory only; verifier remains source of truth",),
        )


__all__ = [
    "IDEDiagnoseFlow",
    "IDEDiagnoseFlowRecord",
    "IDE_DIAGNOSE_FLOW_STATUS_TOKENS",
]
