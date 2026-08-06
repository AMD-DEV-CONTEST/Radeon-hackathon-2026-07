from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable, Mapping

from .v10_contracts import V10ContractError
from .v10_supply_chain import stable_sha256


class ModelProfile(str, Enum):
    E4B = "4b"
    E2B = "2b"


class CPTObjective(str, Enum):
    TEXT = "text"
    IMAGE_TEXT = "image_text"
    LAYOUT = "layout"
    VIDEO_STATE = "video_state"
    AUDIO_TEXT = "audio_text"
    CAMPAIGN_STATE = "campaign_state"
    NEXT_ACTION = "next_action"
    FAILURE = "failure"
    REPAIR = "repair"
    CROSS_CHANNEL = "cross_channel"
    EVIDENCE = "evidence"
    UNCERTAINTY = "uncertainty"


class MonitorMetric(str, Enum):
    TRAIN_LOSS = "train_loss"
    VALIDATION_LOSS = "validation_loss"
    VISUAL_RETENTION = "visual_retention"
    LANGUAGE_RETENTION = "language_retention"
    SCHEMA_VALIDITY = "schema_validity"
    CLAIM_GROUNDING = "claim_grounding"
    STATE_PREDICTION = "state_prediction"


@dataclass(frozen=True)
class BaseRevision:
    model_id: str
    revision: str
    config_sha256: str | None
    tokenizer_sha256: str | None
    processor_sha256: str | None
    artifact_hashes_observed: bool

    def __post_init__(self) -> None:
        if not self.model_id.strip() or not self.revision.strip():
            raise V10ContractError("base model and revision are required")
        hashes = tuple(
            getattr(self, name)
            for name in ("config_sha256", "tokenizer_sha256", "processor_sha256")
        )
        if self.artifact_hashes_observed:
            if any(value is None or len(value) != 64 for value in hashes):
                raise V10ContractError("observed base artifacts require three SHA-256 values")
        elif any(value is not None for value in hashes):
            raise V10ContractError("unobserved base artifacts cannot carry claimed hashes")


@dataclass(frozen=True)
class RadeonMemoryObservation:
    backend: str
    device_name: str
    total_vram_gb: float
    free_vram_gb: float
    receipt_sha256: str
    observed: bool

    def __post_init__(self) -> None:
        if self.backend.lower() not in {"rocm", "hip"}:
            raise V10ContractError("Radeon observation must use ROCm/HIP")
        if not self.device_name.strip() or self.total_vram_gb <= 0:
            raise V10ContractError("Radeon device and VRAM are required")
        if not 0 < self.free_vram_gb <= self.total_vram_gb:
            raise V10ContractError("free VRAM must be within total VRAM")
        if len(self.receipt_sha256) != 64:
            raise V10ContractError("hardware receipt must be SHA-256")


def select_profile(observation: RadeonMemoryObservation) -> ModelProfile:
    if not observation.observed:
        raise V10ContractError("profile selection requires observed Radeon VRAM")
    if observation.free_vram_gb >= 40:
        return ModelProfile.E4B
    if observation.free_vram_gb >= 20:
        return ModelProfile.E2B
    raise V10ContractError("neither frozen 4B nor 2B profile fits observed free VRAM")


@dataclass(frozen=True)
class ObjectiveDefinition:
    objective: CPTObjective
    target: str
    loss: str
    evidence_required: bool
    negative_control: str

    def __post_init__(self) -> None:
        if not self.target.strip() or not self.loss.strip() or not self.negative_control.strip():
            raise V10ContractError("objective target, loss and negative control are required")


def default_objectives() -> tuple[ObjectiveDefinition, ...]:
    definitions = {
        CPTObjective.TEXT: ("next licensed GTM token", "causal_ce", False, "shuffled continuation"),
        CPTObjective.IMAGE_TEXT: ("grounded image-text relation", "contrastive_plus_ce", True, "mismatched image"),
        CPTObjective.LAYOUT: ("region and hierarchy structure", "region_order_ce", True, "region permutation"),
        CPTObjective.VIDEO_STATE: ("next verified frame-state delta", "temporal_state_ce", True, "time reversal"),
        CPTObjective.AUDIO_TEXT: ("timestamped audio-text meaning", "contrastive_plus_ce", True, "shifted transcript"),
        CPTObjective.CAMPAIGN_STATE: ("next campaign world state", "typed_state_ce", True, "stale state"),
        CPTObjective.NEXT_ACTION: ("bounded next action", "action_ce", True, "invalid tool action"),
        CPTObjective.FAILURE: ("first error and propagation", "step_label_ce", True, "success relabel"),
        CPTObjective.REPAIR: ("minimal verified repair", "repair_ce", True, "unverified rewrite"),
        CPTObjective.CROSS_CHANNEL: ("shared claim with channel constraints", "consistency_ce", True, "cross-channel contradiction"),
        CPTObjective.EVIDENCE: ("claim-to-source locator", "grounding_ce", True, "unsupported claim"),
        CPTObjective.UNCERTAINTY: ("calibrated abstain/escalate", "proper_scoring_rule", True, "forced confident answer"),
    }
    return tuple(
        ObjectiveDefinition(kind, *definitions[kind]) for kind in CPTObjective
    )


