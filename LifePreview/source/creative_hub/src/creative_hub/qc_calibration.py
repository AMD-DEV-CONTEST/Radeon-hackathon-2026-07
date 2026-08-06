from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from creative_hub.quality import (
    DefectSeverity,
    EvaluatorBundle,
    FrozenModel,
    MachineJudgment,
    QCDefect,
    QCPromptRevision,
    QualityError,
    QualityStage,
    canonical_digest,
)


class TrialEvaluatorRubric(FrozenModel):
    """Immutable Shidu-trial identity layered on an existing QC stage."""

    stage: QualityStage
    prompt_key: str = Field(pattern=r"^shidu-trial-[a-z]+-qc$")
    prompt_text: str = Field(min_length=1, max_length=100_000)
    rubric_revision_id: str = Field(
        pattern=r"^shidu-trial-[a-z]+-rubric\.v[1-9][0-9]*$"
    )
    criteria: tuple[str, ...] = Field(min_length=1)
    blocking_defect_codes: tuple[str, ...] = Field(min_length=1)
    rubric_digest: str = ""

    @model_validator(mode="after")
    def bind_trial_rubric(self) -> TrialEvaluatorRubric:
        if self.stage not in {
            QualityStage.KEYFRAME,
            QualityStage.CLIP,
            QualityStage.FINAL,
        }:
            raise ValueError(
                "trial evaluator must reuse keyframe, clip, or final stage"
            )
        if len(set(self.criteria)) != len(self.criteria):
            raise ValueError("trial rubric criteria must be unique")
        if len(set(self.blocking_defect_codes)) != len(
            self.blocking_defect_codes
        ):
            raise ValueError("trial blocking defect codes must be unique")
        expected = canonical_digest(
            self.model_dump(mode="json", exclude={"rubric_digest"})
        )
        if self.rubric_digest and self.rubric_digest != expected:
            raise ValueError("rubric_digest does not match immutable rubric")
        object.__setattr__(self, "rubric_digest", expected)
        return self


_TRIAL_EVALUATOR_RUBRICS = (
    TrialEvaluatorRubric(
        stage=QualityStage.KEYFRAME,
        prompt_key="shidu-trial-keyframe-qc",
        prompt_text=(
            "检查试读关键帧的人物、时代、场景和构图是否忠于已锁定的六镜头脚本，"
            "并为每个缺陷定位可复核证据。"
        ),
        rubric_revision_id="shidu-trial-keyframe-rubric.v1",
        criteria=(
            "character_and_era_consistency",
            "scene_and_composition_fidelity",
            "evidence_localization",
        ),
        blocking_defect_codes=(
            "KEYFRAME.CHARACTER_DRIFT",
            "KEYFRAME.ERA_MISMATCH",
            "KEYFRAME.SCRIPT_DIVERGENCE",
        ),
    ),
    TrialEvaluatorRubric(
        stage=QualityStage.CLIP,
        prompt_key="shidu-trial-clip-qc",
        prompt_text=(
            "检查试读片段的运动稳定性、人物与场景连续性、画面文字和镜头脚本一致性，"
            "并将缺陷定位到时间范围和责任节点。"
        ),
        rubric_revision_id="shidu-trial-clip-rubric.v1",
        criteria=(
            "motion_and_visual_integrity",
            "cross_shot_continuity",
            "script_fidelity",
            "evidence_and_responsible_node_localization",
        ),
        blocking_defect_codes=(
            "CLIP.DEFORMATION",
            "CLIP.CONTINUITY_BREAK",
            "CLIP.UNSAFE_TEXT",
            "CLIP.SCRIPT_DIVERGENCE",
        ),
    ),
    TrialEvaluatorRubric(
        stage=QualityStage.FINAL,
        prompt_key="shidu-trial-final-qc",
        prompt_text=(
            "检查六镜头试读成片的旁白、字幕、画面和音频对齐，确认使用已锁定的 "
            "CustomVoice 且不存在口型同步，并给出可复核的最终证据。"
        ),
        rubric_revision_id="shidu-trial-final-rubric.v1",
        criteria=(
            "six_shot_structure",
            "narration_subtitle_alignment",
            "custom_voice_binding",
            "audio_visual_delivery_integrity",
            "evidence_localization",
        ),
        blocking_defect_codes=(
            "FINAL.SHOT_COUNT_MISMATCH",
            "FINAL.AV_MISALIGNMENT",
            "FINAL.VOICE_BINDING_MISMATCH",
            "FINAL.LIPSYNC_PRESENT",
        ),
    ),
)


