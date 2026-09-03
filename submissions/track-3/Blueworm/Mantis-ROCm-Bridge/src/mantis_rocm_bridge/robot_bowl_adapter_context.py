"""Shared static robot-bowl authority context for WP-G3-CORR-019.

This standard-library-only module models the explicit privileged-safety
context required by the user-selected Candidate C design baseline.  It is not
imported by either production executor and does not grant runtime authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from .robot_bowl_collision_semantics import (
    BowlRelation,
    ClampRelation,
    ColliderClass,
    ContactContext,
    Decision,
    RobotGeometry,
    Stage,
    aggregate_decisions,
    exhaustive_parity_matrix,
    shared_decision,
)
from .robot_bowl_policy_authority_review import (
    CandidateDisposition,
    CandidatePolicy,
    candidate_disposition,
)


AUTHORITY_SCHEMA = "g3_robot_bowl_stage_role_authority_v1"
CONTACT_CACHE_SCHEMA = "g3_robot_bowl_contact_cache_v1"
RELEASE_CACHE_SCHEMA = "g3_robot_bowl_completed_release_cache_v1"
AUTHORITY_PROVIDER_ID = "shared_privileged_safety_authority_v1"
POLICY_ID = CandidatePolicy.RELEASE_CONTINUITY.value
PAIR_SEPARATOR = " <> "
CACHE_SEMANTICS = "most_recent_scene_step"


class ActiveSide(str, Enum):
    """Explicit manipulation side."""

    LEFT = "left"
    RIGHT = "right"


class AdapterSource(str, Enum):
    """Static adapter producing a normalized batch."""

    SCRIPTED = "scripted"
    ACT = "act"


@dataclass(frozen=True)
class ExactPair:
    """One canonical bowl-first robot-bowl geometry-pair identity."""

    bowl_label: str
    robot_label: str

    def __post_init__(self) -> None:
        _parse_bowl_label(self.bowl_label)
        _parse_robot_label(self.robot_label)

    @property
    def identity(self) -> str:
        return f"{self.bowl_label}{PAIR_SEPARATOR}{self.robot_label}"

    @property
    def bowl_entity(self) -> str:
        return _parse_bowl_label(self.bowl_label)[0]

    @property
    def robot_link(self) -> str:
        return _parse_robot_label(self.robot_label)[0]

    @property
    def collider_suffix(self) -> str:
        return _parse_robot_label(self.robot_label)[1]

    @classmethod
    def from_raw(cls, raw_pair: str) -> "ExactPair":
        """Parse either raw entity order and emit a bowl-first identity."""

        if not isinstance(raw_pair, str) or not raw_pair:
            raise ValueError("raw pair must be a nonempty string")
        labels = raw_pair.split(PAIR_SEPARATOR)
        if len(labels) != 2 or any(not label for label in labels):
            raise ValueError("raw pair must contain exactly one ' <> ' separator")
        robot_labels = [label for label in labels if label.startswith("mantis:")]
        bowl_labels = [label for label in labels if _is_bowl_label(label)]
        if len(robot_labels) != 1 or len(bowl_labels) != 1:
            raise ValueError(
                "raw pair must contain exactly one Mantis and one bowl label"
            )
        if robot_labels[0] == bowl_labels[0]:
            raise ValueError("robot and bowl labels must be distinct")
        return cls(bowl_label=bowl_labels[0], robot_label=robot_labels[0])


def canonicalize_pairs(raw_pairs: Iterable[str]) -> tuple[ExactPair, ...]:
    """Validate, deduplicate, and sort an exact-pair collection."""

    if isinstance(raw_pairs, (str, bytes)):
        raise ValueError("raw_pairs must be an iterable of pair strings")
    try:
        parsed = tuple(ExactPair.from_raw(pair) for pair in raw_pairs)
    except TypeError as exc:
        raise ValueError("raw_pairs must be iterable") from exc
    by_identity = {pair.identity: pair for pair in parsed}
    return tuple(by_identity[key] for key in sorted(by_identity))


@dataclass(frozen=True)
class ContactCache:
    """Validated exact-pair cache from one most-recent scene step."""

    source_physics_step: int
    exact_pairs: tuple[ExactPair, ...]
    cache_semantics: str = CACHE_SEMANTICS

    def __post_init__(self) -> None:
        _require_nonnegative_int(self.source_physics_step, "source_physics_step")
        if self.cache_semantics != CACHE_SEMANTICS:
            raise ValueError(f"cache_semantics must be {CACHE_SEMANTICS!r}")
        _require_canonical_pair_tuple(self.exact_pairs, "exact_pairs")

    @classmethod
    def from_raw_pairs(
        cls,
        *,
        source_physics_step: int,
        raw_pairs: Iterable[str],
    ) -> "ContactCache":
        return cls(
            source_physics_step=source_physics_step,
            exact_pairs=canonicalize_pairs(raw_pairs),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CONTACT_CACHE_SCHEMA,
            "cache_semantics": self.cache_semantics,
            "source_physics_step": self.source_physics_step,
            "exact_pairs": [pair.identity for pair in self.exact_pairs],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ContactCache":
        data = _require_mapping(payload, "contact cache")
        _require_exact_keys(
            data,
            {
                "schema",
                "cache_semantics",
                "source_physics_step",
                "exact_pairs",
            },
            "contact cache",
        )
        if data["schema"] != CONTACT_CACHE_SCHEMA:
            raise ValueError("contact cache schema changed")
        return cls(
            source_physics_step=data["source_physics_step"],
            exact_pairs=_pairs_from_serialized(data["exact_pairs"]),
            cache_semantics=data["cache_semantics"],
        )


@dataclass(frozen=True)
class CompletedReleaseCache:
    """A sealed exact-pair cache at one explicit release-completion event."""

    episode_id: str
    manipulation_id: int
    selected_bowl: str
    active_side: ActiveSide
    release_transition_sequence: int
    source_physics_step: int
    exact_pairs: tuple[ExactPair, ...]
    sealed: bool = True
    cache_semantics: str = CACHE_SEMANTICS

    def __post_init__(self) -> None:
        _require_nonempty_str(self.episode_id, "episode_id")
        _require_positive_int(self.manipulation_id, "manipulation_id")
        _require_bowl_entity(self.selected_bowl, "selected_bowl")
        if not isinstance(self.active_side, ActiveSide):
            raise ValueError("active_side must be an ActiveSide")
        _require_nonnegative_int(
            self.release_transition_sequence,
            "release_transition_sequence",
        )
        _require_nonnegative_int(self.source_physics_step, "source_physics_step")
        _require_canonical_pair_tuple(self.exact_pairs, "exact_pairs")
        if not isinstance(self.sealed, bool):
            raise ValueError("sealed must be boolean")
        if self.cache_semantics != CACHE_SEMANTICS:
            raise ValueError(f"cache_semantics must be {CACHE_SEMANTICS!r}")

    @classmethod
    def from_raw_pairs(
        cls,
        *,
        episode_id: str,
        manipulation_id: int,
        selected_bowl: str,
        active_side: ActiveSide,
        release_transition_sequence: int,
        source_physics_step: int,
        raw_pairs: Iterable[str],
        sealed: bool = True,
    ) -> "CompletedReleaseCache":
        return cls(
            episode_id=episode_id,
            manipulation_id=manipulation_id,
            selected_bowl=selected_bowl,
            active_side=active_side,
            release_transition_sequence=release_transition_sequence,
            source_physics_step=source_physics_step,
            exact_pairs=canonicalize_pairs(raw_pairs),
            sealed=sealed,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RELEASE_CACHE_SCHEMA,
            "stage": Stage.RELEASE.value,
            "cache_semantics": self.cache_semantics,
            "episode_id": self.episode_id,
            "manipulation_id": self.manipulation_id,
            "selected_bowl": self.selected_bowl,
            "active_side": self.active_side.value,
            "release_transition_sequence": self.release_transition_sequence,
            "source_physics_step": self.source_physics_step,
            "exact_pairs": [pair.identity for pair in self.exact_pairs],
            "sealed": self.sealed,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CompletedReleaseCache":
        data = _require_mapping(payload, "completed release cache")
        _require_exact_keys(
            data,
            {
                "schema",
                "stage",
                "cache_semantics",
                "episode_id",
                "manipulation_id",
                "selected_bowl",
                "active_side",
                "release_transition_sequence",
                "source_physics_step",
                "exact_pairs",
                "sealed",
            },
            "completed release cache",
        )
        if data["schema"] != RELEASE_CACHE_SCHEMA:
            raise ValueError("completed release cache schema changed")
        if data["stage"] != Stage.RELEASE.value:
            raise ValueError("completed release cache stage must be release")
        try:
            active_side = ActiveSide(data["active_side"])
        except (TypeError, ValueError) as exc:
            raise ValueError("completed release cache active_side is invalid") from exc
        return cls(
            episode_id=data["episode_id"],
            manipulation_id=data["manipulation_id"],
            selected_bowl=data["selected_bowl"],
            active_side=active_side,
            release_transition_sequence=data["release_transition_sequence"],
            source_physics_step=data["source_physics_step"],
            exact_pairs=_pairs_from_serialized(data["exact_pairs"]),
            sealed=data["sealed"],
            cache_semantics=data["cache_semantics"],
        )


@dataclass(frozen=True)
class AuthorityEnvelope:
    """Explicit privileged stage/role/cache authority for one safety sample."""

    episode_id: str
    manipulation_id: int
    transition_sequence: int
    stage: Stage
    selected_bowl: str
    active_side: ActiveSide
    current_contact_cache: ContactCache
    previous_completed_release: CompletedReleaseCache | None = None
    authority_provider_id: str = AUTHORITY_PROVIDER_ID
    authority_schema: str = AUTHORITY_SCHEMA
    policy_id: str = POLICY_ID
    privileged_safety_only: bool = True
    policy_observation_visible: bool = False

    def __post_init__(self) -> None:
        _require_nonempty_str(self.episode_id, "episode_id")
        _require_positive_int(self.manipulation_id, "manipulation_id")
        _require_nonnegative_int(self.transition_sequence, "transition_sequence")
        if not isinstance(self.stage, Stage):
            raise ValueError("stage must be a Stage")
        _require_bowl_entity(self.selected_bowl, "selected_bowl")
        if not isinstance(self.active_side, ActiveSide):
            raise ValueError("active_side must be an ActiveSide")
        if not isinstance(self.current_contact_cache, ContactCache):
            raise ValueError("current_contact_cache must be a ContactCache")
        if (
            self.previous_completed_release is not None
            and not isinstance(
                self.previous_completed_release,
                CompletedReleaseCache,
            )
        ):
            raise ValueError(
                "previous_completed_release must be a CompletedReleaseCache or None"
            )
        if self.authority_provider_id != AUTHORITY_PROVIDER_ID:
            raise ValueError(
                f"authority_provider_id must be {AUTHORITY_PROVIDER_ID!r}"
            )
        if self.authority_schema != AUTHORITY_SCHEMA:
            raise ValueError(f"authority_schema must be {AUTHORITY_SCHEMA!r}")
        if self.policy_id != POLICY_ID:
            raise ValueError(f"policy_id must be {POLICY_ID!r}")
        if self.privileged_safety_only is not True:
            raise ValueError("authority must be privileged-safety-only")
        if self.policy_observation_visible is not False:
            raise ValueError("authority must not be policy-observation-visible")

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_schema": self.authority_schema,
            "authority_provider_id": self.authority_provider_id,
            "policy_id": self.policy_id,
            "privileged_safety_only": self.privileged_safety_only,
            "policy_observation_visible": self.policy_observation_visible,
            "episode_id": self.episode_id,
            "manipulation_id": self.manipulation_id,
            "transition_sequence": self.transition_sequence,
            "stage": self.stage.value,
            "selected_bowl": self.selected_bowl,
            "active_side": self.active_side.value,
            "current_contact_cache": self.current_contact_cache.to_dict(),
            "previous_completed_release": (
                None
                if self.previous_completed_release is None
                else self.previous_completed_release.to_dict()
            ),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AuthorityEnvelope":
        data = _require_mapping(payload, "authority envelope")
        _require_exact_keys(
            data,
            {
                "authority_schema",
                "authority_provider_id",
                "policy_id",
                "privileged_safety_only",
                "policy_observation_visible",
                "episode_id",
                "manipulation_id",
                "transition_sequence",
                "stage",
                "selected_bowl",
                "active_side",
                "current_contact_cache",
                "previous_completed_release",
            },
            "authority envelope",
        )
        try:
            stage = Stage(data["stage"])
            active_side = ActiveSide(data["active_side"])
        except (TypeError, ValueError) as exc:
            raise ValueError("authority stage or active_side is invalid") from exc
        release_payload = data["previous_completed_release"]
        return cls(
            episode_id=data["episode_id"],
            manipulation_id=data["manipulation_id"],
            transition_sequence=data["transition_sequence"],
            stage=stage,
            selected_bowl=data["selected_bowl"],
            active_side=active_side,
            current_contact_cache=ContactCache.from_dict(
                data["current_contact_cache"]
            ),
            previous_completed_release=(
                None
                if release_payload is None
                else CompletedReleaseCache.from_dict(release_payload)
            ),
            authority_provider_id=data["authority_provider_id"],
            authority_schema=data["authority_schema"],
            policy_id=data["policy_id"],
            privileged_safety_only=data["privileged_safety_only"],
            policy_observation_visible=data["policy_observation_visible"],
        )


@dataclass(frozen=True)
class ContinuityCheck:
    """Fail-closed release-continuity result and exact rejection reasons."""

    eligible: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.eligible, bool):
            raise ValueError("eligible must be boolean")
        if not isinstance(self.reasons, tuple) or any(
            not isinstance(reason, str) or not reason for reason in self.reasons
        ):
            raise ValueError("reasons must be a tuple of nonempty strings")
        if self.eligible == bool(self.reasons):
            raise ValueError("eligible continuity must have no rejection reasons")


@dataclass(frozen=True)
class AdaptedPair:
    """One exact pair, its normalized context, and Candidate C decision."""

    exact_pair: ExactPair
    context: ContactContext
    continuity: ContinuityCheck
    decision: Decision


@dataclass(frozen=True)
class AdaptedBatch:
    """A nonempty deterministic batch emitted by one static adapter."""

    adapter_source: AdapterSource
    authority: AuthorityEnvelope
    pairs: tuple[AdaptedPair, ...]
    decision: Decision

    def __post_init__(self) -> None:
        if not isinstance(self.adapter_source, AdapterSource):
            raise ValueError("adapter_source must be an AdapterSource")
        if not isinstance(self.authority, AuthorityEnvelope):
            raise ValueError("authority must be an AuthorityEnvelope")
        if not self.pairs or any(
            not isinstance(pair, AdaptedPair) for pair in self.pairs
        ):
            raise ValueError("adapted batch must contain AdaptedPair values")
        if tuple(
            sorted(self.pairs, key=lambda item: item.exact_pair.identity)
        ) != self.pairs:
            raise ValueError("adapted pairs must be in canonical identity order")
        expected = aggregate_decisions(pair.decision for pair in self.pairs)
        if self.decision is not expected:
            raise ValueError("adapted batch decision does not match pair decisions")


def normalize_stage_label(stage_label: str) -> Stage:
    """Map an explicit scripted label by suffix; never infer from time/state."""

    _require_nonempty_str(stage_label, "stage_label")
    suffix = stage_label.rsplit(":", 1)[-1]
    if suffix in (Stage.PLACE.value, Stage.RELEASE.value, Stage.RETREAT.value):
        return Stage(suffix)
    return Stage.OTHER


def context_for_pair(
    exact_pair: ExactPair,
    authority: AuthorityEnvelope,
) -> ContactContext:
    """Normalize one canonical pair using only explicit authority fields."""

    if not isinstance(exact_pair, ExactPair):
        raise ValueError("exact_pair must be an ExactPair")
    if not isinstance(authority, AuthorityEnvelope):
        raise ValueError("authority must be an AuthorityEnvelope")
    link = exact_pair.robot_link
    robot_side = _robot_side(link)
    if _is_clamp_link(link):
        robot_geometry = RobotGeometry.CLAMP
        if robot_side is None:
            clamp_relation = ClampRelation.UNKNOWN
        elif robot_side == authority.active_side.value:
            clamp_relation = ClampRelation.ACTIVE
        else:
            clamp_relation = ClampRelation.INACTIVE
    else:
        robot_geometry = RobotGeometry.NONCLAMP
        clamp_relation = ClampRelation.NOT_APPLICABLE
    return ContactContext(
        stage=authority.stage,
        bowl_relation=(
            BowlRelation.SELECTED
            if exact_pair.bowl_entity == authority.selected_bowl
            else BowlRelation.NONSELECTED
        ),
        robot_geometry=robot_geometry,
        clamp_relation=clamp_relation,
        collider_class=_collider_class(exact_pair.collider_suffix),
    )


def release_continuity_check(
    *,
    exact_pair: ExactPair,
    context: ContactContext,
    authority: AuthorityEnvelope,
) -> ContinuityCheck:
    """Verify exact, sealed, identity-bound, directly adjacent continuity."""

    if not isinstance(exact_pair, ExactPair):
        raise ValueError("exact_pair must be an ExactPair")
    if not isinstance(context, ContactContext):
        raise ValueError("context must be a ContactContext")
    if not isinstance(authority, AuthorityEnvelope):
        raise ValueError("authority must be an AuthorityEnvelope")

    reasons: list[str] = []
    try:
        conditional = (
            candidate_disposition(
                CandidatePolicy.RELEASE_CONTINUITY,
                context,
            )
            is CandidateDisposition.CONDITIONAL
        )
    except ValueError:
        conditional = False
    if not conditional:
        reasons.append("context_not_candidate_c_conditional")
    release = authority.previous_completed_release
    if release is None:
        reasons.append("previous_completed_release_missing")
        return ContinuityCheck(eligible=False, reasons=tuple(reasons))
    if release.sealed is not True:
        reasons.append("previous_completed_release_unsealed")
    if release.episode_id != authority.episode_id:
        reasons.append("episode_id_mismatch")
    if release.manipulation_id != authority.manipulation_id:
        reasons.append("manipulation_id_mismatch")
    if release.selected_bowl != authority.selected_bowl:
        reasons.append("selected_bowl_mismatch")
    if release.active_side is not authority.active_side:
        reasons.append("active_side_mismatch")
    if authority.transition_sequence != release.release_transition_sequence + 1:
        reasons.append("release_retreat_transition_not_adjacent")
    if (
        authority.current_contact_cache.source_physics_step
        < release.source_physics_step
    ):
        reasons.append("current_cache_precedes_release_cache")
    if exact_pair not in release.exact_pairs:
        reasons.append("exact_pair_absent_from_completed_release_cache")
    return ContinuityCheck(
        eligible=not reasons,
        reasons=tuple(reasons),
    )


def candidate_c_pair_decision(
    *,
    exact_pair: ExactPair,
    context: ContactContext,
    authority: AuthorityEnvelope,
) -> tuple[Decision, ContinuityCheck]:
    """Apply the complete 96-context Candidate C design model."""

    if not isinstance(context, ContactContext):
        raise ValueError("context must be a ContactContext")
    if exact_pair not in authority.current_contact_cache.exact_pairs:
        return (
            Decision.FORBID,
            ContinuityCheck(
                eligible=False,
                reasons=("exact_pair_absent_from_current_contact_cache",),
            ),
        )
    if context != context_for_pair(exact_pair, authority):
        return (
            Decision.FORBID,
            ContinuityCheck(
                eligible=False,
                reasons=("context_pair_authority_mismatch",),
            ),
        )
    current_shared = shared_decision(context)
    if current_shared is not Decision.UNRESOLVED:
        return (
            current_shared,
            ContinuityCheck(
                eligible=False,
                reasons=("context_not_candidate_c_conditional",),
            ),
        )
    disposition = candidate_disposition(
        CandidatePolicy.RELEASE_CONTINUITY,
        context,
    )
    if disposition is not CandidateDisposition.CONDITIONAL:
        return (
            Decision.FORBID,
            ContinuityCheck(
                eligible=False,
                reasons=("context_not_candidate_c_conditional",),
            ),
        )
    continuity = release_continuity_check(
        exact_pair=exact_pair,
        context=context,
        authority=authority,
    )
    return (
        Decision.ALLOW if continuity.eligible else Decision.FORBID,
        continuity,
    )


def adapt_scripted_batch(
    *,
    episode_id: str,
    manipulation_id: int,
    transition_sequence: int,
    stage_label: str,
    selected_bowl: str,
    active_side: ActiveSide,
    current_source_physics_step: int,
    raw_pairs: Iterable[str],
    previous_completed_release: CompletedReleaseCache | None = None,
) -> AdaptedBatch:
    """Adapt explicit scripted stage/role inputs without touching runtime."""

    current_cache = ContactCache.from_raw_pairs(
        source_physics_step=current_source_physics_step,
        raw_pairs=raw_pairs,
    )
    authority = AuthorityEnvelope(
        episode_id=episode_id,
        manipulation_id=manipulation_id,
        transition_sequence=transition_sequence,
        stage=normalize_stage_label(stage_label),
        selected_bowl=selected_bowl,
        active_side=active_side,
        current_contact_cache=current_cache,
        previous_completed_release=previous_completed_release,
    )
    return _adapt_batch(AdapterSource.SCRIPTED, authority)


def adapt_act_batch(
    *,
    authority_payload: Mapping[str, Any] | AuthorityEnvelope,
    raw_pairs: Iterable[str],
) -> AdaptedBatch:
    """Adapt ACT pairs only when an explicit shared authority envelope exists."""

    if isinstance(authority_payload, AuthorityEnvelope):
        authority = authority_payload
    else:
        authority = AuthorityEnvelope.from_dict(authority_payload)
    observed = ContactCache.from_raw_pairs(
        source_physics_step=authority.current_contact_cache.source_physics_step,
        raw_pairs=raw_pairs,
    )
    if observed != authority.current_contact_cache:
        raise ValueError(
            "ACT raw pairs do not match the explicit authority current cache"
        )
    return _adapt_batch(AdapterSource.ACT, authority)


def adapter_parity_fingerprint(batch: AdaptedBatch) -> tuple[Any, ...]:
    """Return adapter-source-neutral normalized evidence for parity checks."""

    if not isinstance(batch, AdaptedBatch):
        raise ValueError("batch must be an AdaptedBatch")
    return (
        batch.authority.to_dict(),
        tuple(
            (
                item.exact_pair.identity,
                item.context.stage.value,
                item.context.bowl_relation.value,
                item.context.robot_geometry.value,
                item.context.clamp_relation.value,
                item.context.collider_class.value,
                item.continuity.eligible,
                item.continuity.reasons,
                item.decision.value,
            )
            for item in batch.pairs
        ),
        batch.decision.value,
    )


def candidate_c_matrix_counts(
    *,
    conditional_continuity_eligible: bool,
) -> dict[Decision, int]:
    """Count the frozen complete Candidate C surface over all 96 contexts."""

    if not isinstance(conditional_continuity_eligible, bool):
        raise ValueError("conditional_continuity_eligible must be boolean")
    counts = {Decision.ALLOW: 0, Decision.FORBID: 0}
    for row in exhaustive_parity_matrix():
        if row.shared is not Decision.UNRESOLVED:
            decision = row.shared
        else:
            disposition = candidate_disposition(
                CandidatePolicy.RELEASE_CONTINUITY,
                row.context,
            )
            decision = (
                Decision.ALLOW
                if disposition is CandidateDisposition.CONDITIONAL
                and conditional_continuity_eligible
                else Decision.FORBID
            )
        counts[decision] += 1
    return counts


def _adapt_batch(
    adapter_source: AdapterSource,
    authority: AuthorityEnvelope,
) -> AdaptedBatch:
    if not authority.current_contact_cache.exact_pairs:
        raise ValueError("cannot adapt an empty robot-bowl contact batch")
    rows: list[AdaptedPair] = []
    for exact_pair in authority.current_contact_cache.exact_pairs:
        context = context_for_pair(exact_pair, authority)
        decision, continuity = candidate_c_pair_decision(
            exact_pair=exact_pair,
            context=context,
            authority=authority,
        )
        rows.append(
            AdaptedPair(
                exact_pair=exact_pair,
                context=context,
                continuity=continuity,
                decision=decision,
            )
        )
    pair_rows = tuple(rows)
    return AdaptedBatch(
        adapter_source=adapter_source,
        authority=authority,
        pairs=pair_rows,
        decision=aggregate_decisions(item.decision for item in pair_rows),
    )


def _is_bowl_label(label: Any) -> bool:
    if not isinstance(label, str) or ":" not in label:
        return False
    entity, remainder = label.split(":", 1)
    return entity.startswith("bowl") and bool(entity[4:]) and bool(remainder)


def _parse_bowl_label(label: Any) -> tuple[str, str]:
    if not _is_bowl_label(label):
        raise ValueError("bowl label must be '<bowl-entity>:<geometry>'")
    entity, geometry = label.split(":", 1)
    return entity, geometry


def _parse_robot_label(label: Any) -> tuple[str, str]:
    if not isinstance(label, str):
        raise ValueError("robot label must be a string")
    fields = label.split(":", 2)
    if (
        len(fields) != 3
        or fields[0] != "mantis"
        or not fields[1]
        or not fields[2]
    ):
        raise ValueError(
            "robot label must be 'mantis:<link>:<collider-suffix>'"
        )
    return fields[1], fields[2]


def _is_clamp_link(link: str) -> bool:
    return link.startswith("left_clamp") or link.startswith("right_clamp")


def _robot_side(link: str) -> str | None:
    if link.startswith("left_"):
        return ActiveSide.LEFT.value
    if link.startswith("right_"):
        return ActiveSide.RIGHT.value
    return None


def _collider_class(suffix: str) -> ColliderClass:
    if suffix == ColliderClass.SOURCE_MESH.value:
        return ColliderClass.SOURCE_MESH
    if suffix == ColliderClass.COMPETITION_RIM_SUPPORT.value:
        return ColliderClass.COMPETITION_RIM_SUPPORT
    return ColliderClass.OTHER


def _pairs_from_serialized(payload: Any) -> tuple[ExactPair, ...]:
    if not isinstance(payload, list) or any(
        not isinstance(item, str) for item in payload
    ):
        raise ValueError("serialized exact_pairs must be a list of strings")
    pairs = canonicalize_pairs(payload)
    if [pair.identity for pair in pairs] != payload:
        raise ValueError(
            "serialized exact_pairs must already be unique canonical order"
        )
    return pairs


def _require_canonical_pair_tuple(
    pairs: Any,
    name: str,
) -> None:
    if not isinstance(pairs, tuple) or any(
        not isinstance(pair, ExactPair) for pair in pairs
    ):
        raise ValueError(f"{name} must be a tuple of ExactPair values")
    identities = [pair.identity for pair in pairs]
    if identities != sorted(set(identities)):
        raise ValueError(f"{name} must be unique canonical identity order")


def _require_mapping(payload: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{name} must be an object")
    return payload


def _require_exact_keys(
    payload: Mapping[str, Any],
    expected: set[str],
    name: str,
) -> None:
    if set(payload) != expected:
        raise ValueError(f"{name} fields changed")


def _require_nonempty_str(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a nonempty string")


def _require_bowl_entity(value: Any, name: str) -> None:
    _require_nonempty_str(value, name)
    if not value.startswith("bowl") or not value[4:]:
        raise ValueError(f"{name} must be an exact bowl entity name")


def _require_nonnegative_int(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def _require_positive_int(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


__all__ = [
    "AUTHORITY_PROVIDER_ID",
    "AUTHORITY_SCHEMA",
    "ActiveSide",
    "AdaptedBatch",
    "AdaptedPair",
    "AdapterSource",
    "CACHE_SEMANTICS",
    "CONTACT_CACHE_SCHEMA",
    "CompletedReleaseCache",
    "ContactCache",
    "ContinuityCheck",
    "ExactPair",
    "PAIR_SEPARATOR",
    "POLICY_ID",
    "RELEASE_CACHE_SCHEMA",
    "AuthorityEnvelope",
    "adapt_act_batch",
    "adapt_scripted_batch",
    "adapter_parity_fingerprint",
    "candidate_c_matrix_counts",
    "candidate_c_pair_decision",
    "canonicalize_pairs",
    "context_for_pair",
    "normalize_stage_label",
    "release_continuity_check",
]
