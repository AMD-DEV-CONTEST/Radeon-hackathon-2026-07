"""Repo Clinic workflow checker.

DETERMINEX_REPO_CLINIC_WORKFLOW_LOCK_001 — rung 3.

The Repo Clinic preserves every authority gate the campaign locked
earlier. evaluate() refuses:

  * 'fixed' label without post_apply_verifier_passed
    -> BLOCKED_FALSE_FIXED_LABEL
  * verifier_command absent
    -> BLOCKED_VERIFIER_MISSING
  * source mutation attempted from diagnosis alone, or with a
    local-model admission treated as the source of authorization
    -> BLOCKED_SOURCE_MUTATION_CONFUSION
  * source mutation 'authorized by gate' without temp verifier
    pass + approval present
    -> BLOCKED_SOURCE_MUTATION_CONFUSION
"""

from __future__ import annotations

from .repo_clinic_workflow_record import (
    REPO_CLINIC_FLOW_STEPS,
    REPO_CLINIC_STATES,
    REPO_CLINIC_WORKFLOW_STATUS_TOKENS,
    RepoClinicWorkflowRecord,
)


def canonical_flow_steps() -> tuple[str, ...]:
    return REPO_CLINIC_FLOW_STEPS


def canonical_states() -> tuple[str, ...]:
    return REPO_CLINIC_STATES


