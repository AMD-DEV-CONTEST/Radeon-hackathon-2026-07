from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from dataclasses import asdict, dataclass, field, replace
from typing import Callable, Mapping, Sequence

from .v10_contracts import EvidenceClass, V10ContractError


@dataclass(frozen=True)
class TwinObservation:
    observation_id: str
    audience: str
    offer: str
    creative: str
    channel: str
    context: str
    treated: bool
    outcome: float
    propensity: float
    observed_at: str
    evidence_class: EvidenceClass
    source_locator: str

    def __post_init__(self) -> None:
        if not self.observation_id.strip() or not self.source_locator.strip():
            raise V10ContractError("twin observations require id and source locator")
        if not math.isfinite(self.outcome):
            raise V10ContractError("twin outcome must be finite")
        if not 0 < self.propensity < 1:
            raise V10ContractError("propensity must be strictly between zero and one")


@dataclass(frozen=True)
class TwinQuery:
    audience: str
    offer: str
    creative: str
    channel: str
    context: str
    seed: int
    minimum_support: int = 20


@dataclass(frozen=True)
class TwinPrediction:
    query: TwinQuery
    predicted_control: float
    predicted_treatment: float
    predicted_uplift: float
    interval_low: float
    interval_high: float
    support: int
    method: str
    drivers: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence_class: EvidenceClass = EvidenceClass.SIMULATED
    schema: str = "ProofLaunchTwinPredictionV10"

    @property
    def display_metric(self) -> str:
        return "predicted uplift"


class CausalMarketTwin:
    """Small, auditable reference estimator with strict data-class isolation.

    This is the deterministic V10 control, not a claim that a learned market
    model has already passed causal validation.
    """

    def __init__(self, observations: Sequence[TwinObservation]) -> None:
        if not observations:
            raise V10ContractError("market twin requires observations")
        ids = {item.observation_id for item in observations}
        if len(ids) != len(observations):
            raise V10ContractError("twin observation ids must be unique")
        self._observations = tuple(observations)

    @staticmethod
    def _distance(item: TwinObservation, query: TwinQuery) -> int:
        return sum(
            left != right
            for left, right in (
                (item.audience, query.audience),
                (item.offer, query.offer),
                (item.creative, query.creative),
                (item.channel, query.channel),
                (item.context, query.context),
            )
        )

    @staticmethod
    def _weighted_mean(values: Sequence[tuple[float, float]]) -> float:
        weight = sum(item[1] for item in values)
        if weight <= 0:
            raise V10ContractError("weighted mean has no support")
        return sum(value * item_weight for value, item_weight in values) / weight

    @staticmethod
    def _quantile(values: Sequence[float], quantile: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1)
        return ordered[max(0, index)]

    def predict(self, query: TwinQuery) -> TwinPrediction:
        eligible = [
            item
            for item in self._observations
            if item.evidence_class
            in {EvidenceClass.OBSERVED, EvidenceClass.CAUSAL}
        ]
        if not eligible:
            raise V10ContractError(
                "synthetic and proxy data cannot drive a causal twin estimate"
            )
        ranked = sorted(
            eligible,
            key=lambda item: (
                self._distance(item, query),
                item.observed_at,
                item.observation_id,
            ),
        )
        local = ranked[: max(query.minimum_support, min(100, len(ranked)))]
        treated = [
            (item.outcome, 1.0 / max(item.propensity, 0.05))
            for item in local
            if item.treated
        ]
        control = [
            (item.outcome, 1.0 / max(1.0 - item.propensity, 0.05))
            for item in local
            if not item.treated
        ]
        if not treated or not control:
            raise V10ContractError("twin estimate requires treated and control support")
        treated_mean = self._weighted_mean(treated)
        control_mean = self._weighted_mean(control)
        uplift = treated_mean - control_mean
        pooled = [item.outcome for item in local]
        centre = statistics.fmean(pooled)
        residual_radius = self._quantile(
            [abs(value - centre) for value in pooled],
            0.90,
        )
        rng = random.Random(query.seed)
        deterministic_jitter = rng.uniform(-1e-12, 1e-12)
        warnings: list[str] = []
        if len(local) < query.minimum_support:
            warnings.append("insufficient local support")
        mean_distance = statistics.fmean(self._distance(item, query) for item in local)
        if mean_distance > 2:
            warnings.append("high domain-shift distance")
        if any(item.evidence_class == EvidenceClass.OBSERVED for item in local):
            warnings.append("observational estimate; run a randomized experiment")
        drivers = tuple(
            name
            for name, query_value in (
                ("audience", query.audience),
                ("offer", query.offer),
                ("creative", query.creative),
                ("channel", query.channel),
                ("context", query.context),
            )
            if sum(getattr(item, name) == query_value for item in local)
            >= len(local) / 2
        )
        return TwinPrediction(
            query=query,
            predicted_control=control_mean,
            predicted_treatment=treated_mean + deterministic_jitter,
            predicted_uplift=uplift + deterministic_jitter,
            interval_low=uplift - residual_radius,
            interval_high=uplift + residual_radius,
            support=len(local),
            method="stabilized_ipw_with_empirical_conformal_radius",
            drivers=drivers,
            warnings=tuple(warnings),
        )


