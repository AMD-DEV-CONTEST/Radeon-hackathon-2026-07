from __future__ import annotations

import json
import math
import random
import zlib
from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Mapping, Sequence

from .v10_contracts import EvidenceClass, V10ContractError
from .v10_supply_chain import stable_sha256


_HEX = frozenset("0123456789abcdef")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise V10ContractError(f"{field_name} must be a lowercase SHA-256")


def _require_unit(value: float, field_name: str) -> None:
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise V10ContractError(f"{field_name} must be finite and in [0, 1]")


def _require_text_tuple(values: Sequence[str], field_name: str) -> None:
    if any(not value.strip() for value in values) or len(values) != len(set(values)):
        raise V10ContractError(f"{field_name} must contain unique non-empty values")


class WorldStatus(str, Enum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    AWAITING_HUMAN = "awaiting_human_approval"
    TERMINATED = "terminated"


@dataclass(frozen=True)
class CampaignState:
    campaign_id: str
    objective: str
    phase: str
    status: WorldStatus
    owner: str

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.campaign_id, self.objective, self.phase, self.owner)):
            raise V10ContractError("campaign state fields are required")


@dataclass(frozen=True)
class EvidenceState:
    claim_ids: tuple[str, ...]
    supported_claim_ids: tuple[str, ...]
    source_sha256s: tuple[str, ...]
    invalid_claim_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text_tuple(self.claim_ids, "claim_ids")
        _require_text_tuple(self.supported_claim_ids, "supported_claim_ids")
        _require_text_tuple(self.invalid_claim_ids, "invalid_claim_ids")
        if not set(self.supported_claim_ids).issubset(self.claim_ids):
            raise V10ContractError("supported claims must be declared")
        if not set(self.invalid_claim_ids).issubset(self.claim_ids):
            raise V10ContractError("invalid claims must be declared")
        if set(self.supported_claim_ids) & set(self.invalid_claim_ids):
            raise V10ContractError("a claim cannot be supported and invalid")
        for digest in self.source_sha256s:
            _require_sha256(digest, "source_sha256")

    @property
    def support_rate(self) -> float:
        return len(self.supported_claim_ids) / len(self.claim_ids) if self.claim_ids else 0.0


@dataclass(frozen=True)
class AudienceState:
    segment_ids: tuple[str, ...]
    consent_scopes: tuple[str, ...]
    excluded_sensitive_traits: tuple[str, ...]
    evidence_coverage: float

    def __post_init__(self) -> None:
        _require_text_tuple(self.segment_ids, "segment_ids")
        _require_text_tuple(self.consent_scopes, "consent_scopes")
        _require_text_tuple(self.excluded_sensitive_traits, "excluded_sensitive_traits")
        _require_unit(self.evidence_coverage, "audience evidence coverage")


@dataclass(frozen=True)
class MarketState:
    observed_at: str
    signal_ids: tuple[str, ...]
    competitor_ids: tuple[str, ...]
    evidence_class: EvidenceClass

    def __post_init__(self) -> None:
        if not self.observed_at.strip():
            raise V10ContractError("market observation time is required")
        _require_text_tuple(self.signal_ids, "market signal ids")
        _require_text_tuple(self.competitor_ids, "competitor ids")
        if self.evidence_class is EvidenceClass.SIMULATED:
            raise V10ContractError("observed market state cannot be synthetic")


@dataclass(frozen=True)
class BrandState:
    revision: str
    voice: str
    locked_rules: tuple[str, ...]
    approved_claim_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.revision.strip() or not self.voice.strip():
            raise V10ContractError("brand revision and voice are required")
        _require_text_tuple(self.locked_rules, "brand locked rules")
        _require_text_tuple(self.approved_claim_ids, "brand approved claims")


@dataclass(frozen=True)
class CreativeState:
    concept_id: str
    variant_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]
    measured_quality: float

    def __post_init__(self) -> None:
        if not self.concept_id.strip():
            raise V10ContractError("creative concept id is required")
        _require_text_tuple(self.variant_ids, "creative variants")
        _require_text_tuple(self.claim_ids, "creative claims")
        _require_unit(self.measured_quality, "measured creative quality")


