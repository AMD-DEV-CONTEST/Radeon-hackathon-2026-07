"""Offline fail-closed physical-event authority prototype for WP-G3-CORR-021.

The prototype consumes only exact identities, canonical contact-pair strings,
qualitative booleans produced by future versioned extractors, and explicit
ambiguity reasons.  It intentionally has no raw pose, velocity, force,
penetration, command, action, or elapsed-time input and is not imported by a
production executor.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


WORK_PACKAGE_ID = "WP-G3-CORR-021"
TERMINAL = (
    "COMPLETE_ACT_PHYSICAL_EVENT_AUTHORITY_TRACE_DESIGN_FROZEN_"
    "EXTRACTORS_REQUIRED"
)
TRACE_AUTHORITY_SCHEMA = "g3_act_physical_event_authority_trace_v1"
TRACE_PROVIDER_ID = "act_fail_closed_physical_event_observer_trace_v1"
AUTHORITY_QUALITY = "inferred_by_frozen_qualitative_physical_predicates"
WP019_RUNTIME_CONTRACT_REVISED = False
PRODUCTION_PROVIDER_SELECTED = False
RUNTIME_INTEGRATION_AUTHORIZED = False
RAW_EXTRACTORS_FROZEN = False
NUMERIC_THRESHOLDS_FROZEN = False
PAIR_SEPARATOR = " <> "


class LifecycleState(str, Enum):
    """Ordered trace-only manipulation lifecycle."""

    NO_AUTHORITY = "no_authority"
    ACQUIRED = "acquired"
    PLACE = "place"
    RELEASE = "release"
    RETREAT = "retreat"
    INVALIDATED = "invalidated"


class ActiveSide(str, Enum):
    LEFT = "left"
    RIGHT = "right"


class AmbiguityReason(str, Enum):
    """Frozen reasons that withhold or invalidate trace authority."""

    RESET_IDENTITY_UNVERIFIED = "reset_identity_unverified"
    SELECTED_BOWL_MISSING_OR_NONUNIQUE = (
        "selected_bowl_missing_or_nonunique"
    )
    ACTIVE_SIDE_MISSING_OR_NONUNIQUE = "active_side_missing_or_nonunique"
    OBSERVED_BOWL_MISMATCHES_PRESCRIPTION = (
        "observed_bowl_mismatches_prescription"
    )
    OBSERVED_SIDE_MISMATCHES_PRESCRIPTION = (
        "observed_side_mismatches_prescription"
    )
    SIMULTANEOUS_ACTIVE_SIDES = "simultaneous_active_sides"
    MULTIPLE_SELECTED_BOWLS = "multiple_selected_bowls"
    COMMAND_READBACK_DIVERGENCE = "command_readback_divergence"
    MISSING_OR_STALE_CONTACT_CACHE = "missing_or_stale_contact_cache"
    CONFLICTING_SAME_STEP_EVIDENCE = "conflicting_same_step_evidence"
    RELEASE_WITHOUT_PRIOR_PLACE = "release_without_prior_place"
    RETREAT_WITHOUT_ADJACENT_RELEASE = "retreat_without_adjacent_release"
    REGRASP_AFTER_RELEASE = "regrasp_after_release"
    STAGE_REGRESSION_OR_SKIP = "stage_regression_or_skip"
    FORBIDDEN_NONCLAMP_COLLISION = "forbidden_nonclamp_collision"
    RAW_EXTRACTOR_CONTRACT_MISSING = "raw_extractor_contract_missing"


@dataclass(frozen=True)
class QualitativeEvidenceFrame:
    """One already-adjudicated trace frame.

    Every physical predicate is qualitative.  ``source_physics_step`` and
    ``frame_sequence`` provide identity, freshness, and ordering only; the
    observer never maps a schedule or duration to a stage.
    """

    episode_id: str
    manipulation_id: int
    frame_id: str
    frame_sequence: int
    source_physics_step: int
    expected_selected_bowl: str
    expected_active_side: ActiveSide
    observed_selected_bowl: str | None
    observed_active_side: ActiveSide | None
    manipulation_evidence_present: bool
    reset_identity_verified: bool
    selected_bowl_unique: bool
    active_side_unique: bool
    selected_grasp_verified: bool
    placement_support_verified: bool
    gripper_open_readback_verified: bool
    selected_grasp_released_verified: bool
    post_release_support_verified: bool
    retreat_separation_verified: bool
    selected_bowl_remains_released_verified: bool
    current_cache_fresh: bool
    current_exact_pairs: tuple[str, ...]
    ambiguity_reasons: tuple[AmbiguityReason, ...] = ()
    regrasp_after_release: bool = False
    forbidden_nonclamp_collision: bool = False

    def __post_init__(self) -> None:
        _require_nonempty_str(self.episode_id, "episode_id")
        _require_positive_int(self.manipulation_id, "manipulation_id")
        _require_nonempty_str(self.frame_id, "frame_id")
        _require_nonnegative_int(self.frame_sequence, "frame_sequence")
        _require_nonnegative_int(
            self.source_physics_step,
            "source_physics_step",
        )
        _require_bowl(self.expected_selected_bowl, "expected_selected_bowl")
        if not isinstance(self.expected_active_side, ActiveSide):
            raise ValueError("expected_active_side must be an ActiveSide")
        if self.observed_selected_bowl is not None:
            _require_bowl(
                self.observed_selected_bowl,
                "observed_selected_bowl",
            )
        if (
            self.observed_active_side is not None
            and not isinstance(self.observed_active_side, ActiveSide)
        ):
            raise ValueError("observed_active_side must be an ActiveSide or None")
        boolean_fields = (
            "manipulation_evidence_present",
            "reset_identity_verified",
            "selected_bowl_unique",
            "active_side_unique",
            "selected_grasp_verified",
            "placement_support_verified",
            "gripper_open_readback_verified",
            "selected_grasp_released_verified",
            "post_release_support_verified",
            "retreat_separation_verified",
            "selected_bowl_remains_released_verified",
            "current_cache_fresh",
            "regrasp_after_release",
            "forbidden_nonclamp_collision",
        )
        for name in boolean_fields:
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        _require_canonical_pair_tuple(self.current_exact_pairs)
        if (
            not isinstance(self.ambiguity_reasons, tuple)
            or any(
                not isinstance(reason, AmbiguityReason)
                for reason in self.ambiguity_reasons
            )
            or len(set(self.ambiguity_reasons)) != len(self.ambiguity_reasons)
        ):
            raise ValueError(
                "ambiguity_reasons must be a unique tuple of AmbiguityReason"
            )


@dataclass(frozen=True)
class SealedReleaseRecord:
    """Exact-pair cache sealed at the inferred completed-release event."""

    episode_id: str
    manipulation_id: int
    selected_bowl: str
    active_side: ActiveSide
    release_transition_sequence: int
    source_physics_step: int
    exact_pairs: tuple[str, ...]
    sealed: bool = True

    def __post_init__(self) -> None:
        _require_nonempty_str(self.episode_id, "episode_id")
        _require_positive_int(self.manipulation_id, "manipulation_id")
        _require_bowl(self.selected_bowl, "selected_bowl")
        if not isinstance(self.active_side, ActiveSide):
            raise ValueError("active_side must be an ActiveSide")
        _require_nonnegative_int(
            self.release_transition_sequence,
            "release_transition_sequence",
        )
        _require_nonnegative_int(
            self.source_physics_step,
            "source_physics_step",
        )
        _require_canonical_pair_tuple(self.exact_pairs)
        if self.sealed is not True:
            raise ValueError("release record must be sealed")

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "manipulation_id": self.manipulation_id,
            "selected_bowl": self.selected_bowl,
            "active_side": self.active_side.value,
            "release_transition_sequence": self.release_transition_sequence,
            "source_physics_step": self.source_physics_step,
            "exact_pairs": list(self.exact_pairs),
            "sealed": self.sealed,
        }


@dataclass(frozen=True)
class TraceAuthorityRecord:
    """Trace-only candidate authority, deliberately not a WP-019 envelope."""

    episode_id: str
    manipulation_id: int
    transition_sequence: int
    stage: LifecycleState
    selected_bowl: str
    active_side: ActiveSide
    source_physics_step: int
    current_exact_pairs: tuple[str, ...]
    completed_release: SealedReleaseRecord | None
    authority_schema: str = TRACE_AUTHORITY_SCHEMA
    authority_provider_id: str = TRACE_PROVIDER_ID
    authority_quality: str = AUTHORITY_QUALITY
    trace_only: bool = True
    production_compatible: bool = False

    def __post_init__(self) -> None:
        _require_nonempty_str(self.episode_id, "episode_id")
        _require_positive_int(self.manipulation_id, "manipulation_id")
        _require_bowl(self.selected_bowl, "selected_bowl")
        if not isinstance(self.active_side, ActiveSide):
            raise ValueError("active_side must be an ActiveSide")
        _require_nonnegative_int(
            self.source_physics_step,
            "source_physics_step",
        )
        _require_canonical_pair_tuple(self.current_exact_pairs)
        if self.stage not in (
            LifecycleState.PLACE,
            LifecycleState.RELEASE,
            LifecycleState.RETREAT,
        ):
            raise ValueError("trace authority may emit only place/release/retreat")
        _require_nonnegative_int(
            self.transition_sequence,
            "transition_sequence",
        )
        if self.authority_schema != TRACE_AUTHORITY_SCHEMA:
            raise ValueError("trace authority schema changed")
        if self.authority_provider_id != TRACE_PROVIDER_ID:
            raise ValueError("trace authority provider changed")
        if self.authority_quality != AUTHORITY_QUALITY:
            raise ValueError("trace authority quality changed")
        if self.trace_only is not True or self.production_compatible is not False:
            raise ValueError("trace authority must remain non-production")
        if self.stage in (LifecycleState.RELEASE, LifecycleState.RETREAT):
            if self.completed_release is None:
                raise ValueError("release/retreat authority requires sealed release")
            release = self.completed_release
            if (
                release.episode_id != self.episode_id
                or release.manipulation_id != self.manipulation_id
                or release.selected_bowl != self.selected_bowl
                or release.active_side is not self.active_side
                or release.source_physics_step > self.source_physics_step
            ):
                raise ValueError("completed release identity or ordering mismatch")
            expected_release_sequence = (
                self.transition_sequence
                if self.stage is LifecycleState.RELEASE
                else self.transition_sequence - 1
            )
            if (
                release.release_transition_sequence
                != expected_release_sequence
            ):
                raise ValueError("completed release transition is not adjacent")
        elif self.completed_release is not None:
            raise ValueError("place authority cannot include a completed release")

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_schema": self.authority_schema,
            "authority_provider_id": self.authority_provider_id,
            "authority_quality": self.authority_quality,
            "trace_only": self.trace_only,
            "production_compatible": self.production_compatible,
            "episode_id": self.episode_id,
            "manipulation_id": self.manipulation_id,
            "transition_sequence": self.transition_sequence,
            "stage": self.stage.value,
            "selected_bowl": self.selected_bowl,
            "active_side": self.active_side.value,
            "source_physics_step": self.source_physics_step,
            "current_exact_pairs": list(self.current_exact_pairs),
            "completed_release": (
                None
                if self.completed_release is None
                else self.completed_release.to_dict()
            ),
        }


@dataclass(frozen=True)
class AdjudicationResult:
    state: LifecycleState
    authority: TraceAuthorityRecord | None
    reasons: tuple[str, ...]
    new_transition: bool
    idempotent: bool

    def __post_init__(self) -> None:
        if not isinstance(self.state, LifecycleState):
            raise ValueError("state must be LifecycleState")
        if self.authority is not None and not isinstance(
            self.authority,
            TraceAuthorityRecord,
        ):
            raise ValueError("authority must be TraceAuthorityRecord or None")
        if (
            not isinstance(self.reasons, tuple)
            or any(not isinstance(reason, str) or not reason for reason in self.reasons)
        ):
            raise ValueError("reasons must be nonempty strings")
        if not isinstance(self.new_transition, bool) or not isinstance(
            self.idempotent,
            bool,
        ):
            raise ValueError("result flags must be boolean")
        if self.new_transition and self.idempotent:
            raise ValueError("a transition cannot be idempotent")
        if self.state is LifecycleState.INVALIDATED and self.authority is not None:
            raise ValueError("invalidated state cannot emit authority")


COUNTEREXAMPLE_EXPECTED_EFFECTS: Mapping[str, str] = MappingProxyType(
    {
        "X021-01-TIME-ONLY": "no_authority",
        "X021-02-COMMAND-ONLY": "no_authority",
        "X021-03-CONTACT-ONLY": "no_authority",
        "X021-04-WRONG-BOWL-OR-SIDE": "invalidate",
        "X021-05-BIMANUAL-OR-MULTIBOWL": "invalidate",
        "X021-06-RELEASE-WITHOUT-PLACE": "invalidate",
        "X021-07-REGRASP": "invalidate",
        "X021-08-STALE-OR-CONFLICTING-CACHE": "invalidate",
        "X021-09-RETREAT-COMMAND-WITHOUT-MOTION": "no_authority",
        "X021-10-POLICY-SELF-DECLARATION": "no_authority",
        "X021-11-SEED1630-SCRIPT-ORACLE": "no_authority",
        "X021-12-NONCLAMP-COLLISION": "invalidate",
    }
)


class PhysicalEventTraceAdjudicator:
    """Deterministic, fail-closed, per-manipulation offline state machine."""

    def __init__(
        self,
        *,
        episode_id: str,
        manipulation_id: int,
        expected_selected_bowl: str,
        expected_active_side: ActiveSide,
    ) -> None:
        _require_nonempty_str(episode_id, "episode_id")
        _require_positive_int(manipulation_id, "manipulation_id")
        _require_bowl(expected_selected_bowl, "expected_selected_bowl")
        if not isinstance(expected_active_side, ActiveSide):
            raise ValueError("expected_active_side must be an ActiveSide")
        self.episode_id = episode_id
        self.manipulation_id = manipulation_id
        self.expected_selected_bowl = expected_selected_bowl
        self.expected_active_side = expected_active_side
        self.state = LifecycleState.NO_AUTHORITY
        self.transition_sequence = -1
        self.sealed_release: SealedReleaseRecord | None = None
        self._last_frame_sequence: int | None = None
        self._last_physics_step: int | None = None
        self._last_fingerprint: tuple[Any, ...] | None = None
        self._last_result: AdjudicationResult | None = None
        self._invalidation_reasons: tuple[str, ...] = ()

    def observe(self, frame: QualitativeEvidenceFrame) -> AdjudicationResult:
        if not isinstance(frame, QualitativeEvidenceFrame):
            raise TypeError("frame must be QualitativeEvidenceFrame")
        identity_reasons = self._identity_reasons(frame)
        if identity_reasons:
            return self._invalidate(frame, identity_reasons)

        fingerprint = frame_fingerprint(frame)
        if self._last_physics_step is not None:
            assert self._last_frame_sequence is not None
            if frame.source_physics_step == self._last_physics_step:
                if fingerprint == self._last_fingerprint:
                    assert self._last_result is not None
                    return replace(
                        self._last_result,
                        new_transition=False,
                        idempotent=True,
                    )
                if self.state is LifecycleState.INVALIDATED:
                    return AdjudicationResult(
                        state=self.state,
                        authority=None,
                        reasons=("manipulation_already_invalidated",)
                        + self._invalidation_reasons,
                        new_transition=False,
                        idempotent=False,
                    )
                return self._invalidate(
                    frame,
                    (
                        AmbiguityReason.CONFLICTING_SAME_STEP_EVIDENCE.value,
                    ),
                )
            if (
                frame.source_physics_step < self._last_physics_step
                or frame.frame_sequence <= self._last_frame_sequence
            ):
                return self._invalidate(
                    frame,
                    (
                        AmbiguityReason.MISSING_OR_STALE_CONTACT_CACHE.value,
                        AmbiguityReason.STAGE_REGRESSION_OR_SKIP.value,
                    ),
                )
        if self.state is LifecycleState.INVALIDATED:
            return AdjudicationResult(
                state=self.state,
                authority=None,
                reasons=("manipulation_already_invalidated",)
                + self._invalidation_reasons,
                new_transition=False,
                idempotent=False,
            )

        explicit_reasons = tuple(
            reason.value for reason in frame.ambiguity_reasons
        )
        if frame.forbidden_nonclamp_collision:
            explicit_reasons += (
                AmbiguityReason.FORBIDDEN_NONCLAMP_COLLISION.value,
            )
        if frame.regrasp_after_release:
            explicit_reasons += (
                AmbiguityReason.REGRASP_AFTER_RELEASE.value,
            )
        if explicit_reasons:
            return self._invalidate(frame, _unique(explicit_reasons))

        if not frame.manipulation_evidence_present:
            if self.state is not LifecycleState.NO_AUTHORITY:
                return self._invalidate(
                    frame,
                    (AmbiguityReason.STAGE_REGRESSION_OR_SKIP.value,),
                )
            return self._remember(
                frame,
                AdjudicationResult(
                    state=self.state,
                    authority=None,
                    reasons=("no_manipulation_evidence",),
                    new_transition=False,
                    idempotent=False,
                ),
            )

        evidence_reasons = self._manipulation_evidence_reasons(frame)
        if evidence_reasons:
            return self._invalidate(frame, evidence_reasons)
        return self._advance(frame)

    def _advance(
        self,
        frame: QualitativeEvidenceFrame,
    ) -> AdjudicationResult:
        release_signals = (
            frame.gripper_open_readback_verified
            or frame.selected_grasp_released_verified
            or frame.post_release_support_verified
        )
        if self.state is LifecycleState.NO_AUTHORITY:
            if frame.retreat_separation_verified:
                return self._invalidate(
                    frame,
                    (
                        AmbiguityReason.RETREAT_WITHOUT_ADJACENT_RELEASE.value,
                    ),
                )
            if release_signals:
                return self._invalidate(
                    frame,
                    (
                        AmbiguityReason.RELEASE_WITHOUT_PRIOR_PLACE.value,
                    ),
                )
            if frame.placement_support_verified and not frame.selected_grasp_verified:
                return self._invalidate(
                    frame,
                    (AmbiguityReason.STAGE_REGRESSION_OR_SKIP.value,),
                )
            if frame.selected_grasp_verified:
                self.state = LifecycleState.ACQUIRED
                return self._remember(
                    frame,
                    AdjudicationResult(
                        state=self.state,
                        authority=None,
                        reasons=("acquisition_verified_no_emitting_stage",),
                        new_transition=True,
                        idempotent=False,
                    ),
                )
            return self._no_transition(frame, "acquisition_incomplete")

        if self.state is LifecycleState.ACQUIRED:
            if frame.retreat_separation_verified:
                return self._invalidate(
                    frame,
                    (
                        AmbiguityReason.RETREAT_WITHOUT_ADJACENT_RELEASE.value,
                    ),
                )
            if release_signals or frame.selected_grasp_released_verified:
                return self._invalidate(
                    frame,
                    (
                        AmbiguityReason.RELEASE_WITHOUT_PRIOR_PLACE.value,
                    ),
                )
            if frame.selected_grasp_verified and frame.placement_support_verified:
                self.state = LifecycleState.PLACE
                self.transition_sequence = 0
                return self._emit(frame, new_transition=True)
            if not frame.selected_grasp_verified:
                return self._invalidate(
                    frame,
                    (AmbiguityReason.STAGE_REGRESSION_OR_SKIP.value,),
                )
            return self._no_transition(frame, "placement_support_unverified")

        if self.state is LifecycleState.PLACE:
            if frame.retreat_separation_verified:
                return self._invalidate(
                    frame,
                    (
                        AmbiguityReason.RETREAT_WITHOUT_ADJACENT_RELEASE.value,
                        AmbiguityReason.STAGE_REGRESSION_OR_SKIP.value,
                    ),
                )
            complete_release = (
                frame.gripper_open_readback_verified
                and frame.selected_grasp_released_verified
                and frame.post_release_support_verified
                and frame.selected_bowl_remains_released_verified
            )
            if complete_release:
                self.state = LifecycleState.RELEASE
                self.transition_sequence += 1
                self.sealed_release = SealedReleaseRecord(
                    episode_id=self.episode_id,
                    manipulation_id=self.manipulation_id,
                    selected_bowl=self.expected_selected_bowl,
                    active_side=self.expected_active_side,
                    release_transition_sequence=self.transition_sequence,
                    source_physics_step=frame.source_physics_step,
                    exact_pairs=frame.current_exact_pairs,
                )
                return self._emit(frame, new_transition=True)
            if release_signals:
                return self._remember(
                    frame,
                    AdjudicationResult(
                        state=self.state,
                        authority=None,
                        reasons=("release_conjunction_incomplete",),
                        new_transition=False,
                        idempotent=False,
                    ),
                )
            if frame.selected_grasp_verified and frame.placement_support_verified:
                return self._emit(frame, new_transition=False)
            return self._remember(
                frame,
                AdjudicationResult(
                    state=self.state,
                    authority=None,
                    reasons=("place_state_no_longer_fully_verified",),
                    new_transition=False,
                    idempotent=False,
                ),
            )

        if self.state is LifecycleState.RELEASE:
            if frame.selected_grasp_verified:
                return self._invalidate(
                    frame,
                    (AmbiguityReason.REGRASP_AFTER_RELEASE.value,),
                )
            release_still_verified = (
                frame.selected_grasp_released_verified
                and frame.post_release_support_verified
                and frame.selected_bowl_remains_released_verified
            )
            if not release_still_verified:
                return self._remember(
                    frame,
                    AdjudicationResult(
                        state=self.state,
                        authority=None,
                        reasons=("completed_release_no_longer_fully_verified",),
                        new_transition=False,
                        idempotent=False,
                    ),
                )
            if frame.retreat_separation_verified:
                self.state = LifecycleState.RETREAT
                self.transition_sequence += 1
                return self._emit(frame, new_transition=True)
            return self._emit(frame, new_transition=False)

        if self.state is LifecycleState.RETREAT:
            if frame.selected_grasp_verified:
                return self._invalidate(
                    frame,
                    (AmbiguityReason.REGRASP_AFTER_RELEASE.value,),
                )
            if not (
                frame.retreat_separation_verified
                and frame.selected_grasp_released_verified
                and frame.post_release_support_verified
                and frame.selected_bowl_remains_released_verified
            ):
                return self._invalidate(
                    frame,
                    (AmbiguityReason.STAGE_REGRESSION_OR_SKIP.value,),
                )
            return self._emit(frame, new_transition=False)

        raise AssertionError("invalidated state handled before transition logic")

    def _identity_reasons(
        self,
        frame: QualitativeEvidenceFrame,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if (
            frame.episode_id != self.episode_id
            or frame.manipulation_id != self.manipulation_id
        ):
            reasons.append("observer_transaction_identity_mismatch")
        if frame.expected_selected_bowl != self.expected_selected_bowl:
            reasons.append(
                AmbiguityReason.OBSERVED_BOWL_MISMATCHES_PRESCRIPTION.value
            )
        if frame.expected_active_side is not self.expected_active_side:
            reasons.append(
                AmbiguityReason.OBSERVED_SIDE_MISMATCHES_PRESCRIPTION.value
            )
        return tuple(reasons)

    def _manipulation_evidence_reasons(
        self,
        frame: QualitativeEvidenceFrame,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if not frame.reset_identity_verified:
            reasons.append(AmbiguityReason.RESET_IDENTITY_UNVERIFIED.value)
        if (
            not frame.selected_bowl_unique
            or frame.observed_selected_bowl is None
        ):
            reasons.append(
                AmbiguityReason.SELECTED_BOWL_MISSING_OR_NONUNIQUE.value
            )
        elif frame.observed_selected_bowl != self.expected_selected_bowl:
            reasons.append(
                AmbiguityReason.OBSERVED_BOWL_MISMATCHES_PRESCRIPTION.value
            )
        if not frame.active_side_unique or frame.observed_active_side is None:
            reasons.append(
                AmbiguityReason.ACTIVE_SIDE_MISSING_OR_NONUNIQUE.value
            )
        elif frame.observed_active_side is not self.expected_active_side:
            reasons.append(
                AmbiguityReason.OBSERVED_SIDE_MISMATCHES_PRESCRIPTION.value
            )
        if not frame.current_cache_fresh:
            reasons.append(
                AmbiguityReason.MISSING_OR_STALE_CONTACT_CACHE.value
            )
        return tuple(reasons)

    def _emit(
        self,
        frame: QualitativeEvidenceFrame,
        *,
        new_transition: bool,
    ) -> AdjudicationResult:
        authority = TraceAuthorityRecord(
            episode_id=self.episode_id,
            manipulation_id=self.manipulation_id,
            transition_sequence=self.transition_sequence,
            stage=self.state,
            selected_bowl=self.expected_selected_bowl,
            active_side=self.expected_active_side,
            source_physics_step=frame.source_physics_step,
            current_exact_pairs=frame.current_exact_pairs,
            completed_release=self.sealed_release,
        )
        return self._remember(
            frame,
            AdjudicationResult(
                state=self.state,
                authority=authority,
                reasons=(),
                new_transition=new_transition,
                idempotent=False,
            ),
        )

    def _no_transition(
        self,
        frame: QualitativeEvidenceFrame,
        reason: str,
    ) -> AdjudicationResult:
        return self._remember(
            frame,
            AdjudicationResult(
                state=self.state,
                authority=None,
                reasons=(reason,),
                new_transition=False,
                idempotent=False,
            ),
        )

    def _invalidate(
        self,
        frame: QualitativeEvidenceFrame,
        reasons: tuple[str, ...],
    ) -> AdjudicationResult:
        self.state = LifecycleState.INVALIDATED
        self._invalidation_reasons = _unique(reasons)
        result = AdjudicationResult(
            state=self.state,
            authority=None,
            reasons=self._invalidation_reasons,
            new_transition=True,
            idempotent=False,
        )
        return self._remember(frame, result)

    def _remember(
        self,
        frame: QualitativeEvidenceFrame,
        result: AdjudicationResult,
    ) -> AdjudicationResult:
        self._last_frame_sequence = frame.frame_sequence
        self._last_physics_step = frame.source_physics_step
        self._last_fingerprint = frame_fingerprint(frame)
        self._last_result = result
        return result


def frame_from_mapping(payload: Mapping[str, Any]) -> QualitativeEvidenceFrame:
    """Strictly parse one JSON fixture frame; unexpected fields are rejected."""

    if not isinstance(payload, Mapping):
        raise ValueError("frame payload must be an object")
    expected = {
        "episode_id",
        "manipulation_id",
        "frame_id",
        "frame_sequence",
        "source_physics_step",
        "expected_selected_bowl",
        "expected_active_side",
        "observed_selected_bowl",
        "observed_active_side",
        "manipulation_evidence_present",
        "reset_identity_verified",
        "selected_bowl_unique",
        "active_side_unique",
        "selected_grasp_verified",
        "placement_support_verified",
        "gripper_open_readback_verified",
        "selected_grasp_released_verified",
        "post_release_support_verified",
        "retreat_separation_verified",
        "selected_bowl_remains_released_verified",
        "current_cache_fresh",
        "current_exact_pairs",
        "ambiguity_reasons",
        "regrasp_after_release",
        "forbidden_nonclamp_collision",
    }
    if set(payload) != expected:
        raise ValueError("fixture frame fields changed")
    try:
        expected_side = ActiveSide(payload["expected_active_side"])
        observed_side = (
            None
            if payload["observed_active_side"] is None
            else ActiveSide(payload["observed_active_side"])
        )
        ambiguity_reasons = tuple(
            AmbiguityReason(reason) for reason in payload["ambiguity_reasons"]
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("fixture enum field is invalid") from exc
    pairs = payload["current_exact_pairs"]
    if not isinstance(pairs, list) or any(
        not isinstance(pair, str) for pair in pairs
    ):
        raise ValueError("current_exact_pairs must be a list of strings")
    return QualitativeEvidenceFrame(
        episode_id=payload["episode_id"],
        manipulation_id=payload["manipulation_id"],
        frame_id=payload["frame_id"],
        frame_sequence=payload["frame_sequence"],
        source_physics_step=payload["source_physics_step"],
        expected_selected_bowl=payload["expected_selected_bowl"],
        expected_active_side=expected_side,
        observed_selected_bowl=payload["observed_selected_bowl"],
        observed_active_side=observed_side,
        manipulation_evidence_present=payload[
            "manipulation_evidence_present"
        ],
        reset_identity_verified=payload["reset_identity_verified"],
        selected_bowl_unique=payload["selected_bowl_unique"],
        active_side_unique=payload["active_side_unique"],
        selected_grasp_verified=payload["selected_grasp_verified"],
        placement_support_verified=payload["placement_support_verified"],
        gripper_open_readback_verified=payload[
            "gripper_open_readback_verified"
        ],
        selected_grasp_released_verified=payload[
            "selected_grasp_released_verified"
        ],
        post_release_support_verified=payload[
            "post_release_support_verified"
        ],
        retreat_separation_verified=payload[
            "retreat_separation_verified"
        ],
        selected_bowl_remains_released_verified=payload[
            "selected_bowl_remains_released_verified"
        ],
        current_cache_fresh=payload["current_cache_fresh"],
        current_exact_pairs=tuple(pairs),
        ambiguity_reasons=ambiguity_reasons,
        regrasp_after_release=payload["regrasp_after_release"],
        forbidden_nonclamp_collision=payload[
            "forbidden_nonclamp_collision"
        ],
    )


def frame_fingerprint(frame: QualitativeEvidenceFrame) -> tuple[Any, ...]:
    """Return a complete immutable fingerprint for same-step idempotence."""

    if not isinstance(frame, QualitativeEvidenceFrame):
        raise TypeError("frame must be QualitativeEvidenceFrame")
    return tuple(getattr(frame, name) for name in frame.__dataclass_fields__)


def _require_canonical_pair_tuple(pairs: Any) -> None:
    if not isinstance(pairs, tuple) or any(
        not isinstance(pair, str) for pair in pairs
    ):
        raise ValueError("current exact pairs must be a tuple of strings")
    if list(pairs) != sorted(set(pairs)):
        raise ValueError("current exact pairs must be unique canonical order")
    for pair in pairs:
        labels = pair.split(PAIR_SEPARATOR)
        if (
            len(labels) != 2
            or not labels[0].startswith("bowl")
            or ":" not in labels[0]
            or not labels[1].startswith("mantis:")
            or labels[1].count(":") < 2
        ):
            raise ValueError(
                "exact pairs must be canonical bowl-first robot-bowl identities"
            )


def _require_nonempty_str(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a nonempty string")


def _require_bowl(value: Any, name: str) -> None:
    _require_nonempty_str(value, name)
    if not value.startswith("bowl") or not value[4:]:
        raise ValueError(f"{name} must be an exact bowl identity")


def _require_nonnegative_int(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def _require_positive_int(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


__all__ = [
    "AUTHORITY_QUALITY",
    "COUNTEREXAMPLE_EXPECTED_EFFECTS",
    "NUMERIC_THRESHOLDS_FROZEN",
    "PRODUCTION_PROVIDER_SELECTED",
    "RAW_EXTRACTORS_FROZEN",
    "RUNTIME_INTEGRATION_AUTHORIZED",
    "TERMINAL",
    "TRACE_AUTHORITY_SCHEMA",
    "TRACE_PROVIDER_ID",
    "WORK_PACKAGE_ID",
    "WP019_RUNTIME_CONTRACT_REVISED",
    "ActiveSide",
    "AdjudicationResult",
    "AmbiguityReason",
    "LifecycleState",
    "PhysicalEventTraceAdjudicator",
    "QualitativeEvidenceFrame",
    "SealedReleaseRecord",
    "TraceAuthorityRecord",
    "frame_fingerprint",
    "frame_from_mapping",
]
