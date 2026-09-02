from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from itertools import combinations
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import AwareDatetime, Field, model_validator

from colorgraph.agent.creative_contracts import (
    CompiledCandidate,
    CritiqueDimension,
    IntentionalException,
    IntentionalExceptionKind,
    NonEmptyString,
    NormalizedScore,
    Sha256,
    StrictFrozenModel,
    VisualCritique,
    canonical_sha256,
)
from colorgraph.agent.creative_critic import PairwiseVisualCriticReport
from colorgraph.agent.creative_search import (
    CandidateAttemptStatus,
    SearchCandidateRecord,
)
from colorgraph.domain.grade_graph import GradeGraph
from colorgraph.grading.looks import graph_digest

CREATIVE_RANKING_VERSION = "colorgraph.creative-candidate-ranking/v1"

_OBJECTIVE_ORDER = (
    CritiqueDimension.CONCEPT_ALIGNMENT,
    CritiqueDimension.SCENE_SUPPORT,
    CritiqueDimension.VISUAL_HIERARCHY,
    CritiqueDimension.EXPRESSIVE_STRENGTH,
    CritiqueDimension.NATURALNESS,
    CritiqueDimension.DISTINCTIVENESS,
    CritiqueDimension.OVERGRADING_RISK,
    CritiqueDimension.CONTEXT_CONSISTENCY,
)


class RankingGate(StrEnum):
    TECHNICAL_DELIVERY = "technical_delivery"
    INTENT_AND_PROTECTION = "intent_and_protection"
    TEMPORAL_CONSISTENCY = "temporal_consistency"
    HUMAN_PREFERENCE = "human_preference"


class CandidateGateRejection(StrictFrozenModel):
    candidate_id: NonEmptyString
    reasons: list[NonEmptyString] = Field(min_length=1)
    evidence_ids: list[NonEmptyString] = Field(min_length=1)


class RankingGateTrace(StrictFrozenModel):
    gate: RankingGate
    input_candidate_ids: list[NonEmptyString]
    passing_candidate_ids: list[NonEmptyString]
    rejections: list[CandidateGateRejection]
    skipped: bool = False
    detail: NonEmptyString

    @model_validator(mode="after")
    def partition_inputs(self) -> RankingGateTrace:
        inputs = self.input_candidate_ids
        passing = self.passing_candidate_ids
        rejected = [item.candidate_id for item in self.rejections]
        if len(inputs) != len(set(inputs)):
            raise ValueError("ranking gate inputs must be unique")
        if len(passing) != len(set(passing)):
            raise ValueError("ranking gate passing IDs must be unique")
        if len(rejected) != len(set(rejected)):
            raise ValueError("ranking gate rejection IDs must be unique")
        if self.skipped:
            if passing != inputs or self.rejections:
                raise ValueError("a skipped gate must preserve every input")
        elif set(passing) | set(rejected) != set(inputs):
            raise ValueError("ranking gate must account for every input candidate")
        if set(passing) & set(rejected):
            raise ValueError("ranking gate cannot both pass and reject a candidate")
        return self


class TemporalConsistencyEvidence(StrictFrozenModel):
    schema_version: Literal["colorgraph.temporal-ranking-evidence/v1"] = (
        "colorgraph.temporal-ranking-evidence/v1"
    )
    candidate_id: NonEmptyString
    scene_id: NonEmptyString
    rendered_sha256: Sha256
    evaluated_frame_indices: list[int] = Field(min_length=2)
    within_shot_passed: bool
    between_shot_applicable: bool
    between_shot_passed: bool
    mask_continuity_passed: bool
    evidence_ids: list[NonEmptyString] = Field(min_length=1)
    failure_reasons: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_temporal_result(self) -> TemporalConsistencyEvidence:
        if len(self.evaluated_frame_indices) != len(
            set(self.evaluated_frame_indices)
        ):
            raise ValueError("temporal evidence frame indices must be unique")
        if not self.between_shot_applicable and not self.between_shot_passed:
            raise ValueError("a non-applicable between-shot check must pass neutrally")
        passed = (
            self.within_shot_passed
            and self.between_shot_passed
            and self.mask_continuity_passed
        )
        if passed == bool(self.failure_reasons):
            raise ValueError(
                "temporal failure reasons must exist exactly when a check fails"
            )
        return self


