"""Assembly of the IDE-facing repair state.

Takes a :class:`VerifiedRepairTrace` (and optionally an
:class:`ApprovalGateDecision`) and emits a flat :class:`IDERepairState`
that the front-end can render directly. The model is a pure function —
no I/O beyond reading lock + evidence file *names* for the pointer
block.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from repair.human_approval_record import ApprovalGateDecision  # noqa: E402
from repair.verified_repair_trace_record import VerifiedRepairTrace  # noqa: E402

from .repair_state_record import (
    IDE_REPAIR_STATE_TOKENS,
    EvidencePointers,
    IDERepairState,
    IntakeStatus,
    ModelRouteStatus,
    PatchPlanStatus,
    PatchTempStatus,
    PatchVerifierStatus,
    SourceApprovalStatus,
    VerifierStatus,
)


def _verifier_status_from_trace(trace: VerifiedRepairTrace) -> VerifierStatus:
    spr = trace.safe_patch_result or {}
    vs = str(spr.get("verifier_status") or "")
    if not vs or vs == "PATCH_VERIFIER_SKIPPED":
        return VerifierStatus.MISSING
    return VerifierStatus.AVAILABLE


def _model_route_status(trace: VerifiedRepairTrace) -> tuple[ModelRouteStatus, str]:
    # Use the BUILD_DIAGNOSIS decision (first in the pipeline) as the
    # representative route status.
    if not trace.route_decisions:
        return ModelRouteStatus.BLOCKED, ""
    rec = trace.route_decisions[0]
    decision = str(rec.get("decision", ""))
    model_id = str(rec.get("selected_model_id", ""))
    if decision.startswith("ROUTE_BLOCKED_"):
        return ModelRouteStatus.BLOCKED, ""
    if decision == "ROUTE_NO_MODEL_REQUIRED":
        return ModelRouteStatus.NO_MODEL, ""
    return ModelRouteStatus.SELECTED, model_id


def _patch_plan_status(trace: VerifiedRepairTrace) -> PatchPlanStatus:
    if trace.mocked_patch_plan and trace.mocked_patch_plan.get("kind"):
        return PatchPlanStatus.AVAILABLE
    return PatchPlanStatus.UNAVAILABLE


def _patch_temp_status(trace: VerifiedRepairTrace) -> PatchTempStatus:
    spr = trace.safe_patch_result or {}
    status = str(spr.get("status") or "")
    if status == "PATCH_APPLIED_TO_TEMP_WORKSPACE":
        return PatchTempStatus.APPLIED
    return PatchTempStatus.FAILED


def _patch_verifier_status(trace: VerifiedRepairTrace) -> PatchVerifierStatus:
    spr = trace.safe_patch_result or {}
    vs = str(spr.get("verifier_status") or "")
    if vs == "PATCH_VERIFIER_PASSED_TEMP_ONLY":
        return PatchVerifierStatus.PASSED_TEMP_ONLY
    if vs == "PATCH_VERIFIER_FAILED":
        return PatchVerifierStatus.FAILED
    return PatchVerifierStatus.SKIPPED


def _source_approval_status(
    approval: ApprovalGateDecision | None,
) -> tuple[SourceApprovalStatus, bool]:
    if approval is None:
        return SourceApprovalStatus.REQUIRED, False
    if approval.decision == "SOURCE_MUTATION_APPROVAL_ACCEPTED_FIXTURE":
        return SourceApprovalStatus.ACCEPTED_FIXTURE, True
    if approval.decision == "SOURCE_MUTATION_APPROVAL_REQUIRED":
        return SourceApprovalStatus.REQUIRED, False
    return SourceApprovalStatus.MUTATION_BLOCKED, False


def build_ide_state(
    trace: VerifiedRepairTrace,
    *,
    approval: ApprovalGateDecision | None = None,
    lock_paths: tuple[str, ...] = (),
    evidence_paths: tuple[str, ...] = (),
) -> IDERepairState:
    """Build a flat IDERepairState from a trace + optional approval."""
    intake = (
        IntakeStatus.UNSUPPORTED
        if trace.final_status == "TRACE_BLOCKED_UNSUPPORTED_REPO"
        else IntakeStatus.READY
    )
    verifier = _verifier_status_from_trace(trace)
    route_status, model_id = _model_route_status(trace)
    plan_status = _patch_plan_status(trace)
    temp_status = _patch_temp_status(trace)
    verifier_status = _patch_verifier_status(trace)
    approval_status, mutation_authorized = _source_approval_status(approval)

    statuses_seen: list[str] = [
        intake.value,
        verifier.value,
        route_status.value,
        plan_status.value,
        temp_status.value,
        verifier_status.value,
        approval_status.value,
        "CORPUS_ELIGIBILITY_FALSE",
    ]
    if lock_paths or evidence_paths:
        statuses_seen.append("EVIDENCE_AVAILABLE")

    # Source-mutation-blocked override: only when the approval call
    # *attempted and failed* (decision starts with SOURCE_MUTATION_BLOCKED_).
    # A "required" decision means no packet was submitted yet — that's
    # the REQUIRED state, not a blocked state.
    if approval is not None and approval.is_blocked:
        approval_status = SourceApprovalStatus.MUTATION_BLOCKED
        mutation_authorized = False

    return IDERepairState(
        workspace=trace.workspace,
        trace_id=trace.trace_id,
        intake=intake.value,
        adapter_name=trace.adapter_name,
        build_system_id=trace.build_system_id,
        verifier=verifier.value,
        model_route=route_status.value,
        selected_model_id=model_id,
        patch_plan=plan_status.value,
        patch_temp=temp_status.value,
        patch_verifier=verifier_status.value,
        source_approval=approval_status.value,
        source_mutation_authorized=mutation_authorized,
        corpus_eligibility="CORPUS_ELIGIBILITY_FALSE",
        training_eligible=False,
        evidence=EvidencePointers(
            locks=tuple(lock_paths),
            evidence_files=tuple(evidence_paths),
        ),
        statuses_seen=tuple(statuses_seen),
    )


__all__ = [
    "build_ide_state",
    "IDERepairState",
    "IDE_REPAIR_STATE_TOKENS",
    "EvidencePointers",
    "IntakeStatus",
    "VerifierStatus",
    "ModelRouteStatus",
    "PatchPlanStatus",
    "PatchTempStatus",
    "PatchVerifierStatus",
    "SourceApprovalStatus",
]
