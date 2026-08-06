from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Mapping, Sequence

from .v10_contracts import V10ContractError
from .v10_supply_chain import stable_sha256


class Channel(str, Enum):
    AMAZON = "amazon"
    SHOPIFY = "shopify"
    META = "meta"
    TIKTOK = "tiktok"
    LINKEDIN = "linkedin"
    YOUTUBE = "youtube"
    PERFORMANCE_MAX = "performance_max"
    EMAIL = "email"
    LANDING_PAGE = "landing_page"


@dataclass(frozen=True)
class ChannelAsset:
    asset_id: str
    channel: Channel
    strategy_id: str
    audience_id: str
    claim_ids: tuple[str, ...]
    message_proposition: str
    creative_angle: str
    call_to_action: str
    disclosure_locator: str | None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.asset_id,
                self.strategy_id,
                self.audience_id,
                self.message_proposition,
                self.creative_angle,
                self.call_to_action,
            )
        ):
            raise V10ContractError("channel asset fields cannot be empty")
        if not self.claim_ids:
            raise V10ContractError("channel asset requires at least one claim")

    @property
    def expression_digest(self) -> str:
        return stable_sha256(
            {
                "message_proposition": self.message_proposition,
                "creative_angle": self.creative_angle,
                "call_to_action": self.call_to_action,
            }
        )


@dataclass(frozen=True)
class CrossChannelReceipt:
    strategy_consistent: bool
    audience_consistent: bool
    claims_substantiated: bool
    expressions_nonduplicate: bool
    channels: tuple[str, ...]
    receipt_sha256: str


def audit_cross_channel_campaign(
    assets: Sequence[ChannelAsset],
    *,
    substantiated_claims: Mapping[str, str],
) -> CrossChannelReceipt:
    if len(assets) < 2 or len({item.channel for item in assets}) != len(assets):
        raise V10ContractError("cross-channel audit requires distinct channels")
    strategies = {item.strategy_id for item in assets}
    audiences = {item.audience_id for item in assets}
    expressions = [item.expression_digest for item in assets]
    used_claims = {claim for item in assets for claim in item.claim_ids}
    located = all(
        claim in substantiated_claims and substantiated_claims[claim].strip()
        for claim in used_claims
    )
    body = {
        "strategy_consistent": len(strategies) == 1,
        "audience_consistent": len(audiences) == 1,
        "claims_substantiated": located,
        "expressions_nonduplicate": len(expressions) == len(set(expressions)),
        "channels": tuple(sorted(item.channel.value for item in assets)),
    }
    return CrossChannelReceipt(**body, receipt_sha256=stable_sha256(body))


@dataclass(frozen=True)
class PerformanceHypothesis:
    hypothesis_id: str
    intervention: str
    causal_mechanism: str
    primary_metric: str
    baseline_value: float
    minimum_detectable_effect: float
    expected_direction: str
    evidence_locator: str
    pre_registered: bool
    outcome_observed: bool = False

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.hypothesis_id,
                self.intervention,
                self.causal_mechanism,
                self.primary_metric,
                self.evidence_locator,
            )
        ):
            raise V10ContractError("performance hypothesis must be fully specified")
        if self.expected_direction not in {"increase", "decrease"}:
            raise V10ContractError("expected direction must be increase or decrease")
        if not all(
            math.isfinite(value)
            for value in (self.baseline_value, self.minimum_detectable_effect)
        ) or self.minimum_detectable_effect <= 0:
            raise V10ContractError("hypothesis values must be finite with positive MDE")
        if not self.pre_registered:
            raise V10ContractError("performance hypotheses must be pre-registered")


