from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Mapping, Sequence

from .v10_contracts import V10ContractError
from .v10_supply_chain import stable_sha256


_HEX = frozenset("0123456789abcdef")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise V10ContractError(f"{field_name} must be a lowercase SHA-256")


def _require_unit(value: float, field_name: str) -> None:
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise V10ContractError(f"{field_name} must be in the unit interval")


class RewardDimension(str, Enum):
    EVIDENCE = "evidence"
    STRATEGY = "strategy"
    CREATIVE = "creative"
    COPY = "copy"
    IDENTITY = "identity"
    BRAND = "brand"
    OCR = "ocr"
    TEMPORAL = "temporal"
    CHANNEL = "channel"
    SAFETY = "safety"
    EFFICIENCY = "efficiency"
    DIVERSITY = "diversity"
    STOP = "stop"


@dataclass(frozen=True)
class RewardVector:
    candidate_id: str
    values: Mapping[RewardDimension, float]
    evidence_locators: Mapping[RewardDimension, str]
    observed: bool

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise V10ContractError("reward candidate identity is required")
        if set(self.values) != set(RewardDimension):
            raise V10ContractError("reward vector must contain every dimension exactly once")
        if set(self.evidence_locators) != set(RewardDimension):
            raise V10ContractError("every reward dimension needs an evidence locator")
        for dimension, value in self.values.items():
            _require_unit(value, dimension.value)
            if not self.evidence_locators[dimension].strip():
                raise V10ContractError("reward evidence locators cannot be empty")

    @property
    def digest(self) -> str:
        return stable_sha256(
            {
                "candidate_id": self.candidate_id,
                "values": {key.value: self.values[key] for key in RewardDimension},
                "evidence_locators": {
                    key.value: self.evidence_locators[key] for key in RewardDimension
                },
                "observed": self.observed,
            }
        )


@dataclass(frozen=True)
class NormalizationBounds:
    lower: Mapping[RewardDimension, float]
    upper: Mapping[RewardDimension, float]

    def __post_init__(self) -> None:
        if set(self.lower) != set(RewardDimension) or set(self.upper) != set(
            RewardDimension
        ):
            raise V10ContractError("normalization bounds must cover every reward")
        for dimension in RewardDimension:
            low = self.lower[dimension]
            high = self.upper[dimension]
            if not all(math.isfinite(value) for value in (low, high)) or low >= high:
                raise V10ContractError("reward normalization bounds must be finite and ordered")


def normalize_reward_values(
    raw: Mapping[RewardDimension, float], bounds: NormalizationBounds
) -> dict[RewardDimension, float]:
    if set(raw) != set(RewardDimension):
        raise V10ContractError("raw reward vector is incomplete")
    normalized = {}
    for dimension in RewardDimension:
        value = raw[dimension]
        if not math.isfinite(value):
            raise V10ContractError("raw rewards must be finite")
        low, high = bounds.lower[dimension], bounds.upper[dimension]
        normalized[dimension] = max(0.0, min(1.0, (value - low) / (high - low)))
    return normalized


@dataclass(frozen=True)
class CalibrationCurve:
    raw_knots: tuple[float, ...]
    calibrated_knots: tuple[float, ...]
    held_out_artifact_sha256: str

    def __post_init__(self) -> None:
        if len(self.raw_knots) < 2 or len(self.raw_knots) != len(self.calibrated_knots):
            raise V10ContractError("calibration knots must align and contain endpoints")
        if tuple(sorted(self.raw_knots)) != self.raw_knots or len(set(self.raw_knots)) != len(
            self.raw_knots
        ):
            raise V10ContractError("raw calibration knots must be strictly increasing")
        if tuple(sorted(self.calibrated_knots)) != self.calibrated_knots:
            raise V10ContractError("calibration mapping must be monotonic")
        for value in (*self.raw_knots, *self.calibrated_knots):
            _require_unit(value, "calibration knot")
        if self.raw_knots[0] != 0 or self.raw_knots[-1] != 1:
            raise V10ContractError("calibration curve must bind zero and one")
        _require_sha256(self.held_out_artifact_sha256, "held_out_artifact_sha256")