@dataclass(frozen=True)
class AssetState:
    artifact_sha256s: tuple[str, ...]
    rights_approved: bool
    visual_identity_locked: bool
    pending_repairs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for digest in self.artifact_sha256s:
            _require_sha256(digest, "artifact_sha256")
        _require_text_tuple(self.pending_repairs, "pending repairs")


@dataclass(frozen=True)
class ChannelState:
    selected_channels: tuple[str, ...]
    ready_channels: tuple[str, ...]
    published_channels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text_tuple(self.selected_channels, "selected channels")
        _require_text_tuple(self.ready_channels, "ready channels")
        _require_text_tuple(self.published_channels, "published channels")
        if not set(self.ready_channels).issubset(self.selected_channels):
            raise V10ContractError("ready channels must be selected")
        if not set(self.published_channels).issubset(self.ready_channels):
            raise V10ContractError("published channels must have been ready")


@dataclass(frozen=True)
class RiskState:
    risk_scores: Mapping[str, float]
    hard_blocks: tuple[str, ...]
    accepted_risks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, value in self.risk_scores.items():
            if not name.strip():
                raise V10ContractError("risk names are required")
            _require_unit(value, f"risk {name}")
        _require_text_tuple(self.hard_blocks, "risk hard blocks")
        _require_text_tuple(self.accepted_risks, "accepted risks")
        if set(self.hard_blocks) & set(self.accepted_risks):
            raise V10ContractError("hard-blocked risk cannot be accepted")


@dataclass(frozen=True)
class MemoryState:
    revision: str
    atom_ids: tuple[str, ...]
    stale_atom_ids: tuple[str, ...]
    conflict_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.revision.strip():
            raise V10ContractError("memory revision is required")
        _require_text_tuple(self.atom_ids, "memory atom ids")
        _require_text_tuple(self.stale_atom_ids, "stale memory ids")
        _require_text_tuple(self.conflict_ids, "memory conflict ids")
        if not set(self.stale_atom_ids).issubset(self.atom_ids):
            raise V10ContractError("stale memory must refer to known atoms")


@dataclass(frozen=True)
class UncertaintyState:
    component_scores: Mapping[str, float]
    escalation_threshold: float = 0.35

    def __post_init__(self) -> None:
        if not self.component_scores:
            raise V10ContractError("uncertainty components are required")
        for name, value in self.component_scores.items():
            _require_unit(value, f"uncertainty {name}")
        _require_unit(self.escalation_threshold, "uncertainty escalation threshold")

    @property
    def maximum(self) -> float:
        return max(self.component_scores.values())


@dataclass(frozen=True)
class CostState:
    budget_usd: float
    spent_usd: float
    projected_usd: float
    generated_tokens: int
    gpu_seconds: int

    def __post_init__(self) -> None:
        values = (self.budget_usd, self.spent_usd, self.projected_usd)
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise V10ContractError("cost values must be finite and non-negative")
        if self.spent_usd > self.budget_usd or self.generated_tokens < 0 or self.gpu_seconds < 0:
            raise V10ContractError("cost state exceeds observed budget or has negative usage")

    @property
    def remaining_usd(self) -> float:
        return self.budget_usd - self.spent_usd


@dataclass(frozen=True)
class CampaignWorldSnapshot:
    campaign: CampaignState
    evidence: EvidenceState
    audience: AudienceState
    market: MarketState
    brand: BrandState
    creative: CreativeState
    assets: AssetState
    channels: ChannelState
    risks: RiskState
    memory: MemoryState
    uncertainty: UncertaintyState
    costs: CostState
    sequence: int = 0

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise V10ContractError("world-state sequence must be non-negative")

    @property
    def digest(self) -> str:
        return stable_sha256(asdict(self))


class WorldActionKind(str, Enum):
    RESEARCH = "research"
    PLAN = "plan"
    CREATIVE = "creative"
    GENERATE = "generate"
    AUDIT = "audit"
    REPAIR = "repair"
    ROLLBACK = "rollback"


