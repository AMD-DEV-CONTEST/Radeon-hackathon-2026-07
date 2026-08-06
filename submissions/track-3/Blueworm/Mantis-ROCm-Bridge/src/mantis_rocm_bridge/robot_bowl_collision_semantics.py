"""Authority-neutral robot-bowl collision semantics for WP-G3-CORR-017.

This module is a standard-library-only design and validation artifact.  It
models the two frozen current classifiers and exposes their agreement or
divergence.  It is intentionally not imported by either runtime executor and
does not select a competition safety policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import product
from typing import Iterable


class Stage(str, Enum):
    """Normalized task-stage suffix."""

    PLACE = "place"
    RELEASE = "release"
    RETREAT = "retreat"
    OTHER = "other"


class BowlRelation(str, Enum):
    """Whether the contacted bowl is the currently selected bowl."""

    SELECTED = "selected"
    NONSELECTED = "nonselected"


class RobotGeometry(str, Enum):
    """Robot geometry class participating in one robot-bowl pair."""

    CLAMP = "clamp"
    NONCLAMP = "nonclamp"


class ClampRelation(str, Enum):
    """Relation of a clamp geometry to the current active side."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class ColliderClass(str, Enum):
    """Descriptive bowl-collider class; it is not a policy input today."""

    SOURCE_MESH = "source_mesh_collision"
    COMPETITION_RIM_SUPPORT = "competition_rim_support_collision"
    OTHER = "other"