def evaluate(
    *,
    fixed_label_enabled: bool,
    verifier_command_present: bool,
    temp_verifier_passed: bool,
    approval_present: bool,
    source_mutation_attempted: bool,
    source_mutation_authorized_by_gate: bool,
    post_apply_verifier_passed: bool,
    diagnosis_treated_as_authorization: bool = False,
    local_model_admission_treated_as_source_authorization: bool = False,
) -> RepoClinicWorkflowRecord:
    # 1. Verifier discovery must succeed before anything else can run.
    if not verifier_command_present and (
        source_mutation_attempted or source_mutation_authorized_by_gate or fixed_label_enabled
    ):
        return _block(
            "REPO_CLINIC_WORKFLOW_BLOCKED_VERIFIER_MISSING",
            note=(
                "verifier_command not discovered; mutation/authorization "
                "cannot proceed and 'fixed' label cannot be shown"
            ),
            fixed_label_enabled=fixed_label_enabled,
            verifier_command_present=verifier_command_present,
            temp_verifier_passed=temp_verifier_passed,
            approval_present=approval_present,
            source_mutation_attempted=source_mutation_attempted,
            source_mutation_authorized_by_gate=source_mutation_authorized_by_gate,
            post_apply_verifier_passed=post_apply_verifier_passed,
            diagnosis_treated_as_authorization=diagnosis_treated_as_authorization,
            local_model_admission_treated_as_source_authorization=local_model_admission_treated_as_source_authorization,
        )

    # 2. Source mutation confusion: diagnosis alone or admission alone
    # cannot be treated as source authorization.
    if diagnosis_treated_as_authorization or local_model_admission_treated_as_source_authorization:
        return _block(
            "REPO_CLINIC_WORKFLOW_BLOCKED_SOURCE_MUTATION_CONFUSION",
            note=(
                "diagnosis or local-model admission was treated as source "
                "authorization; only the explicit approval + verifier gate "
                "may authorize source mutation"
            ),
            fixed_label_enabled=fixed_label_enabled,
            verifier_command_present=verifier_command_present,
            temp_verifier_passed=temp_verifier_passed,
            approval_present=approval_present,
            source_mutation_attempted=source_mutation_attempted,
            source_mutation_authorized_by_gate=source_mutation_authorized_by_gate,
            post_apply_verifier_passed=post_apply_verifier_passed,
            diagnosis_treated_as_authorization=diagnosis_treated_as_authorization,
            local_model_admission_treated_as_source_authorization=local_model_admission_treated_as_source_authorization,
        )

    # 3. source_mutation_authorized_by_gate requires temp_verifier_passed AND approval_present.
    if source_mutation_authorized_by_gate and not (temp_verifier_passed and approval_present):
        return _block(
            "REPO_CLINIC_WORKFLOW_BLOCKED_SOURCE_MUTATION_CONFUSION",
            note=(
                "source_mutation_authorized_by_gate=True without "
                f"temp_verifier_passed={temp_verifier_passed} and "
                f"approval_present={approval_present}"
            ),
            fixed_label_enabled=fixed_label_enabled,
            verifier_command_present=verifier_command_present,
            temp_verifier_passed=temp_verifier_passed,
            approval_present=approval_present,
            source_mutation_attempted=source_mutation_attempted,
            source_mutation_authorized_by_gate=source_mutation_authorized_by_gate,
            post_apply_verifier_passed=post_apply_verifier_passed,
            diagnosis_treated_as_authorization=diagnosis_treated_as_authorization,
            local_model_admission_treated_as_source_authorization=local_model_admission_treated_as_source_authorization,
        )

    # 4. 'Fixed' label only after post-apply verifier passes.
    if fixed_label_enabled and not post_apply_verifier_passed:
        return _block(
            "REPO_CLINIC_WORKFLOW_BLOCKED_FALSE_FIXED_LABEL",
            note=("'fixed' label cannot be shown without post_apply_verifier_passed"),
            fixed_label_enabled=fixed_label_enabled,
            verifier_command_present=verifier_command_present,
            temp_verifier_passed=temp_verifier_passed,
            approval_present=approval_present,
            source_mutation_attempted=source_mutation_attempted,
            source_mutation_authorized_by_gate=source_mutation_authorized_by_gate,
            post_apply_verifier_passed=post_apply_verifier_passed,
            diagnosis_treated_as_authorization=diagnosis_treated_as_authorization,
            local_model_admission_treated_as_source_authorization=local_model_admission_treated_as_source_authorization,
        )

    return RepoClinicWorkflowRecord(
        decision="REPO_CLINIC_WORKFLOW_WRITTEN",
        flow_steps=REPO_CLINIC_FLOW_STEPS,
        states=REPO_CLINIC_STATES,
        fixed_label_enabled=fixed_label_enabled,
        verifier_command_present=verifier_command_present,
        temp_verifier_passed=temp_verifier_passed,
        approval_present=approval_present,
        source_mutation_attempted=source_mutation_attempted,
        source_mutation_authorized_by_gate=source_mutation_authorized_by_gate,
        post_apply_verifier_passed=post_apply_verifier_passed,
        diagnosis_treated_as_authorization=False,
        local_model_admission_treated_as_source_authorization=False,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(
            "verifier required for any authorization path",
            "diagnosis is not authorization",
            "local-model admission is not source authorization",
            "'fixed' label requires post-apply verifier pass",
            "training_eligible stays False",
        ),
    )


def _block(decision: str, *, note: str, **kw) -> RepoClinicWorkflowRecord:
    return RepoClinicWorkflowRecord(
        decision=decision,
        flow_steps=REPO_CLINIC_FLOW_STEPS,
        states=REPO_CLINIC_STATES,
        fixed_label_enabled=kw["fixed_label_enabled"],
        verifier_command_present=kw["verifier_command_present"],
        temp_verifier_passed=kw["temp_verifier_passed"],
        approval_present=kw["approval_present"],
        source_mutation_attempted=kw["source_mutation_attempted"],
        source_mutation_authorized_by_gate=kw["source_mutation_authorized_by_gate"],
        post_apply_verifier_passed=kw["post_apply_verifier_passed"],
        diagnosis_treated_as_authorization=kw["diagnosis_treated_as_authorization"],
        local_model_admission_treated_as_source_authorization=kw[
            "local_model_admission_treated_as_source_authorization"
        ],
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(note,),
    )


__all__ = [
    "canonical_flow_steps",
    "canonical_states",
    "evaluate",
    "REPO_CLINIC_WORKFLOW_STATUS_TOKENS",
    "REPO_CLINIC_STATES",
    "REPO_CLINIC_FLOW_STEPS",
    "RepoClinicWorkflowRecord",
]
