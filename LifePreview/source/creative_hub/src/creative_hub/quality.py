from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from shared_contracts import H3CandidateScoreV1


def canonical_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class QualityError(RuntimeError):
    pass


class QualityStage(StrEnum):
    ASSET = "asset"
    KEYFRAME = "keyframe"
    CLIP = "clip"
    FINAL = "final"

    @property
    def ordinal(self) -> int:
        return tuple(QualityStage).index(self)


class HumanReviewMode(StrEnum):
    ALL = "ALL"
    EXCEPTIONS_ONLY = "EXCEPTIONS_ONLY"
    OFF = "OFF"


class GateExhaustionPolicy(StrEnum):
    BLOCK = "BLOCK"
    DEGRADED_ACCEPT = "DEGRADED_ACCEPT"


class MachineJudgment(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class DefectSeverity(StrEnum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class RepairDisposition(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PLANNED = "PLANNED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


class GateOutcomeKind(StrEnum):
    SELECTED = "SELECTED"
    REWORK_PLANNED = "REWORK_PLANNED"
    WAITING_HUMAN = "WAITING_HUMAN"
    DEGRADED_ACCEPTED = "DEGRADED_ACCEPTED"
    BLOCKED_UNCERTIFIED = "BLOCKED_UNCERTIFIED"


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArtifactBinding(FrozenModel):
    project_id: UUID
    artifact_id: UUID
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    operation_run_id: UUID
    operation_attempt_id: UUID


class EvidencePackBinding(FrozenModel):
    project_id: UUID
    evidence_pack_id: UUID
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_ids: tuple[UUID, ...] = ()


class QCPromptRevision(FrozenModel):
    prompt_revision_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    prompt_key: str = Field(min_length=1, max_length=120)
    stage: QualityStage
    revision: int = Field(ge=1)
    prompt_text: str = Field(min_length=1, max_length=100_000)
    parent_revision_id: UUID | None = None
    created_by_actor: str = Field(min_length=1, max_length=200)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    prompt_digest: str = ""

    @model_validator(mode="after")
    def bind_digest(self) -> QCPromptRevision:
        expected = canonical_digest(
            {
                "project_id": str(self.project_id),
                "prompt_key": self.prompt_key,
                "stage": self.stage.value,
                "revision": self.revision,
                "prompt_text": self.prompt_text,
                "parent_revision_id": (
                    None
                    if self.parent_revision_id is None
                    else str(self.parent_revision_id)
                ),
            }
        )
        if self.prompt_digest and self.prompt_digest != expected:
            raise ValueError("prompt_digest does not match immutable prompt")
        object.__setattr__(self, "prompt_digest", expected)
        return self


class PromptRevisionStore:
    """Small append-only prompt store; durable adapters persist the same model."""

    def __init__(self) -> None:
        self._revisions: dict[UUID, QCPromptRevision] = {}
        self._heads: dict[tuple[UUID, str, QualityStage], UUID] = {}

    def create(
        self,
        *,
        project_id: UUID,
        prompt_key: str,
        stage: QualityStage,
        prompt_text: str,
        created_by_actor: str,
    ) -> QCPromptRevision:
        key = (project_id, prompt_key, stage)
        parent = self._revisions.get(self._heads.get(key))
        revision = QCPromptRevision(
            project_id=project_id,
            prompt_key=prompt_key,
            stage=stage,
            revision=1 if parent is None else parent.revision + 1,
            prompt_text=prompt_text,
            parent_revision_id=(
                None if parent is None else parent.prompt_revision_id
            ),
            created_by_actor=created_by_actor,
        )
        self._revisions[revision.prompt_revision_id] = revision
        self._heads[key] = revision.prompt_revision_id
        return revision

    def get(self, prompt_revision_id: UUID) -> QCPromptRevision:
        try:
            return self._revisions[prompt_revision_id]
        except KeyError as exc:
            raise QualityError("prompt revision not found") from exc


class EvaluatorBundle(FrozenModel):
    project_id: UUID
    stage: QualityStage
    prompt_revision_id: UUID
    prompt_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    rubric_revision_id: str = Field(min_length=1, max_length=200)
    rubric_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_name: str = Field(min_length=1, max_length=200)
    model_version: str = Field(min_length=1, max_length=200)
    implementation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def bundle_digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


class QCDefect(FrozenModel):
    defect_code: str = Field(pattern=r"^[A-Z][A-Z0-9_.-]{0,99}$")
    severity: DefectSeverity
    message: str = Field(min_length=1, max_length=2_000)
    time_range_ms: tuple[int, int] | None = None
    subject_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    responsible_node_ids: tuple[str, ...] = ()
    recommended_repair_action: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def valid_time_range(self) -> QCDefect:
        if self.time_range_ms is not None:
            start, end = self.time_range_ms
            if start < 0 or end < start:
                raise ValueError("defect time range is invalid")
        return self


class RepairResult(FrozenModel):
    disposition: RepairDisposition
    derived_operation_run_id: UUID | None = None
    produced_artifact_id: UUID | None = None
    detail: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def valid_identity(self) -> RepairResult:
        if self.disposition is RepairDisposition.SUCCEEDED and (
            self.derived_operation_run_id is None
            or self.produced_artifact_id is None
        ):
            raise ValueError("successful repair requires operation and artifact")
        return self


class ResourceUsage(FrozenModel):
    cost_micros: int = Field(default=0, ge=0)
    gpu_seconds: float = Field(default=0, ge=0)
    wall_seconds: float = Field(default=0, ge=0)

    def plus(self, other: ResourceUsage) -> ResourceUsage:
        return ResourceUsage(
            cost_micros=self.cost_micros + other.cost_micros,
            gpu_seconds=self.gpu_seconds + other.gpu_seconds,
            wall_seconds=self.wall_seconds + other.wall_seconds,
        )


class EvaluatorRepairDirective(FrozenModel):
    changed_parameters: dict[str, Any] = Field(default_factory=dict)
    estimated_usage: ResourceUsage = Field(default_factory=ResourceUsage)


class QCEvaluatorResult(FrozenModel):
    judgment: MachineJudgment
    quality_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    defects: tuple[QCDefect, ...] = ()
    recommended_actions: tuple[str, ...] = ()
    repair_result: RepairResult
    h3_qc: H3CandidateScoreV1 | None = None
    repair_directive: EvaluatorRepairDirective | None = None
    generation_usage: ResourceUsage = Field(default_factory=ResourceUsage)

    @model_validator(mode="after")
    def judgment_matches_defects(self) -> QCEvaluatorResult:
        if self.judgment is MachineJudgment.PASS and self.defects:
            raise ValueError(
                "PASS evaluator result cannot carry unresolved defects"
            )
        if self.judgment is MachineJudgment.FAIL and not self.defects:
            raise ValueError(
                "FAIL evaluator result requires at least one defect"
            )
        return self


class QCEvaluation(FrozenModel):
    evaluation_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    workflow_run_id: UUID
    stage: QualityStage
    gate_key: str | None = Field(default=None, min_length=1, max_length=200)
    artifact: ArtifactBinding
    evidence_pack: EvidencePackBinding
    expected_selection_version: int = Field(ge=0)
    evaluator: EvaluatorBundle
    judgment: MachineJudgment
    quality_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    defects: tuple[QCDefect, ...] = ()
    recommended_actions: tuple[str, ...] = ()
    repair_result: RepairResult
    h3_qc: H3CandidateScoreV1 | None = None
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    evaluation_digest: str = ""

    @model_validator(mode="after")
    def validate_and_digest(self) -> QCEvaluation:
        object.__setattr__(
            self, "gate_key", _normalized_gate_key(self.stage, self.gate_key)
        )
        if self.project_id != self.evaluator.project_id:
            raise ValueError("evaluation/evaluator project mismatch")
        if (
            self.project_id != self.artifact.project_id
            or self.project_id != self.evidence_pack.project_id
        ):
            raise ValueError("evaluation inputs must share one project")
        if self.stage != self.evaluator.stage:
            raise ValueError("evaluation/evaluator stage mismatch")
        if self.judgment is MachineJudgment.PASS and self.defects:
            raise ValueError("PASS evaluation cannot carry unresolved defects")
        if self.judgment is MachineJudgment.FAIL and not self.defects:
            raise ValueError("FAIL evaluation requires at least one defect")
        if self.h3_qc is not None and self.stage is not QualityStage.CLIP:
            raise ValueError("H3 audiovisual QC is only valid at the clip stage")
        if self.artifact.artifact_id in self.evidence_pack.artifact_ids:
            # The evaluated output may be one of the EvidencePack sources; this
            # is intentionally permitted. The check merely keeps the branch
            # explicit and documents that IDs, not paths, are authoritative.
            pass
        excluded = {"evaluation_digest"}
        if self.h3_qc is None:
            excluded.add("h3_qc")
        payload = self.model_dump(mode="json", exclude=excluded)
        expected = canonical_digest(payload)
        if self.evaluation_digest and self.evaluation_digest != expected:
            raise ValueError("evaluation_digest does not match evaluation")
        object.__setattr__(self, "evaluation_digest", expected)
        return self


class GateBudget(FrozenModel):
    max_repair_count: int = Field(ge=0)
    max_cost_micros: int = Field(ge=0)
    max_gpu_seconds: float = Field(ge=0)
    max_wall_seconds: float = Field(ge=0)

    @field_validator("max_repair_count", "max_cost_micros", mode="before")
    @classmethod
    def strict_integer_budget(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("integer gate budgets must be integers")
        return value

    @field_validator("max_gpu_seconds", "max_wall_seconds", mode="before")
    @classmethod
    def strict_finite_seconds(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("gate seconds must be numeric")
        if not math.isfinite(float(value)):
            raise ValueError("gate seconds must be finite")
        return value

    def permits(
        self,
        *,
        repair_count: int,
        usage: ResourceUsage,
    ) -> bool:
        return (
            repair_count <= self.max_repair_count
            and usage.cost_micros <= self.max_cost_micros
            and usage.gpu_seconds <= self.max_gpu_seconds
            and usage.wall_seconds <= self.max_wall_seconds
        )


class GatePolicySnapshot(FrozenModel):
    policy_snapshot_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    workflow_run_id: UUID
    stage: QualityStage
    gate_key: str | None = Field(default=None, min_length=1, max_length=200)
    review_mode: HumanReviewMode
    exhaustion_policy: GateExhaustionPolicy = (
        GateExhaustionPolicy.DEGRADED_ACCEPT
    )
    machine_qc_required: bool = True
    budget: GateBudget
    ranking_revision: str = Field(min_length=1, max_length=100)
    ranking_weights: dict[str, float] = Field(
        default_factory=lambda: {"quality_score": 1.0, "confidence": 0.01}
    )
    prompt_revision_id: UUID
    rubric_revision_id: str = Field(min_length=1, max_length=200)
    evaluator_bundle_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    policy_digest: str = ""

    @field_validator("ranking_weights", mode="before")
    @classmethod
    def strict_ranking_weight_input(cls, value: Any) -> Any:
        if not isinstance(value, dict) or not value:
            raise ValueError("ranking weights must be snapshotted")
        for key, weight in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError("ranking weight keys must be non-empty strings")
            if isinstance(weight, bool) or not isinstance(weight, (int, float)):
                raise ValueError("ranking weights must be numeric")
        return value

    @model_validator(mode="after")
    def mandatory_and_digest(self) -> GatePolicySnapshot:
        object.__setattr__(
            self, "gate_key", _normalized_gate_key(self.stage, self.gate_key)
        )
        if not self.machine_qc_required:
            raise ValueError("machine QC is mandatory at every quality gate")
        if not self.ranking_weights:
            raise ValueError("ranking weights must be snapshotted")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
            for value in self.ranking_weights.values()
        ):
            raise ValueError("ranking weights must be finite non-negative numbers")
        if not any(float(value) > 0 for value in self.ranking_weights.values()):
            raise ValueError("at least one ranking weight must be positive")
        expected = canonical_digest(
            self.model_dump(mode="json", exclude={"policy_digest"})
        )
        if self.policy_digest and self.policy_digest != expected:
            raise ValueError("policy_digest does not match policy")
        object.__setattr__(self, "policy_digest", expected)
        return self


class CandidateVersion(FrozenModel):
    candidate_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    workflow_run_id: UUID
    stage: QualityStage
    gate_key: str | None = Field(default=None, min_length=1, max_length=200)
    ordinal: int = Field(ge=1)
    artifact: ArtifactBinding
    evaluation: QCEvaluation
    generation_usage: ResourceUsage = Field(default_factory=ResourceUsage)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    candidate_digest: str = ""

    @model_validator(mode="after")
    def fixed_evaluation(self) -> CandidateVersion:
        object.__setattr__(
            self, "gate_key", _normalized_gate_key(self.stage, self.gate_key)
        )
        if (
            self.project_id != self.evaluation.project_id
            or self.workflow_run_id != self.evaluation.workflow_run_id
            or self.stage != self.evaluation.stage
            or self.gate_key != self.evaluation.gate_key
        ):
            raise ValueError("candidate/evaluation scope mismatch")
        if self.artifact != self.evaluation.artifact:
            raise ValueError("evaluation must bind the exact candidate artifact")
        expected = canonical_digest(
            self.model_dump(mode="json", exclude={"candidate_digest"})
        )
        if self.candidate_digest and self.candidate_digest != expected:
            raise ValueError("candidate_digest does not match candidate")
        object.__setattr__(self, "candidate_digest", expected)
        return self


class RepairProposal(FrozenModel):
    repair_plan_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    workflow_run_id: UUID
    stage: QualityStage
    gate_key: str | None = Field(default=None, min_length=1, max_length=200)
    parent_candidate_id: UUID
    target_node_ids: tuple[str, ...]
    target_node_stages: dict[str, QualityStage]
    changed_parameters: dict[str, Any]
    estimated_usage: ResourceUsage

    @model_validator(mode="after")
    def current_stage_targets_only(self) -> RepairProposal:
        object.__setattr__(
            self, "gate_key", _normalized_gate_key(self.stage, self.gate_key)
        )
        if set(self.target_node_ids) != set(self.target_node_stages):
            raise ValueError("repair target stage map must be complete")
        if any(
            target_stage is not self.stage
            for target_stage in self.target_node_stages.values()
        ):
            raise ValueError("repair targets must remain in the current stage")
        return self


class GateOutcome(FrozenModel):
    kind: GateOutcomeKind
    stage: QualityStage
    gate_key: str | None = Field(default=None, min_length=1, max_length=200)
    candidate_id: UUID
    selected_candidate_id: UUID | None = None
    expected_selection_version: int
    unresolved_defects: tuple[QCDefect, ...] = ()
    repair_proposal: RepairProposal | None = None
    reason: str

    @model_validator(mode="after")
    def exact_gate(self) -> GateOutcome:
        object.__setattr__(
            self, "gate_key", _normalized_gate_key(self.stage, self.gate_key)
        )
        if (
            self.repair_proposal is not None
            and self.repair_proposal.gate_key != self.gate_key
        ):
            raise ValueError("gate outcome/repair proposal gate mismatch")
        return self


def _normalized_gate_key(
    stage: QualityStage,
    gate_key: str | None,
) -> str:
    value = stage.value if gate_key is None else gate_key
    if not value or value != value.strip() or len(value) > 200:
        raise ValueError("quality gate key is invalid")
    return value
