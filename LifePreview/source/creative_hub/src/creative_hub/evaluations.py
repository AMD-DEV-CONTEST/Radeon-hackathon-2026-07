from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    ActivationCandidateRecord,
    CalibrationRunRecord,
    EvaluationEvidenceRecord,
    EvaluationRecord,
    EvaluationScoreRecord,
    PreferenceEventRecord,
    PreferenceProfileRecord,
)
from .rubric import (
    AI_SHORT_DRAMA_PROFILE_ID,
    AI_SHORT_DRAMA_RUBRIC_ID,
    AI_SHORT_DRAMA_RUBRIC_VERSION,
    CORE_DIMENSION_IDS,
    EvaluationStage,
    EvaluationSubjectType,
    PreferenceAction,
    STAGE_DIMENSIONS,
    ensure_rubric_v1,
)


class EvaluationError(RuntimeError):
    pass


class EvaluationConflict(EvaluationError):
    pass


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceSpanInput(StrictPayload):
    evidence_ref: str = Field(min_length=1, max_length=500)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def valid_span(self):
        if (
            self.start_ms is not None
            and self.end_ms is not None
            and self.end_ms < self.start_ms
        ):
            raise ValueError("evidence end_ms cannot precede start_ms")
        return self


class EvaluationScoreInput(StrictPayload):
    dimension_id: str = Field(min_length=1, max_length=100)
    score: int | None = Field(default=None, ge=1, le=10)
    confidence: float | None = Field(default=None, ge=0, le=1)
    reason: str = Field(min_length=1, max_length=2000)
    na_reason: str | None = Field(default=None, min_length=1, max_length=500)
    evidence_spans: tuple[EvidenceSpanInput, ...] = ()
    original_value: float | None = None
    original_scale: str | None = Field(default=None, max_length=100)
    migration_version: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def score_or_na(self):
        if self.score is None and not self.na_reason:
            raise ValueError("N/A score requires na_reason")
        if self.score is not None and self.na_reason is not None:
            raise ValueError("scored dimension cannot include na_reason")
        return self


class PreferenceSignalInput(StrictPayload):
    action: PreferenceAction | None = None
    preferred_take_ids: tuple[str, ...] = ()
    feedback: str | None = Field(default=None, max_length=4000)
    context: dict[str, Any] = Field(default_factory=dict)


class EvaluationSubmission(StrictPayload):
    subject_type: EvaluationSubjectType
    scores: tuple[EvaluationScoreInput, ...]
    evaluator_model: str | None = Field(default=None, max_length=200)
    model_version: str | None = Field(default=None, max_length=200)
    prompt_version: str | None = Field(default=None, max_length=200)
    raw_response_ref: str | None = Field(default=None, max_length=500)
    supersedes_id: UUID | None = None
    evidence_mode: str = Field(default="full_video", pattern="^(full_video|frames_only)$")
    profile_id: str = Field(
        default=AI_SHORT_DRAMA_PROFILE_ID,
        min_length=1,
        max_length=100,
    )
    lineage_group: str = Field(min_length=1, max_length=255)
    project_id: str | None = Field(default=None, max_length=255)
    scene_id: str | None = Field(default=None, max_length=255)
    knowledge_pack_version: str | None = Field(default=None, max_length=255)
    preference: PreferenceSignalInput | None = None