def calibrate_probability(value: float, curve: CalibrationCurve) -> float:
    _require_unit(value, "raw reward probability")
    for index in range(1, len(curve.raw_knots)):
        right = curve.raw_knots[index]
        if value <= right:
            left = curve.raw_knots[index - 1]
            ratio = (value - left) / (right - left)
            return curve.calibrated_knots[index - 1] + ratio * (
                curve.calibrated_knots[index] - curve.calibrated_knots[index - 1]
            )
    return curve.calibrated_knots[-1]


@dataclass(frozen=True)
class LexicographicSafetyPolicy:
    hard_floors: Mapping[RewardDimension, float]
    pareto_dimensions: tuple[RewardDimension, ...]
    scalar_flattening_allowed: bool = False

    def __post_init__(self) -> None:
        required = {
            RewardDimension.SAFETY,
            RewardDimension.EVIDENCE,
            RewardDimension.IDENTITY,
            RewardDimension.STOP,
        }
        if set(self.hard_floors) != required:
            raise V10ContractError("lexicographic hard floors are incomplete")
        for dimension, value in self.hard_floors.items():
            _require_unit(value, f"{dimension.value} floor")
        if set(self.pareto_dimensions) != set(RewardDimension) - required:
            raise V10ContractError("Pareto dimensions must cover every non-hard reward")
        if self.scalar_flattening_allowed:
            raise V10ContractError("reward vectors cannot be flattened into one scalar")


def default_safety_policy() -> LexicographicSafetyPolicy:
    hard = {
        RewardDimension.SAFETY: 0.99,
        RewardDimension.EVIDENCE: 0.98,
        RewardDimension.IDENTITY: 0.98,
        RewardDimension.STOP: 0.99,
    }
    return LexicographicSafetyPolicy(
        hard_floors=hard,
        pareto_dimensions=tuple(item for item in RewardDimension if item not in hard),
    )


def _admissible(vector: RewardVector, policy: LexicographicSafetyPolicy) -> bool:
    return all(vector.values[key] >= floor for key, floor in policy.hard_floors.items())


def _dominates(
    left: RewardVector, right: RewardVector, dimensions: Sequence[RewardDimension]
) -> bool:
    return all(left.values[key] >= right.values[key] for key in dimensions) and any(
        left.values[key] > right.values[key] for key in dimensions
    )


def pareto_select(
    vectors: Sequence[RewardVector],
    policy: LexicographicSafetyPolicy | None = None,
) -> tuple[RewardVector, ...]:
    gate = policy or default_safety_policy()
    identifiers = [item.candidate_id for item in vectors]
    if len(identifiers) != len(set(identifiers)):
        raise V10ContractError("candidate identities must be unique")
    admissible = tuple(item for item in vectors if _admissible(item, gate))
    return tuple(
        item
        for item in admissible
        if not any(
            other is not item
            and _dominates(other, item, gate.pareto_dimensions)
            for other in admissible
        )
    )


class FeedbackKind(str, Enum):
    AUDIT = "audit_feedback"
    TOOL_ERROR = "tool_error_feedback"
    HUMAN_CRITIQUE = "human_critique_feedback"


@dataclass(frozen=True)
class RichFeedback:
    kind: FeedbackKind
    visible_feedback: str
    rule_id: str
    evidence_locator: str
    repair_action: str
    approved: bool
    hidden_reasoning_persisted: bool = False

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.visible_feedback,
                self.rule_id,
                self.evidence_locator,
                self.repair_action,
            )
        ):
            raise V10ContractError("rich feedback requires visible, located repair data")
        if self.hidden_reasoning_persisted:
            raise V10ContractError("rich feedback cannot persist hidden reasoning")