@dataclass(frozen=True)
class MixScheduleStage:
    name: str
    start_fraction: float
    end_fraction: float
    modality_mix: Mapping[str, float]
    task_mix: Mapping[CPTObjective, float]

    def __post_init__(self) -> None:
        if not self.name.strip() or not 0 <= self.start_fraction < self.end_fraction <= 1:
            raise V10ContractError("curriculum fraction interval is invalid")
        for label, mix in (("modality", self.modality_mix), ("task", self.task_mix)):
            if not mix or any(value < 0 for value in mix.values()):
                raise V10ContractError(f"{label} mix is invalid")
            if not math.isclose(sum(mix.values()), 1.0, abs_tol=1e-9):
                raise V10ContractError(f"{label} mix must sum to one")
        if set(self.task_mix) != set(CPTObjective):
            raise V10ContractError("task mix must cover all CPT objectives")


def default_mix_schedule() -> tuple[MixScheduleStage, ...]:
    grounding = {
        objective: (0.14 if objective in {CPTObjective.TEXT, CPTObjective.IMAGE_TEXT, CPTObjective.EVIDENCE} else 0.58 / 9)
        for objective in CPTObjective
    }
    state = {
        objective: (0.12 if objective in {CPTObjective.CAMPAIGN_STATE, CPTObjective.NEXT_ACTION, CPTObjective.FAILURE, CPTObjective.REPAIR} else 0.52 / 8)
        for objective in CPTObjective
    }
    integration = {objective: 1.0 / len(CPTObjective) for objective in CPTObjective}
    return (
        MixScheduleStage(
            "grounding", 0.0, 0.35,
            {"text": 0.35, "image_text": 0.30, "video": 0.12, "audio": 0.08, "document_screen": 0.15},
            grounding,
        ),
        MixScheduleStage(
            "state_and_repair", 0.35, 0.75,
            {"text": 0.25, "image_text": 0.25, "video": 0.18, "audio": 0.10, "document_screen": 0.22},
            state,
        ),
        MixScheduleStage(
            "cross_channel_integration", 0.75, 1.0,
            {"text": 0.20, "image_text": 0.25, "video": 0.20, "audio": 0.10, "document_screen": 0.25},
            integration,
        ),
    )


@dataclass(frozen=True)
class LearningRatePolicy:
    vision_tower: float
    connector: float
    language_model: float
    adapter: float

    def __post_init__(self) -> None:
        if self.vision_tower != 0.0:
            raise V10ContractError("vision tower is frozen for multimodal retention")
        if min(self.connector, self.language_model, self.adapter) <= 0:
            raise V10ContractError("connector, LLM and adapter learning rates must be positive")
        if not self.connector >= self.adapter >= self.language_model:
            raise V10ContractError("learning-rate ordering must be connector >= adapter >= LLM")


@dataclass(frozen=True)
class CPTExecutionSettings:
    packing: bool
    packing_resets_position_and_attention: bool
    gradient_checkpointing: bool
    gradient_accumulation_steps: int
    bf16: bool
    deterministic_seed: int
    maximum_wall_clock_hours: float
    checkpoint_interval_steps: int
    save_optimizer: bool
    save_scheduler: bool
    save_rng_state: bool

    def __post_init__(self) -> None:
        if not self.packing or not self.packing_resets_position_and_attention:
            raise V10ContractError("packing must isolate example attention and positions")
        if not self.gradient_checkpointing or self.gradient_accumulation_steps < 1:
            raise V10ContractError("memory controls are incomplete")
        if not self.bf16:
            raise V10ContractError("the frozen Radeon CPT profile requires BF16")
        if self.maximum_wall_clock_hours != 6.0:
            raise V10ContractError("CPT wall-clock budget must be exactly six hours")
        if self.checkpoint_interval_steps < 1:
            raise V10ContractError("checkpoint interval must be positive")
        if not all((self.save_optimizer, self.save_scheduler, self.save_rng_state)):
            raise V10ContractError("checkpoint must save optimizer, scheduler and RNG")


@dataclass(frozen=True)
class ResumeCheckpoint:
    checkpoint_id: str
    step: int
    model_sha256: str
    optimizer_sha256: str
    scheduler_sha256: str
    rng_state_sha256: str
    data_revision: str

    def __post_init__(self) -> None:
        if not self.checkpoint_id.strip() or self.step < 1 or not self.data_revision.strip():
            raise V10ContractError("checkpoint identity, step and data revision are required")
        for name in ("model_sha256", "optimizer_sha256", "scheduler_sha256", "rng_state_sha256"):
            if len(str(getattr(self, name))) != 64:
                raise V10ContractError(f"{name} must be SHA-256")