class HumanPreferenceEvidence(StrictFrozenModel):
    schema_version: Literal["colorgraph.project-human-preference/v1"] = (
        "colorgraph.project-human-preference/v1"
    )
    project_id: NonEmptyString
    user_scope_id: NonEmptyString
    ordered_candidate_ids: list[NonEmptyString] = Field(min_length=1)
    evidence_digest: Sha256
    recorded_at: AwareDatetime
    statement: NonEmptyString

    @model_validator(mode="after")
    def unique_candidates(self) -> HumanPreferenceEvidence:
        if len(self.ordered_candidate_ids) != len(
            set(self.ordered_candidate_ids)
        ):
            raise ValueError("human preference candidate IDs must be unique")
        return self


class CreativeRankingPolicy(StrictFrozenModel):
    schema_version: Literal["colorgraph.creative-ranking-policy/v1"] = (
        "colorgraph.creative-ranking-policy/v1"
    )
    minimum_concept_alignment: NormalizedScore = 0.35
    minimum_scene_support: NormalizedScore = 0.35
    minimum_visual_hierarchy: NormalizedScore = 0.3
    minimum_naturalness: NormalizedScore = 0.25
    maximum_overgrading_risk: NormalizedScore = 0.75
    minimum_context_consistency: NormalizedScore = 0.35
    minimum_temporal_frames: int = Field(default=2, ge=2, le=7)
    maximum_exception_naturalness_relaxation: NormalizedScore = 0.1
    maximum_exception_overgrading_relaxation: NormalizedScore = 0.1
    require_complete_blind_pairwise: bool = True


class CreativeCandidateRankingReport(StrictFrozenModel):
    schema_version: Literal["colorgraph.creative-candidate-ranking-report/v1"] = (
        "colorgraph.creative-candidate-ranking-report/v1"
    )
    ranking_version: Literal["colorgraph.creative-candidate-ranking/v1"] = (
        CREATIVE_RANKING_VERSION
    )
    input_digest: Sha256
    policy_digest: Sha256
    evaluated_at: AwareDatetime
    candidate_ids: list[NonEmptyString] = Field(min_length=1)
    gate_traces: list[RankingGateTrace] = Field(min_length=4, max_length=4)
    objective_values: dict[
        NonEmptyString,
        dict[CritiqueDimension, NormalizedScore],
    ]
    pareto_fronts: list[list[NonEmptyString]]
    pareto_candidate_ids: list[NonEmptyString]
    retained_candidate_ids: list[NonEmptyString]
    pairwise_comparison_digests: list[Sha256]
    missing_pairwise_pairs: list[list[NonEmptyString]]
    blind_pairwise_complete: bool
    applied_exception_ids: dict[NonEmptyString, list[NonEmptyString]]
    human_preference_applied: bool
    selected_candidate_id: NonEmptyString | None = None
    runner_up_candidate_id: NonEmptyString | None = None
    ranking_order: list[NonEmptyString] = Field(min_length=1)
    selection_status: NonEmptyString
    automatic_selection_allowed: bool
    selection_digest: Sha256

    @model_validator(mode="after")
    def validate_report(self) -> CreativeCandidateRankingReport:
        if len(self.candidate_ids) != len(set(self.candidate_ids)):
            raise ValueError("ranking report candidate IDs must be unique")
        if set(self.ranking_order) != set(self.candidate_ids) or len(
            self.ranking_order
        ) != len(self.candidate_ids):
            raise ValueError("ranking order must contain every candidate exactly once")
        if [item.gate for item in self.gate_traces] != list(RankingGate):
            raise ValueError("ranking report must preserve the four gate order")
        if self.pareto_candidate_ids != (
            self.pareto_fronts[0] if self.pareto_fronts else []
        ):
            raise ValueError("Pareto candidate IDs must equal the first front")
        if not set(self.retained_candidate_ids) <= set(self.candidate_ids):
            raise ValueError("retained candidates must belong to the ranking input")
        if (self.selected_candidate_id is None) != (
            self.runner_up_candidate_id is None
        ):
            raise ValueError("selected candidate and runner-up must be set together")
        if self.selected_candidate_id is not None:
            if self.selected_candidate_id == self.runner_up_candidate_id:
                raise ValueError("selected candidate and runner-up must differ")
            if {
                self.selected_candidate_id,
                self.runner_up_candidate_id,
            } - set(self.retained_candidate_ids):
                raise ValueError("selection must stay inside the retained comparison set")
        if self.automatic_selection_allowed and self.selected_candidate_id is None:
            raise ValueError("automatic selection requires a selected candidate")
        if self.blind_pairwise_complete != (not self.missing_pairwise_pairs):
            raise ValueError("pairwise completeness differs from missing-pair evidence")
        return self