def tokenize_rich_feedback(feedback: RichFeedback) -> tuple[str, ...]:
    if feedback.kind is FeedbackKind.HUMAN_CRITIQUE and not feedback.approved:
        raise V10ContractError("human critique must be explicitly approved for training")
    return (
        f"<feedback:{feedback.kind.value}>",
        f"<rule>{feedback.rule_id}</rule>",
        f"<evidence>{feedback.evidence_locator}</evidence>",
        f"<message>{feedback.visible_feedback}</message>",
        f"<repair>{feedback.repair_action}</repair>",
        "</feedback>",
    )


class AlignmentMethod(str, Enum):
    ORPO = "orpo_baseline"
    SIMPO = "simpo_baseline"
    MDPO = "mdpo_multimodal_baseline"
    MICRO_GRPO = "micro_grpo"


@dataclass(frozen=True)
class AlignmentMethodSpec:
    method: AlignmentMethod
    reference_model_required: bool
    pairwise_preferences: bool
    multimodal_conditioned: bool
    online_rollouts: bool
    group_size: int
    objective: str

    def __post_init__(self) -> None:
        if not self.objective.strip() or self.group_size < 1:
            raise V10ContractError("alignment method needs an objective and group size")
        if self.method is AlignmentMethod.MICRO_GRPO:
            if not self.online_rollouts or not 2 <= self.group_size <= 8:
                raise V10ContractError("micro-GRPO requires bounded online groups")
        elif self.group_size != 2 or not self.pairwise_preferences:
            raise V10ContractError("preference baselines require response pairs")
        if self.method is AlignmentMethod.MDPO and not self.multimodal_conditioned:
            raise V10ContractError("MDPO must remain multimodal-conditioned")


def default_alignment_methods() -> tuple[AlignmentMethodSpec, ...]:
    return (
        AlignmentMethodSpec(
            AlignmentMethod.ORPO, False, True, False, False, 2, "sft_plus_odds_ratio"
        ),
        AlignmentMethodSpec(
            AlignmentMethod.SIMPO, False, True, False, False, 2, "length_normalized_margin"
        ),
        AlignmentMethodSpec(
            AlignmentMethod.MDPO, True, True, True, False, 2, "conditional_multimodal_preference"
        ),
        AlignmentMethodSpec(
            AlignmentMethod.MICRO_GRPO, True, False, True, True, 4, "group_relative_policy"
        ),
    )


@dataclass(frozen=True)
class AlignmentBudget:
    wall_clock_seconds: int = 7_200
    hard_stop: bool = True
    unapproved_extension_allowed: bool = False

    def __post_init__(self) -> None:
        if self.wall_clock_seconds != 7_200:
            raise V10ContractError("alignment run budget must be exactly two hours")
        if not self.hard_stop or self.unapproved_extension_allowed:
            raise V10ContractError("alignment budget cannot silently extend")


@dataclass(frozen=True)
class AlignmentMonitorThresholds:
    maximum_reward_proxy_gap: float = 0.10
    maximum_length_correlation: float = 0.15
    maximum_invalid_tool_gain: float = 0.0
    maximum_judge_disagreement: float = 0.10
    maximum_visual_metric_gap: float = 0.08


@dataclass(frozen=True)
class AlignmentMonitorObservation:
    reward_proxy_gap: float
    length_correlation: float
    invalid_tool_gain: float
    judge_disagreement: float
    visual_metric_gap: float

    def __post_init__(self) -> None:
        if any(not math.isfinite(value) for value in asdict(self).values()):
            raise V10ContractError("alignment monitor observations must be finite")


def alignment_monitor_failures(
    observation: AlignmentMonitorObservation,
    thresholds: AlignmentMonitorThresholds | None = None,
) -> tuple[str, ...]:
    gate = thresholds or AlignmentMonitorThresholds()
    failures = []
    if observation.reward_proxy_gap > gate.maximum_reward_proxy_gap:
        failures.append("reward_hacking")
    if abs(observation.length_correlation) > gate.maximum_length_correlation:
        failures.append("length_hacking")
    if observation.invalid_tool_gain > gate.maximum_invalid_tool_gain:
        failures.append("tool_call_hacking")
    if observation.judge_disagreement > gate.maximum_judge_disagreement:
        failures.append("judge_gaming")
    if observation.visual_metric_gap > gate.maximum_visual_metric_gap:
        failures.append("visual_metric_gaming")
    return tuple(failures)