@dataclass(frozen=True)
class CampaignAction:
    action_id: str
    kind: str
    parameters: Mapping[str, str | float | int | bool]
    cost: float
    risk: float

    def __post_init__(self) -> None:
        if not self.action_id.strip() or not self.kind.strip():
            raise V10ContractError("campaign action id and kind are required")
        if self.cost < 0 or not 0 <= self.risk <= 1:
            raise V10ContractError("campaign action cost/risk are invalid")


@dataclass(frozen=True)
class CampaignWorldState:
    state_id: str
    observed: Mapping[str, str | float | int | bool]
    latent: Mapping[str, float]
    predicted_outcomes: Mapping[str, float]
    evidence_class: EvidenceClass

    @property
    def digest(self) -> str:
        payload = json.dumps(
            asdict(self),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TransitionCandidate:
    next_state: CampaignWorldState
    expected_value: float
    uncertainty: float
    rationale: str

    def __post_init__(self) -> None:
        if not math.isfinite(self.expected_value):
            raise V10ContractError("transition value must be finite")
        if not 0 <= self.uncertainty <= 1:
            raise V10ContractError("transition uncertainty must be in [0, 1]")
        if not self.rationale.strip():
            raise V10ContractError("transition requires a decision rationale")


@dataclass(frozen=True)
class PlannedStep:
    action: CampaignAction
    candidate: TransitionCandidate


@dataclass(frozen=True)
class WorldModelRoute:
    steps: tuple[PlannedStep, ...]
    score: float
    stopped_reason: str
    requires_human: bool
    schema: str = "ProofLaunchWorldModelRouteV10"


TransitionModel = Callable[
    [CampaignWorldState, CampaignAction, int],
    TransitionCandidate,
]


class ActionConditionedPlanner:
    """Bounded beam search with evidence and uncertainty stop conditions."""

    def __init__(
        self,
        transition_model: TransitionModel,
        *,
        branch_limit: int = 8,
        beam_width: int = 4,
        depth_limit: int = 3,
        uncertainty_stop: float = 0.35,
    ) -> None:
        if branch_limit < 1 or branch_limit > 8:
            raise V10ContractError("branch_limit must be between one and eight")
        if beam_width < 1 or beam_width > branch_limit:
            raise V10ContractError("beam_width must fit inside branch_limit")
        if depth_limit < 1 or depth_limit > 3:
            raise V10ContractError("depth_limit must be between one and three")
        self.transition_model = transition_model
        self.branch_limit = branch_limit
        self.beam_width = beam_width
        self.depth_limit = depth_limit
        self.uncertainty_stop = uncertainty_stop

    def plan(
        self,
        initial: CampaignWorldState,
        actions: Sequence[CampaignAction],
        *,
        seed: int,
    ) -> WorldModelRoute:
        if not actions:
            raise V10ContractError("planner requires at least one action")
        candidates = tuple(
            sorted(actions, key=lambda item: (item.action_id, item.kind))[
                : self.branch_limit
            ]
        )
        frontier: list[tuple[float, CampaignWorldState, tuple[PlannedStep, ...]]] = [
            (0.0, initial, ())
        ]
        stopped_for_uncertainty = False
        for depth in range(self.depth_limit):
            expanded: list[
                tuple[float, CampaignWorldState, tuple[PlannedStep, ...]]
            ] = []
            for score, state, steps in frontier:
                for offset, action in enumerate(candidates):
                    prediction = self.transition_model(
                        state,
                        action,
                        seed + depth * self.branch_limit + offset,
                    )
                    if prediction.uncertainty > self.uncertainty_stop:
                        stopped_for_uncertainty = True
                        continue
                    step_score = (
                        prediction.expected_value
                        - action.cost
                        - action.risk
                        - prediction.uncertainty
                    )
                    expanded.append(
                        (
                            score + step_score,
                            prediction.next_state,
                            steps + (PlannedStep(action, prediction),),
                        )
                    )
            if not expanded:
                break
            expanded.sort(
                key=lambda item: (
                    -item[0],
                    tuple(step.action.action_id for step in item[2]),
                )
            )
            frontier = expanded[: self.beam_width]
        best = max(
            frontier,
            key=lambda item: (
                item[0],
                tuple(step.action.action_id for step in item[2]),
            ),
        )
        reason = (
            "uncertainty threshold reached; request evidence or experiment"
            if stopped_for_uncertainty
            else "bounded search completed"
        )
        return WorldModelRoute(
            steps=best[2],
            score=best[0],
            stopped_reason=reason,
            requires_human=stopped_for_uncertainty
            or any(step.action.risk >= 0.7 for step in best[2]),
        )


_GENOME_AXES = {
    "big_idea",
    "single_minded_proposition",
    "reasons_to_believe",
    "brand",
    "visual",
    "motion",
    "sound",
    "channel",
    "constraints",
}


@dataclass(frozen=True)
class CampaignGenome:
    genome_id: str
    big_idea: str
    single_minded_proposition: str
    reasons_to_believe: tuple[str, ...]
    brand: Mapping[str, str]
    visual: Mapping[str, str]
    motion: Mapping[str, str]
    sound: Mapping[str, str]
    channel: Mapping[str, str]
    constraints: tuple[str, ...]
    locked_axes: frozenset[str] = frozenset()
    parent_digest: str | None = None
    generation: int = 0

    def __post_init__(self) -> None:
        if not self.genome_id.strip() or not self.big_idea.strip():
            raise V10ContractError("campaign genome id and Big Idea are required")
        if not self.single_minded_proposition.strip():
            raise V10ContractError("single-minded proposition is required")
        unknown_locks = set(self.locked_axes) - _GENOME_AXES
        if unknown_locks:
            raise V10ContractError(f"unknown genome locks: {sorted(unknown_locks)}")

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["locked_axes"] = sorted(self.locked_axes)
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def mutate(self, mutation_id: str, **changes: object) -> CampaignGenome:
        unknown = set(changes) - _GENOME_AXES
        if unknown:
            raise V10ContractError(f"unknown genome axes: {sorted(unknown)}")
        locked = set(changes) & set(self.locked_axes)
        if locked:
            raise V10ContractError(f"cannot mutate locked axes: {sorted(locked)}")
        prior = self.digest
        return replace(
            self,
            genome_id=mutation_id,
            parent_digest=prior,
            generation=self.generation + 1,
            **changes,
        )

    def distance(self, other: CampaignGenome) -> float:
        changed = sum(
            getattr(self, axis) != getattr(other, axis) for axis in _GENOME_AXES
        )
        return changed / len(_GENOME_AXES)


@dataclass(frozen=True)
class ExperimentAssignment:
    unit_id: str
    arm: str
    outcome: float
    preperiod_covariate: float
    segment: str


@dataclass(frozen=True)
class ExperimentReport:
    control_arm: str
    treatment_arm: str
    sample_count: int
    treatment_share: float
    srm_z: float
    srm_passed: bool
    raw_effect: float
    cuped_effect: float
    standard_error: float
    interval_low: float
    interval_high: float
    evidence_class: EvidenceClass
    warnings: tuple[str, ...]
    schema: str = "ProofLaunchExperimentReportV10"


class CausalExperimentAutopilot:
    """Two-arm SRM + CUPED reference analyzer with fail-closed attribution."""

    def analyze(
        self,
        assignments: Sequence[ExperimentAssignment],
        *,
        control_arm: str,
        treatment_arm: str,
        expected_treatment_share: float = 0.5,
        randomized: bool,
    ) -> ExperimentReport:
        if not 0 < expected_treatment_share < 1:
            raise V10ContractError("expected treatment share must be in (0, 1)")
        ids = [item.unit_id for item in assignments]
        if len(ids) != len(set(ids)):
            raise V10ContractError("experiment unit ids must be unique")
        control = [item for item in assignments if item.arm == control_arm]
        treatment = [item for item in assignments if item.arm == treatment_arm]
        if len(control) < 2 or len(treatment) < 2:
            raise V10ContractError("each experiment arm requires at least two units")
        total = len(control) + len(treatment)
        treatment_share = len(treatment) / total
        expected = total * expected_treatment_share
        variance = total * expected_treatment_share * (
            1 - expected_treatment_share
        )
        srm_z = abs(len(treatment) - expected) / math.sqrt(variance)
        srm_passed = srm_z < 3.29

        combined = control + treatment
        x_mean = statistics.fmean(item.preperiod_covariate for item in combined)
        y_mean = statistics.fmean(item.outcome for item in combined)
        covariance = statistics.fmean(
            (item.preperiod_covariate - x_mean) * (item.outcome - y_mean)
            for item in combined
        )
        x_variance = statistics.fmean(
            (item.preperiod_covariate - x_mean) ** 2 for item in combined
        )
        theta = covariance / x_variance if x_variance > 0 else 0.0

        def adjusted(items: Sequence[ExperimentAssignment]) -> list[float]:
            return [
                item.outcome - theta * (item.preperiod_covariate - x_mean)
                for item in items
            ]

        control_adjusted = adjusted(control)
        treatment_adjusted = adjusted(treatment)
        raw_effect = statistics.fmean(item.outcome for item in treatment) - (
            statistics.fmean(item.outcome for item in control)
        )
        cuped_effect = statistics.fmean(treatment_adjusted) - statistics.fmean(
            control_adjusted
        )
        control_variance = statistics.variance(control_adjusted)
        treatment_variance = statistics.variance(treatment_adjusted)
        standard_error = math.sqrt(
            control_variance / len(control)
            + treatment_variance / len(treatment)
        )
        warnings: list[str] = []
        if not randomized:
            warnings.append("assignment was not randomized")
        if not srm_passed:
            warnings.append("sample ratio mismatch")
        evidence_class = (
            EvidenceClass.CAUSAL
            if randomized and srm_passed
            else EvidenceClass.OBSERVED
        )
        return ExperimentReport(
            control_arm=control_arm,
            treatment_arm=treatment_arm,
            sample_count=total,
            treatment_share=treatment_share,
            srm_z=srm_z,
            srm_passed=srm_passed,
            raw_effect=raw_effect,
            cuped_effect=cuped_effect,
            standard_error=standard_error,
            interval_low=cuped_effect - 1.96 * standard_error,
            interval_high=cuped_effect + 1.96 * standard_error,
            evidence_class=evidence_class,
            warnings=tuple(warnings),
        )

