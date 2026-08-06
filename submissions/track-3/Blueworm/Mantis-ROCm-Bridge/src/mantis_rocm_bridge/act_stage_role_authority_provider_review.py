"""Pure feasibility model for ACT privileged stage/role authority providers.

This module is deliberately disconnected from the production ACT and scripted
executors.  It reviews provider designs and models fail-closed adjudication of
*already validated* evidence booleans; it does not derive semantic events from
raw time, pose, action, command, or contact values.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


WORK_PACKAGE_ID = "WP-G3-CORR-020"
TERMINAL = (
    "COMPLETE_ACT_STAGE_ROLE_AUTHORITY_PROVIDER_REVIEW_USER_DECISION_REQUIRED"
)
RECOMMENDED_NEXT_INVESTIGATION = (
    "P020-B-FAIL-CLOSED-PHYSICAL-EVENT-OBSERVER"
)
PRODUCTION_PROVIDER_SELECTED = False
RUNTIME_INTEGRATION_AUTHORIZED = False


class AuthorityField(str, Enum):
    """The four privileged fields required by the WP-019 context."""

    STAGE = "stage"
    SELECTED_BOWL = "selected_bowl"
    ACTIVE_SIDE = "active_side"
    RELEASE_TRANSITION = "release_transition"


class CandidateId(str, Enum):
    """User-decision provider candidates in their frozen order."""

    EXPLICIT_TRANSACTION_SUPERVISOR = (
        "P020-A-EXPLICIT-TRANSACTION-SUPERVISOR"
    )
    FAIL_CLOSED_PHYSICAL_EVENT_OBSERVER = (
        "P020-B-FAIL-CLOSED-PHYSICAL-EVENT-OBSERVER"
    )
    NO_PROVIDER_STRICT_FALLBACK = "P020-C-NO-PROVIDER-STRICT-FALLBACK"


class AuthorityQuality(str, Enum):
    EXPLICIT = "explicit"
    INFERRED_BY_FROZEN_PHYSICAL_PREDICATES = (
        "inferred_by_frozen_physical_predicates"
    )
    NONE = "none"


@dataclass(frozen=True)
class CandidateReview:
    """One source-backed provider feasibility result."""

    candidate_id: CandidateId
    summary: str
    authority_quality: AuthorityQuality
    provided_fields: tuple[AuthorityField, ...]
    wp019_compatible_without_revision: bool
    current_act_architecture_compatible: bool
    requires_controller_or_execution_architecture_change: bool
    production_ready_now: bool
    seed1630_continuity_status: str
    primary_risk: str
    required_next_gate: str

    def __post_init__(self) -> None:
        if not self.summary or not self.primary_risk or not self.required_next_gate:
            raise ValueError("candidate review text fields must be nonempty")
        if len(self.provided_fields) != len(set(self.provided_fields)):
            raise ValueError("provided_fields must be unique")
        if self.production_ready_now:
            raise ValueError("WP-020 has no production-ready candidate")


ALL_AUTHORITY_FIELDS = tuple(AuthorityField)


CANDIDATES = MappingProxyType(
    {
        CandidateId.EXPLICIT_TRANSACTION_SUPERVISOR: CandidateReview(
            candidate_id=CandidateId.EXPLICIT_TRANSACTION_SUPERVISOR,
            summary=(
                "A privileged task transaction supervisor owns the ordered "
                "manipulation and emits explicit stage and role events."
            ),
            authority_quality=AuthorityQuality.EXPLICIT,
            provided_fields=ALL_AUTHORITY_FIELDS,
            wp019_compatible_without_revision=True,
            current_act_architecture_compatible=False,
            requires_controller_or_execution_architecture_change=True,
            production_ready_now=False,
            seed1630_continuity_status="available_after_validated_implementation",
            primary_risk=(
                "It hybridizes the autonomous ACT execution and may change "
                "the evaluated policy architecture or behavior."
            ),
            required_next_gate=(
                "Prove whether a non-actuating explicit transaction interface "
                "is possible; otherwise separately authorize an execution-"
                "architecture change."
            ),
        ),
        CandidateId.FAIL_CLOSED_PHYSICAL_EVENT_OBSERVER: CandidateReview(
            candidate_id=CandidateId.FAIL_CLOSED_PHYSICAL_EVENT_OBSERVER,
            summary=(
                "A passive deterministic observer emits authority only after "
                "unique, validated physical-event evidence."
            ),
            authority_quality=(
                AuthorityQuality.INFERRED_BY_FROZEN_PHYSICAL_PREDICATES
            ),
            provided_fields=ALL_AUTHORITY_FIELDS,
            wp019_compatible_without_revision=False,
            current_act_architecture_compatible=True,
            requires_controller_or_execution_architecture_change=False,
            production_ready_now=False,
            seed1630_continuity_status="unproven",
            primary_risk=(
                "Its predicates become a new safety-critical semantic "
                "estimator and ambiguous behavior must fail closed."
            ),
            required_next_gate=(
                "Freeze trace-only predicates and ambiguity semantics, obtain "
                "an explicit WP-019 revision decision, and validate adversarial "
                "traces before runtime use."
            ),
        ),
        CandidateId.NO_PROVIDER_STRICT_FALLBACK: CandidateReview(
            candidate_id=CandidateId.NO_PROVIDER_STRICT_FALLBACK,
            summary=(
                "No provider is created; missing authority keeps every "
                "continuity-dependent Candidate C cell forbidden."
            ),
            authority_quality=AuthorityQuality.NONE,
            provided_fields=(),
            wp019_compatible_without_revision=True,
            current_act_architecture_compatible=True,
            requires_controller_or_execution_architecture_change=False,
            production_ready_now=False,
            seed1630_continuity_status="cannot_supply",
            primary_risk=(
                "It preserves the seed-1630 false-positive path and cannot "
                "establish scripted/ACT Candidate C parity."
            ),
            required_next_gate=(
                "Freeze a separate strict-fallback runtime-integration design "
                "in which missing authority always forbids."
            ),
        ),
    }
)


@dataclass(frozen=True)
class RejectedShortcut:
    shortcut_id: str
    reason: str
    defeated_by: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.shortcut_id or not self.reason or not self.defeated_by:
            raise ValueError("rejected shortcut fields must be nonempty")


REJECTED_SHORTCUTS = (
    RejectedShortcut(
        "policy_step_or_elapsed_time_schedule",
        "Time does not prove manipulation identity or completed release.",
        ("X020-01-TIMING-DRIFT", "X020-06-REGRASP-AFTER-OPEN"),
    ),
    RejectedShortcut(
        "pose_or_task_progress_only",
        "Pose can be produced by a drop, push, or wrong-arm manipulation.",
        ("X020-02-WRONG-BOWL-POSE", "X020-08-RESET-PRESCRIPTION-VERSUS-ACTUAL-BEHAVIOR"),
    ),
    RejectedShortcut(
        "action_or_gripper_command_only",
        "A command may be clipped, delayed, or physically blocked.",
        ("X020-03-COMMAND-READBACK-DIVERGENCE", "X020-06-REGRASP-AFTER-OPEN"),
    ),
    RejectedShortcut(
        "contact_pair_only",
        "Contact may be incidental, simultaneous, or with a nonselected bowl.",
        ("X020-04-INCIDENTAL-OR-MULTIPLE-CONTACT", "X020-05-BIMANUAL-OVERLAP"),
    ),
    RejectedShortcut(
        "policy_emitted_stage_or_role_head",
        "Policy self-declaration is not independent privileged safety authority.",
        ("X020-09-POLICY-SELF-DECLARATION",),
    ),
    RejectedShortcut(
        "per_seed_script_or_replay_oracle",
        "Seed-specific labels overfit evaluation and are not production semantics.",
        ("X020-08-RESET-PRESCRIPTION-VERSUS-ACTUAL-BEHAVIOR",),
    ),
)


@dataclass(frozen=True)
class Counterexample:
    counterexample_id: str
    scenario: str
    candidate_a_effect: str
    candidate_b_effect: str
    candidate_c_effect: str

    def __post_init__(self) -> None:
        values = (
            self.counterexample_id,
            self.scenario,
            self.candidate_a_effect,
            self.candidate_b_effect,
            self.candidate_c_effect,
        )
        if any(not value for value in values):
            raise ValueError("counterexample fields must be nonempty")


COUNTEREXAMPLES = (
    Counterexample(
        "X020-01-TIMING-DRIFT",
        "The learned trajectory reaches a nominal time window early or late.",
        "explicit_event_required",
        "no_authority_from_time",
        "forbid",
    ),
    Counterexample(
        "X020-02-WRONG-BOWL-POSE",
        "A wrong bowl reaches a target-like pose after a push or drop.",
        "transaction_identity_rejects",
        "no_authority_without_unique_identity",
        "forbid",
    ),
    Counterexample(
        "X020-03-COMMAND-READBACK-DIVERGENCE",
        "An open command is clipped, delayed, or mechanically blocked.",
        "completed_event_required",
        "no_authority_without_validated_readback_event",
        "forbid",
    ),
    Counterexample(
        "X020-04-INCIDENTAL-OR-MULTIPLE-CONTACT",
        "One arm contacts selected and nonselected bowls simultaneously.",
        "transaction_scope_rejects_extra_contact",
        "no_authority_on_nonunique_selected_bowl",
        "forbid",
    ),
    Counterexample(
        "X020-05-BIMANUAL-OVERLAP",
        "Both arms manipulate or contact different bowls at the same tick.",
        "requires_explicitly_owned_single_transaction",
        "no_authority_on_nonunique_active_side",
        "forbid",
    ),
    Counterexample(
        "X020-06-REGRASP-AFTER-OPEN",
        "A gripper opens and then recontacts or regrasps before retreat.",
        "new_explicit_event_sequence_required",
        "no_authority_without_unique_adjacent_release",
        "forbid",
    ),
    Counterexample(
        "X020-07-RELEASE-CONTACT-PERSISTS",
        "The exact robot-bowl pair persists from completed release into retreat.",
        "sealed_explicit_release_cache_can_qualify",
        "requires_validated_sealed_continuity",
        "forbid",
    ),
    Counterexample(
        "X020-08-RESET-PRESCRIPTION-VERSUS-ACTUAL-BEHAVIOR",
        "Reset prescribes one bowl and side but ACT acts on another.",
        "explicit_transaction_violation",
        "no_authority_without_observed_unique_match",
        "forbid",
    ),
    Counterexample(
        "X020-09-POLICY-SELF-DECLARATION",
        "A learned head declares a stage inconsistent with physical state.",
        "policy_declaration_not_authority",
        "policy_declaration_not_evidence",
        "forbid",
    ),
    Counterexample(
        "X020-10-MISSING-OR-STALE-CACHE",
        "Release evidence is absent, unsealed, non-adjacent, or stale.",
        "explicit_cache_validation_rejects",
        "no_authority",
        "forbid",
    ),
)


_STAGE_VALUES = frozenset(("place", "release", "retreat", "other"))
_ACTIVE_SIDE_VALUES = frozenset(("left", "right"))


@dataclass(frozen=True)
class AdjudicatedObserverEvidence:
    """Pre-adjudicated booleans for a future trace-only observer prototype.

    No raw numeric signal is accepted here.  The caller must separately freeze
    and validate any physical predicate before setting one of these flags.
    """

    episode_id: str | None
    manipulation_id: int | None
    transition_sequence: int | None
    stage: str | None
    selected_bowl: str | None
    active_side: str | None
    release_transition_sequence: int | None
    source_reset_identity_valid: bool
    selected_bowl_unique: bool
    active_side_unique: bool
    stage_event_validated: bool
    release_event_validated: bool
    current_cache_fresh: bool
    previous_release_cache_sealed: bool
    cache_identity_match: bool
    release_transition_adjacent: bool
    evidence_ambiguous: bool = False
    simultaneous_active_sides: bool = False
    multiple_selected_bowls: bool = False


@dataclass(frozen=True)
class ObserverAuthority:
    episode_id: str
    manipulation_id: int
    transition_sequence: int
    stage: str
    selected_bowl: str
    active_side: str
    release_transition_sequence: int


@dataclass(frozen=True)
class ObserverVerdict:
    authority_granted: bool
    reasons: tuple[str, ...]
    authority: ObserverAuthority | None

    def __post_init__(self) -> None:
        if self.authority_granted != (self.authority is not None):
            raise ValueError("authority_granted must match authority presence")
        if self.authority_granted and self.reasons:
            raise ValueError("granted authority cannot carry rejection reasons")
        if not self.authority_granted and not self.reasons:
            raise ValueError("rejected authority must explain why")


def adjudicate_passive_observer_evidence(
    evidence: AdjudicatedObserverEvidence,
) -> ObserverVerdict:
    """Fail closed over already-adjudicated evidence for Candidate B.

    This is not a runtime stage estimator.  It is a pure completeness and
    ambiguity gate for a possible later trace-only design.
    """

    if not isinstance(evidence, AdjudicatedObserverEvidence):
        raise TypeError("evidence must be AdjudicatedObserverEvidence")
    reasons: list[str] = []
    if not isinstance(evidence.episode_id, str) or not evidence.episode_id:
        reasons.append("episode_id_missing")
    if (
        isinstance(evidence.manipulation_id, bool)
        or not isinstance(evidence.manipulation_id, int)
        or evidence.manipulation_id <= 0
    ):
        reasons.append("manipulation_id_missing")
    if (
        isinstance(evidence.transition_sequence, bool)
        or not isinstance(evidence.transition_sequence, int)
        or evidence.transition_sequence < 0
    ):
        reasons.append("transition_sequence_missing")
    if evidence.stage not in _STAGE_VALUES:
        reasons.append("stage_missing_or_invalid")
    if (
        not isinstance(evidence.selected_bowl, str)
        or not evidence.selected_bowl.startswith("bowl")
        or not evidence.selected_bowl[4:]
    ):
        reasons.append("selected_bowl_missing_or_invalid")
    if evidence.active_side not in _ACTIVE_SIDE_VALUES:
        reasons.append("active_side_missing_or_invalid")
    if (
        isinstance(evidence.release_transition_sequence, bool)
        or not isinstance(evidence.release_transition_sequence, int)
        or evidence.release_transition_sequence < 0
    ):
        reasons.append("release_transition_sequence_missing")

    boolean_requirements = (
        ("source_reset_identity_unverified", evidence.source_reset_identity_valid),
        ("selected_bowl_not_unique", evidence.selected_bowl_unique),
        ("active_side_not_unique", evidence.active_side_unique),
        ("stage_event_unvalidated", evidence.stage_event_validated),
        ("release_event_unvalidated", evidence.release_event_validated),
        ("current_cache_stale", evidence.current_cache_fresh),
        (
            "previous_release_cache_unsealed",
            evidence.previous_release_cache_sealed,
        ),
        ("cache_identity_mismatch", evidence.cache_identity_match),
        (
            "release_transition_not_adjacent",
            evidence.release_transition_adjacent,
        ),
    )
    for reason, passed in boolean_requirements:
        if passed is not True:
            reasons.append(reason)
    if evidence.evidence_ambiguous:
        reasons.append("evidence_ambiguous")
    if evidence.simultaneous_active_sides:
        reasons.append("simultaneous_active_sides")
    if evidence.multiple_selected_bowls:
        reasons.append("multiple_selected_bowls")

    if reasons:
        return ObserverVerdict(
            authority_granted=False,
            reasons=tuple(reasons),
            authority=None,
        )
    assert evidence.episode_id is not None
    assert evidence.manipulation_id is not None
    assert evidence.transition_sequence is not None
    assert evidence.stage is not None
    assert evidence.selected_bowl is not None
    assert evidence.active_side is not None
    assert evidence.release_transition_sequence is not None
    return ObserverVerdict(
        authority_granted=True,
        reasons=(),
        authority=ObserverAuthority(
            episode_id=evidence.episode_id,
            manipulation_id=evidence.manipulation_id,
            transition_sequence=evidence.transition_sequence,
            stage=evidence.stage,
            selected_bowl=evidence.selected_bowl,
            active_side=evidence.active_side,
            release_transition_sequence=evidence.release_transition_sequence,
        ),
    )


def decision_gate() -> Mapping[str, Any]:
    """Return the frozen pending-user-decision boundary."""

    return MappingProxyType(
        {
            "status": "PENDING_USER_SELECTION",
            "recommended_next_investigation": RECOMMENDED_NEXT_INVESTIGATION,
            "recommendation_scope": (
                "trace-only predicate and ambiguity design, not production "
                "provider selection"
            ),
            "production_provider_selected": PRODUCTION_PROVIDER_SELECTED,
            "runtime_integration_authorized": RUNTIME_INTEGRATION_AUTHORIZED,
            "no_runtime_implementation_gate_open": True,
        }
    )


def counterexample_ids() -> tuple[str, ...]:
    return tuple(row.counterexample_id for row in COUNTEREXAMPLES)


def shortcut_counterexample_coverage() -> Mapping[str, tuple[str, ...]]:
    return MappingProxyType(
        {row.shortcut_id: row.defeated_by for row in REJECTED_SHORTCUTS}
    )


__all__ = [
    "ALL_AUTHORITY_FIELDS",
    "CANDIDATES",
    "COUNTEREXAMPLES",
    "PRODUCTION_PROVIDER_SELECTED",
    "RECOMMENDED_NEXT_INVESTIGATION",
    "REJECTED_SHORTCUTS",
    "RUNTIME_INTEGRATION_AUTHORIZED",
    "TERMINAL",
    "WORK_PACKAGE_ID",
    "AdjudicatedObserverEvidence",
    "AuthorityField",
    "AuthorityQuality",
    "CandidateId",
    "CandidateReview",
    "Counterexample",
    "ObserverAuthority",
    "ObserverVerdict",
    "RejectedShortcut",
    "adjudicate_passive_observer_evidence",
    "counterexample_ids",
    "decision_gate",
    "shortcut_counterexample_coverage",
]