def _qc_digest(record: SearchCandidateRecord) -> str | None:
    return canonical_sha256(record.qc) if record.qc is not None else None


def _rendered_digest(record: SearchCandidateRecord) -> str:
    return canonical_sha256(
        {
            "candidate_frames": [
                {
                    "frame_index": item.frame_index,
                    "time_seconds": item.time_seconds,
                    "sha256": item.candidate_sha256,
                }
                for item in record.samples
            ]
        }
    )


def _compiled_contract(record: SearchCandidateRecord) -> CompiledCandidate | None:
    path = Path(record.contract_path)
    if not path.is_file():
        return None
    try:
        contract = CompiledCandidate.model_validate_json(
            path.read_text(encoding="utf-8"),
            strict=True,
        )
    except (OSError, ValueError):
        return None
    if (
        contract.candidate_id != record.candidate_id
        or contract.compiled_graph_digest != record.compiled_graph_digest
    ):
        return None
    return contract


def _compiled_assets(
    record: SearchCandidateRecord,
) -> tuple[CompiledCandidate, GradeGraph, GradeGraph] | None:
    contract = _compiled_contract(record)
    if contract is None:
        return None
    try:
        graph = GradeGraph.model_validate_json(
            Path(record.graph_path).read_text(encoding="utf-8"),
        )
        undo = GradeGraph.model_validate_json(
            Path(record.undo_graph_path).read_text(encoding="utf-8"),
        )
    except (OSError, ValueError):
        return None
    if (
        graph_digest(graph) != contract.compiled_graph_digest
        or graph_digest(undo) != contract.undo_graph_digest
        or graph.project_id != undo.project_id
    ):
        return None
    return contract, graph, undo


def _sha256_file(path: str) -> str | None:
    resolved = Path(path)
    if not resolved.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with resolved.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def _critique_scores(
    critique: VisualCritique,
) -> dict[CritiqueDimension, float]:
    return {item.dimension: float(item.score) for item in critique.scores}


def _objective_values(
    critique: VisualCritique,
) -> dict[CritiqueDimension, float]:
    scores = _critique_scores(critique)
    return {
        dimension: (
            1.0 - scores[dimension]
            if dimension == CritiqueDimension.OVERGRADING_RISK
            else scores[dimension]
        )
        for dimension in _OBJECTIVE_ORDER
    }


def _dominates(
    left: Mapping[CritiqueDimension, float],
    right: Mapping[CritiqueDimension, float],
) -> bool:
    if set(left) != set(right):
        raise ValueError("creative Pareto candidates must expose identical dimensions")
    return all(left[key] >= right[key] - 1e-12 for key in left) and any(
        left[key] > right[key] + 1e-12 for key in left
    )


def creative_pareto_fronts(
    objectives: Mapping[str, Mapping[CritiqueDimension, float]],
) -> list[list[str]]:
    if not objectives:
        return []
    if any(
        set(values) != set(_OBJECTIVE_ORDER)
        for values in objectives.values()
    ):
        raise ValueError("creative Pareto objectives must cover all Critic dimensions")
    if any(
        not np.isfinite(float(value))
        for values in objectives.values()
        for value in values.values()
    ):
        raise ValueError("creative Pareto objectives must be finite")
    remaining = set(objectives)
    fronts: list[list[str]] = []
    while remaining:
        front = sorted(
            candidate_id
            for candidate_id in remaining
            if not any(
                _dominates(objectives[other], objectives[candidate_id])
                for other in remaining
                if other != candidate_id
            )
        )
        if not front:  # pragma: no cover - finite partial order invariant
            raise RuntimeError("creative Pareto construction made no progress")
        fronts.append(front)
        remaining.difference_update(front)
    return fronts


def _quality_key(
    candidate_id: str,
    objectives: Mapping[str, Mapping[CritiqueDimension, float]],
) -> tuple[float | str, ...]:
    values = objectives[candidate_id]
    return (
        -min(values.values()),
        *(-values[dimension] for dimension in _OBJECTIVE_ORDER),
        candidate_id,
    )


