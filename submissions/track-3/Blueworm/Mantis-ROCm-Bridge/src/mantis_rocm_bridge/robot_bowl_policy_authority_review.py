"""Pure-Python policy-authority candidate review for WP-G3-CORR-018.

The functions in this module classify only the 42 contexts that
WP-G3-CORR-017 left unresolved.  They model user-decision candidates and
adapter capability; they do not select or implement a runtime safety policy.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum

from .robot_bowl_collision_semantics import (
    BowlRelation,
    ClampRelation,
    ContactContext,
    Decision,
    RobotGeometry,
    Stage,
    exhaustive_parity_matrix,
    shared_decision,
)


class CandidatePolicy(str, Enum):
    """Frozen user-decision candidates."""

    STRICT_CONSENSUS = "C018-A-STRICT-CONSENSUS"
    CLAMP_ONLY = "C018-B-CLAMP-ONLY"
    RELEASE_CONTINUITY = "C018-C-RELEASE-CONTINUITY"


class CandidateDisposition(str, Enum):
    """Static disposition of one previously unresolved context."""

    ALLOW = "allow"
    FORBID = "forbid"
    CONDITIONAL = "conditional"


class UnresolvedClass(str, Enum):
    """The five predeclared equivalence classes for the 42-cell review."""

    SELECTED_NONCLAMP = "U018-SELECTED-NONCLAMP"
    NONSELECTED_PLACE_RELEASE_INACTIVE_UNKNOWN = (
        "U018-NONSEL-PLACE-RELEASE-INACTIVE-UNKNOWN"
    )
    NONSELECTED_RETREAT_ACTIVE = "U018-NONSEL-RETREAT-ACTIVE"
    NONSELECTED_RETREAT_INACTIVE_UNKNOWN = (
        "U018-NONSEL-RETREAT-INACTIVE-UNKNOWN"
    )
    NONSELECTED_OTHER_ALL_CLAMPS = "U018-NONSEL-OTHER-ALL-CLAMPS"


@dataclass(frozen=True)
class CandidateRow:
    """One unresolved context and all three candidate dispositions."""

    context: ContactContext
    equivalence_class: UnresolvedClass
    strict_consensus: CandidateDisposition
    clamp_only: CandidateDisposition
    release_continuity: CandidateDisposition


@dataclass(frozen=True)
class AdapterGate:
    """Static capability result for a future shared runtime adapter."""

    candidate: CandidatePolicy
    required_context: tuple[str, ...]
    scripted_missing: tuple[str, ...]
    act_missing: tuple[str, ...]
    status: str
    runtime_implementation_authorized: bool = False


def unresolved_contexts() -> tuple[ContactContext, ...]:
    """Return exactly the WP-017 unresolved contexts in deterministic order."""

    return tuple(
        row.context
        for row in exhaustive_parity_matrix()
        if row.shared is Decision.UNRESOLVED
    )


def unresolved_class(context: ContactContext) -> UnresolvedClass:
    """Assign one previously unresolved context to its frozen class."""

    _require_unresolved(context)
    if (
        context.bowl_relation is BowlRelation.SELECTED
        and context.robot_geometry is RobotGeometry.NONCLAMP
    ):
        return UnresolvedClass.SELECTED_NONCLAMP

    if (
        context.bowl_relation is BowlRelation.NONSELECTED
        and context.robot_geometry is RobotGeometry.CLAMP
    ):
        if context.stage in (Stage.PLACE, Stage.RELEASE):
            if context.clamp_relation in (
                ClampRelation.INACTIVE,
                ClampRelation.UNKNOWN,
            ):
                return (
                    UnresolvedClass.NONSELECTED_PLACE_RELEASE_INACTIVE_UNKNOWN
                )
        elif context.stage is Stage.RETREAT:
            if context.clamp_relation is ClampRelation.ACTIVE:
                return UnresolvedClass.NONSELECTED_RETREAT_ACTIVE
            if context.clamp_relation in (
                ClampRelation.INACTIVE,
                ClampRelation.UNKNOWN,
            ):
                return UnresolvedClass.NONSELECTED_RETREAT_INACTIVE_UNKNOWN
        elif context.stage is Stage.OTHER:
            return UnresolvedClass.NONSELECTED_OTHER_ALL_CLAMPS

    raise ValueError("unresolved context is outside the frozen WP-018 classes")


def candidate_disposition(
    candidate: CandidatePolicy,
    context: ContactContext,
) -> CandidateDisposition:
    """Return a static candidate disposition without selecting a policy."""

    if not isinstance(candidate, CandidatePolicy):
        raise ValueError("candidate must be a CandidatePolicy")
    category = unresolved_class(context)

    if candidate is CandidatePolicy.STRICT_CONSENSUS:
        return CandidateDisposition.FORBID

    if candidate is CandidatePolicy.CLAMP_ONLY:
        if context.robot_geometry is RobotGeometry.CLAMP:
            return CandidateDisposition.ALLOW
        return CandidateDisposition.FORBID

    if category is UnresolvedClass.NONSELECTED_RETREAT_ACTIVE:
        return CandidateDisposition.CONDITIONAL
    return CandidateDisposition.FORBID


def resolve_release_continuity_condition(
    context: ContactContext,
    *,
    exact_pair_present_in_completed_release_cache: bool,
) -> Decision:
    """Resolve Candidate C's conditional cell for design validation only.

    ``True`` means the exact raw pair was present in the immediately preceding
    completed release cache.  ``False`` means it was absent or the provenance
    was not established.  This helper is not a runtime policy and is not
    imported by either executor.
    """

    if not isinstance(exact_pair_present_in_completed_release_cache, bool):
        raise ValueError("release-cache continuity flag must be boolean")
    disposition = candidate_disposition(
        CandidatePolicy.RELEASE_CONTINUITY,
        context,
    )
    if disposition is CandidateDisposition.CONDITIONAL:
        return (
            Decision.ALLOW
            if exact_pair_present_in_completed_release_cache
            else Decision.FORBID
        )
    return Decision.FORBID


def candidate_matrix() -> tuple[CandidateRow, ...]:
    """Return the complete deterministic 42-row candidate matrix."""

    rows: list[CandidateRow] = []
    for context in unresolved_contexts():
        rows.append(
            CandidateRow(
                context=context,
                equivalence_class=unresolved_class(context),
                strict_consensus=candidate_disposition(
                    CandidatePolicy.STRICT_CONSENSUS,
                    context,
                ),
                clamp_only=candidate_disposition(
                    CandidatePolicy.CLAMP_ONLY,
                    context,
                ),
                release_continuity=candidate_disposition(
                    CandidatePolicy.RELEASE_CONTINUITY,
                    context,
                ),
            )
        )
    return tuple(rows)


def candidate_counts(
    candidate: CandidatePolicy,
) -> dict[CandidateDisposition, int]:
    """Count dispositions over exactly the 42 reviewed contexts."""

    counts = Counter(
        candidate_disposition(candidate, context)
        for context in unresolved_contexts()
    )
    return {
        disposition: int(counts.get(disposition, 0))
        for disposition in CandidateDisposition
    }


def unresolved_class_counts() -> dict[UnresolvedClass, int]:
    """Count the five frozen equivalence classes."""

    counts = Counter(unresolved_class(context) for context in unresolved_contexts())
    return {
        category: int(counts.get(category, 0))
        for category in UnresolvedClass
    }


def adapter_gate(candidate: CandidatePolicy) -> AdapterGate:
    """Return the frozen preimplementation capability gate for a candidate."""

    if not isinstance(candidate, CandidatePolicy):
        raise ValueError("candidate must be a CandidatePolicy")
    if candidate is CandidatePolicy.CLAMP_ONLY:
        return AdapterGate(
            candidate=candidate,
            required_context=("robot_geometry",),
            scripted_missing=(),
            act_missing=(),
            status="statically_feasible_but_policy_risk_unaccepted",
        )
    if candidate is CandidatePolicy.STRICT_CONSENSUS:
        return AdapterGate(
            candidate=candidate,
            required_context=(
                "stage",
                "bowl_relation",
                "robot_geometry",
                "clamp_relation",
            ),
            scripted_missing=(),
            act_missing=(
                "authoritative_task_stage",
                "selected_bowl",
                "active_side",
            ),
            status="blocked_missing_act_context",
        )
    return AdapterGate(
        candidate=candidate,
        required_context=(
            "stage",
            "bowl_relation",
            "robot_geometry",
            "clamp_relation",
            "exact_pair_identity",
            "previous_completed_release_pair_set",
            "authoritative_release_transition_event",
        ),
        scripted_missing=(
            "versioned_previous_completed_release_pair_set",
        ),
        act_missing=(
            "authoritative_task_stage",
            "selected_bowl",
            "active_side",
            "versioned_previous_completed_release_pair_set",
            "authoritative_release_transition_event",
        ),
        status="blocked_missing_shared_stage_role_and_cache_context",
    )


def _require_unresolved(context: ContactContext) -> None:
    if not isinstance(context, ContactContext):
        raise ValueError("context must be a ContactContext")
    if shared_decision(context) is not Decision.UNRESOLVED:
        raise ValueError("WP-G3-CORR-018 reviews only WP-017 unresolved contexts")


__all__ = [
    "AdapterGate",
    "CandidateDisposition",
    "CandidatePolicy",
    "CandidateRow",
    "UnresolvedClass",
    "adapter_gate",
    "candidate_counts",
    "candidate_disposition",
    "candidate_matrix",
    "resolve_release_continuity_condition",
    "unresolved_class",
    "unresolved_class_counts",
    "unresolved_contexts",
]
