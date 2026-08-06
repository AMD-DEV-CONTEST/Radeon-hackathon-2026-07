from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable, Mapping

from .v10_contracts import V10ContractError
from .v10_supply_chain import stable_sha256


class CurriculumStage(str, Enum):
    EVIDENCE = "evidence"
    AUDIENCE = "audience"
    STRATEGY = "strategy"
    CREATIVE = "creative"
    COPY = "copy"
    ART = "art"
    CHANNEL = "channel"
    PRODUCTION = "production"
    COMPLIANCE = "compliance"
    AUDIT = "audit"
    REPAIR = "repair"
    MEMORY = "memory"
    PLANNING = "planning"
    STOP = "stop"


class CurriculumInput(str, Enum):
    SHORT_TEXT = "short_text"
    LONG_DOCUMENT = "long_document"
    SINGLE_IMAGE = "single_image"
    MULTI_IMAGE = "multi_image"
    VIDEO_FRAMES = "video_frames"
    AUDIO = "audio"
    TOOL_TRAJECTORY = "tool_trajectory"
    STATE_TRAJECTORY = "state_trajectory"
    CROSS_CHANNEL = "cross_channel"


class TrainerVariant(str, Enum):
    SFT = "sft"
    DFT = "dft"


class ComparisonMetric(str, Enum):
    TOKEN_ACCURACY = "token_accuracy"
    VISUAL_DEPENDENCE = "visual_dependence"
    FOUR_A_SCORE = "four_a_score"
    STATE_PREDICTION = "state_prediction"
    GENERAL_REGRESSION = "general_regression"


CANONICAL_STAGE_ORDER = tuple(CurriculumStage)
CANONICAL_INPUT_ORDER = tuple(CurriculumInput)


@dataclass(frozen=True)
class StageDefinition:
    stage: CurriculumStage
    required_outputs: tuple[str, ...]
    forbidden_shortcuts: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.required_outputs or not self.forbidden_shortcuts:
            raise V10ContractError("each curriculum stage needs outputs and negative controls")


def default_stage_definitions() -> tuple[StageDefinition, ...]:
    outputs = {
        CurriculumStage.EVIDENCE: ("claim_source_locator", "evidence_conflict"),
        CurriculumStage.AUDIENCE: ("icp", "jtbd", "audience_uncertainty"),
        CurriculumStage.STRATEGY: ("smp", "rtb", "offer"),
        CurriculumStage.CREATIVE: ("big_idea", "creative_route"),
        CurriculumStage.COPY: ("headline", "body_copy", "cta"),
        CurriculumStage.ART: ("key_visual_brief", "layout_constraints"),
        CurriculumStage.CHANNEL: ("channel_adaptation", "cross_channel_claim"),
        CurriculumStage.PRODUCTION: ("asset_spec", "render_checks"),
        CurriculumStage.COMPLIANCE: ("risk_decision", "required_disclosure"),
        CurriculumStage.AUDIT: ("first_error", "propagation", "severity"),
        CurriculumStage.REPAIR: ("minimal_patch", "repair_verification"),
        CurriculumStage.MEMORY: ("memory_operation", "scope_and_ttl"),
        CurriculumStage.PLANNING: ("bounded_plan", "tool_budget"),
        CurriculumStage.STOP: ("stop_retry_fallback_escalate", "terminal_reason"),
    }
    return tuple(
        StageDefinition(
            stage=stage,
            required_outputs=outputs[stage],
            forbidden_shortcuts=(
                "unsupported_claim",
                "hidden_reasoning",
                "unbounded_tool_action",
            ),
        )
        for stage in CANONICAL_STAGE_ORDER
    )


@dataclass(frozen=True)
class InputPhase:
    input_kind: CurriculumInput
    minimum_preceding_kinds: tuple[CurriculumInput, ...]
    evidence_required: bool


def default_input_curriculum() -> tuple[InputPhase, ...]:
    phases = []
    for index, kind in enumerate(CANONICAL_INPUT_ORDER):
        phases.append(
            InputPhase(
                input_kind=kind,
                minimum_preceding_kinds=CANONICAL_INPUT_ORDER[:index],
                evidence_required=kind is not CurriculumInput.SHORT_TEXT,
            )
        )
    return tuple(phases)


@dataclass(frozen=True)
class LossPolicy:
    positive_token_weights: Mapping[str, float]
    unsafe_action_target_weight: float
    unsafe_action_unlikelihood_weight: float

    def __post_init__(self) -> None:
        required = {"claim", "locator", "smp", "rtb", "big_idea", "json", "stop"}
        if set(self.positive_token_weights) != required:
            raise V10ContractError("loss policy must cover all seven emphasis targets")
        if any(not math.isfinite(value) or value <= 1 for value in self.positive_token_weights.values()):
            raise V10ContractError("emphasis weights must be finite and above one")
        if self.unsafe_action_target_weight != 0:
            raise V10ContractError("unsafe action cannot be a positive generation target")
        if self.unsafe_action_unlikelihood_weight <= 1:
            raise V10ContractError("unsafe action requires an explicit negative objective")


def default_loss_policy() -> LossPolicy:
    return LossPolicy(
        positive_token_weights={
            "claim": 2.0,
            "locator": 2.0,
            "smp": 1.6,
            "rtb": 1.6,
            "big_idea": 1.5,
            "json": 1.8,
            "stop": 2.2,
        },
        unsafe_action_target_weight=0.0,
        unsafe_action_unlikelihood_weight=2.5,
    )