def _valid_exception_relaxations(
    record: SearchCandidateRecord,
    exceptions: Sequence[IntentionalException],
    *,
    evaluated_at: datetime,
    policy: CreativeRankingPolicy,
) -> tuple[float, float, list[str]]:
    contract = _compiled_contract(record)
    if contract is None:
        return 0.0, 0.0, []
    naturalness = 0.0
    overgrading = 0.0
    applied: list[str] = []
    for exception in exceptions:
        if (
            exception.candidate_digest != record.compiled_graph_digest
            or exception.source_graph_digest != contract.source_graph_digest
            or exception.scope.scene_id not in {None, record.scene_id}
            or exception.declared_at > evaluated_at
            or (
                exception.expires_at is not None
                and exception.expires_at <= evaluated_at
            )
        ):
            continue
        if exception.kind == IntentionalExceptionKind.SELECTIVE_SATURATION_PUSH:
            naturalness = max(
                naturalness,
                min(
                    policy.maximum_exception_naturalness_relaxation,
                    exception.maximum_metric_value,
                ),
            )
        overgrading = max(
            overgrading,
            min(
                policy.maximum_exception_overgrading_relaxation,
                exception.maximum_metric_value,
            ),
        )
        applied.append(exception.exception_id)
    return naturalness, overgrading, sorted(applied)


def _technical_gate(
    records: Sequence[SearchCandidateRecord],
) -> tuple[list[str], list[CandidateGateRejection]]:
    passing: list[str] = []
    rejections: list[CandidateGateRejection] = []
    for record in records:
        reasons: list[str] = []
        evidence: list[str] = []
        if record.status == CandidateAttemptStatus.RENDER_FAILED:
            reasons.append(f"render_failed:{record.failure_detail}")
            evidence.append(f"render:{record.cache_key}")
        elif (
            record.status != CandidateAttemptStatus.HARD_PASS
            or record.qc is None
            or not record.qc.hard_passed
        ):
            if record.qc is not None:
                failed = [item for item in record.qc.checks if not item.passed]
                reasons.extend(
                    f"hard_gate:{item.check_id}:frames="
                    + ",".join(str(value) for value in item.frame_indices)
                    for item in failed
                )
                evidence.extend(
                    f"qc:{record.candidate_id}:{item.check_id}"
                    for item in failed
                )
            if not reasons:
                reasons.append("hard_gate:status_not_passed")
                evidence.append(f"qc:{record.candidate_id}")
        elif _compiled_assets(record) is None:
            reasons.append("compiled_contract_missing_stale_or_corrupt")
            evidence.append(f"contract:{record.cache_key}")
        else:
            invalid_rendered_assets = [
                f"{sample.frame_index}:{role}"
                for sample in record.samples
                for role, path, expected in (
                    ("source", sample.source_path, sample.source_sha256),
                    ("current", sample.current_path, sample.current_sha256),
                    (
                        "candidate",
                        sample.candidate_path,
                        sample.candidate_sha256,
                    ),
                )
                if _sha256_file(path) != expected
            ]
            if invalid_rendered_assets:
                reasons.append(
                    "rendered_asset_missing_or_digest_mismatch:"
                    + ",".join(invalid_rendered_assets)
                )
                evidence.extend(
                    f"render:{record.cache_key}:{item}"
                    for item in invalid_rendered_assets
                )
        if reasons:
            rejections.append(
                CandidateGateRejection(
                    candidate_id=record.candidate_id,
                    reasons=reasons,
                    evidence_ids=evidence,
                )
            )
        else:
            passing.append(record.candidate_id)
    return passing, rejections