def trial_evaluator_rubrics() -> tuple[TrialEvaluatorRubric, ...]:
    return _TRIAL_EVALUATOR_RUBRICS


def build_trial_evaluator_bundle(
    *,
    project_id: UUID,
    prompt: QCPromptRevision,
    rubric: TrialEvaluatorRubric,
    model_name: str,
    model_version: str,
    implementation_digest: str,
) -> EvaluatorBundle:
    """Freeze one exact prompt/rubric/model implementation combination."""

    if prompt.project_id != project_id:
        raise QualityError("trial evaluator prompt project mismatch")
    if prompt.stage is not rubric.stage:
        raise QualityError("trial evaluator prompt stage mismatch")
    if prompt.prompt_key != rubric.prompt_key:
        raise QualityError("trial evaluator prompt key mismatch")
    return EvaluatorBundle(
        project_id=project_id,
        stage=rubric.stage,
        prompt_revision_id=prompt.prompt_revision_id,
        prompt_digest=prompt.prompt_digest,
        rubric_revision_id=rubric.rubric_revision_id,
        rubric_digest=rubric.rubric_digest,
        model_name=model_name,
        model_version=model_version,
        implementation_digest=implementation_digest,
    )


class LabelSource(StrEnum):
    HUMAN = "HUMAN"
    MACHINE = "MACHINE"