def _canonical_sha(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _rank(values: list[float]) -> list[float]:
    positions: dict[float, list[int]] = defaultdict(list)
    for index, value in enumerate(values):
        positions[value].append(index)
    ranks = [0.0] * len(values)
    next_rank = 1
    for value in sorted(positions):
        indexes = positions[value]
        average = (next_rank + next_rank + len(indexes) - 1) / 2
        for index in indexes:
            ranks[index] = average
        next_rank += len(indexes)
    return ranks


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum(
        (a - left_mean) * (b - right_mean)
        for a, b in zip(left, right, strict=True)
    )
    left_variance = sum((value - left_mean) ** 2 for value in left)
    right_variance = sum((value - right_mean) ** 2 for value in right)
    denominator = math.sqrt(left_variance * right_variance)
    if denominator == 0:
        return None
    return numerator / denominator


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


class EvaluationRepository:
    """Append-only evaluations plus shadow-only preference calibration."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _validate_submission(
        self,
        *,
        stage: EvaluationStage,
        submission: EvaluationSubmission,
    ) -> None:
        expected = STAGE_DIMENSIONS[stage]
        supplied = tuple(score.dimension_id for score in submission.scores)
        if len(supplied) != len(set(supplied)):
            raise EvaluationError("evaluation dimensions must be unique")
        if set(supplied) != set(expected):
            missing = sorted(set(expected) - set(supplied))
            unexpected = sorted(set(supplied) - set(expected))
            raise EvaluationError(
                f"evaluation applicability mismatch; missing={missing}, "
                f"unexpected={unexpected}"
            )
        if stage in {EvaluationStage.FACTORY_QC, EvaluationStage.HUB_AI}:
            if not (
                submission.evaluator_model
                and submission.model_version
                and submission.prompt_version
            ):
                raise EvaluationError(
                    "AI evaluation requires evaluator model, model version, "
                    "and prompt version"
                )
            for score in submission.scores:
                if score.score is not None and score.confidence is None:
                    raise EvaluationError(
                        "AI scored dimensions require confidence"
                    )
        elif any(
            (
                submission.evaluator_model,
                submission.model_version,
                submission.prompt_version,
                submission.raw_response_ref,
            )
        ):
            raise EvaluationError(
                "human evaluation cannot claim AI evaluator metadata"
            )
        if stage is not EvaluationStage.HUB_HUMAN and submission.preference:
            raise EvaluationError(
                "preference signal is only valid for human evaluation"
            )
        if submission.evidence_mode == "frames_only":
            unavailable = {
                "motion_naturalness",
                "lipsync_quality",
                "audio_technical_quality",
            }
            invalid = [
                score.dimension_id
                for score in submission.scores
                if score.dimension_id in unavailable and score.score is not None
            ]
            if invalid:
                raise EvaluationError(
                    "frame-only evidence must mark motion, lipsync, and audio "
                    f"dimensions N/A: {sorted(invalid)}"
                )

    def _record_payload(self, record: EvaluationRecord) -> dict:
        scores = self._session.scalars(
            select(EvaluationScoreRecord)
            .where(EvaluationScoreRecord.evaluation_id == record.id)
            .order_by(EvaluationScoreRecord.dimension_id)
        ).all()
        evidence = self._session.scalars(
            select(EvaluationEvidenceRecord)
            .where(EvaluationEvidenceRecord.evaluation_id == record.id)
            .order_by(
                EvaluationEvidenceRecord.dimension_id,
                EvaluationEvidenceRecord.id,
            )
        ).all()
        by_dimension: dict[str, list[dict]] = defaultdict(list)
        for item in evidence:
            by_dimension[item.dimension_id].append(
                {
                    "evidence_ref": item.evidence_ref,
                    **item.span,
                }
            )
        return {
            "evaluation_id": str(record.id),
            "take_id": record.take_id,
            "stage": record.stage,
            "subject_type": record.subject_type,
            "rubric_id": record.rubric_id,
            "rubric_version": record.rubric_version,
            "rubric_payload_sha256": record.rubric_payload_sha256,
            "evaluator_model": record.evaluator_model,
            "model_version": record.model_version,
            "prompt_version": record.prompt_version,
            "raw_response_ref": record.raw_response_ref,
            "actor_id": record.actor_id,
            "supersedes_id": (
                None if record.supersedes_id is None else str(record.supersedes_id)
            ),
            "profile_id": record.profile_id,
            "lineage_group": record.lineage_group,
            "project_id": record.project_id,
            "scene_id": record.scene_id,
            "knowledge_pack_version": record.knowledge_pack_version,
            "created_at": record.created_at.isoformat(),
            "scores": [
                {
                    "dimension_id": score.dimension_id,
                    "score": score.score,
                    "confidence": score.confidence,
                    "reason": score.reason,
                    "na_reason": score.na_reason,
                    "evidence_spans": by_dimension[score.dimension_id],
                    "original_value": score.original_value,
                    "original_scale": score.original_scale,
                    "migration_version": score.migration_version,
                }
                for score in scores
            ],
        }

    def get(self, evaluation_id: UUID) -> dict | None:
        record = self._session.get(EvaluationRecord, evaluation_id)
        return None if record is None else self._record_payload(record)

    def list_for_take(self, take_id: str) -> tuple[dict, ...]:
        records = self._session.scalars(
            select(EvaluationRecord)
            .where(EvaluationRecord.take_id == take_id)
            .order_by(EvaluationRecord.created_at, EvaluationRecord.id)
        ).all()
        return tuple(self._record_payload(record) for record in records)

    def store(
        self,
        *,
        take_id: str,
        stage: EvaluationStage,
        submission: EvaluationSubmission,
        actor_id: str,
        idempotency_key: str,
    ) -> tuple[dict, bool]:
        if not idempotency_key or len(idempotency_key) > 255:
            raise EvaluationError("evaluation idempotency key is invalid")
        self._validate_submission(stage=stage, submission=submission)
        rubric = ensure_rubric_v1(self._session)
        submission_payload = {
            "take_id": take_id,
            "stage": stage.value,
            "actor_id": actor_id,
            **submission.model_dump(mode="json"),
        }
        submission_sha = _canonical_sha(submission_payload)
        existing = self._session.scalar(
            select(EvaluationRecord).where(
                EvaluationRecord.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            if existing.submission_sha256 != submission_sha:
                raise EvaluationConflict(
                    "evaluation idempotency key conflicts with stored content"
                )
            return self._record_payload(existing), False

        if submission.supersedes_id is not None:
            superseded = self._session.get(
                EvaluationRecord,
                submission.supersedes_id,
            )
            if superseded is None:
                raise EvaluationError("superseded evaluation is unavailable")
            if (
                superseded.take_id != take_id
                or superseded.stage != stage.value
                or superseded.profile_id != submission.profile_id
            ):
                raise EvaluationError(
                    "superseded evaluation must have the same take, stage, "
                    "and profile"
                )
            already_superseded = self._session.scalar(
                select(EvaluationRecord).where(
                    EvaluationRecord.supersedes_id == superseded.id
                )
            )
            if already_superseded is not None:
                raise EvaluationConflict(
                    "evaluation already has a superseding revision"
                )

        record = EvaluationRecord(
            id=uuid4(),
            take_id=take_id,
            stage=stage.value,
            subject_type=submission.subject_type.value,
            rubric_id=AI_SHORT_DRAMA_RUBRIC_ID,
            rubric_version=AI_SHORT_DRAMA_RUBRIC_VERSION,
            rubric_payload_sha256=rubric.payload_sha256,
            submission_sha256=submission_sha,
            evaluator_model=submission.evaluator_model,
            model_version=submission.model_version,
            prompt_version=submission.prompt_version,
            raw_response_ref=submission.raw_response_ref,
            actor_id=actor_id,
            supersedes_id=submission.supersedes_id,
            idempotency_key=idempotency_key,
            profile_id=submission.profile_id,
            lineage_group=submission.lineage_group,
            project_id=submission.project_id,
            scene_id=submission.scene_id,
            knowledge_pack_version=submission.knowledge_pack_version,
        )
        self._session.add(record)
        self._session.flush()
        for score in submission.scores:
            self._session.add(
                EvaluationScoreRecord(
                    evaluation_id=record.id,
                    dimension_id=score.dimension_id,
                    score=score.score,
                    confidence=score.confidence,
                    reason=score.reason,
                    na_reason=score.na_reason,
                    original_value=score.original_value,
                    original_scale=score.original_scale,
                    migration_version=score.migration_version,
                )
            )
            for span in score.evidence_spans:
                span_payload = span.model_dump(
                    mode="json",
                    exclude={"evidence_ref"},
                    exclude_none=True,
                )
                self._session.add(
                    EvaluationEvidenceRecord(
                        evaluation_id=record.id,
                        dimension_id=score.dimension_id,
                        evidence_ref=span.evidence_ref,
                        span=span_payload,
                    )
                )
        self._session.flush()
        if stage is EvaluationStage.HUB_HUMAN:
            self._store_preference_event(
                record=record,
                submission=submission,
                idempotency_key=f"{idempotency_key}:preference",
            )
        self._session.flush()
        return self._record_payload(record), True

    def _score_map(self, evaluation_id: UUID) -> dict[str, int]:
        return {
            record.dimension_id: record.score
            for record in self._session.scalars(
                select(EvaluationScoreRecord).where(
                    EvaluationScoreRecord.evaluation_id == evaluation_id,
                    EvaluationScoreRecord.score.is_not(None),
                )
            )
            if record.score is not None
        }

    def _store_preference_event(
        self,
        *,
        record: EvaluationRecord,
        submission: EvaluationSubmission,
        idempotency_key: str,
    ) -> None:
        ai_record = self._session.scalar(
            select(EvaluationRecord)
            .where(
                EvaluationRecord.take_id == record.take_id,
                EvaluationRecord.stage == EvaluationStage.HUB_AI.value,
                EvaluationRecord.profile_id == record.profile_id,
            )
            .order_by(EvaluationRecord.created_at.desc(), EvaluationRecord.id.desc())
        )
        human_scores = self._score_map(record.id)
        ai_scores = {} if ai_record is None else self._score_map(ai_record.id)
        deltas = {
            dimension_id: float(human_score - ai_scores[dimension_id])
            for dimension_id, human_score in human_scores.items()
            if dimension_id in ai_scores
        }
        signal = submission.preference or PreferenceSignalInput()
        context = {
            **signal.context,
            "evidence_mode": submission.evidence_mode,
            "project_id": submission.project_id,
            "scene_id": submission.scene_id,
            "knowledge_pack_version": submission.knowledge_pack_version,
            "human_evaluation_id": str(record.id),
            "ai_evaluation_id": (
                None if ai_record is None else str(ai_record.id)
            ),
        }
        self._session.add(
            PreferenceEventRecord(
                id=uuid4(),
                idempotency_key=idempotency_key,
                profile_id=record.profile_id,
                take_id=record.take_id,
                lineage_group=record.lineage_group,
                human_evaluation_id=record.id,
                ai_evaluation_id=None if ai_record is None else ai_record.id,
                action=None if signal.action is None else signal.action.value,
                preferred_take_ids=list(signal.preferred_take_ids),
                feedback=signal.feedback,
                score_deltas=deltas,
                context=context,
            )
        )
        self._session.flush()
        self._refresh_profile(record.profile_id)

    def _paired_rows(self, profile_id: str) -> tuple[list, list[dict]]:
        events = self._session.scalars(
            select(PreferenceEventRecord)
            .where(PreferenceEventRecord.profile_id == profile_id)
            .order_by(PreferenceEventRecord.created_at, PreferenceEventRecord.id)
        ).all()
        paired = [event for event in events if event.ai_evaluation_id is not None]
        rows: list[dict] = []
        for event in paired:
            human = self._score_map(event.human_evaluation_id)
            ai = self._score_map(event.ai_evaluation_id)
            for dimension_id in sorted(set(human) & set(ai)):
                rows.append(
                    {
                        "lineage": event.lineage_group,
                        "dimension": dimension_id,
                        "ai": float(ai[dimension_id]),
                        "human": float(human[dimension_id]),
                        "delta": float(human[dimension_id] - ai[dimension_id]),
                        "core": dimension_id in CORE_DIMENSION_IDS,
                    }
                )
        return paired, rows

    def _build_shadow_report(self, profile_id: str) -> dict:
        paired, rows = self._paired_rows(profile_id)
        lineages = sorted({event.lineage_group for event in paired})
        base = {
            "profile_id": profile_id,
            "paired_samples": len(paired),
            "lineage_groups": len(lineages),
            "fit_threshold": 20,
            "validation_threshold": 50,
            "minimum_validation_lineages": 10,
            "active_config_id": None,
            "activation_enabled": False,
            "activation_candidate_id": None,
            "status": "collecting",
            "metrics": None,
        }
        if len(paired) < 20:
            base["next_gate_remaining"] = 20 - len(paired)
            return base
        base["status"] = (
            "validation_ready"
            if len(paired) >= 50 and len(lineages) >= 10
            else "fit_ready"
        )
        base["next_gate_remaining"] = max(0, 50 - len(paired))
        if len(lineages) < 2 or not rows:
            base["status"] = "fit_ready"
            base["metrics"] = {
                "reason": "at least two lineage groups are required for grouped split"
            }
            return base

        ordered_lineages = sorted(
            lineages,
            key=lambda item: hashlib.sha256(item.encode("utf-8")).hexdigest(),
        )
        validation_count = max(1, math.ceil(len(ordered_lineages) * 0.2))
        validation = set(ordered_lineages[-validation_count:])
        training = set(ordered_lineages) - validation
        training_rows = [row for row in rows if row["lineage"] in training]
        validation_rows = [row for row in rows if row["lineage"] in validation]
        corrections: dict[str, float] = {}
        for dimension_id in HUB_DIMENSION_IDS_LOCAL:
            deltas = [
                row["delta"]
                for row in training_rows
                if row["dimension"] == dimension_id
            ]
            if deltas:
                corrections[dimension_id] = sum(deltas) / len(deltas)
        usable = [
            row
            for row in validation_rows
            if row["dimension"] in corrections
        ]
        if not usable:
            base["metrics"] = {
                "reason": "grouped validation has no dimensions learned in training"
            }
            return base
        baseline_mae = sum(abs(row["delta"]) for row in usable) / len(usable)
        personalized_mae = sum(
            abs(row["delta"] - corrections[row["dimension"]])
            for row in usable
        ) / len(usable)
        improvement = baseline_mae - personalized_mae

        per_core_regression: dict[str, float] = {}
        for dimension_id in CORE_DIMENSION_IDS:
            dimension_rows = [
                row for row in usable if row["dimension"] == dimension_id
            ]
            if not dimension_rows:
                continue
            baseline = sum(abs(row["delta"]) for row in dimension_rows) / len(
                dimension_rows
            )
            personalized = sum(
                abs(row["delta"] - corrections[dimension_id])
                for row in dimension_rows
            ) / len(dimension_rows)
            per_core_regression[dimension_id] = personalized - baseline
        max_core_regression = max(per_core_regression.values(), default=0.0)

        input_sha = _canonical_sha(
            [
                {
                    "human": str(event.human_evaluation_id),
                    "ai": str(event.ai_evaluation_id),
                    "lineage": event.lineage_group,
                    "deltas": event.score_deltas,
                }
                for event in paired
            ]
        )
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in usable:
            grouped[row["lineage"]].append(row)
        validation_groups = sorted(grouped)
        rng = random.Random(int(input_sha[:16], 16))
        bootstrap_improvements = []
        for _ in range(400):
            sampled = [
                row
                for _group in range(len(validation_groups))
                for row in grouped[rng.choice(validation_groups)]
            ]
            sample_baseline = sum(abs(row["delta"]) for row in sampled) / len(
                sampled
            )
            sample_personalized = sum(
                abs(row["delta"] - corrections[row["dimension"]])
                for row in sampled
            ) / len(sampled)
            bootstrap_improvements.append(
                sample_baseline - sample_personalized
            )
        ci = [
            _percentile(bootstrap_improvements, 0.025),
            _percentile(bootstrap_improvements, 0.975),
        ]
        human_values = [row["human"] for row in usable]
        corrected_values = [
            max(
                1.0,
                min(
                    10.0,
                    row["ai"] + corrections[row["dimension"]],
                ),
            )
            for row in usable
        ]
        spearman = _correlation(
            _rank(corrected_values),
            _rank(human_values),
        )
        eligible = (
            len(paired) >= 50
            and len(lineages) >= 10
            and improvement >= 0.3
            and ci[0] > 0
            and max_core_regression <= 0.5
        )
        metrics = {
            "input_sha256": input_sha,
            "training_lineages": sorted(training),
            "validation_lineages": sorted(validation),
            "baseline_macro_mae": round(baseline_mae, 6),
            "personalized_macro_mae": round(personalized_mae, 6),
            "mae_improvement": round(improvement, 6),
            "bootstrap_95_improvement": [round(value, 6) for value in ci],
            "max_core_dimension_regression": round(max_core_regression, 6),
            "spearman": None if spearman is None else round(spearman, 6),
            "preference_choice_accuracy": None,
            "preference_choice_accuracy_reason": (
                "no pairwise take choices in the current validation set"
            ),
            "corrections": {
                key: round(value, 6) for key, value in corrections.items()
            },
            "candidate_gate_passed": eligible,
        }
        base["metrics"] = metrics
        base["_calibration"] = {
            "input_sha256": input_sha,
            "training_lineages": sorted(training),
            "validation_lineages": sorted(validation),
            "eligible": eligible,
        }
        return base

    def _refresh_profile(self, profile_id: str) -> None:
        report = self._build_shadow_report(profile_id)
        calibration = report.pop("_calibration", None)
        profile = self._session.get(PreferenceProfileRecord, profile_id)
        status_value = (
            "collecting"
            if report["paired_samples"] < 20
            else (
                "validation_ready"
                if report["paired_samples"] >= 50
                and report["lineage_groups"] >= 10
                else "fit_ready"
            )
        )
        if profile is None:
            profile = PreferenceProfileRecord(
                profile_id=profile_id,
                status=status_value,
                paired_samples=report["paired_samples"],
                lineage_groups=report["lineage_groups"],
                last_report=dict(report),
            )
            self._session.add(profile)
        else:
            profile.status = status_value
            profile.paired_samples = report["paired_samples"]
            profile.lineage_groups = report["lineage_groups"]
            profile.last_report = dict(report)
        if calibration is None:
            return
        existing = self._session.scalar(
            select(CalibrationRunRecord).where(
                CalibrationRunRecord.input_sha256
                == calibration["input_sha256"]
            )
        )
        if existing is None:
            existing = CalibrationRunRecord(
                id=uuid4(),
                profile_id=profile_id,
                input_sha256=calibration["input_sha256"],
                status=(
                    "candidate"
                    if calibration["eligible"]
                    else "shadow"
                ),
                training_lineages=calibration["training_lineages"],
                validation_lineages=calibration["validation_lineages"],
                metrics=report["metrics"],
            )
            self._session.add(existing)
            self._session.flush()
        if calibration["eligible"]:
            candidate = self._session.scalar(
                select(ActivationCandidateRecord).where(
                    ActivationCandidateRecord.calibration_run_id == existing.id
                )
            )
            if candidate is None:
                candidate = ActivationCandidateRecord(
                    id=uuid4(),
                    calibration_run_id=existing.id,
                    profile_id=profile_id,
                    status="awaiting_r4",
                    metrics=report["metrics"],
                )
                self._session.add(candidate)
                self._session.flush()
            report["activation_candidate_id"] = str(candidate.id)
            profile.last_report = dict(report)

    def shadow_report(
        self,
        profile_id: str = AI_SHORT_DRAMA_PROFILE_ID,
    ) -> dict:
        profile = self._session.get(PreferenceProfileRecord, profile_id)
        if profile is None:
            return self._build_shadow_report(profile_id)
        return dict(profile.last_report)


HUB_DIMENSION_IDS_LOCAL = STAGE_DIMENSIONS[EvaluationStage.HUB_HUMAN]