_ALLOWED_SCOPES = {
    WorldActionKind.RESEARCH: frozenset({"evidence", "audience", "market", "memory", "uncertainty", "costs"}),
    WorldActionKind.PLAN: frozenset({"campaign", "channels", "uncertainty", "costs"}),
    WorldActionKind.CREATIVE: frozenset({"creative", "uncertainty", "costs"}),
    WorldActionKind.GENERATE: frozenset({"assets", "creative", "uncertainty", "costs"}),
    WorldActionKind.AUDIT: frozenset({"evidence", "assets", "risks", "uncertainty", "costs"}),
    WorldActionKind.REPAIR: frozenset({"creative", "assets", "risks", "uncertainty", "costs"}),
    WorldActionKind.ROLLBACK: frozenset({"campaign", "evidence", "audience", "market", "brand", "creative", "assets", "channels", "risks", "memory", "uncertainty", "costs"}),
}


@dataclass(frozen=True)
class WorldAction:
    action_id: str
    kind: WorldActionKind
    expected_state_sha256: str
    mutation_scopes: tuple[str, ...]
    payload: Mapping[str, object]
    estimated_cost_usd: float
    risk: float
    requires_human_approval: bool = False
    approval_receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.action_id.strip() or not self.payload:
            raise V10ContractError("world action id and payload are required")
        _require_sha256(self.expected_state_sha256, "expected_state_sha256")
        _require_text_tuple(self.mutation_scopes, "mutation scopes")
        if not math.isfinite(self.estimated_cost_usd) or self.estimated_cost_usd < 0:
            raise V10ContractError("world action cost is invalid")
        _require_unit(self.risk, "world action risk")
        if self.approval_receipt_sha256 is not None:
            _require_sha256(self.approval_receipt_sha256, "approval_receipt_sha256")

    @property
    def digest(self) -> str:
        return stable_sha256(asdict(self))