class Decision(str, Enum):
    """Normalized classification result."""

    ALLOW = "allow"
    FORBID = "forbid"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class ContactContext:
    """Validated normalized inputs for one robot-bowl contact pair."""

    stage: Stage
    bowl_relation: BowlRelation
    robot_geometry: RobotGeometry
    clamp_relation: ClampRelation
    collider_class: ColliderClass

    def __post_init__(self) -> None:
        enum_fields = (
            ("stage", self.stage, Stage),
            ("bowl_relation", self.bowl_relation, BowlRelation),
            ("robot_geometry", self.robot_geometry, RobotGeometry),
            ("clamp_relation", self.clamp_relation, ClampRelation),
            ("collider_class", self.collider_class, ColliderClass),
        )
        for name, value, enum_type in enum_fields:
            if not isinstance(value, enum_type):
                raise ValueError(f"{name} must be a {enum_type.__name__}")

        if self.robot_geometry is RobotGeometry.CLAMP:
            if self.clamp_relation is ClampRelation.NOT_APPLICABLE:
                raise ValueError(
                    "clamp geometry requires active, inactive, or unknown "
                    "clamp_relation"
                )
        elif self.clamp_relation is not ClampRelation.NOT_APPLICABLE:
            raise ValueError(
                "nonclamp geometry requires not_applicable clamp_relation"
            )

    @classmethod
    def from_values(
        cls,
        *,
        stage: str,
        bowl_relation: str,
        robot_geometry: str,
        clamp_relation: str,
        collider_class: str,
    ) -> "ContactContext":
        """Build and validate a context from serialized contract values."""

        try:
            return cls(
                stage=Stage(stage),
                bowl_relation=BowlRelation(bowl_relation),
                robot_geometry=RobotGeometry(robot_geometry),
                clamp_relation=ClampRelation(clamp_relation),
                collider_class=ColliderClass(collider_class),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid robot-bowl contact context: {exc}") from exc


@dataclass(frozen=True)
class MatrixRow:
    """One deterministic row in the exhaustive normalized parity matrix."""

    context: ContactContext
    scripted_expert: Decision
    act_g3: Decision
    shared: Decision


def scripted_expert_decision(context: ContactContext) -> Decision:
    """Project the frozen v131 scripted-expert single-pair semantics.

    The runtime skips the selected bowl.  For a nonselected bowl its
    ``expected_stack_contact`` exception requires place/release stage and an
    active-side clamp for every pair.  Applying this function per pair and
    aggregating with :func:`aggregate_decisions` is equivalent to that
    ``all(...)`` behavior.
    """

    _require_context(context)
    if context.bowl_relation is BowlRelation.SELECTED:
        return Decision.ALLOW
    if (
        context.stage in (Stage.PLACE, Stage.RELEASE)
        and context.robot_geometry is RobotGeometry.CLAMP
        and context.clamp_relation is ClampRelation.ACTIVE
    ):
        return Decision.ALLOW
    return Decision.FORBID


def act_g3_decision(context: ContactContext) -> Decision:
    """Project the frozen current ACT G3 single-pair semantics."""

    _require_context(context)
    if context.robot_geometry is RobotGeometry.CLAMP:
        return Decision.ALLOW
    return Decision.FORBID


def shared_decision(context: ContactContext) -> Decision:
    """Return current agreement, or ``unresolved`` when classifiers differ.

    This function is authority-neutral evidence logic.  It is not an executable
    competition safety policy.
    """

    scripted = scripted_expert_decision(context)
    act = act_g3_decision(context)
    if scripted is act:
        return scripted
    return Decision.UNRESOLVED


def aggregate_decisions(decisions: Iterable[Decision]) -> Decision:
    """Aggregate a nonempty pair set deterministically and fail closed.

    A forbidden pair dominates an unresolved pair, which dominates an all-allow
    batch.  Empty batches and non-Decision values are rejected rather than
    treated as allowed.
    """

    items = tuple(decisions)
    if not items:
        raise ValueError("cannot aggregate an empty decision batch")
    if any(not isinstance(item, Decision) for item in items):
        raise ValueError("decision batch contains a non-Decision value")
    if Decision.FORBID in items:
        return Decision.FORBID
    if Decision.UNRESOLVED in items:
        return Decision.UNRESOLVED
    return Decision.ALLOW


def scripted_expert_batch_decision(
    contexts: Iterable[ContactContext],
) -> Decision:
    """Aggregate the scripted-expert projection across contact pairs."""

    return aggregate_decisions(
        scripted_expert_decision(context) for context in contexts
    )


def act_g3_batch_decision(contexts: Iterable[ContactContext]) -> Decision:
    """Aggregate the ACT G3 projection across contact pairs."""

    return aggregate_decisions(act_g3_decision(context) for context in contexts)


def shared_batch_decision(contexts: Iterable[ContactContext]) -> Decision:
    """Aggregate authority-neutral agreement across contact pairs."""

    return aggregate_decisions(shared_decision(context) for context in contexts)


def exhaustive_parity_matrix() -> tuple[MatrixRow, ...]:
    """Return every valid normalized context in deterministic enum order."""

    contexts: list[ContactContext] = []
    for stage, bowl_relation, robot_geometry, collider_class in product(
        Stage,
        BowlRelation,
        RobotGeometry,
        ColliderClass,
    ):
        clamp_relations = (
            (
                ClampRelation.ACTIVE,
                ClampRelation.INACTIVE,
                ClampRelation.UNKNOWN,
            )
            if robot_geometry is RobotGeometry.CLAMP
            else (ClampRelation.NOT_APPLICABLE,)
        )
        for clamp_relation in clamp_relations:
            contexts.append(
                ContactContext(
                    stage=stage,
                    bowl_relation=bowl_relation,
                    robot_geometry=robot_geometry,
                    clamp_relation=clamp_relation,
                    collider_class=collider_class,
                )
            )
    return tuple(
        MatrixRow(
            context=context,
            scripted_expert=scripted_expert_decision(context),
            act_g3=act_g3_decision(context),
            shared=shared_decision(context),
        )
        for context in contexts
    )


def _require_context(context: ContactContext) -> None:
    if not isinstance(context, ContactContext):
        raise ValueError("context must be a ContactContext")


__all__ = [
    "BowlRelation",
    "ClampRelation",
    "ColliderClass",
    "ContactContext",
    "Decision",
    "MatrixRow",
    "RobotGeometry",
    "Stage",
    "act_g3_batch_decision",
    "act_g3_decision",
    "aggregate_decisions",
    "exhaustive_parity_matrix",
    "scripted_expert_batch_decision",
    "scripted_expert_decision",
    "shared_batch_decision",
    "shared_decision",
]