@dataclass(frozen=True)
class ABExperimentPlan:
    experiment_id: str
    hypothesis_id: str
    changed_variable: str
    control_id: str
    treatment_id: str
    primary_metric: str
    randomization_unit: str
    traffic_split: tuple[float, float]
    minimum_sample_size_per_arm: int
    duration_days: int
    ramp_up_days: int
    srm_p_value_floor: float
    automatic_publish: bool = False

    def __post_init__(self) -> None:
        required = (
            self.experiment_id,
            self.hypothesis_id,
            self.changed_variable,
            self.control_id,
            self.treatment_id,
            self.primary_metric,
            self.randomization_unit,
        )
        if not all(value.strip() for value in required):
            raise V10ContractError("A/B plan fields cannot be empty")
        if self.control_id == self.treatment_id:
            raise V10ContractError("control and treatment must be distinct")
        if len(self.traffic_split) != 2 or not math.isclose(sum(self.traffic_split), 1.0):
            raise V10ContractError("A/B traffic split must sum to one")
        if any(value <= 0 for value in self.traffic_split):
            raise V10ContractError("both A/B arms require positive traffic")
        if self.minimum_sample_size_per_arm < 100:
            raise V10ContractError("A/B plan is underpowered by contract")
        if self.duration_days < 1 or not 0 <= self.ramp_up_days < self.duration_days:
            raise V10ContractError("A/B duration and ramp-up are invalid")
        if not 0 < self.srm_p_value_floor < 1:
            raise V10ContractError("SRM threshold must be in (0,1)")
        if self.automatic_publish:
            raise V10ContractError("experiment winners require human release")


@dataclass(frozen=True)
class CreativeFatiguePlan:
    plan_id: str
    leading_metric: str
    lagging_metric: str
    lookback_days: int
    leading_decline_threshold: float
    lagging_decline_threshold: float
    minimum_impressions: int
    refresh_actions: tuple[str, ...]
    protected_holdout_fraction: float

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.plan_id, self.leading_metric, self.lagging_metric)
        ) or not self.refresh_actions:
            raise V10ContractError("fatigue plan requires metrics and refresh actions")
        if self.lookback_days < 2 or self.minimum_impressions < 100:
            raise V10ContractError("fatigue plan observation window is insufficient")
        for value in (
            self.leading_decline_threshold,
            self.lagging_decline_threshold,
            self.protected_holdout_fraction,
        ):
            if not math.isfinite(value) or not 0 < value < 1:
                raise V10ContractError("fatigue thresholds must be in (0,1)")

    def refresh_required(
        self, *, impressions: int, leading_decline: float, lagging_decline: float
    ) -> bool:
        return impressions >= self.minimum_impressions and (
            leading_decline >= self.leading_decline_threshold
            or lagging_decline >= self.lagging_decline_threshold
        )


@dataclass(frozen=True)
class AudienceLearningPlan:
    plan_id: str
    audience_id: str
    prior_hypothesis: str
    allowed_signals: tuple[str, ...]
    update_rule: str
    minimum_evidence_count: int
    forbidden_sensitive_attributes: tuple[str, ...]
    human_approval_required: bool

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.plan_id,
                self.audience_id,
                self.prior_hypothesis,
                self.update_rule,
            )
        ) or not self.allowed_signals or not self.forbidden_sensitive_attributes:
            raise V10ContractError("audience learning contract is incomplete")
        if self.minimum_evidence_count < 2 or not self.human_approval_required:
            raise V10ContractError("audience updates require evidence and human approval")
        overlap = {
            item.lower() for item in self.allowed_signals
        } & {item.lower() for item in self.forbidden_sensitive_attributes}
        if overlap:
            raise V10ContractError("sensitive attributes cannot be learning signals")

    def update_admitted(self, evidence_count: int, human_approved: bool) -> bool:
        return evidence_count >= self.minimum_evidence_count and human_approved


def planned_gtm_skill_card() -> Mapping[str, object]:
    body = {
        "schema": "ProofLaunch4AGtmSkillCardV1",
        "execution_status": "output_contracts_verified_distillation_not_executed",
        "distilled_skills": None,
        "trained_adapter": None,
        "five_rater_scores": None,
        "mean_rating": None,
        "publishable_rate": None,
        "frozen_employee_v1": None,
        "promotion_eligible": False,
        "truth_boundary": (
            "Cross-channel and learning-plan mechanics are verified. No professional "
            "skill distillation, five-rater 4A evaluation or model-quality result is claimed."
        ),
    }
    return {**body, "card_sha256": stable_sha256(body)}