class VerifierKind(str, Enum):
    ADVERSARIAL = "adversarial_verifier"
    HELD_OUT = "held_out_verifier"
    HUMAN = "human_spot_check"


@dataclass(frozen=True)
class VerifierReceipt:
    kind: VerifierKind
    verifier_revision: str
    dataset_sha256: str
    evaluated_count: int
    passed_count: int
    independent: bool
    observed: bool

    def __post_init__(self) -> None:
        if not self.verifier_revision.strip():
            raise V10ContractError("verifier revision is required")
        _require_sha256(self.dataset_sha256, "dataset_sha256")
        if self.evaluated_count < 0 or not 0 <= self.passed_count <= self.evaluated_count:
            raise V10ContractError("verifier counts are invalid")
        if self.observed and (not self.independent or self.evaluated_count == 0):
            raise V10ContractError("observed verifiers must be independent and non-empty")


@dataclass(frozen=True)
class VerifierQuorumPolicy:
    required_kinds: tuple[VerifierKind, ...] = tuple(VerifierKind)
    minimum_human_fraction: float = 0.05
    all_must_pass: bool = True

    def __post_init__(self) -> None:
        if set(self.required_kinds) != set(VerifierKind):
            raise V10ContractError("adversarial, held-out and human verification are mandatory")
        if not 0 < self.minimum_human_fraction <= 1 or not self.all_must_pass:
            raise V10ContractError("verifier quorum must fail closed")


def verifier_quorum_passes(
    receipts: Sequence[VerifierReceipt],
    total_rollouts: int,
    policy: VerifierQuorumPolicy | None = None,
) -> bool:
    gate = policy or VerifierQuorumPolicy()
    if total_rollouts < 1 or {item.kind for item in receipts} != set(gate.required_kinds):
        return False
    if len({item.dataset_sha256 for item in receipts}) != len(receipts):
        return False
    by_kind = {item.kind: item for item in receipts}
    human = by_kind[VerifierKind.HUMAN]
    if human.evaluated_count / total_rollouts < gate.minimum_human_fraction:
        return False
    return all(
        item.observed
        and item.independent
        and item.evaluated_count > 0
        and item.passed_count == item.evaluated_count
        for item in receipts
    )


@dataclass(frozen=True)
class AlignmentRunReceipt:
    method: AlignmentMethod
    training_observed: bool
    rollout_sha256: str | None
    reward_trace_sha256: str | None
    verifier_trace_sha256: str | None
    monitor_failures: tuple[str, ...]
    regression_observed: bool | None

    def __post_init__(self) -> None:
        for field in ("rollout_sha256", "reward_trace_sha256", "verifier_trace_sha256"):
            value = getattr(self, field)
            if value is not None:
                _require_sha256(value, field)


def alignment_promotion_eligible(receipt: AlignmentRunReceipt) -> bool:
    return (
        receipt.training_observed
        and receipt.rollout_sha256 is not None
        and receipt.reward_trace_sha256 is not None
        and receipt.verifier_trace_sha256 is not None
        and not receipt.monitor_failures
        and receipt.regression_observed is False
    )


def planned_alignment_card() -> dict[str, object]:
    return {
        "schema": "ProofLaunchMultiObjectiveAlignmentCardV1",
        "status": "planned_not_executed",
        "training_observed": False,
        "reward_dimensions": [item.value for item in RewardDimension],
        "methods": [item.method.value for item in default_alignment_methods()],
        "policy_gain": None,
        "trajectory_gain": None,
        "visual_gain": None,
        "calibration_gain": None,
        "inference_cost": None,
        "rollout_evidence": None,
        "reward_trace": None,
        "verifier_trace": None,
        "rl_report": None,
        "rl_card": None,
        "selected_adapter": None,
        "promotion_eligible": False,
    }

