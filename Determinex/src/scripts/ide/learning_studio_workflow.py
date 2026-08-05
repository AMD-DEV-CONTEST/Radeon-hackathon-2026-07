"""Learning Studio workflow checker.

DETERMINEX_LEARNING_STUDIO_WORKFLOW_LOCK_001 — rung 5.

Learning outputs are non-authorizing by construction. evaluate()
refuses any LearningStudioOutput that:

  * claims_repair_success or claims_authorized_apply
    -> BLOCKED_FALSE_SUCCESS
  * suggests a fix or new project but does not route to the
    appropriate gated workflow (repo_clinic / idea_lab)
    -> BLOCKED_MUTATION_CONFUSION
"""

from __future__ import annotations

from .learning_studio_workflow_record import (
    LEARNING_MODES,
    LEARNING_STUDIO_WORKFLOW_STATUS_TOKENS,
    LearningStudioOutput,
    LearningStudioWorkflowRecord,
)


def canonical_modes() -> tuple[str, ...]:
    return LEARNING_MODES


def evaluate(output: LearningStudioOutput | None) -> LearningStudioWorkflowRecord:
    if output is None:
        return LearningStudioWorkflowRecord(
            decision="LEARNING_STUDIO_WORKFLOW_WRITTEN",
            modes_supported=LEARNING_MODES,
            output=None,
            non_authorizing=True,
            routes_to_gated_workflow_when_needed=True,
            source_mutation_authorized=False,
            training_eligible=False,
            notes=("no output supplied; workflow definition only",),
        )

    if output.mode not in LEARNING_MODES:
        return _block(
            "LEARNING_STUDIO_BLOCKED_MUTATION_CONFUSION",
            output=output,
            note=f"unknown learning mode {output.mode!r}",
        )

    # Hard rule: learning outputs may not claim repair success or
    # authorized apply.
    if output.claims_repair_success or output.claims_authorized_apply:
        return _block(
            "LEARNING_STUDIO_BLOCKED_FALSE_SUCCESS",
            output=output,
            note=(
                "learning output claimed repair success or authorized "
                "apply; learning is non-authorizing"
            ),
        )

    # Hard rule: forbidden phrasing in body.
    text_l = output.text.lower()
    forbidden = (
        "patch applied",
        "now fixed",
        "source mutation authorized",
        "approved",
        "this fix has been applied",
        "training row written",
    )
    for phrase in forbidden:
        if phrase in text_l:
            return _block(
                "LEARNING_STUDIO_BLOCKED_FALSE_SUCCESS",
                output=output,
                note=(
                    f"learning text contains forbidden phrase {phrase!r}; "
                    "learning may explain but not authorize or claim apply"
                ),
            )

    # Hard rule: any suggestion of a fix must route to repo_clinic;
    # any suggestion of a new project must route to idea_lab.
    if output.suggests_fix and output.routes_to != "repo_clinic":
        return _block(
            "LEARNING_STUDIO_BLOCKED_MUTATION_CONFUSION",
            output=output,
            note=(
                "output suggests_fix=True but routes_to != 'repo_clinic'; "
                "all fix-suggestions must route through repo_clinic gates"
            ),
        )
    if output.suggests_new_project and output.routes_to != "idea_lab":
        return _block(
            "LEARNING_STUDIO_BLOCKED_MUTATION_CONFUSION",
            output=output,
            note=(
                "output suggests_new_project=True but routes_to != 'idea_lab'; "
                "new-project suggestions must route through idea_lab gates"
            ),
        )

    return LearningStudioWorkflowRecord(
        decision="LEARNING_STUDIO_NON_AUTHORIZING_PASSED",
        modes_supported=LEARNING_MODES,
        output=output,
        non_authorizing=True,
        routes_to_gated_workflow_when_needed=True,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(
            "learning output explains, does not authorize",
            "fix suggestions route to repo_clinic gates",
            "new-project suggestions route to idea_lab gates",
            "training_eligible False",
        ),
    )


def _block(
    decision: str,
    *,
    output: LearningStudioOutput,
    note: str,
) -> LearningStudioWorkflowRecord:
    return LearningStudioWorkflowRecord(
        decision=decision,
        modes_supported=LEARNING_MODES,
        output=output,
        non_authorizing=True,
        routes_to_gated_workflow_when_needed=False,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(note,),
    )


__all__ = [
    "canonical_modes",
    "evaluate",
    "LEARNING_STUDIO_WORKFLOW_STATUS_TOKENS",
    "LEARNING_MODES",
    "LearningStudioOutput",
    "LearningStudioWorkflowRecord",
]