def _intent_gate(
    records: Mapping[str, SearchCandidateRecord],
    candidate_ids: Sequence[str],
    critiques: Mapping[str, VisualCritique],
    exceptions: Mapping[str, Sequence[IntentionalException]],
    *,
    evaluated_at: datetime,
    policy: CreativeRankingPolicy,
) -> tuple[list[str], list[CandidateGateRejection], dict[str, list[str]]]:
    passing: list[str] = []
    rejections: list[CandidateGateRejection] = []
    applied_exceptions: dict[str, list[str]] = {}
    for candidate_id in candidate_ids:
        record = records[candidate_id]
        critique = critiques.get(candidate_id)
        reasons: list[str] = []
        evidence: list[str] = []
        if critique is None:
            reasons.append("visual_critique_missing")
            evidence.append(f"critic:{candidate_id}:missing")
        else:
            expected_qc = _qc_digest(record)
            expected_render = _rendered_digest(record)
            if critique.technical_integrity_sha256 != expected_qc:
                reasons.append("visual_critique_qc_digest_mismatch")
            if critique.rendered_sha256 != expected_render:
                reasons.append("visual_critique_render_digest_mismatch")
            if not critique.position_swap_consistent:
                reasons.append("visual_critique_position_swap_inconsistent")
            if any(
                not item.frame_regions or not item.counter_frame_regions
                for item in critique.scores
            ):
                reasons.append("visual_critique_missing_region_or_counterevidence")
            naturalness_relaxation, risk_relaxation, applied = (
                _valid_exception_relaxations(
                    record,
                    exceptions.get(candidate_id, ()),
                    evaluated_at=evaluated_at,
                    policy=policy,
                )
            )
            applied_exceptions[candidate_id] = applied
            scores = _critique_scores(critique)
            thresholds = (
                (
                    CritiqueDimension.CONCEPT_ALIGNMENT,
                    scores[CritiqueDimension.CONCEPT_ALIGNMENT],
                    policy.minimum_concept_alignment,
                    "minimum",
                ),
                (
                    CritiqueDimension.SCENE_SUPPORT,
                    scores[CritiqueDimension.SCENE_SUPPORT],
                    policy.minimum_scene_support,
                    "minimum",
                ),
                (
                    CritiqueDimension.VISUAL_HIERARCHY,
                    scores[CritiqueDimension.VISUAL_HIERARCHY],
                    policy.minimum_visual_hierarchy,
                    "minimum",
                ),
                (
                    CritiqueDimension.NATURALNESS,
                    scores[CritiqueDimension.NATURALNESS],
                    max(
                        0.0,
                        policy.minimum_naturalness - naturalness_relaxation,
                    ),
                    "minimum",
                ),
                (
                    CritiqueDimension.OVERGRADING_RISK,
                    scores[CritiqueDimension.OVERGRADING_RISK],
                    min(
                        1.0,
                        policy.maximum_overgrading_risk + risk_relaxation,
                    ),
                    "maximum",
                ),
            )
            for dimension, observed, threshold, comparison in thresholds:
                failed = (
                    observed < threshold
                    if comparison == "minimum"
                    else observed > threshold
                )
                if failed:
                    reasons.append(
                        f"critic_gate:{dimension.value}:{comparison}:"
                        f"observed={observed:.6f}:threshold={threshold:.6f}"
                    )
            evidence.extend(
                sorted(
                    {
                        item.evidence_id
                        for score in critique.scores
                        for item in (
                            *score.frame_regions,
                            *score.counter_frame_regions,
                        )
                    }
                )
            )
            evidence.extend(f"exception:{item}" for item in applied)
        if reasons:
            rejections.append(
                CandidateGateRejection(
                    candidate_id=candidate_id,
                    reasons=reasons,
                    evidence_ids=evidence or [f"critic:{candidate_id}"],
                )
            )
        else:
            passing.append(candidate_id)
    return passing, rejections, applied_exceptions


def _temporal_gate(
    records: Mapping[str, SearchCandidateRecord],
    candidate_ids: Sequence[str],
    critiques: Mapping[str, VisualCritique],
    temporal: Mapping[str, TemporalConsistencyEvidence],
    *,
    policy: CreativeRankingPolicy,
) -> tuple[list[str], list[CandidateGateRejection]]:
    passing: list[str] = []
    rejections: list[CandidateGateRejection] = []
    for candidate_id in candidate_ids:
        record = records[candidate_id]
        critique = critiques[candidate_id]
        evidence = temporal.get(candidate_id)
        reasons: list[str] = []
        evidence_ids: list[str] = []
        if evidence is None:
            reasons.append("temporal_evidence_missing")
            evidence_ids.append(f"temporal:{candidate_id}:missing")
        else:
            known_frames = {item.frame_index for item in record.samples}
            if evidence.scene_id != record.scene_id:
                reasons.append("temporal_scene_mismatch")
            if evidence.rendered_sha256 != _rendered_digest(record):
                reasons.append("temporal_render_digest_mismatch")
            if (
                len(evidence.evaluated_frame_indices)
                < policy.minimum_temporal_frames
            ):
                reasons.append("temporal_frame_coverage_insufficient")
            if not set(evidence.evaluated_frame_indices) <= known_frames:
                reasons.append("temporal_evidence_references_unknown_frame")
            if not evidence.within_shot_passed:
                reasons.append("within_shot_temporal_failure")
            if evidence.between_shot_applicable and not evidence.between_shot_passed:
                reasons.append("between_shot_temporal_failure")
            if not evidence.mask_continuity_passed:
                reasons.append("mask_temporal_failure")
            scores = _critique_scores(critique)
            context_score = scores[CritiqueDimension.CONTEXT_CONSISTENCY]
            if context_score < policy.minimum_context_consistency:
                reasons.append(
                    "critic_gate:context_consistency:minimum:"
                    f"observed={context_score:.6f}:"
                    f"threshold={policy.minimum_context_consistency:.6f}"
                )
            evidence_ids.extend(evidence.evidence_ids)
        if reasons:
            rejections.append(
                CandidateGateRejection(
                    candidate_id=candidate_id,
                    reasons=reasons,
                    evidence_ids=evidence_ids,
                )
            )
        else:
            passing.append(candidate_id)
    return passing, rejections


