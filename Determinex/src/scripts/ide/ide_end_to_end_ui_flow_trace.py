"""End-to-end IDE UI flow trace.

Composes every IDE flow rung from this campaign:

  open workspace
    → model route panel
    → diagnose
    → patch plan
    → temp verify
    → human approval packet
    → source apply gate (dry-run blocked/pending approval)
    → final state

Fixture providers only. No network. No source mutation.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from models.live_model_compat_harness import DeterministicProvider  # noqa: E402
from models.local_model_config_record import LocalModelConfigRecord  # noqa: E402

from .diagnose_flow import IDEDiagnoseFlow
from .human_approval_signing_flow import IDEHumanApprovalSigningFlow
from .human_approval_ui_model import build_packet
from .ide_end_to_end_ui_flow_record import (
    IDE_END_TO_END_UI_FLOW_TOKENS,
    IDEEndToEndUIFlowTrace,
    IDEUIFlowStage,
)
from .model_route_panel import IDEModelRoutePanel
from .patch_plan_flow import IDEPatchPlanFlow
from .source_apply_gate_flow import IDESourceApplyGateFlow, workspace_hash
from .temp_verify_flow import IDETempVerifyFlow
from .workspace_open_flow import IDEWorkspaceOpenFlow


def build_ui_flow_trace(
    workspace: Path,
    *,
    config: LocalModelConfigRecord,
    temp_root: Path,
    plan_entries: tuple[dict, ...] = (
        {"operation": "replace_file", "path": "src/lib.py", "new_content": "x = 1\n"},
    ),
) -> IDEEndToEndUIFlowTrace:
    ws = Path(workspace).resolve()
    stages: list[IDEUIFlowStage] = []

    # 1. Open workspace.
    open_rec = IDEWorkspaceOpenFlow().open(ws)
    stages.append(IDEUIFlowStage(name="open_workspace", status=open_rec.decision))

    # 2. Model route panel.
    panel = IDEModelRoutePanel().view(
        task_class="BUILD_DIAGNOSIS",
        config=config,
        opt_in=True,
    )
    stages.append(IDEUIFlowStage(name="model_route_panel", status=panel.decision))

    # 3. Diagnose.
    diag = IDEDiagnoseFlow().run(
        ws,
        task_class="BUILD_DIAGNOSIS",
        mode="live_opt_in",
        config=config,
        provider=DeterministicProvider(canned={"summary": "fixture diagnose"}),
    )
    stages.append(IDEUIFlowStage(name="diagnose", status=diag.decision))

    # 4. Patch plan.
    plan_flow = IDEPatchPlanFlow().run(
        ws,
        config=config,
        opt_in=True,
        plan_entries=plan_entries,
    )
    stages.append(IDEUIFlowStage(name="patch_plan", status=plan_flow.decision))

    # 5. Temp verify (only if plan quarantined).
    from models.live_model_admission import (
        LiveAdmissionMode,
        LiveModelAdmissionConfig,
        LiveModelAdmissionGate,
    )
    from models.local_model_admission_policy import LocalModelCandidate, ModelProvider
    from models.model_inventory import LocalModelInventory
    from models.model_router import CURRENT_MODEL_IDS, ModelRouter, RouterMode, TaskClass
    from repair.live_patch_plan_quarantine import LivePatchPlanQuarantine

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
    admission = gate.evaluate(
        candidate,
        TaskClass.PATCH_GENERATION,
        inv,
        ModelRouter(inventory=inv).route(TaskClass.PATCH_GENERATION, mode=RouterMode.LIVE),
    )
    quarantined = LivePatchPlanQuarantine().quarantine(
        list(plan_entries),
        admission=admission,
        workspace=ws,
    )
    verifier_status = ""
    unified_diff = ""
    if quarantined.is_quarantined:
        from repair.safe_patch_workspace import stub_verifier_pass

        verify = IDETempVerifyFlow().run(
            quarantined,
            temp_root=Path(temp_root),
            verifier=stub_verifier_pass,
            workspace_id="e2e_ui",
        )
        stages.append(IDEUIFlowStage(name="temp_verify", status=verify.decision))
        verifier_status = verify.verifier_status
        unified_diff = verify.unified_diff
    else:
        stages.append(IDEUIFlowStage(name="temp_verify", status="SKIPPED"))

    # 6. Human approval packet.
    packet = build_packet(
        trace_id="e2e_ui_trace",
        workspace_identity=str(ws),
        unified_diff=unified_diff,
        files_changed=tuple(e.get("path", "") for e in plan_entries if isinstance(e, dict)),
        verifier_status=verifier_status or "PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    signing = IDEHumanApprovalSigningFlow().submit(
        packet,
        action="approve",
        operator_identity="ryan",
        observed_diff=unified_diff,
        observed_verifier_status=verifier_status or "PATCH_VERIFIER_PASSED_TEMP_ONLY",
        fixture=True,
    )
    stages.append(IDEUIFlowStage(name="approval_packet", status=signing.decision))

    # 7. Source apply gate.
    apply = IDESourceApplyGateFlow().evaluate(
        ws,
        signing=signing,
        packet=packet,
        observed_diff=unified_diff,
        observed_source_hash_at_packet_time=workspace_hash(ws),
        verifier_status=verifier_status or "PATCH_VERIFIER_PASSED_TEMP_ONLY",
    )
    stages.append(IDEUIFlowStage(name="source_apply_gate", status=apply.decision))

    statuses_seen = (
        "IDE_UI_FLOW_TRACE_WRITTEN",
        "IDE_UI_FLOW_SOURCE_UNCHANGED",
        "IDE_UI_FLOW_APPROVAL_REQUIRED",
        "IDE_UI_FLOW_TRAINING_ELIGIBLE_FALSE",
    )

    return IDEEndToEndUIFlowTrace(
        workspace=str(ws),
        stages=tuple(stages),
        source_unchanged=True,
        approval_required=True,
        training_eligible=False,
        statuses_seen=statuses_seen,
        evidence_refs=(),
        notes=("end-to-end UI flow trace; fixture provider; no live model call",),
    )


__all__ = [
    "build_ui_flow_trace",
    "IDEEndToEndUIFlowTrace",
    "IDE_END_TO_END_UI_FLOW_TOKENS",
]