def action_rejection_reasons(
    state: CampaignWorldSnapshot,
    action: WorldAction,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if state.campaign.status is WorldStatus.TERMINATED:
        reasons.append("terminal_state")
    if action.expected_state_sha256 != state.digest:
        reasons.append("stale_state")
    if not set(action.mutation_scopes).issubset(_ALLOWED_SCOPES[action.kind]):
        reasons.append("illegal_mutation_scope")
    if str(action.payload.get("operation", "")).lower() in {"publish", "send", "release"}:
        reasons.append("publication_not_a_world_model_action")
    if action.estimated_cost_usd > state.costs.remaining_usd:
        reasons.append("budget_exceeded")
    if state.risks.hard_blocks and action.kind not in {
        WorldActionKind.RESEARCH,
        WorldActionKind.AUDIT,
        WorldActionKind.REPAIR,
        WorldActionKind.ROLLBACK,
    }:
        reasons.append("hard_risk_block")
    if (action.risk >= 0.7 or action.requires_human_approval) and action.approval_receipt_sha256 is None:
        reasons.append("human_approval_required")
    return tuple(reasons)


def legal_actions(
    state: CampaignWorldSnapshot,
    actions: Sequence[WorldAction],
) -> tuple[WorldAction, ...]:
    return tuple(action for action in actions if not action_rejection_reasons(state, action))


def lifecycle_status(state: CampaignWorldSnapshot) -> WorldStatus:
    if state.campaign.status is WorldStatus.TERMINATED:
        return WorldStatus.TERMINATED
    if state.risks.hard_blocks or state.costs.projected_usd > state.costs.remaining_usd:
        return WorldStatus.BLOCKED
    if state.uncertainty.maximum > state.uncertainty.escalation_threshold:
        return WorldStatus.AWAITING_HUMAN
    return state.campaign.status


@dataclass(frozen=True)
class TransitionReceipt:
    before_sha256: str
    action_sha256: str
    after_sha256: str
    status: WorldStatus
    simulated: bool = True


def transition_state(
    state: CampaignWorldSnapshot,
    action: WorldAction,
) -> tuple[CampaignWorldSnapshot, TransitionReceipt]:
    failures = action_rejection_reasons(state, action)
    if failures:
        raise V10ContractError(f"illegal action: {','.join(failures)}")
    after = replace(
        state,
        campaign=replace(state.campaign, phase=str(action.payload.get("next_phase", state.campaign.phase))),
        costs=replace(
            state.costs,
            spent_usd=state.costs.spent_usd + action.estimated_cost_usd,
            projected_usd=max(0.0, state.costs.projected_usd - action.estimated_cost_usd),
        ),
        sequence=state.sequence + 1,
    )
    status = lifecycle_status(after)
    after = replace(after, campaign=replace(after.campaign, status=status))
    return after, TransitionReceipt(state.digest, action.digest, after.digest, status)


@dataclass(frozen=True)
class FutureValue:
    four_a_value: float
    risk_value: float
    latency_ms: float
    diversity_value: float
    cost_usd: float
    uncertainty: float

    def __post_init__(self) -> None:
        for field_name in ("four_a_value", "risk_value", "diversity_value", "uncertainty"):
            _require_unit(getattr(self, field_name), field_name)
        if not math.isfinite(self.latency_ms) or self.latency_ms < 0:
            raise V10ContractError("future latency must be finite and non-negative")
        if not math.isfinite(self.cost_usd) or self.cost_usd < 0:
            raise V10ContractError("future cost must be finite and non-negative")


@dataclass(frozen=True)
class FuturePrediction:
    prediction_id: str
    initial_state_sha256: str
    action_sha256: str
    predicted_state_sha256: str
    values: FutureValue
    assumptions: tuple[str, ...]
    evidence_class: EvidenceClass = EvidenceClass.SIMULATED

    def __post_init__(self) -> None:
        for field_name in ("initial_state_sha256", "action_sha256", "predicted_state_sha256"):
            _require_sha256(getattr(self, field_name), field_name)
        if not self.prediction_id.strip() or not self.assumptions:
            raise V10ContractError("future prediction identity and assumptions are required")
        if self.evidence_class is not EvidenceClass.SIMULATED:
            raise V10ContractError("future predictions must remain simulated")


def predict_future(
    state: CampaignWorldSnapshot,
    action: WorldAction,
    *,
    seed: int,
    quality_delta: float,
    diversity_delta: float,
    latency_ms: float,
) -> FuturePrediction:
    if action.expected_state_sha256 != state.digest:
        raise V10ContractError("prediction action is not bound to current state")
    rng = random.Random(seed)
    jitter = rng.uniform(-0.005, 0.005)
    quality = min(1.0, max(0.0, state.creative.measured_quality + quality_delta + jitter))
    diversity = min(1.0, max(0.0, len(state.creative.variant_ids) / 10 + diversity_delta))
    risk = min(1.0, max([0.0, *state.risks.risk_scores.values()]) + action.risk / 2)
    uncertainty = min(1.0, state.uncertainty.maximum + abs(jitter))
    projected = stable_sha256(
        {
            "state": state.digest,
            "action": action.digest,
            "quality": quality,
            "risk": risk,
            "uncertainty": uncertainty,
            "seed": seed,
        }
    )
    return FuturePrediction(
        prediction_id=f"prediction-{action.action_id}-{seed}",
        initial_state_sha256=state.digest,
        action_sha256=action.digest,
        predicted_state_sha256=projected,
        values=FutureValue(
            four_a_value=quality,
            risk_value=risk,
            latency_ms=latency_ms,
            diversity_value=diversity,
            cost_usd=action.estimated_cost_usd,
            uncertainty=uncertainty,
        ),
        assumptions=("action succeeds", "input state remains fresh", "no unmodeled external shock"),
    )


@dataclass(frozen=True)
class FutureTrajectory:
    profile: str
    predictions: tuple[FuturePrediction, ...]

    @property
    def values(self) -> FutureValue:
        final = self.predictions[-1].values
        return FutureValue(
            four_a_value=final.four_a_value,
            risk_value=max(item.values.risk_value for item in self.predictions),
            latency_ms=sum(item.values.latency_ms for item in self.predictions),
            diversity_value=final.diversity_value,
            cost_usd=sum(item.values.cost_usd for item in self.predictions),
            uncertainty=max(item.values.uncertainty for item in self.predictions),
        )


def generate_three_future_trajectories(
    state: CampaignWorldSnapshot,
    action: WorldAction,
    *,
    seed: int,
) -> tuple[FutureTrajectory, ...]:
    profiles = (
        ("conservative", 0.03, 0.02, 900.0),
        ("balanced", 0.08, 0.08, 1200.0),
        ("exploratory", 0.14, 0.18, 1800.0),
    )
    return tuple(
        FutureTrajectory(
            profile,
            (predict_future(state, action, seed=seed + index, quality_delta=quality, diversity_delta=diversity, latency_ms=latency),),
        )
        for index, (profile, quality, diversity, latency) in enumerate(profiles)
    )


def counterfactual_rollout(
    state: CampaignWorldSnapshot,
    factual_action: WorldAction,
    counterfactual_action: WorldAction,
    *,
    seed: int,
) -> tuple[FuturePrediction, FuturePrediction]:
    common = dict(seed=seed, quality_delta=0.08, diversity_delta=0.08, latency_ms=1200.0)
    factual = predict_future(state, factual_action, **common)
    counterfactual = predict_future(state, counterfactual_action, **common)
    if factual.initial_state_sha256 != counterfactual.initial_state_sha256:
        raise V10ContractError("counterfactuals must share the same initial state")
    return factual, counterfactual


def _dominates(left: FutureValue, right: FutureValue) -> bool:
    left_values = (left.four_a_value, left.diversity_value, -left.risk_value, -left.latency_ms, -left.cost_usd, -left.uncertainty)
    right_values = (right.four_a_value, right.diversity_value, -right.risk_value, -right.latency_ms, -right.cost_usd, -right.uncertainty)
    return all(a >= b for a, b in zip(left_values, right_values)) and any(a > b for a, b in zip(left_values, right_values))


def pareto_trajectories(trajectories: Sequence[FutureTrajectory]) -> tuple[FutureTrajectory, ...]:
    if not trajectories:
        raise V10ContractError("Pareto selection requires trajectories")
    return tuple(
        item
        for index, item in enumerate(trajectories)
        if not any(
            index != other_index and _dominates(other.values, item.values)
            for other_index, other in enumerate(trajectories)
        )
    )


def state_diff(before: CampaignWorldSnapshot, after: CampaignWorldSnapshot) -> Mapping[str, object]:
    before_data = asdict(before)
    after_data = asdict(after)
    return {
        key: {"before": before_data[key], "after": after_data[key]}
        for key in before_data
        if before_data[key] != after_data[key]
    }


@dataclass(frozen=True)
class WorldStateRecord:
    sequence: int
    parent_record_sha256: str
    state_sha256: str
    action_sha256: str
    diff_sha256: str

    @property
    def digest(self) -> str:
        return stable_sha256(asdict(self))


class WorldStateLedger:
    def __init__(self, initial: CampaignWorldSnapshot) -> None:
        self._snapshots = [initial]
        self._records: list[WorldStateRecord] = []

    @property
    def records(self) -> tuple[WorldStateRecord, ...]:
        return tuple(self._records)

    def append(self, action: WorldAction, after: CampaignWorldSnapshot) -> WorldStateRecord:
        before = self._snapshots[-1]
        if action.expected_state_sha256 != before.digest or after.sequence != before.sequence + 1:
            raise V10ContractError("ledger append is not a contiguous state transition")
        record = WorldStateRecord(
            sequence=after.sequence,
            parent_record_sha256=self._records[-1].digest if self._records else "0" * 64,
            state_sha256=after.digest,
            action_sha256=action.digest,
            diff_sha256=stable_sha256(state_diff(before, after)),
        )
        self._snapshots.append(after)
        self._records.append(record)
        return record

    def verify(self) -> bool:
        for index, record in enumerate(self._records):
            expected_parent = self._records[index - 1].digest if index else "0" * 64
            if record.parent_record_sha256 != expected_parent:
                return False
            if record.state_sha256 != self._snapshots[index + 1].digest:
                return False
            if record.diff_sha256 != stable_sha256(state_diff(self._snapshots[index], self._snapshots[index + 1])):
                return False
        return True

    def replay(self, sequence: int) -> CampaignWorldSnapshot:
        if not 0 <= sequence < len(self._snapshots):
            raise V10ContractError("state replay sequence is outside ledger")
        if not self.verify():
            raise V10ContractError("state ledger hash chain is invalid")
        return self._snapshots[sequence]


def compress_state(state: CampaignWorldSnapshot) -> bytes:
    payload = json.dumps(asdict(state), default=lambda value: value.value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return zlib.compress(payload, level=9)


def decompress_state(compressed: bytes) -> Mapping[str, object]:
    try:
        value = json.loads(zlib.decompress(compressed).decode("utf-8"))
    except (zlib.error, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise V10ContractError("compressed state is invalid") from error
    if not isinstance(value, dict):
        raise V10ContractError("decompressed state must be an object")
    return value


def state_mermaid(state: CampaignWorldSnapshot) -> str:
    status = lifecycle_status(state).value
    return "\n".join(
        (
            "flowchart LR",
            f'  C["Campaign {state.campaign.campaign_id}"] --> E["Evidence {state.evidence.support_rate:.0%}"]',
            f'  E --> R["Risk blocks {len(state.risks.hard_blocks)}"]',
            f'  R --> S["Status {status}"]',
            f'  C --> A["Assets {len(state.assets.artifact_sha256s)}"]',
            f'  A --> H["Channels ready {len(state.channels.ready_channels)}"]',
        )
    )


class PredictionErrorSource(str, Enum):
    WORLD_MODEL = "world_model_error"
    EXECUTOR = "executor_error"
    DATA = "data_error"


@dataclass(frozen=True)
class PredictionActualReceipt:
    prediction: FuturePrediction
    actual_values: FutureValue | None
    actual_state_sha256: str | None
    actual_observed: bool
    input_fresh: bool
    action_matched: bool
    execution_success: bool

    def __post_init__(self) -> None:
        if self.actual_observed:
            if self.actual_values is None or self.actual_state_sha256 is None:
                raise V10ContractError("observed actual needs values and state hash")
            _require_sha256(self.actual_state_sha256, "actual_state_sha256")
        elif self.actual_values is not None or self.actual_state_sha256 is not None:
            raise V10ContractError("unobserved actual cannot carry result values")

    @property
    def error_source(self) -> PredictionErrorSource:
        if not self.actual_observed or not self.input_fresh:
            return PredictionErrorSource.DATA
        if not self.action_matched or not self.execution_success:
            return PredictionErrorSource.EXECUTOR
        return PredictionErrorSource.WORLD_MODEL

    @property
    def deviations(self) -> Mapping[str, float] | None:
        if self.actual_values is None:
            return None
        predicted = self.prediction.values
        return {
            "four_a_value": abs(predicted.four_a_value - self.actual_values.four_a_value),
            "risk_value": abs(predicted.risk_value - self.actual_values.risk_value),
            "latency_ms": abs(predicted.latency_ms - self.actual_values.latency_ms),
            "diversity_value": abs(predicted.diversity_value - self.actual_values.diversity_value),
            "cost_usd": abs(predicted.cost_usd - self.actual_values.cost_usd),
            "uncertainty": abs(predicted.uncertainty - self.actual_values.uncertainty),
        }


def hard_sample_from_deviation(
    receipt: PredictionActualReceipt,
    *,
    unit_tolerance: float = 0.15,
    latency_tolerance_ms: float = 500.0,
    cost_tolerance_usd: float = 1.0,
) -> Mapping[str, object] | None:
    deviations = receipt.deviations
    if deviations is None:
        return {
            "prediction_id": receipt.prediction.prediction_id,
            "error_source": receipt.error_source.value,
            "reason": "actual_unobserved_or_invalid",
            "sample_sha256": stable_sha256(asdict(receipt.prediction)),
        }
    failed = {
        key: value
        for key, value in deviations.items()
        if value > (
            latency_tolerance_ms if key == "latency_ms" else cost_tolerance_usd if key == "cost_usd" else unit_tolerance
        )
    }
    if not failed:
        return None
    payload: dict[str, object] = {
        "prediction_id": receipt.prediction.prediction_id,
        "error_source": receipt.error_source.value,
        "failed_dimensions": failed,
    }
    payload["sample_sha256"] = stable_sha256(payload)
    return payload


def future_state_accuracy(
    receipts: Sequence[PredictionActualReceipt],
    *,
    tolerance: float = 0.15,
) -> Mapping[str, object]:
    observed = [receipt for receipt in receipts if receipt.actual_observed and receipt.deviations is not None]
    if not observed:
        raise V10ContractError("future-state accuracy needs observed actual outcomes")
    dimensions = ("four_a_value", "risk_value", "diversity_value", "uncertainty")
    mae = {
        dimension: sum(receipt.deviations[dimension] for receipt in observed if receipt.deviations is not None) / len(observed)
        for dimension in dimensions
    }
    within = sum(
        all(receipt.deviations[dimension] <= tolerance for dimension in dimensions)
        for receipt in observed
        if receipt.deviations is not None
    ) / len(observed)
    return {
        "observed_count": len(observed),
        "mean_absolute_error": mae,
        "all_core_dimensions_within_tolerance_rate": within,
        "tolerance": tolerance,
    }


def uncertainty_calibration_error(
    receipts: Sequence[PredictionActualReceipt],
    *,
    tolerance: float = 0.15,
    bins: int = 5,
) -> float:
    observed = [receipt for receipt in receipts if receipt.actual_observed and receipt.deviations is not None]
    if not observed or bins < 2:
        raise V10ContractError("uncertainty calibration needs observed outcomes and bins")
    rows = []
    for receipt in observed:
        assert receipt.deviations is not None
        error_event = float(
            any(
                receipt.deviations[dimension] > tolerance
                for dimension in ("four_a_value", "risk_value", "diversity_value", "uncertainty")
            )
        )
        rows.append((receipt.prediction.values.uncertainty, error_event))
    calibration_error = 0.0
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        bucket = [
            row for row in rows
            if lower <= row[0] <= upper and (index == bins - 1 or row[0] < upper)
        ]
        if bucket:
            predicted = sum(row[0] for row in bucket) / len(bucket)
            observed_error = sum(row[1] for row in bucket) / len(bucket)
            calibration_error += len(bucket) / len(rows) * abs(predicted - observed_error)
    return calibration_error


def freeze_world_model_v1() -> Mapping[str, object]:
    payload: dict[str, object] = {
        "schema": "ProofLaunchCampaignWorldModelV1",
        "version": "1.0.0",
        "status": "frozen_contract_not_trained",
        "state_components": (
            "campaign", "evidence", "audience", "market", "brand", "creative",
            "assets", "channels", "risks", "memory", "uncertainty", "costs",
        ),
        "action_kinds": tuple(item.value for item in WorldActionKind),
        "future_profiles": ("conservative", "balanced", "exploratory"),
        "pareto_objectives": {
            "maximize": ("four_a_value", "diversity_value"),
            "minimize": ("risk_value", "latency_ms", "cost_usd", "uncertainty"),
        },
        "error_sources": tuple(item.value for item in PredictionErrorSource),
        "runtime_truth": {
            "trained_predictor_observed": False,
            "radeon_execution_observed": False,
            "prediction_actual_pairs_observed": 0,
            "future_state_accuracy": None,
            "selected_checkpoint": None,
        },
        "truth_boundary": "Typed deterministic world-state and evaluation mechanics only; future predictions are simulated and no learned world-model accuracy or business outcome is claimed.",
    }
    payload["content_sha256"] = stable_sha256(payload)
    return payload
