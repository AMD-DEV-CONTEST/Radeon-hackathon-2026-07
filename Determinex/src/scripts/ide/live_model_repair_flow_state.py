"""Live-model repair flow state assembly for the IDE.

Composes:
  * LiveModelAdmissionRecord
  * LiveDiagnoseTrace (optional)
  * QuarantinedPatchPlan (optional)
  * LiveTempPatchVerifierResult (optional)

into a flat IDELiveModelRepairFlowState the frontend can render.
Pure function — no I/O, no source mutation.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from models.live_model_admission_record import LiveModelAdmissionRecord  # noqa: E402
from repair.live_diagnose_trace_record import LiveDiagnoseTrace  # noqa: E402
from repair.live_patch_plan_record import QuarantinedPatchPlan  # noqa: E402
from repair.live_temp_patch_verifier_record import LiveTempPatchVerifierResult  # noqa: E402

from .live_model_repair_flow_record import (
    IDE_LIVE_MODEL_REPAIR_FLOW_STATE_TOKENS,
    IDELiveModelRepairFlowState,
)


def build_live_flow_state(
    workspace: Path | str,
    *,
    admission: LiveModelAdmissionRecord,
    diagnose: LiveDiagnoseTrace | None = None,
    plan: QuarantinedPatchPlan | None = None,
    verifier_result: LiveTempPatchVerifierResult | None = None,
    evidence_locks: tuple[str, ...] = (),
    evidence_files: tuple[str, ...] = (),
) -> IDELiveModelRepairFlowState:
    statuses: list[str] = []
    notes: list[str] = []

    # Admission.
    if admission.is_ready and admission.live_call_authorized:
        live_admission = "LIVE_MODEL_ADMITTED"
    else:
        live_admission = "LIVE_MODEL_NOT_ADMITTED"
    statuses.append(live_admission)

    # Diagnosis advisory.
    diagnosis_advisory = "LIVE_MODEL_NOT_ADMITTED"
    if diagnose is not None:
        if diagnose.is_written:
            diagnosis_advisory = "DIAGNOSIS_ADVISORY_AVAILABLE"
            statuses.append(diagnosis_advisory)
        else:
            diagnosis_advisory = "LIVE_MODEL_NOT_ADMITTED"

    # Patch plan.
    patch_plan_status = "LIVE_MODEL_NOT_ADMITTED"
    if plan is not None:
        if plan.is_quarantined:
            patch_plan_status = "PATCH_PLAN_QUARANTINED"
            statuses.append(patch_plan_status)

    # Temp patch verifier.
    temp_status = "LIVE_MODEL_NOT_ADMITTED"
    if verifier_result is not None:
        if verifier_result.is_passed_temp_only:
            temp_status = "TEMP_PATCH_VERIFIER_PASSED"
        elif verifier_result.decision == "LIVE_PATCH_VERIFIER_FAILED":
            temp_status = "TEMP_PATCH_VERIFIER_FAILED"
        statuses.append(temp_status)

    # Human approval and source mutation are ALWAYS conservative.
    human_approval = "HUMAN_APPROVAL_REQUIRED"
    source_mutation = "SOURCE_MUTATION_BLOCKED"
    training_eligibility = "TRAINING_ELIGIBLE_FALSE"
    statuses.extend([human_approval, source_mutation, training_eligibility])

    if evidence_locks or evidence_files:
        statuses.append("EVIDENCE_AVAILABLE")

    return IDELiveModelRepairFlowState(
        workspace=str(workspace),
        live_admission=live_admission,
        diagnosis_advisory=diagnosis_advisory,
        patch_plan=patch_plan_status,
        temp_patch_verifier=temp_status,
        human_approval=human_approval,
        source_mutation=source_mutation,
        training_eligibility=training_eligibility,
        statuses_seen=tuple(statuses),
        evidence_locks=tuple(evidence_locks),
        evidence_files=tuple(evidence_files),
        notes=tuple(notes),
    )


__all__ = [
    "build_live_flow_state",
    "IDELiveModelRepairFlowState",
    "IDE_LIVE_MODEL_REPAIR_FLOW_STATE_TOKENS",
]