@dataclass(frozen=True)
class CheckpointMetrics:
    checkpoint_id: str
    step: int
    train_loss: float
    validation_loss: float
    visual_retention: float
    language_retention: float
    schema_validity: float
    claim_grounding: float
    state_prediction: float

    def __post_init__(self) -> None:
        values = asdict(self)
        values.pop("checkpoint_id")
        values.pop("step")
        if not self.checkpoint_id.strip() or self.step < 1:
            raise V10ContractError("checkpoint metrics need identity and step")
        if any(not math.isfinite(value) for value in values.values()):
            raise V10ContractError("checkpoint metrics must be finite")
        for name in (
            "visual_retention", "language_retention", "schema_validity",
            "claim_grounding", "state_prediction",
        ):
            if not 0 <= getattr(self, name) <= 1:
                raise V10ContractError(f"{name} must be in [0,1]")


@dataclass(frozen=True)
class CheckpointSelection:
    selected_checkpoint_id: str
    last_checkpoint_id: str
    selected_is_last: bool
    scores: Mapping[str, float]
    rejected: Mapping[str, tuple[str, ...]]
    digest: str


def select_best_checkpoint(metrics: Iterable[CheckpointMetrics]) -> CheckpointSelection:
    items = tuple(metrics)
    if len(items) < 2:
        raise V10ContractError("checkpoint selection requires at least two checkpoints")
    rejected: dict[str, tuple[str, ...]] = {}
    scores: dict[str, float] = {}
    for item in items:
        failures = []
        if item.visual_retention < 0.95:
            failures.append("visual retention")
        if item.language_retention < 0.95:
            failures.append("language retention")
        if item.schema_validity < 0.98:
            failures.append("schema validity")
        if item.claim_grounding < 0.95:
            failures.append("Claim grounding")
        if item.state_prediction < 0.90:
            failures.append("state prediction")
        if failures:
            rejected[item.checkpoint_id] = tuple(failures)
            continue
        scores[item.checkpoint_id] = (
            0.15 * item.visual_retention
            + 0.15 * item.language_retention
            + 0.20 * item.schema_validity
            + 0.25 * item.claim_grounding
            + 0.25 * item.state_prediction
            - 0.02 * item.validation_loss
        )
    if not scores:
        raise V10ContractError("all checkpoints fail retention or capability gates")
    selected = max(scores, key=lambda key: (scores[key], -next(item.step for item in items if item.checkpoint_id == key)))
    last = max(items, key=lambda item: item.step).checkpoint_id
    material = {"selected": selected, "last": last, "scores": scores, "rejected": rejected}
    return CheckpointSelection(
        selected_checkpoint_id=selected,
        last_checkpoint_id=last,
        selected_is_last=selected == last,
        scores=scores,
        rejected=rejected,
        digest=stable_sha256(material),
    )


@dataclass(frozen=True)
class CPTContract:
    base: BaseRevision
    profile: ModelProfile
    objectives: tuple[ObjectiveDefinition, ...]
    schedule: tuple[MixScheduleStage, ...]
    learning_rates: LearningRatePolicy
    settings: CPTExecutionSettings
    monitor_metrics: tuple[MonitorMetric, ...]

    def __post_init__(self) -> None:
        if {item.objective for item in self.objectives} != set(CPTObjective):
            raise V10ContractError("CPT objectives are incomplete")
        if tuple(item.start_fraction for item in self.schedule) != (0.0, 0.35, 0.75):
            raise V10ContractError("CPT curriculum stages are not frozen")
        if tuple(item.end_fraction for item in self.schedule) != (0.35, 0.75, 1.0):
            raise V10ContractError("CPT curriculum stages have gaps or overlap")
        if set(self.monitor_metrics) != set(MonitorMetric):
            raise V10ContractError("CPT monitor set is incomplete")

    @property
    def digest(self) -> str:
        return stable_sha256(asdict(self))


def planned_cpt_card(contract: CPTContract) -> dict:
    payload = {
        "schema": "ProofLaunchCPTCardV1",
        "contract_digest": contract.digest,
        "base_model": contract.base.model_id,
        "base_revision": contract.base.revision,
        "profile": contract.profile.value,
        "objective_count": len(contract.objectives),
        "training_observed": False,
        "base_evaluation_observed": False,
        "radeon_memory_observed": False,
        "selected_checkpoint": None,
        "throughput_tokens_per_second": None,
        "peak_vram_gb": None,
        "energy_proxy": None,
        "data_revision": None,
        "learning_curve": None,
        "promotion_eligible": False,
        "truth_boundary": "This is a frozen CPT execution contract, not a training receipt.",
    }
    payload["content_sha256"] = stable_sha256(payload)
    return payload
