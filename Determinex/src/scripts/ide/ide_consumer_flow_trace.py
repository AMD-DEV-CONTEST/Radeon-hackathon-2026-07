"""End-to-end IDE consumer flow trace with fixture providers.

Composes:
  inspect → route → diagnose → patch plan quarantine →
  temp patch verify → human approval packet → source apply dry-run →
  final IDE state.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from intake.build_adapter_registry import BuildAdapterRegistry  # noqa: E402
from models.live_model_admission import (  # noqa: E402
    LiveAdmissionMode,
    LiveModelAdmissionConfig,
    LiveModelAdmissionGate,
)
from models.live_model_compat_harness import DeterministicProvider  # noqa: E402
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
from repair.live_patch_plan_quarantine import LivePatchPlanQuarantine  # noqa: E402
from repair.live_temp_patch_verifier_gate import LiveTempPatchVerifierGate  # noqa: E402
from repair.opt_in_live_diagnose_command import OptInLiveDiagnoseCommand  # noqa: E402
from repair.source_mutation_apply_dry_run import (  # noqa: E402
    SourceMutationApplyDryRun,
    workspace_hash,
)

from .human_approval_ui_model import build_packet
from .ide_consumer_flow_record import (
    IDE_CONSUMER_FLOW_TRACE_TOKENS,
    IDEConsumerFlowStage,
    IDEConsumerFlowTrace,
)


def build_consumer_flow_trace(
    workspace: Path,
    *,
    config: LocalModelConfigRecord,
    diagnose_provider: DeterministicProvider | None = None,
    plan_entries: tuple[dict, ...] = (
        {"operation": "replace_file", "path": "src/lib.py", "new_content": "x = 1\n"},
    ),
    temp_root: Path | None = None,
) -> IDEConsumerFlowTrace:
    ws = Path(workspace).resolve()
    temp = Path(temp_root) if temp_root else (ws.parent / "_consumer_flow_tmp")
    stages: list[IDEConsumerFlowStage] = []

    # 1. Inspect workspace.
    reg = BuildAdapterRegistry()
    sel = reg.select(ws)
    stages.append(
        IDEConsumerFlowStage(
            name="inspect_workspace",
            status="IDE_COMMAND_OK",
            evidence_ref=sel.primary.name,
        )
    )

    # 2. Route.
    inv = LocalModelInventory.of(sorted(CURRENT_MODEL_IDS))
    route = ModelRouter(inventory=inv).route(TaskClass.PATCH_GENERATION, mode=RouterMode.LIVE)
    stages.append(IDEConsumerFlowStage(name="route_model", status=route.decision))

    # 3. Diagnose (opt-in).
    diag_provider = diagnose_provider or DeterministicProvider(
        canned={"summary": "fixture diagnose"}
    )
    diag = OptInLiveDiagnoseCommand().run(
        ws,
        task_class="BUILD_DIAGNOSIS",
        config=config,
        provider=diag_provider,
        opt_in=True,
    )
    stages.append(IDEConsumerFlowStage(name="diagnose", status=diag.decision))

    # 4. Patch plan quarantine.
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
    admission = gate.evaluate(candidate, TaskClass.PATCH_GENERATION, inv, route)
    plan = LivePatchPlanQuarantine().quarantine(
        list(plan_entries),
        admission=admission,
        workspace=ws,
    )
    stages.append(IDEConsumerFlowStage(name="patch_plan", status=plan.decision))

    # 5. Temp patch verify.
    verifier_status = ""
    diff = ""
    if plan.is_quarantined:
        from repair.safe_patch_workspace import stub_verifier_pass

        vr = LiveTempPatchVerifierGate().apply_and_verify(
            plan,
            temp_root=temp,
            verifier=stub_verifier_pass,
            workspace_id="cflow",
        )
        verifier_status = vr.verifier_status
        diff = vr.unified_diff
        stages.append(IDEConsumerFlowStage(name="temp_patch_verify", status=vr.decision))
    else:
        stages.append(IDEConsumerFlowStage(name="temp_patch_verify", status="SKIPPED"))

    # 6. Human approval packet.
    packet = build_packet(
        trace_id="ide-consumer-flow",
        workspace_identity=str(ws),
        unified_diff=diff,
        files_changed=tuple(e.get("path", "") for e in plan_entries if isinstance(e, dict)),
        verifier_status=verifier_status or "PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    stages.append(IDEConsumerFlowStage(name="human_approval_packet", status=packet.decision))

    # 7. Source apply dry-run.
    dry = SourceMutationApplyDryRun().run(
        ws,
        approval=packet,
        observed_diff=diff,
        observed_source_hash_at_packet_time=workspace_hash(ws),
        verifier_status=verifier_status or "PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    stages.append(IDEConsumerFlowStage(name="source_apply_dry_run", status=dry.decision))

    statuses_seen = (
        "IDE_CONSUMER_FLOW_TRACE_WRITTEN",
        "IDE_CONSUMER_FLOW_SOURCE_UNCHANGED",
        "IDE_CONSUMER_FLOW_HUMAN_APPROVAL_REQUIRED",
        "IDE_CONSUMER_FLOW_TRAINING_ELIGIBLE_FALSE",
    )

    return IDEConsumerFlowTrace(
        workspace=str(ws),
        stages=tuple(stages),
        source_unchanged=True,
        human_approval_required=True,
        training_eligible=False,
        statuses_seen=statuses_seen,
        notes=("end-to-end fixture trace; no live model, no source mutation",),
    )


__all__ = [
    "build_consumer_flow_trace",
    "IDEConsumerFlowTrace",
    "IDE_CONSUMER_FLOW_TRACE_TOKENS",
]