@dataclass(frozen=True)
class TrainerContract:
    variant: TrainerVariant
    completion_only_loss: bool
    token_weighting: bool
    negative_unlikelihood_loss: bool
    train_split: str
    validation_split: str
    test_split_visible: bool

    def __post_init__(self) -> None:
        if not self.completion_only_loss or self.test_split_visible:
            raise V10ContractError("training must be completion-only and test-blind")
        if self.variant is TrainerVariant.SFT and self.token_weighting:
            raise V10ContractError("ordinary SFT is the unweighted control")
        if self.variant is TrainerVariant.DFT and not (
            self.token_weighting and self.negative_unlikelihood_loss
        ):
            raise V10ContractError("DFT requires positive weights and negative unlikelihood")
        if self.train_split == self.validation_split:
            raise V10ContractError("training and validation splits must differ")


def default_trainer_contracts() -> tuple[TrainerContract, ...]:
    return (
        TrainerContract(
            TrainerVariant.SFT, True, False, False, "train", "validation", False
        ),
        TrainerContract(
            TrainerVariant.DFT, True, True, True, "train", "validation", False
        ),
    )


@dataclass(frozen=True)
class StageArtifact:
    stage: CurriculumStage
    adapter_sha256: str
    data_revision: str
    data_sha256: str
    metrics_sha256: str
    previous_stage_digest: str | None
    observed_training: bool

    def __post_init__(self) -> None:
        if not self.data_revision.strip():
            raise V10ContractError("stage artifact requires a data revision")
        for field in ("adapter_sha256", "data_sha256", "metrics_sha256"):
            if len(getattr(self, field)) != 64:
                raise V10ContractError(f"{field} must be SHA-256")
        if self.previous_stage_digest is not None and len(self.previous_stage_digest) != 64:
            raise V10ContractError("previous stage digest must be SHA-256")

    @property
    def digest(self) -> str:
        return stable_sha256(asdict(self))


@dataclass(frozen=True)
class StageReplay:
    artifacts: tuple[StageArtifact, ...]

    def __post_init__(self) -> None:
        if not self.artifacts:
            raise V10ContractError("stage replay cannot be empty")
        positions = [CANONICAL_STAGE_ORDER.index(item.stage) for item in self.artifacts]
        if positions != sorted(positions) or len(positions) != len(set(positions)):
            raise V10ContractError("stage replay must be unique and canonical-order")
        for index, artifact in enumerate(self.artifacts):
            expected = None if index == 0 else self.artifacts[index - 1].digest
            if artifact.previous_stage_digest != expected:
                raise V10ContractError("stage replay hash chain is broken")

    def rollback(self, stage: CurriculumStage) -> tuple[StageArtifact, ...]:
        for index, artifact in enumerate(self.artifacts):
            if artifact.stage is stage:
                return self.artifacts[: index + 1]
        raise V10ContractError("rollback stage is absent from replay")

    @property
    def digest(self) -> str:
        return stable_sha256([item.digest for item in self.artifacts])


@dataclass(frozen=True)
class SFTContract:
    stages: tuple[StageDefinition, ...]
    inputs: tuple[InputPhase, ...]
    loss_policy: LossPolicy
    trainers: tuple[TrainerContract, ...]
    comparison_metrics: tuple[ComparisonMetric, ...]

    def __post_init__(self) -> None:
        if tuple(item.stage for item in self.stages) != CANONICAL_STAGE_ORDER:
            raise V10ContractError("fourteen SFT stages must use canonical order")
        if tuple(item.input_kind for item in self.inputs) != CANONICAL_INPUT_ORDER:
            raise V10ContractError("nine input phases must use canonical order")
        if {item.variant for item in self.trainers} != set(TrainerVariant):
            raise V10ContractError("ordinary SFT and DFT contracts are both required")
        if set(self.comparison_metrics) != set(ComparisonMetric):
            raise V10ContractError("SFT/DFT comparison metric set is incomplete")

    @property
    def digest(self) -> str:
        return stable_sha256(asdict(self))


def planned_sft_card(contract: SFTContract) -> dict:
    payload = {
        "schema": "ProofLaunchSFTCardV1",
        "contract_sha256": contract.digest,
        "stage_count": len(contract.stages),
        "input_phase_count": len(contract.inputs),
        "trainer_variants": [item.variant.value for item in contract.trainers],
        "training_observed": False,
        "ordinary_sft_metrics": None,
        "dft_metrics": None,
        "random_order_control": None,
        "reverse_curriculum_control": None,
        "curriculum_gain": None,
        "selected_adapter": None,
        "promotion_eligible": False,
        "truth_boundary": "Frozen SFT/DFT execution and rollback contract; no trained adapter or comparative result is claimed.",
    }
    payload["content_sha256"] = stable_sha256(payload)
    return payload


def build_controlled_replay(stages: Iterable[CurriculumStage]) -> StageReplay:
    artifacts = []
    previous = None
    for index, stage in enumerate(stages):
        seed = {"stage": stage.value, "index": index, "fixture": "non_model_contract"}
        artifact = StageArtifact(
            stage=stage,
            adapter_sha256=stable_sha256({**seed, "kind": "adapter"}),
            data_revision=f"controlled-{stage.value}-v1",
            data_sha256=stable_sha256({**seed, "kind": "data"}),
            metrics_sha256=stable_sha256({**seed, "kind": "metrics"}),
            previous_stage_digest=previous,
            observed_training=False,
        )
        artifacts.append(artifact)
        previous = artifact.digest
    return StageReplay(tuple(artifacts))