class HumanGoldLabel(FrozenModel):
    label_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    stage: QualityStage
    artifact_id: UUID
    artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer_id: str = Field(min_length=1, max_length=200)
    source: LabelSource = LabelSource.HUMAN
    judgment: MachineJudgment
    defects: tuple[QCDefect, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def human_only(self) -> HumanGoldLabel:
        if self.source is not LabelSource.HUMAN:
            raise ValueError("machine judgments cannot become Gold labels")
        if self.judgment is MachineJudgment.PASS and self.defects:
            raise ValueError("Gold PASS cannot carry defects")
        if self.judgment is MachineJudgment.FAIL and not self.defects:
            raise ValueError("Gold FAIL requires defects")
        return self

    @property
    def semantic_digest(self) -> str:
        return canonical_digest(
            {
                "project_id": str(self.project_id),
                "stage": self.stage.value,
                "artifact_id": str(self.artifact_id),
                "artifact_digest": self.artifact_digest,
                "judgment": self.judgment.value,
                "defects": [
                    item.model_dump(mode="json") for item in self.defects
                ],
                "evidence_refs": sorted(self.evidence_refs),
            }
        )


class GoldItem(FrozenModel):
    gold_item_id: UUID = Field(default_factory=uuid4)
    artifact_id: UUID
    artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage: QualityStage
    judgment: MachineJudgment
    defects: tuple[QCDefect, ...]
    evidence_refs: tuple[str, ...]
    source_label_ids: tuple[UUID, ...]
    promotion_method: str = Field(pattern=r"^(DUAL_AGREEMENT|ARBITRATION)$")

    @model_validator(mode="after")
    def valid_human_promotion(self) -> GoldItem:
        expected = 2 if self.promotion_method == "DUAL_AGREEMENT" else 3
        if (
            len(self.source_label_ids) != expected
            or len(set(self.source_label_ids)) != expected
        ):
            raise ValueError(
                "Gold promotion requires distinct human source labels"
            )
        if self.judgment is MachineJudgment.PASS and self.defects:
            raise ValueError("Gold PASS cannot carry defects")
        if self.judgment is MachineJudgment.FAIL and not self.defects:
            raise ValueError("Gold FAIL requires defects")
        return self


class GoldDatasetRevision(FrozenModel):
    dataset_revision_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    dataset_key: str = Field(min_length=1, max_length=120)
    revision: int = Field(ge=1)
    parent_revision_id: UUID | None = None
    items: tuple[GoldItem, ...]
    created_by_actor: str = Field(min_length=1, max_length=200)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    dataset_digest: str = ""

    @model_validator(mode="after")
    def digest_items(self) -> GoldDatasetRevision:
        if len({item.artifact_id for item in self.items}) != len(self.items):
            raise ValueError("Gold dataset has duplicate artifact identities")
        expected = canonical_digest(
            self.model_dump(mode="json", exclude={"dataset_digest"})
        )
        if self.dataset_digest and self.dataset_digest != expected:
            raise ValueError("dataset_digest does not match Gold revision")
        object.__setattr__(self, "dataset_digest", expected)
        return self


class GoldDatasetBuilder:
    @staticmethod
    def _require_human(*labels: HumanGoldLabel) -> None:
        if any(item.source is not LabelSource.HUMAN for item in labels):
            raise QualityError("machine judgments cannot enter Gold datasets")

    def promote_dual(
        self,
        first: HumanGoldLabel,
        second: HumanGoldLabel,
    ) -> GoldItem:
        self._require_human(first, second)
        if first.reviewer_id == second.reviewer_id:
            raise QualityError("Gold promotion requires two distinct reviewers")
        if first.semantic_digest != second.semantic_digest:
            raise QualityError("disputed labels require human arbitration")
        return GoldItem(
            artifact_id=first.artifact_id,
            artifact_digest=first.artifact_digest,
            stage=first.stage,
            judgment=first.judgment,
            defects=first.defects,
            evidence_refs=tuple(sorted(first.evidence_refs)),
            source_label_ids=(first.label_id, second.label_id),
            promotion_method="DUAL_AGREEMENT",
        )

    def arbitrate(
        self,
        *,
        disputed: tuple[HumanGoldLabel, HumanGoldLabel],
        arbiter: HumanGoldLabel,
    ) -> GoldItem:
        self._require_human(*disputed, arbiter)
        reviewers = {item.reviewer_id for item in disputed}
        if arbiter.reviewer_id in reviewers:
            raise QualityError("arbiter must be an independent human reviewer")
        if any(
            (
                item.project_id != arbiter.project_id
                or item.stage != arbiter.stage
                or item.artifact_id != arbiter.artifact_id
                or item.artifact_digest != arbiter.artifact_digest
            )
            for item in disputed
        ):
            raise QualityError("arbitration labels do not bind one artifact")
        return GoldItem(
            artifact_id=arbiter.artifact_id,
            artifact_digest=arbiter.artifact_digest,
            stage=arbiter.stage,
            judgment=arbiter.judgment,
            defects=arbiter.defects,
            evidence_refs=tuple(sorted(arbiter.evidence_refs)),
            source_label_ids=(
                disputed[0].label_id,
                disputed[1].label_id,
                arbiter.label_id,
            ),
            promotion_method="ARBITRATION",
        )


class CalibrationThresholds(FrozenModel):
    minimum_samples: int = Field(ge=1)
    maximum_severe_false_acceptance_rate: float = Field(ge=0, le=1)
    maximum_false_acceptance_rate: float = Field(ge=0, le=1)
    maximum_false_rejection_rate: float = Field(ge=0, le=1)
    minimum_evidence_localization_rate: float = Field(ge=0, le=1)
    minimum_repair_success_rate: float = Field(ge=0, le=1)
    maximum_average_cost_micros: int = Field(ge=0)


class CalibrationPrediction(FrozenModel):
    artifact_id: UUID
    judgment: MachineJudgment
    defects: tuple[QCDefect, ...] = ()
    evidence_localized: bool
    repair_succeeded: bool | None = None
    cost_micros: int = Field(ge=0)


class CalibrationReport(FrozenModel):
    report_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    stage: QualityStage
    gold_dataset_revision_id: UUID
    gold_dataset_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_bundle_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    sample_count: int = Field(ge=0)
    severe_false_acceptance_rate: float = Field(ge=0, le=1)
    false_acceptance_rate: float = Field(ge=0, le=1)
    false_rejection_rate: float = Field(ge=0, le=1)
    evidence_localization_rate: float = Field(ge=0, le=1)
    repair_success_rate: float = Field(ge=0, le=1)
    average_cost_micros: float = Field(ge=0)
    passed: bool
    failures: tuple[str, ...]

    @model_validator(mode="after")
    def consistent_verdict(self) -> CalibrationReport:
        if self.passed != (not self.failures):
            raise ValueError("calibration verdict/failures are inconsistent")
        return self


def evaluate_calibration(
    *,
    bundle: EvaluatorBundle,
    dataset: GoldDatasetRevision,
    predictions: tuple[CalibrationPrediction, ...],
    thresholds: CalibrationThresholds,
) -> CalibrationReport:
    if bundle.project_id != dataset.project_id:
        raise QualityError("calibration bundle/dataset project mismatch")
    gold = {item.artifact_id: item for item in dataset.items}
    predicted = {item.artifact_id: item for item in predictions}
    if set(gold) != set(predicted):
        raise QualityError("predictions must exactly cover the Gold revision")
    if any(item.stage != bundle.stage for item in dataset.items):
        raise QualityError("Gold items do not match evaluator stage")

    false_accepts = 0
    severe_false_accepts = 0
    false_rejects = 0
    gold_failures = 0
    gold_severe_failures = 0
    gold_passes = 0
    evidence_localized = 0
    repair_trials = 0
    repair_successes = 0
    costs = 0
    for artifact_id, item in gold.items():
        prediction = predicted[artifact_id]
        costs += prediction.cost_micros
        if item.judgment is MachineJudgment.FAIL:
            gold_failures += 1
            if any(
                defect.severity is DefectSeverity.CRITICAL
                for defect in item.defects
            ):
                gold_severe_failures += 1
        else:
            gold_passes += 1
        if prediction.evidence_localized:
            evidence_localized += 1
        if (
            item.judgment is MachineJudgment.FAIL
            and prediction.judgment is MachineJudgment.PASS
        ):
            false_accepts += 1
            if any(
                defect.severity is DefectSeverity.CRITICAL
                for defect in item.defects
            ):
                severe_false_accepts += 1
        if (
            item.judgment is MachineJudgment.PASS
            and prediction.judgment is MachineJudgment.FAIL
        ):
            false_rejects += 1
        if prediction.repair_succeeded is not None:
            repair_trials += 1
            repair_successes += int(prediction.repair_succeeded)

    count = len(gold)
    metrics = {
        "severe_false_acceptance_rate": (
            0.0
            if gold_severe_failures == 0
            else severe_false_accepts / gold_severe_failures
        ),
        "false_acceptance_rate": (
            0.0 if gold_failures == 0 else false_accepts / gold_failures
        ),
        "false_rejection_rate": (
            0.0 if gold_passes == 0 else false_rejects / gold_passes
        ),
        "evidence_localization_rate": (
            0.0 if count == 0 else evidence_localized / count
        ),
        "repair_success_rate": (
            0.0 if repair_trials == 0 else repair_successes / repair_trials
        ),
        "average_cost_micros": 0.0 if count == 0 else costs / count,
    }
    failures = []
    if count < thresholds.minimum_samples:
        failures.append("minimum_samples")
    comparisons = (
        (
            "severe_false_acceptance_rate",
            metrics["severe_false_acceptance_rate"]
            <= thresholds.maximum_severe_false_acceptance_rate,
        ),
        (
            "false_acceptance_rate",
            metrics["false_acceptance_rate"]
            <= thresholds.maximum_false_acceptance_rate,
        ),
        (
            "false_rejection_rate",
            metrics["false_rejection_rate"]
            <= thresholds.maximum_false_rejection_rate,
        ),
        (
            "evidence_localization_rate",
            metrics["evidence_localization_rate"]
            >= thresholds.minimum_evidence_localization_rate,
        ),
        (
            "repair_success_rate",
            metrics["repair_success_rate"]
            >= thresholds.minimum_repair_success_rate,
        ),
        (
            "average_cost_micros",
            metrics["average_cost_micros"]
            <= thresholds.maximum_average_cost_micros,
        ),
    )
    failures.extend(name for name, passed in comparisons if not passed)
    return CalibrationReport(
        project_id=bundle.project_id,
        stage=bundle.stage,
        gold_dataset_revision_id=dataset.dataset_revision_id,
        gold_dataset_digest=dataset.dataset_digest,
        evaluator_bundle_digest=bundle.bundle_digest,
        sample_count=count,
        passed=not failures,
        failures=tuple(failures),
        **metrics,
    )


class CertificationStatus(StrEnum):
    CERTIFIED = "CERTIFIED"
    REVOKED = "REVOKED"


class EvaluatorMaturity(StrEnum):
    SHADOW = "SHADOW"
    CERTIFIED = "CERTIFIED"
    REVOKED = "REVOKED"


class EvaluatorCertification(FrozenModel):
    certification_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    stage: QualityStage
    evaluator_bundle_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    calibration_report_id: UUID
    gold_dataset_revision_id: UUID
    status: CertificationStatus = CertificationStatus.CERTIFIED
    issued_by_actor: str = Field(min_length=1, max_length=200)
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CertificationRegistry:
    """Version-exact certification; a prompt edit creates a new Shadow bundle."""

    def __init__(self) -> None:
        self._events: dict[str, list[EvaluatorCertification]] = defaultdict(list)

    def certify(
        self,
        *,
        bundle: EvaluatorBundle,
        report: CalibrationReport,
        issued_by_actor: str,
    ) -> EvaluatorCertification:
        if (
            report.project_id != bundle.project_id
            or report.stage != bundle.stage
            or report.evaluator_bundle_digest != bundle.bundle_digest
        ):
            raise QualityError("certification report does not bind evaluator")
        if not report.passed:
            raise QualityError("failed calibration cannot be certified")
        certification = EvaluatorCertification(
            project_id=bundle.project_id,
            stage=bundle.stage,
            evaluator_bundle_digest=bundle.bundle_digest,
            calibration_report_id=report.report_id,
            gold_dataset_revision_id=report.gold_dataset_revision_id,
            issued_by_actor=issued_by_actor,
        )
        self._events[bundle.bundle_digest].append(certification)
        return certification

    def revoke(
        self,
        *,
        bundle: EvaluatorBundle,
        calibration_report_id: UUID,
        gold_dataset_revision_id: UUID,
        actor_id: str,
    ) -> EvaluatorCertification:
        event = EvaluatorCertification(
            project_id=bundle.project_id,
            stage=bundle.stage,
            evaluator_bundle_digest=bundle.bundle_digest,
            calibration_report_id=calibration_report_id,
            gold_dataset_revision_id=gold_dataset_revision_id,
            status=CertificationStatus.REVOKED,
            issued_by_actor=actor_id,
        )
        self._events[bundle.bundle_digest].append(event)
        return event

    def is_certified(self, bundle: EvaluatorBundle) -> bool:
        events = self._events.get(bundle.bundle_digest, [])
        return bool(events and events[-1].status is CertificationStatus.CERTIFIED)

    def maturity(self, bundle: EvaluatorBundle) -> EvaluatorMaturity:
        events = self._events.get(bundle.bundle_digest, [])
        if not events:
            return EvaluatorMaturity.SHADOW
        return EvaluatorMaturity(events[-1].status.value)