def _report_pair(
    report: PairwiseVisualCriticReport,
) -> tuple[str, str] | None:
    candidate_ids = sorted({item.candidate_id for item in report.critiques})
    if len(candidate_ids) != 2:
        return None
    if (
        not report.position_swap_consistent
        or not all(item.valid for item in report.output_audits)
        or (
            report.preferred_candidate_id is not None
            and report.preferred_candidate_id not in candidate_ids
        )
    ):
        return None
    return candidate_ids[0], candidate_ids[1]


def _comparison_digest(report: PairwiseVisualCriticReport) -> str:
    return canonical_sha256(report)


def _candidate_order(
    retained: Sequence[str],
    objectives: Mapping[str, Mapping[CritiqueDimension, float]],
    reports_by_pair: Mapping[tuple[str, str], PairwiseVisualCriticReport],
    human_preference: HumanPreferenceEvidence | None,
) -> list[str]:
    wins = {candidate_id: 0 for candidate_id in retained}
    for report in reports_by_pair.values():
        if report.preferred_candidate_id in wins:
            wins[report.preferred_candidate_id] += 1
    human_rank = (
        {
            candidate_id: index
            for index, candidate_id in enumerate(
                human_preference.ordered_candidate_ids
            )
        }
        if human_preference is not None
        else {}
    )
    return sorted(
        retained,
        key=lambda candidate_id: (
            human_rank.get(candidate_id, len(retained)),
            -wins[candidate_id],
            *_quality_key(candidate_id, objectives),
        ),
    )


