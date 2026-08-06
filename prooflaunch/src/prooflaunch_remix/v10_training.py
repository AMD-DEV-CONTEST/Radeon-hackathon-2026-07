from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping, Sequence

from .quality_contract import wilson_lower_bound
from .v10_contracts import V10ContractError


class DataRight(str, Enum):
    OWNED = "owned"
    PERMISSIVE = "permissive"
    PUBLIC_DOMAIN = "public_domain"
    RESEARCH_ONLY = "research_only"
    UNKNOWN = "unknown"


class DataSplit(str, Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class TrainingPhase(str, Enum):
    MULTIMODAL_CPT = "multimodal_cpt"
    CURRICULUM_SFT = "curriculum_sft"
    DIRECT_FEEDBACK = "direct_feedback"
    ON_POLICY_DISTILLATION = "on_policy_distillation"
    MULTI_OBJECTIVE_RL = "multi_objective_rl"
    ADAPTER_EXPERT_CONSOLIDATION = "adapter_expert_consolidation"


class TrainingPhaseStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    ROLLED_BACK = "rolled_back"
    BLOCKED = "blocked"


_HEX = frozenset("0123456789abcdef")


def _sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(char not in _HEX for char in value):
        raise V10ContractError(f"{field_name} must be a lowercase SHA-256")


@dataclass(frozen=True)
class TrainingSample:
    sample_id: str
    content_sha256: str
    task_family: str
    modalities: tuple[str, ...]
    source_locator: str
    source_right: DataRight
    license_id: str
    split: DataSplit
    captured_at: str
    teacher_ref: str | None = None
    synthetic: bool = False

    def __post_init__(self) -> None:
        if not self.sample_id.strip() or not self.task_family.strip():
            raise V10ContractError("training sample id and task family are required")
        _sha256(self.content_sha256, "content_sha256")
        if not self.modalities:
            raise V10ContractError("training sample needs at least one modality")
        if not self.source_locator.strip() or not self.license_id.strip():
            raise V10ContractError("training sample source and license are required")
        try:
            datetime.fromisoformat(self.captured_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise V10ContractError("captured_at must be ISO-8601") from error


@dataclass(frozen=True)
class CorpusAudit:
    passed: bool
    sample_count: int
    split_counts: Mapping[str, int]
    task_counts: Mapping[str, int]
    modality_counts: Mapping[str, int]
    synthetic_rate: float
    failures: tuple[str, ...]
    schema: str = "ProofLaunchCorpusAuditV10"


@dataclass(frozen=True)
class TrainingCorpusManifest:
    samples: tuple[TrainingSample, ...]
    temporal_holdout_start: str
    allowed_rights: frozenset[DataRight] = frozenset(
        {
            DataRight.OWNED,
            DataRight.PERMISSIVE,
            DataRight.PUBLIC_DOMAIN,
        }
    )
    schema: str = "ProofLaunchTrainingCorpusV10"

    def audit(self) -> CorpusAudit:
        failures: list[str] = []
        ids = [sample.sample_id for sample in self.samples]
        hashes = [sample.content_sha256 for sample in self.samples]
        if len(ids) != len(set(ids)):
            failures.append("duplicate sample ids")
        if len(hashes) != len(set(hashes)):
            failures.append("content hash leakage or duplication across splits")
        forbidden = [
            sample.sample_id
            for sample in self.samples
            if sample.source_right not in self.allowed_rights
        ]
        if forbidden:
            failures.append(f"unusable data rights: {', '.join(forbidden[:5])}")
        split_counts = {split.value: 0 for split in DataSplit}
        task_counts: dict[str, int] = {}
        modality_counts: dict[str, int] = {}
        cutoff = datetime.fromisoformat(
            self.temporal_holdout_start.replace("Z", "+00:00")
        )
        for sample in self.samples:
            split_counts[sample.split.value] += 1
            task_counts[sample.task_family] = task_counts.get(
                sample.task_family, 0
            ) + 1
            for modality in sample.modalities:
                modality_counts[modality] = modality_counts.get(modality, 0) + 1
            captured = datetime.fromisoformat(
                sample.captured_at.replace("Z", "+00:00")
            )
            if sample.split == DataSplit.TRAIN and captured >= cutoff:
                failures.append(
                    f"train sample {sample.sample_id} crosses temporal holdout"
                )
            if sample.split == DataSplit.TEST and captured < cutoff:
                failures.append(
                    f"test sample {sample.sample_id} predates temporal holdout"
                )
        for split, count in split_counts.items():
            if count == 0:
                failures.append(f"{split} split is empty")
        synthetic_rate = (
            sum(sample.synthetic for sample in self.samples) / len(self.samples)
            if self.samples
            else 0.0
        )
        if not self.samples:
            failures.append("corpus is empty")
        return CorpusAudit(
            passed=not failures,
            sample_count=len(self.samples),
            split_counts=split_counts,
            task_counts=task_counts,
            modality_counts=modality_counts,
            synthetic_rate=synthetic_rate,
            failures=tuple(dict.fromkeys(failures)),
        )

    @property
    def digest(self) -> str:
        payload = {
            "schema": self.schema,
            "temporal_holdout_start": self.temporal_holdout_start,
            "allowed_rights": sorted(item.value for item in self.allowed_rights),
            "samples": [
                {
                    **asdict(sample),
                    "source_right": sample.source_right.value,
                    "split": sample.split.value,
                }
                for sample in self.samples
            ],
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class MetricGate:
    metric: str
    threshold: float
    higher_is_better: bool
    maximum_regression: float | None = None

    def passes(self, metrics: Mapping[str, float]) -> bool:
        actual = metrics.get(self.metric)
        if actual is None or not math.isfinite(actual):
            return False
        return (
            actual >= self.threshold
            if self.higher_is_better
            else actual <= self.threshold
        )


@dataclass(frozen=True)
class CurriculumStage:
    phase: TrainingPhase
    objective: str
    trainable_modules: tuple[str, ...]
    frozen_modules: tuple[str, ...]
    loss_terms: Mapping[str, float]
    maximum_gpu_hours: float
    checkpoint_every_steps: int
    acceptance_gates: tuple[MetricGate, ...]
    rollback_checkpoint: str
    teacher_policy: str

    def __post_init__(self) -> None:
        if not self.objective.strip():
            raise V10ContractError("training objective is required")
        if set(self.trainable_modules) & set(self.frozen_modules):
            raise V10ContractError("a module cannot be trainable and frozen")
        if not self.trainable_modules:
            raise V10ContractError("training stage needs trainable modules")
        if not self.frozen_modules:
            raise V10ContractError("training stage needs explicit frozen modules")
        if self.maximum_gpu_hours <= 0 or self.checkpoint_every_steps < 1:
            raise V10ContractError("training budget/checkpoint interval is invalid")
        if not self.acceptance_gates:
            raise V10ContractError("training stage requires acceptance gates")
        if not self.rollback_checkpoint.strip():
            raise V10ContractError("rollback checkpoint is required")


@dataclass(frozen=True)
class V10TrainingPlan:
    base_model: str
    base_revision: str
    stages: tuple[CurriculumStage, ...]
    radeon_required: bool
    multi_gpu_required: bool
    minimum_world_size: int
    preferred_world_size: int
    preferred_strategy: str
    memory_fallback_strategy: str
    single_gpu_baseline_required: bool
    single_gpu_may_promote: bool
    maximum_resident_heavy_models_per_rank: int
    expected_global_batch_size: int
    cold_launch_trials: int
    checkpoint_resume_trials: int
    two_gpu_minimum_speedup: float
    minimum_parallel_efficiency: float
    maximum_total_gpu_hours: float
    maximum_wall_clock_hours: float
    judge_human_label_minimum: int
    judge_tpr_minimum: float
    judge_tnr_minimum: float
    schema: str = "ProofLaunchTrainingPlanMultiGpuV10"

    def __post_init__(self) -> None:
        if not self.base_model.strip():
            raise V10ContractError("base model is required")
        if len(self.base_revision) != 40 or any(
            char not in _HEX for char in self.base_revision
        ):
            raise V10ContractError("base revision must be an immutable git commit")
        expected_order = tuple(TrainingPhase)
        actual_order = tuple(stage.phase for stage in self.stages)
        if actual_order != expected_order:
            raise V10ContractError(
                "training curriculum must follow CPT→SFT→DFT→OPD→RL→experts"
            )
        if not self.radeon_required:
            raise V10ContractError("official V10 training plan must require Radeon")
        if not self.multi_gpu_required or self.minimum_world_size < 2:
            raise V10ContractError(
                "official V10 training plan must require at least two GPUs"
            )
        if self.preferred_world_size < self.minimum_world_size:
            raise V10ContractError(
                "preferred world size cannot be below the required world size"
            )
        if self.preferred_strategy != "ddp":
            raise V10ContractError("DDP must be the memory-fit default")
        if self.memory_fallback_strategy != "fsdp2":
            raise V10ContractError("FSDP2 must be the verified memory fallback")
        if not self.single_gpu_baseline_required or self.single_gpu_may_promote:
            raise V10ContractError(
                "single GPU is required only as a non-promotable equivalence baseline"
            )
        if self.maximum_resident_heavy_models_per_rank != 1:
            raise V10ContractError(
                "each rank may hold at most one heavy model replica or shard"
            )
        if self.expected_global_batch_size < 1:
            raise V10ContractError("global batch size must be frozen and positive")
        if self.cold_launch_trials < 3 or self.checkpoint_resume_trials < 2:
            raise V10ContractError(
                "multi-GPU stability requires three cold launches and two resumes"
            )
        if self.two_gpu_minimum_speedup < 1.5:
            raise V10ContractError("two-GPU speedup floor must be at least 1.5x")
        if self.minimum_parallel_efficiency < 0.70:
            raise V10ContractError(
                "parallel-efficiency floor must be at least 70 percent"
            )
        total = sum(stage.maximum_gpu_hours for stage in self.stages)
        if total > self.maximum_total_gpu_hours:
            raise V10ContractError("stage GPU budgets exceed the total plan budget")
        if self.maximum_wall_clock_hours <= 0:
            raise V10ContractError("wall-clock budget must be positive")
        if self.judge_human_label_minimum < 100:
            raise V10ContractError("judge calibration requires at least 100 labels")
        if self.judge_tpr_minimum < 0.8 or self.judge_tnr_minimum < 0.8:
            raise V10ContractError("judge TPR and TNR floors must each be at least 0.8")

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "base_model": self.base_model,
            "base_revision": self.base_revision,
            "distributed_execution": {
                "radeon_required": self.radeon_required,
                "multi_gpu_required": self.multi_gpu_required,
                "minimum_world_size": self.minimum_world_size,
                "preferred_world_size": self.preferred_world_size,
                "preferred_strategy": self.preferred_strategy,
                "memory_fallback_strategy": self.memory_fallback_strategy,
                "forbidden_strategy": "device_map=auto",
                "single_gpu_baseline_required": self.single_gpu_baseline_required,
                "single_gpu_may_promote": self.single_gpu_may_promote,
                "maximum_resident_heavy_models_per_rank": (
                    self.maximum_resident_heavy_models_per_rank
                ),
                "expected_global_batch_size": self.expected_global_batch_size,
                "cold_launch_trials": self.cold_launch_trials,
                "checkpoint_resume_trials": self.checkpoint_resume_trials,
                "two_gpu_minimum_speedup": self.two_gpu_minimum_speedup,
                "minimum_parallel_efficiency": (
                    self.minimum_parallel_efficiency
                ),
                "rank_loss_policy": "abort",
                "checkpoint_owner": "rank_0_atomic_commit",
            },
            "maximum_total_gpu_hours": self.maximum_total_gpu_hours,
            "maximum_wall_clock_hours": self.maximum_wall_clock_hours,
            "judge_calibration": {
                "human_label_minimum": self.judge_human_label_minimum,
                "tpr_minimum": self.judge_tpr_minimum,
                "tnr_minimum": self.judge_tnr_minimum,
            },
            "stages": [
                {
                    **asdict(stage),
                    "phase": stage.phase.value,
                    "acceptance_gates": [
                        asdict(gate) for gate in stage.acceptance_gates
                    ],
                }
                for stage in self.stages
            ],
        }


def default_v10_training_plan() -> V10TrainingPlan:
    retention = MetricGate(
        "general_multimodal_regression",
        0.005,
        higher_is_better=False,
    )
    structured = MetricGate(
        "structured_output_valid_rate",
        0.998,
        higher_is_better=True,
    )
    return V10TrainingPlan(
        base_model="AI-ModelScope/Gemma-4-E4B-it",
        base_revision="4f5f0c899a9b6d34c4b463f557c31c8ac6c767cc",
        radeon_required=True,
        multi_gpu_required=True,
        minimum_world_size=2,
        preferred_world_size=4,
        preferred_strategy="ddp",
        memory_fallback_strategy="fsdp2",
        single_gpu_baseline_required=True,
        single_gpu_may_promote=False,
        maximum_resident_heavy_models_per_rank=1,
        expected_global_batch_size=16,
        cold_launch_trials=3,
        checkpoint_resume_trials=2,
        two_gpu_minimum_speedup=1.5,
        minimum_parallel_efficiency=0.70,
        maximum_total_gpu_hours=40.0,
        maximum_wall_clock_hours=20.0,
        judge_human_label_minimum=100,
        judge_tpr_minimum=0.80,
        judge_tnr_minimum=0.80,
        stages=(
            CurriculumStage(
                phase=TrainingPhase.MULTIMODAL_CPT,
                objective=(
                    "continued pretraining on licensed interleaved GTM evidence "
                    "while retaining frozen vision/audio towers"
                ),
                trainable_modules=("language_model_lora", "multimodal_connector_lora"),
                frozen_modules=("vision_tower", "audio_tower", "base_weights"),
                loss_terms={"next_token": 1.0, "retention": 0.2},
                maximum_gpu_hours=8.0,
                checkpoint_every_steps=100,
                acceptance_gates=(retention,),
                rollback_checkpoint="base",
                teacher_policy="no teacher; licensed corpus only",
            ),
            CurriculumStage(
                phase=TrainingPhase.CURRICULUM_SFT,
                objective="short-to-long typed GTM tasks with grounded multimodal outputs",
                trainable_modules=("language_model_lora",),
                frozen_modules=("vision_tower", "audio_tower", "base_weights"),
                loss_terms={"supervised": 1.0, "schema": 0.2},
                maximum_gpu_hours=8.0,
                checkpoint_every_steps=100,
                acceptance_gates=(retention, structured),
                rollback_checkpoint="multimodal_cpt",
                teacher_policy="licensed expert demonstrations with source locators",
            ),
            CurriculumStage(
                phase=TrainingPhase.DIRECT_FEEDBACK,
                objective="4A text-gradient revisions without collapsing taste to one scalar",
                trainable_modules=("language_model_lora",),
                frozen_modules=("vision_tower", "audio_tower", "base_weights"),
                loss_terms={"revision": 1.0, "dimension_feedback": 0.5},
                maximum_gpu_hours=6.0,
                checkpoint_every_steps=80,
                acceptance_gates=(
                    retention,
                    MetricGate("four_a_overall_mean", 4.6, True),
                ),
                rollback_checkpoint="curriculum_sft",
                teacher_policy="five-dimension human feedback; no hidden chain of thought",
            ),
            CurriculumStage(
                phase=TrainingPhase.ON_POLICY_DISTILLATION,
                objective=(
                    "distill tool choice, stopping, and recovery on student trajectories "
                    "with high-entropy branch monitoring"
                ),
                trainable_modules=("language_model_lora",),
                frozen_modules=("vision_tower", "audio_tower", "base_weights"),
                loss_terms={"on_policy_kl": 0.6, "trajectory": 0.4, "entropy": 0.1},
                maximum_gpu_hours=7.0,
                checkpoint_every_steps=50,
                acceptance_gates=(
                    retention,
                    MetricGate("agent_success_rate", 0.97, True),
                    MetricGate("tool_error_rate", 0.005, False),
                ),
                rollback_checkpoint="direct_feedback",
                teacher_policy=(
                    "open frozen teacher; precomputed privileged signals; "
                    "teacher-information-gain gate"
                ),
            ),
            CurriculumStage(
                phase=TrainingPhase.MULTI_OBJECTIVE_RL,
                objective=(
                    "optimize claim safety, task success, taste, identity, and cost "
                    "with separate rewards and hard constraints"
                ),
                trainable_modules=("language_model_lora",),
                frozen_modules=("vision_tower", "audio_tower", "base_weights"),
                loss_terms={
                    "task": 0.3,
                    "claim": 0.2,
                    "taste": 0.2,
                    "identity": 0.2,
                    "cost": 0.1,
                },
                maximum_gpu_hours=7.0,
                checkpoint_every_steps=50,
                acceptance_gates=(
                    retention,
                    MetricGate("critical_unsupported_claim_count", 0, False),
                    MetricGate("agent_success_rate", 0.99, True),
                ),
                rollback_checkpoint="on_policy_distillation",
                teacher_policy="calibrated critics plus deterministic hard gates",
            ),
            CurriculumStage(
                phase=TrainingPhase.ADAPTER_EXPERT_CONSOLIDATION,
                objective=(
                    "consolidate GTM role adapters into sparse top-2 experts "
                    "with generalist fallback"
                ),
                trainable_modules=("adapter_router", "role_adapters"),
                frozen_modules=(
                    "vision_tower",
                    "audio_tower",
                    "base_weights",
                    "accepted_lora_backbone",
                ),
                loss_terms={"routing": 0.5, "task": 0.4, "balance": 0.1},
                maximum_gpu_hours=4.0,
                checkpoint_every_steps=50,
                acceptance_gates=(
                    retention,
                    MetricGate("router_fallback_success_rate", 0.99, True),
                    MetricGate("gtm_gain_vs_v9", 0.20, True),
                ),
                rollback_checkpoint="multi_objective_rl",
                teacher_policy="accepted stage checkpoints only",
            ),
        ),
    )


@dataclass(frozen=True)
class JudgeCalibration:
    true_positive: int
    false_negative: int
    true_negative: int
    false_positive: int

    @property
    def label_count(self) -> int:
        return (
            self.true_positive
            + self.false_negative
            + self.true_negative
            + self.false_positive
        )

    @property
    def tpr(self) -> float:
        denominator = self.true_positive + self.false_negative
        return self.true_positive / denominator if denominator else 0.0

    @property
    def tnr(self) -> float:
        denominator = self.true_negative + self.false_positive
        return self.true_negative / denominator if denominator else 0.0

    def passes(self, plan: V10TrainingPlan) -> bool:
        return (
            self.label_count >= plan.judge_human_label_minimum
            and self.tpr > plan.judge_tpr_minimum
            and self.tnr > plan.judge_tnr_minimum
        )


@dataclass
class TrainingRunState:
    plan: V10TrainingPlan
    corpus_digest: str
    statuses: dict[TrainingPhase, TrainingPhaseStatus] = field(
        default_factory=lambda: {
            phase: TrainingPhaseStatus.PENDING for phase in TrainingPhase
        }
    )
    checkpoint_sha256: dict[TrainingPhase, str] = field(default_factory=dict)
    metrics: dict[TrainingPhase, Mapping[str, float]] = field(default_factory=dict)

    def start(self, phase: TrainingPhase) -> None:
        expected = tuple(TrainingPhase).index(phase)
        predecessors = tuple(TrainingPhase)[:expected]
        if any(
            self.statuses[item] != TrainingPhaseStatus.PASSED
            for item in predecessors
        ):
            raise V10ContractError("training phases must pass in curriculum order")
        if self.statuses[phase] != TrainingPhaseStatus.PENDING:
            raise V10ContractError("training phase is not pending")
        self.statuses[phase] = TrainingPhaseStatus.RUNNING

    def finish(
        self,
        phase: TrainingPhase,
        *,
        checkpoint_sha256: str,
        metrics: Mapping[str, float],
    ) -> TrainingPhaseStatus:
        if self.statuses[phase] != TrainingPhaseStatus.RUNNING:
            raise V10ContractError("training phase is not running")
        _sha256(checkpoint_sha256, "checkpoint_sha256")
        stage = next(item for item in self.plan.stages if item.phase == phase)
        self.metrics[phase] = dict(metrics)
        passed = all(gate.passes(metrics) for gate in stage.acceptance_gates)
        self.statuses[phase] = (
            TrainingPhaseStatus.PASSED
            if passed
            else TrainingPhaseStatus.ROLLED_BACK
        )
        if passed:
            self.checkpoint_sha256[phase] = checkpoint_sha256
        return self.statuses[phase]


@dataclass(frozen=True)
class PreferenceEvidence:
    preferred_count: int
    comparison_count: int

    @property
    def rate(self) -> float:
        return self.preferred_count / self.comparison_count

    @property
    def wilson_lower_95(self) -> float:
        return wilson_lower_bound(self.preferred_count, self.comparison_count)

    @property
    def passes_v10(self) -> bool:
        return self.rate >= 0.80 and self.wilson_lower_95 > 0.70
