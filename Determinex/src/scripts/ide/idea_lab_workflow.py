"""Idea Lab workflow checker.

DETERMINEX_IDEA_LAB_WORKFLOW_LOCK_001 — rung 2.

evaluate(...) takes the runtime state of an Idea Lab session and
returns IDEA_LAB_WORKFLOW_WRITTEN iff the workflow's hard rules
hold:

  * 'Build It' is disabled until support_check_passed is True
    (BLOCKED_MISSING_SUPPORT_CHECK if support check skipped).
  * 'Working' label is disabled until build_verifier_passed AND
    tests_passed AND smoke_passed are all True
    (BLOCKED_FALSE_SUCCESS if any of them False).
  * Unsupported features must be visible
    (BLOCKED_UNSUPPORTED_CLAIM if hidden).
  * External setup caveats must be visible.
  * training_eligible must remain False everywhere.
"""

from __future__ import annotations

from .idea_lab_workflow_record import (
    IDEA_LAB_FLOW_STEPS,
    IDEA_LAB_STATES,
    IDEA_LAB_WORKFLOW_STATUS_TOKENS,
    IdeaLabWorkflowRecord,
)


def canonical_flow_steps() -> tuple[str, ...]:
    return IDEA_LAB_FLOW_STEPS


def canonical_states() -> tuple[str, ...]:
    return IDEA_LAB_STATES


def evaluate(
    *,
    build_it_enabled: bool,
    working_label_enabled: bool,
    unsupported_features_visible: bool,
    external_caveats_visible: bool,
    support_check_passed: bool,
    build_verifier_passed: bool,
    tests_passed: bool,
    smoke_passed: bool,
) -> IdeaLabWorkflowRecord:
    # Hard rule: unsupported features must be surfaced.
    if not unsupported_features_visible:
        return _block(
            "IDEA_LAB_WORKFLOW_BLOCKED_UNSUPPORTED_CLAIM",
            note=(
                "unsupported_features_visible is False; unsupported "
                "requests must be surfaced, not hidden"
            ),
            build_it_enabled=build_it_enabled,
            working_label_enabled=working_label_enabled,
            unsupported_features_visible=unsupported_features_visible,
            external_caveats_visible=external_caveats_visible,
            support_check_passed=support_check_passed,
            build_verifier_passed=build_verifier_passed,
            tests_passed=tests_passed,
            smoke_passed=smoke_passed,
        )
    if not external_caveats_visible:
        return _block(
            "IDEA_LAB_WORKFLOW_BLOCKED_UNSUPPORTED_CLAIM",
            note=(
                "external_caveats_visible is False; external cost / setup "
                "caveats must be shown to the operator"
            ),
            build_it_enabled=build_it_enabled,
            working_label_enabled=working_label_enabled,
            unsupported_features_visible=unsupported_features_visible,
            external_caveats_visible=external_caveats_visible,
            support_check_passed=support_check_passed,
            build_verifier_passed=build_verifier_passed,
            tests_passed=tests_passed,
            smoke_passed=smoke_passed,
        )

    # Hard rule: Build It enabled implies support check passed.
    if build_it_enabled and not support_check_passed:
        return _block(
            "IDEA_LAB_WORKFLOW_BLOCKED_MISSING_SUPPORT_CHECK",
            note=(
                "build_it_enabled=True without support_check_passed; "
                "'Build It' must remain disabled until the support matrix "
                "check passes"
            ),
            build_it_enabled=build_it_enabled,
            working_label_enabled=working_label_enabled,
            unsupported_features_visible=unsupported_features_visible,
            external_caveats_visible=external_caveats_visible,
            support_check_passed=support_check_passed,
            build_verifier_passed=build_verifier_passed,
            tests_passed=tests_passed,
            smoke_passed=smoke_passed,
        )

    # Hard rule: Working label enabled requires every verifier pass.
    if working_label_enabled and not (build_verifier_passed and tests_passed and smoke_passed):
        return _block(
            "IDEA_LAB_WORKFLOW_BLOCKED_FALSE_SUCCESS",
            note=(
                "working_label_enabled=True without full evidence: "
                f"build={build_verifier_passed} tests={tests_passed} "
                f"smoke={smoke_passed}; 'Working' label requires all three"
            ),
            build_it_enabled=build_it_enabled,
            working_label_enabled=working_label_enabled,
            unsupported_features_visible=unsupported_features_visible,
            external_caveats_visible=external_caveats_visible,
            support_check_passed=support_check_passed,
            build_verifier_passed=build_verifier_passed,
            tests_passed=tests_passed,
            smoke_passed=smoke_passed,
        )

    return IdeaLabWorkflowRecord(
        decision="IDEA_LAB_WORKFLOW_WRITTEN",
        flow_steps=IDEA_LAB_FLOW_STEPS,
        states=IDEA_LAB_STATES,
        build_it_enabled=build_it_enabled,
        working_label_enabled=working_label_enabled,
        unsupported_features_visible=unsupported_features_visible,
        external_caveats_visible=external_caveats_visible,
        support_check_passed=support_check_passed,
        build_verifier_passed=build_verifier_passed,
        tests_passed=tests_passed,
        smoke_passed=smoke_passed,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(
            "Build It disabled until support check passes",
            "'Working' label requires build+test+smoke evidence",
            "unsupported features and external caveats both visible",
            "training_eligible False",
        ),
    )


def _block(decision: str, *, note: str, **kw) -> IdeaLabWorkflowRecord:
    return IdeaLabWorkflowRecord(
        decision=decision,
        flow_steps=IDEA_LAB_FLOW_STEPS,
        states=IDEA_LAB_STATES,
        build_it_enabled=kw["build_it_enabled"],
        working_label_enabled=kw["working_label_enabled"],
        unsupported_features_visible=kw["unsupported_features_visible"],
        external_caveats_visible=kw["external_caveats_visible"],
        support_check_passed=kw["support_check_passed"],
        build_verifier_passed=kw["build_verifier_passed"],
        tests_passed=kw["tests_passed"],
        smoke_passed=kw["smoke_passed"],
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(note,),
    )


__all__ = [
    "canonical_flow_steps",
    "canonical_states",
    "evaluate",
    "IDEA_LAB_WORKFLOW_STATUS_TOKENS",
    "IDEA_LAB_STATES",
    "IDEA_LAB_FLOW_STEPS",
    "IdeaLabWorkflowRecord",
]