def rank_creative_candidates(
    *,
    records: Sequence[SearchCandidateRecord],
    critiques: Sequence[VisualCritique],
    temporal_evidence: Sequence[TemporalConsistencyEvidence],
    pairwise_reports: Sequence[PairwiseVisualCriticReport],
    evaluated_at: datetime,
    intentional_exceptions: Mapping[
        str,
        Sequence[IntentionalException],
    ]
    | None = None,
    human_preference: HumanPreferenceEvidence | None = None,
    policy: CreativeRankingPolicy | None = None,
) -> CreativeCandidateRankingReport:
    policy = policy or CreativeRankingPolicy()
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("creative ranking evaluation time must be timezone-aware")
    candidate_ids = [item.candidate_id for item in records]
    if not candidate_ids:
        raise ValueError("creative ranking requires at least one candidate")
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("creative ranking candidate IDs must be unique")
    records_by_id = {item.candidate_id: item for item in records}
    critiques_by_id = {item.candidate_id: item for item in critiques}
    temporal_by_id = {item.candidate_id: item for item in temporal_evidence}
    if len(critiques_by_id) != len(critiques):
        raise ValueError("creative ranking critiques must be unique per candidate")
    if len(temporal_by_id) != len(temporal_evidence):
        raise ValueError("temporal ranking evidence must be unique per candidate")
    if not set(critiques_by_id) <= set(candidate_ids):
        raise ValueError("creative ranking critique references an unknown candidate")
    if not set(temporal_by_id) <= set(candidate_ids):
        raise ValueError("temporal evidence references an unknown candidate")
    exceptions = intentional_exceptions or {}
    if not set(exceptions) <= set(candidate_ids):
        raise ValueError("intentional exception references an unknown candidate")

    technical_pass, technical_rejections = _technical_gate(records)
    technical_trace = RankingGateTrace(
        gate=RankingGate.TECHNICAL_DELIVERY,
        input_candidate_ids=candidate_ids,
        passing_candidate_ids=technical_pass,
        rejections=technical_rejections,
        detail=(
            "Compiler contract, rendered assets, and every deterministic "
            "non-waivable QC check are required before creative scoring."
        ),
    )

    intent_pass, intent_rejections, applied_exceptions = _intent_gate(
        records_by_id,
        technical_pass,
        critiques_by_id,
        exceptions,
        evaluated_at=evaluated_at,
        policy=policy,
    )
    intent_trace = RankingGateTrace(
        gate=RankingGate.INTENT_AND_PROTECTION,
        input_candidate_ids=technical_pass,
        passing_candidate_ids=intent_pass,
        rejections=intent_rejections,
        detail=(
            "Blind Critic evidence must support intent and default protections; "
            "bounded exceptions may relax only naturalness/overgrading defaults."
        ),
    )

    temporal_pass, temporal_rejections = _temporal_gate(
        records_by_id,
        intent_pass,
        critiques_by_id,
        temporal_by_id,
        policy=policy,
    )
    temporal_trace = RankingGateTrace(
        gate=RankingGate.TEMPORAL_CONSISTENCY,
        input_candidate_ids=intent_pass,
        passing_candidate_ids=temporal_pass,
        rejections=temporal_rejections,
        detail=(
            "Within-shot, applicable between-shot, mask, and Critic context "
            "consistency evidence must all pass."
        ),
    )

    objectives = {
        candidate_id: _objective_values(critiques_by_id[candidate_id])
        for candidate_id in temporal_pass
    }
    fronts = creative_pareto_fronts(objectives)
    pareto_ids = fronts[0] if fronts else []
    retained = list(pareto_ids)
    if len(retained) == 1 and len(fronts) > 1:
        retained.append(
            sorted(
                fronts[1],
                key=lambda candidate_id: _quality_key(
                    candidate_id,
                    objectives,
                ),
            )[0]
        )

    reports_by_pair: dict[tuple[str, str], PairwiseVisualCriticReport] = {}
    for report in pairwise_reports:
        pair = _report_pair(report)
        if pair is None or not set(pair) <= set(retained):
            continue
        if pair in reports_by_pair:
            if _comparison_digest(reports_by_pair[pair]) != _comparison_digest(
                report
            ):
                raise ValueError("conflicting blind pairwise reports for one pair")
            continue
        reports_by_pair[pair] = report
    required_pairs = {
        tuple(sorted(pair))
        for pair in combinations(retained, 2)
    }
    missing_pairs = sorted(required_pairs - set(reports_by_pair))
    comparison_complete = not missing_pairs

    if human_preference is not None:
        if not set(human_preference.ordered_candidate_ids) <= set(retained):
            raise ValueError(
                "human preference cannot resurrect a candidate rejected by an earlier gate"
            )
        retained_projects = {
            assets[2].project_id
            for candidate_id in retained
            if (assets := _compiled_assets(records_by_id[candidate_id]))
            is not None
        }
        if retained_projects != {human_preference.project_id}:
            raise ValueError(
                "human preference belongs to another project or stale candidate set"
            )
        human_trace = RankingGateTrace(
            gate=RankingGate.HUMAN_PREFERENCE,
            input_candidate_ids=retained,
            passing_candidate_ids=retained,
            rejections=[],
            detail=(
                "Project/user-scoped human order is applied only inside the "
                "retained comparison set."
            ),
        )
    else:
        human_trace = RankingGateTrace(
            gate=RankingGate.HUMAN_PREFERENCE,
            input_candidate_ids=retained,
            passing_candidate_ids=retained,
            rejections=[],
            skipped=True,
            detail="No human preference was supplied; this optional gate was skipped.",
        )

    selection_pool_order = _candidate_order(
        retained,
        objectives,
        reports_by_pair,
        human_preference,
    )
    can_select = len(selection_pool_order) >= 2 and (
        comparison_complete or not policy.require_complete_blind_pairwise
    )
    if can_select:
        selected_id = selection_pool_order[0]
        runner_up_id = selection_pool_order[1]
        calibrated = all(
            report.auto_selection_allowed
            for report in reports_by_pair.values()
        )
        automatic_allowed = (
            human_preference is None
            and comparison_complete
            and calibrated
        )
        if human_preference is not None:
            selection_status = "selected-human-preference"
        elif automatic_allowed:
            selection_status = "selected-calibrated-blind-critic"
        else:
            selection_status = "selected-shadow-requires-confirmation"
    else:
        selected_id = None
        runner_up_id = None
        automatic_allowed = False
        selection_status = (
            "awaiting-blind-pairwise"
            if len(selection_pool_order) >= 2
            else "insufficient-gate-survivors"
        )

    ordered_groups = [
        selection_pool_order,
        [
            candidate_id
            for front in fronts
            for candidate_id in sorted(
                front,
                key=lambda value: _quality_key(value, objectives),
            )
            if candidate_id not in selection_pool_order
        ],
        [item.candidate_id for item in temporal_rejections],
        [item.candidate_id for item in intent_rejections],
        [item.candidate_id for item in technical_rejections],
    ]
    ranking_order: list[str] = []
    for group in ordered_groups:
        for candidate_id in group:
            if candidate_id not in ranking_order:
                ranking_order.append(candidate_id)
    if set(ranking_order) != set(candidate_ids):
        raise RuntimeError("creative ranking did not account for every candidate")

    report_digests = sorted(
        _comparison_digest(report)
        for report in reports_by_pair.values()
    )
    input_digest = canonical_sha256(
        {
            "records": [item.model_dump(mode="json") for item in records],
            "critiques": [item.model_dump(mode="json") for item in critiques],
            "temporal_evidence": [
                item.model_dump(mode="json") for item in temporal_evidence
            ],
            "pairwise_report_digests": report_digests,
            "intentional_exceptions": {
                key: [item.model_dump(mode="json") for item in value]
                for key, value in sorted(exceptions.items())
            },
            "human_preference": (
                human_preference.model_dump(mode="json")
                if human_preference is not None
                else None
            ),
            "evaluated_at": evaluated_at.isoformat(),
        }
    )
    gate_traces = [
        technical_trace,
        intent_trace,
        temporal_trace,
        human_trace,
    ]
    selection_digest = canonical_sha256(
        {
            "ranking_version": CREATIVE_RANKING_VERSION,
            "input_digest": input_digest,
            "policy_digest": canonical_sha256(policy),
            "gate_traces": [
                item.model_dump(mode="json") for item in gate_traces
            ],
            "objectives": {
                key: {
                    dimension.value: value
                    for dimension, value in values.items()
                }
                for key, values in objectives.items()
            },
            "fronts": fronts,
            "retained": retained,
            "pairwise_report_digests": report_digests,
            "missing_pairs": missing_pairs,
            "selected": selected_id,
            "runner_up": runner_up_id,
            "ranking_order": ranking_order,
        }
    )
    return CreativeCandidateRankingReport(
        input_digest=input_digest,
        policy_digest=canonical_sha256(policy),
        evaluated_at=evaluated_at,
        candidate_ids=candidate_ids,
        gate_traces=gate_traces,
        objective_values=objectives,
        pareto_fronts=fronts,
        pareto_candidate_ids=pareto_ids,
        retained_candidate_ids=retained,
        pairwise_comparison_digests=report_digests,
        missing_pairwise_pairs=[list(item) for item in missing_pairs],
        blind_pairwise_complete=comparison_complete,
        applied_exception_ids=applied_exceptions,
        human_preference_applied=human_preference is not None,
        selected_candidate_id=selected_id,
        runner_up_candidate_id=runner_up_id,
        ranking_order=ranking_order,
        selection_status=selection_status,
        automatic_selection_allowed=automatic_allowed,
        selection_digest=selection_digest,
    )


def ranking_order_for_search(
    report: CreativeCandidateRankingReport,
    survivors: Sequence[SearchCandidateRecord],
) -> list[str]:
    survivor_ids = {item.candidate_id for item in survivors}
    ordered = [
        candidate_id
        for candidate_id in report.ranking_order
        if candidate_id in survivor_ids
    ]
    if len(ordered) != len(survivor_ids) or set(ordered) != survivor_ids:
        raise ValueError("ranking report does not cover every search survivor")
    if (
        report.selected_candidate_id is not None
        and ordered[0] != report.selected_candidate_id
    ):
        raise ValueError("search order does not begin with the selected candidate")
    return ordered
