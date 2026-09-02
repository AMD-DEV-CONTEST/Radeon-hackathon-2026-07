from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

import numpy as np
from pydantic import Field, model_validator

from colorgraph.evaluation.models import StrictEvaluationModel
from colorgraph.evaluation.review import (
    Preference,
    ReviewResponse,
    ReviewSession,
    ReviewSessionKey,
    aggregate_review_responses,
)

BRADLEY_TERRY_VERSION = "colorgraph.domain-bradley-terry/v1"


class PreferenceSplit(StrEnum):
    TRAIN = "train"
    CALIBRATION = "calibration"
    TEST = "test"


class PairwiseChoice(StrEnum):
    A = "a"
    B = "b"
    TIE = "tie"


class PairwisePreferenceRecord(StrictEvaluationModel):
    id: str
    pair_id: str
    source_id: str
    candidate_a_id: str
    candidate_b_id: str
    reviewer_id: str
    choice: PairwiseChoice
    confidence: int = Field(ge=1, le=5)
    split: PreferenceSplit
    features_a: dict[str, float]
    features_b: dict[str, float]

    @model_validator(mode="after")
    def validate_pair(self) -> PairwisePreferenceRecord:
        if self.candidate_a_id == self.candidate_b_id:
            raise ValueError("pairwise candidates must differ")
        if not self.features_a or set(self.features_a) != set(self.features_b):
            raise ValueError("pairwise candidates must expose the same non-empty features")
        if not all(
            np.isfinite(float(value))
            for value in [*self.features_a.values(), *self.features_b.values()]
        ):
            raise ValueError("pairwise features must be finite")
        return self


class PreferenceTrainingConfig(StrictEvaluationModel):
    feature_names: list[str] | None = None
    baseline_features: dict[str, str] = Field(
        default_factory=lambda: {
            "rule_wins": "rule_score",
            "clip": "clip_score",
            "siglip2": "siglip2_score",
        }
    )
    l2_regularization: float = Field(default=0.05, gt=0)
    maximum_iterations: int = Field(default=100, ge=10, le=1000)
    convergence_tolerance: float = Field(default=1e-8, gt=0)
    bootstrap_samples: int = Field(default=500, ge=20, le=10_000)
    bootstrap_seed: int = 20260730
    minimum_pairs_per_split: int = Field(default=5, ge=2)
    minimum_reviewers_per_pair: int = Field(default=3, ge=3)
    calibration_bins: int = Field(default=10, ge=3, le=50)

    @model_validator(mode="after")
    def validate_features(self) -> PreferenceTrainingConfig:
        if self.feature_names is not None and (
            not self.feature_names
            or len(self.feature_names) != len(set(self.feature_names))
        ):
            raise ValueError("feature_names must be non-empty and unique")
        if (
            not self.baseline_features
            or len(self.baseline_features)
            != len(set(self.baseline_features.values()))
        ):
            raise ValueError("baseline features must be non-empty and distinct")
        return self


class ReviewerReliability(StrictEvaluationModel):
    reviewer_id: str
    decisive_ratings: int
    leave_one_out_agreements: int
    consensus_accuracy: float = Field(ge=0, le=1)
    ci95_low: float = Field(ge=0, le=1)
    ci95_high: float = Field(ge=0, le=1)
    training_weight: float = Field(gt=0, le=1)


class ReviewerAgreementReport(StrictEvaluationModel):
    fleiss_kappa: float
    valid_ratings: int
    ties: int
    reviewers: list[ReviewerReliability]
    weight_source_split: PreferenceSplit = PreferenceSplit.TRAIN


class PreferenceMetricSummary(StrictEvaluationModel):
    pairs: int
    decisive_pairs: int
    pairwise_accuracy: float = Field(ge=0, le=1)
    bradley_terry_log_loss: float = Field(ge=0)
    brier_score: float = Field(ge=0)
    expected_calibration_error: float = Field(ge=0, le=1)
    accuracy_ci95_low: float = Field(ge=0, le=1)
    accuracy_ci95_high: float = Field(ge=0, le=1)
    log_loss_ci95_low: float = Field(ge=0)
    log_loss_ci95_high: float = Field(ge=0)


class PreferenceBaselineComparison(StrictEvaluationModel):
    baseline: str
    feature_name: str
    calibrated_temperature: float = Field(gt=0)
    metrics: PreferenceMetricSummary
    accuracy_difference: float
    accuracy_difference_ci95_low: float
    accuracy_difference_ci95_high: float
    log_loss_difference: float
    log_loss_difference_ci95_low: float
    log_loss_difference_ci95_high: float
    significantly_better: bool


class BradleyTerryArtifact(StrictEvaluationModel):
    schema_version: str = BRADLEY_TERRY_VERSION
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    model_id: str
    feature_names: list[str]
    feature_scales: dict[str, float]
    coefficients: dict[str, float]
    coefficient_ci95: dict[str, tuple[float, float]]
    temperature: float = Field(gt=0)
    l2_regularization: float = Field(gt=0)
    iterations: int
    converged: bool
    reviewer_weights: dict[str, float]
    training_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    split_source_digests: dict[str, str]


class PreferenceTrainingReport(StrictEvaluationModel):
    schema_version: str = "colorgraph.preference-training-report/v1"
    artifact: BradleyTerryArtifact
    split_pair_counts: dict[str, int]
    split_tie_counts: dict[str, int]
    reviewer_agreement: ReviewerAgreementReport
    test_metrics: PreferenceMetricSummary
    baseline_comparisons: list[PreferenceBaselineComparison]
    all_required_baselines_significantly_better: bool
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _PairExample:
    pair_id: str
    source_id: str
    feature_difference: np.ndarray
    target: float
    weight: float


@dataclass(frozen=True, slots=True)
class _FitResult:
    coefficients: np.ndarray
    covariance: np.ndarray
    iterations: int
    converged: bool


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _wilson(successes: int, total: int) -> tuple[float, float]:
    if total == 0:
        return 0.0, 1.0
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z**2 / total
    center = (proportion + z**2 / (2 * total)) / denominator
    margin = (
        z
        * np.sqrt(
            proportion * (1 - proportion) / total
            + z**2 / (4 * total**2)
        )
        / denominator
    )
    return float(max(0.0, center - margin)), float(min(1.0, center + margin))


def _validate_records(
    records: Sequence[PairwisePreferenceRecord],
    config: PreferenceTrainingConfig,
) -> list[str]:
    if not records:
        raise ValueError("pairwise preference records cannot be empty")
    record_ids = [record.id for record in records]
    if len(record_ids) != len(set(record_ids)):
        raise ValueError("pairwise preference record ids must be unique")
    feature_names = (
        sorted(records[0].features_a)
        if config.feature_names is None
        else list(config.feature_names)
    )
    if any(
        set(record.features_a) != set(feature_names)
        for record in records
    ):
        raise ValueError("every preference record must use the frozen feature schema")
    missing_baselines = set(config.baseline_features.values()) - set(feature_names)
    if missing_baselines:
        raise ValueError(
            f"preference records lack required baseline features: {sorted(missing_baselines)}"
        )
    source_splits: dict[str, PreferenceSplit] = {}
    pair_records: dict[tuple[str, str], list[PairwisePreferenceRecord]] = defaultdict(list)
    for record in records:
        previous = source_splits.setdefault(record.source_id, record.split)
        if previous != record.split:
            raise ValueError(
                f"source {record.source_id!r} leaks across preference splits"
            )
        pair_records[(record.source_id, record.pair_id)].append(record)
    for key, grouped in pair_records.items():
        reviewers = [record.reviewer_id for record in grouped]
        if len(reviewers) != len(set(reviewers)):
            raise ValueError(f"duplicate reviewer rating for pair {key}")
        if len(grouped) < config.minimum_reviewers_per_pair:
            raise ValueError(
                f"pair {key} has fewer than {config.minimum_reviewers_per_pair} reviewers"
            )
        first = grouped[0]
        if any(
            record.split != first.split
            or record.candidate_a_id != first.candidate_a_id
            or record.candidate_b_id != first.candidate_b_id
            or record.features_a != first.features_a
            or record.features_b != first.features_b
            for record in grouped[1:]
        ):
            raise ValueError(f"pair {key} has inconsistent candidate evidence")
    pair_counts = {
        split: len(
            {
                (record.source_id, record.pair_id)
                for record in records
                if record.split == split
            }
        )
        for split in PreferenceSplit
    }
    insufficient = {
        split.value: count
        for split, count in pair_counts.items()
        if count < config.minimum_pairs_per_split
    }
    if insufficient:
        raise ValueError(
            "preference splits do not meet minimum pair counts: "
            f"{insufficient}"
        )
    return feature_names


def _variable_fleiss_kappa(
    records: Sequence[PairwisePreferenceRecord],
) -> float:
    grouped: dict[tuple[str, str], list[PairwisePreferenceRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.source_id, record.pair_id)].append(record)
    agreements: list[float] = []
    totals = np.zeros(3, dtype=np.float64)
    for pair_records in grouped.values():
        counts = np.array(
            [
                sum(record.choice == PairwiseChoice.A for record in pair_records),
                sum(record.choice == PairwiseChoice.B for record in pair_records),
                sum(record.choice == PairwiseChoice.TIE for record in pair_records),
            ],
            dtype=np.float64,
        )
        ratings = float(counts.sum())
        totals += counts
        if ratings >= 2:
            agreements.append(
                float(np.sum(counts * (counts - 1)) / (ratings * (ratings - 1)))
            )
    if not agreements or totals.sum() == 0:
        return 0.0
    observed = float(np.mean(agreements))
    proportions = totals / totals.sum()
    expected = float(np.sum(proportions**2))
    return (
        float((observed - expected) / (1 - expected))
        if expected < 1 - 1e-12
        else 0.0
    )


def _reviewer_reliability(
    records: Sequence[PairwisePreferenceRecord],
) -> tuple[dict[str, float], list[ReviewerReliability]]:
    grouped: dict[tuple[str, str], list[PairwisePreferenceRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.source_id, record.pair_id)].append(record)
    agreement_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for pair_records in grouped.values():
        for record in pair_records:
            if record.choice == PairwiseChoice.TIE:
                continue
            other = [
                item.choice
                for item in pair_records
                if item.reviewer_id != record.reviewer_id
                and item.choice != PairwiseChoice.TIE
            ]
            if not other:
                continue
            a_votes = sum(choice == PairwiseChoice.A for choice in other)
            b_votes = len(other) - a_votes
            if a_votes == b_votes:
                continue
            consensus = PairwiseChoice.A if a_votes > b_votes else PairwiseChoice.B
            counts = agreement_counts[record.reviewer_id]
            counts[1] += 1
            counts[0] += int(record.choice == consensus)
    reviewer_ids = sorted({record.reviewer_id for record in records})
    weights: dict[str, float] = {}
    reports: list[ReviewerReliability] = []
    for reviewer_id in reviewer_ids:
        agreements, total = agreement_counts[reviewer_id]
        accuracy = agreements / total if total else 0.5
        low, high = _wilson(agreements, total)
        shrunk = (agreements + 2) / (total + 4)
        weight = float(np.clip(0.5 + max(0.0, shrunk - 0.5), 0.5, 1.0))
        weights[reviewer_id] = weight
        reports.append(
            ReviewerReliability(
                reviewer_id=reviewer_id,
                decisive_ratings=total,
                leave_one_out_agreements=agreements,
                consensus_accuracy=accuracy,
                ci95_low=low,
                ci95_high=high,
                training_weight=weight,
            )
        )
    return weights, reports


def _aggregate_examples(
    records: Sequence[PairwisePreferenceRecord],
    *,
    feature_names: Sequence[str],
    reviewer_weights: Mapping[str, float],
) -> list[_PairExample]:
    grouped: dict[tuple[str, str], list[PairwisePreferenceRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.source_id, record.pair_id)].append(record)
    examples: list[_PairExample] = []
    for (source_id, pair_id), pair_records in sorted(grouped.items()):
        first = pair_records[0]
        a_weight = 0.0
        b_weight = 0.0
        tie_weight = 0.0
        for record in pair_records:
            weight = reviewer_weights.get(record.reviewer_id, 0.75) * (
                record.confidence / 5
            )
            if record.choice == PairwiseChoice.A:
                a_weight += weight
            elif record.choice == PairwiseChoice.B:
                b_weight += weight
            else:
                tie_weight += weight * 0.5
        total = a_weight + b_weight + tie_weight
        if total <= 0:
            continue
        target = (a_weight + tie_weight * 0.5) / total
        difference = np.asarray(
            [
                first.features_a[name] - first.features_b[name]
                for name in feature_names
            ],
            dtype=np.float64,
        )
        examples.append(
            _PairExample(
                pair_id=pair_id,
                source_id=source_id,
                feature_difference=difference,
                target=float(target),
                weight=float(total),
            )
        )
    return examples


def _arrays(
    examples: Sequence[_PairExample],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    return (
        np.stack([example.feature_difference for example in examples]),
        np.asarray([example.target for example in examples], dtype=np.float64),
        np.asarray([example.weight for example in examples], dtype=np.float64),
        np.asarray([example.source_id for example in examples], dtype=object),
    )


def _sigmoid(logits: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-np.clip(logits, -60, 60)))


def _fit_bradley_terry(
    features: np.ndarray,
    targets: np.ndarray,
    weights: np.ndarray,
    *,
    l2_regularization: float,
    maximum_iterations: int,
    tolerance: float,
) -> _FitResult:
    coefficients = np.zeros(features.shape[1], dtype=np.float64)
    total_weight = max(float(weights.sum()), 1e-12)

    def loss(values: np.ndarray) -> float:
        logits = features @ values
        cross_entropy = np.logaddexp(0, logits) - targets * logits
        return float(
            np.dot(weights, cross_entropy) / total_weight
            + 0.5 * l2_regularization * np.dot(values, values)
        )

    converged = False
    hessian = np.eye(features.shape[1], dtype=np.float64)
    iteration = 0
    for _iteration in range(1, maximum_iterations + 1):
        iteration = _iteration
        probabilities = _sigmoid(features @ coefficients)
        gradient = (
            features.T @ (weights * (probabilities - targets)) / total_weight
            + l2_regularization * coefficients
        )
        curvature = weights * probabilities * (1 - probabilities)
        hessian = (
            (features.T * curvature) @ features / total_weight
            + np.eye(features.shape[1]) * l2_regularization
        )
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError:
            step = np.linalg.pinv(hessian) @ gradient
        if float(np.linalg.norm(step, ord=np.inf)) <= tolerance:
            converged = True
            break
        current_loss = loss(coefficients)
        step_scale = 1.0
        while step_scale >= 1 / 1024:
            candidate = coefficients - step * step_scale
            if loss(candidate) <= current_loss:
                coefficients = candidate
                break
            step_scale *= 0.5
        else:
            break
    covariance = np.linalg.pinv(hessian) / max(total_weight, 1.0)
    return _FitResult(
        coefficients=coefficients,
        covariance=covariance,
        iterations=iteration,
        converged=converged,
    )


def _weighted_log_loss(
    logits: np.ndarray,
    targets: np.ndarray,
    weights: np.ndarray,
    temperature: float,
) -> float:
    scaled = logits / temperature
    losses = np.logaddexp(0, scaled) - targets * scaled
    return float(np.dot(weights, losses) / max(float(weights.sum()), 1e-12))


def _calibrate_temperature(
    logits: np.ndarray,
    targets: np.ndarray,
    weights: np.ndarray,
) -> float:
    grid = np.linspace(-3.5, 3.5, 281)
    losses = np.asarray(
        [
            _weighted_log_loss(logits, targets, weights, float(np.exp(value)))
            for value in grid
        ]
    )
    best = int(np.argmin(losses))
    left = grid[max(0, best - 1)]
    right = grid[min(len(grid) - 1, best + 1)]
    ratio = (np.sqrt(5) - 1) / 2
    for _ in range(50):
        x1 = right - ratio * (right - left)
        x2 = left + ratio * (right - left)
        loss1 = _weighted_log_loss(logits, targets, weights, float(np.exp(x1)))
        loss2 = _weighted_log_loss(logits, targets, weights, float(np.exp(x2)))
        if loss1 <= loss2:
            right = x2
        else:
            left = x1
    return float(np.exp((left + right) / 2))


def _metric_values(
    probabilities: np.ndarray,
    targets: np.ndarray,
    weights: np.ndarray,
    *,
    calibration_bins: int,
) -> tuple[float, float, float, float, int]:
    decisive = np.abs(targets - 0.5) > 1e-9
    if not decisive.any():
        raise ValueError("preference evaluation has no decisive expert consensus")
    accuracy = float(
        (
            (probabilities[decisive] >= 0.5)
            == (targets[decisive] > 0.5)
        ).mean()
    )
    epsilon = 1e-12
    bounded_probabilities = np.clip(
        probabilities,
        epsilon,
        1 - epsilon,
    )
    log_loss = float(
        np.dot(
            weights,
            -targets * np.log(bounded_probabilities)
            - (1 - targets) * np.log(1 - bounded_probabilities),
        )
        / max(float(weights.sum()), epsilon)
    )
    brier = float(
        np.dot(weights, (probabilities - targets) ** 2)
        / max(float(weights.sum()), epsilon)
    )
    boundaries = np.linspace(0, 1, calibration_bins + 1)
    calibration_error = 0.0
    total_weight = float(weights.sum())
    for lower, upper in zip(boundaries[:-1], boundaries[1:], strict=True):
        selected = (
            (probabilities >= lower)
            & (
                probabilities <= upper
                if upper == 1
                else probabilities < upper
            )
        )
        if not selected.any():
            continue
        bin_weight = float(weights[selected].sum())
        calibration_error += (
            bin_weight
            / max(total_weight, epsilon)
            * abs(
                float(np.average(probabilities[selected], weights=weights[selected]))
                - float(np.average(targets[selected], weights=weights[selected]))
            )
        )
    return accuracy, log_loss, brier, calibration_error, int(decisive.sum())


def _cluster_bootstrap_indices(
    source_ids: np.ndarray,
    targets: np.ndarray,
    *,
    samples: int,
    seed: int,
) -> list[np.ndarray]:
    unique_sources = np.unique(source_ids)
    if unique_sources.size < 2:
        raise ValueError("test uncertainty requires at least two independent sources")
    by_source = {
        source: np.flatnonzero(source_ids == source)
        for source in unique_sources
    }
    random = np.random.default_rng(seed)
    results: list[np.ndarray] = []
    attempts = 0
    while len(results) < samples and attempts < samples * 20:
        attempts += 1
        selected = random.choice(
            unique_sources,
            size=len(unique_sources),
            replace=True,
        )
        indices = np.concatenate([by_source[source] for source in selected])
        if (np.abs(targets[indices] - 0.5) > 1e-9).any():
            results.append(indices)
    if len(results) < samples:
        raise ValueError(
            "test bootstrap could not draw decisive source-level preference samples"
        )
    return results


def _metric_summary(
    probabilities: np.ndarray,
    targets: np.ndarray,
    weights: np.ndarray,
    source_ids: np.ndarray,
    *,
    bootstrap_indices: Sequence[np.ndarray],
    calibration_bins: int,
) -> PreferenceMetricSummary:
    accuracy, log_loss, brier, calibration_error, decisive = _metric_values(
        probabilities,
        targets,
        weights,
        calibration_bins=calibration_bins,
    )
    bootstrapped = [
        _metric_values(
            probabilities[indices],
            targets[indices],
            weights[indices],
            calibration_bins=calibration_bins,
        )
        for indices in bootstrap_indices
    ]
    accuracy_values = np.asarray([item[0] for item in bootstrapped])
    log_loss_values = np.asarray([item[1] for item in bootstrapped])
    return PreferenceMetricSummary(
        pairs=len(targets),
        decisive_pairs=decisive,
        pairwise_accuracy=accuracy,
        bradley_terry_log_loss=log_loss,
        brier_score=brier,
        expected_calibration_error=calibration_error,
        accuracy_ci95_low=float(np.quantile(accuracy_values, 0.025)),
        accuracy_ci95_high=float(np.quantile(accuracy_values, 0.975)),
        log_loss_ci95_low=float(np.quantile(log_loss_values, 0.025)),
        log_loss_ci95_high=float(np.quantile(log_loss_values, 0.975)),
    )


def preference_probability(
    artifact: BradleyTerryArtifact,
    features_a: Mapping[str, float],
    features_b: Mapping[str, float],
) -> float:
    expected = set(artifact.feature_names)
    if set(features_a) != expected or set(features_b) != expected:
        raise ValueError("preference prediction features do not match the artifact")
    difference = np.asarray(
        [
            (float(features_a[name]) - float(features_b[name]))
            / artifact.feature_scales[name]
            for name in artifact.feature_names
        ]
    )
    coefficients = np.asarray(
        [artifact.coefficients[name] for name in artifact.feature_names]
    )
    return float(_sigmoid(np.asarray([difference @ coefficients / artifact.temperature]))[0])


def preference_records_from_review(
    session: ReviewSession,
    session_key: ReviewSessionKey,
    responses: Sequence[ReviewResponse],
    *,
    candidate_features: Mapping[str, Mapping[str, float]],
    split_by_source: Mapping[str, PreferenceSplit | str],
) -> list[PairwisePreferenceRecord]:
    aggregate_review_responses(session, session_key, list(responses))
    assignments = {
        (reviewer_session.reviewer_id, assignment.pair_id): assignment
        for reviewer_session in session.sessions
        for assignment in reviewer_session.assignments
    }
    source_by_pair = {
        assignment.pair_id: assignment.source_id
        for reviewer_session in session.sessions
        for assignment in reviewer_session.assignments
    }
    records: list[PairwisePreferenceRecord] = []
    for response in responses:
        if response.preference == Preference.REJECT:
            continue
        canonical = session_key.canonical_pairs[response.pair_id]
        source_id = source_by_pair[response.pair_id]
        try:
            split = PreferenceSplit(split_by_source[source_id])
            features_a = dict(candidate_features[canonical["candidate_a"]])
            features_b = dict(candidate_features[canonical["candidate_b"]])
        except KeyError as exc:
            raise ValueError(
                f"review preference lacks split/features for {source_id!r}"
            ) from exc
        if response.preference == Preference.TIE:
            choice = PairwiseChoice.TIE
        else:
            assignment = assignments[(response.reviewer_id, response.pair_id)]
            blind_code = (
                assignment.blind_a
                if response.preference == Preference.A
                else assignment.blind_b
            )
            selected = session_key.mappings[
                f"{response.reviewer_id}:{response.pair_id}"
            ][blind_code]
            choice = (
                PairwiseChoice.A
                if selected == canonical["candidate_a"]
                else PairwiseChoice.B
            )
        records.append(
            PairwisePreferenceRecord(
                id=(
                    f"{session.session_id}:{response.reviewer_id}:"
                    f"{response.pair_id}"
                ),
                pair_id=response.pair_id,
                source_id=source_id,
                candidate_a_id=canonical["candidate_a"],
                candidate_b_id=canonical["candidate_b"],
                reviewer_id=response.reviewer_id,
                choice=choice,
                confidence=response.confidence,
                split=split,
                features_a=features_a,
                features_b=features_b,
            )
        )
    return records


def train_bradley_terry_preference(
    records: Sequence[PairwisePreferenceRecord],
    *,
    config: PreferenceTrainingConfig | None = None,
) -> PreferenceTrainingReport:
    selected_config = config or PreferenceTrainingConfig()
    feature_names = _validate_records(records, selected_config)
    train_records = [
        record for record in records if record.split == PreferenceSplit.TRAIN
    ]
    reviewer_weights, reliability = _reviewer_reliability(train_records)
    agreement = ReviewerAgreementReport(
        fleiss_kappa=_variable_fleiss_kappa(records),
        valid_ratings=len(records),
        ties=sum(record.choice == PairwiseChoice.TIE for record in records),
        reviewers=reliability,
    )
    split_examples = {
        split: _aggregate_examples(
            [record for record in records if record.split == split],
            feature_names=feature_names,
            reviewer_weights=reviewer_weights,
        )
        for split in PreferenceSplit
    }
    train_x, train_y, train_weight, _ = _arrays(
        split_examples[PreferenceSplit.TRAIN]
    )
    scales = np.sqrt(np.average(train_x**2, axis=0, weights=train_weight))
    scales = np.where(scales >= 1e-8, scales, 1.0)
    standardized_train = train_x / scales
    fitted = _fit_bradley_terry(
        standardized_train,
        train_y,
        train_weight,
        l2_regularization=selected_config.l2_regularization,
        maximum_iterations=selected_config.maximum_iterations,
        tolerance=selected_config.convergence_tolerance,
    )
    calibration_x, calibration_y, calibration_weight, _ = _arrays(
        split_examples[PreferenceSplit.CALIBRATION]
    )
    temperature = _calibrate_temperature(
        calibration_x / scales @ fitted.coefficients,
        calibration_y,
        calibration_weight,
    )
    test_x, test_y, test_weight, test_sources = _arrays(
        split_examples[PreferenceSplit.TEST]
    )
    if not (np.abs(test_y - 0.5) > 1e-9).any():
        raise ValueError("preference evaluation has no decisive expert consensus")
    test_logits = test_x / scales @ fitted.coefficients
    model_probabilities = _sigmoid(test_logits / temperature)
    bootstrap_indices = _cluster_bootstrap_indices(
        test_sources,
        test_y,
        samples=selected_config.bootstrap_samples,
        seed=selected_config.bootstrap_seed,
    )
    model_metrics = _metric_summary(
        model_probabilities,
        test_y,
        test_weight,
        test_sources,
        bootstrap_indices=bootstrap_indices,
        calibration_bins=selected_config.calibration_bins,
    )
    comparisons: list[PreferenceBaselineComparison] = []
    for baseline, feature_name in selected_config.baseline_features.items():
        feature_index = feature_names.index(feature_name)
        calibration_logits = calibration_x[:, feature_index]
        baseline_temperature = _calibrate_temperature(
            calibration_logits,
            calibration_y,
            calibration_weight,
        )
        baseline_probabilities = _sigmoid(
            test_x[:, feature_index] / baseline_temperature
        )
        baseline_metrics = _metric_summary(
            baseline_probabilities,
            test_y,
            test_weight,
            test_sources,
            bootstrap_indices=bootstrap_indices,
            calibration_bins=selected_config.calibration_bins,
        )
        accuracy_differences: list[float] = []
        loss_differences: list[float] = []
        for indices in bootstrap_indices:
            model_values = _metric_values(
                model_probabilities[indices],
                test_y[indices],
                test_weight[indices],
                calibration_bins=selected_config.calibration_bins,
            )
            baseline_values = _metric_values(
                baseline_probabilities[indices],
                test_y[indices],
                test_weight[indices],
                calibration_bins=selected_config.calibration_bins,
            )
            accuracy_differences.append(model_values[0] - baseline_values[0])
            loss_differences.append(model_values[1] - baseline_values[1])
        accuracy_interval = np.quantile(accuracy_differences, [0.025, 0.975])
        loss_interval = np.quantile(loss_differences, [0.025, 0.975])
        comparisons.append(
            PreferenceBaselineComparison(
                baseline=baseline,
                feature_name=feature_name,
                calibrated_temperature=baseline_temperature,
                metrics=baseline_metrics,
                accuracy_difference=(
                    model_metrics.pairwise_accuracy
                    - baseline_metrics.pairwise_accuracy
                ),
                accuracy_difference_ci95_low=float(accuracy_interval[0]),
                accuracy_difference_ci95_high=float(accuracy_interval[1]),
                log_loss_difference=(
                    model_metrics.bradley_terry_log_loss
                    - baseline_metrics.bradley_terry_log_loss
                ),
                log_loss_difference_ci95_low=float(loss_interval[0]),
                log_loss_difference_ci95_high=float(loss_interval[1]),
                significantly_better=(
                    float(accuracy_interval[0]) > 0
                    and float(loss_interval[1]) < 0
                ),
            )
        )

    standard_errors = np.sqrt(np.maximum(np.diag(fitted.covariance), 0.0))
    training_payload = {
        "records": [
            record.model_dump(mode="json")
            for record in sorted(records, key=lambda item: item.id)
        ],
        "config": selected_config.model_dump(mode="json"),
        "feature_names": feature_names,
    }
    training_digest = _canonical_sha256(training_payload)
    source_digests = {
        split.value: _canonical_sha256(
            sorted(
                {
                    record.source_id
                    for record in records
                    if record.split == split
                }
            )
        )
        for split in PreferenceSplit
    }
    artifact = BradleyTerryArtifact(
        model_id=f"bt-{training_digest[:16]}",
        feature_names=feature_names,
        feature_scales={
            name: float(scales[index])
            for index, name in enumerate(feature_names)
        },
        coefficients={
            name: float(fitted.coefficients[index])
            for index, name in enumerate(feature_names)
        },
        coefficient_ci95={
            name: (
                float(fitted.coefficients[index] - 1.96 * standard_errors[index]),
                float(fitted.coefficients[index] + 1.96 * standard_errors[index]),
            )
            for index, name in enumerate(feature_names)
        },
        temperature=temperature,
        l2_regularization=selected_config.l2_regularization,
        iterations=fitted.iterations,
        converged=fitted.converged,
        reviewer_weights=reviewer_weights,
        training_digest=training_digest,
        split_source_digests=source_digests,
    )
    split_pair_counts = {
        split.value: len(split_examples[split]) for split in PreferenceSplit
    }
    split_tie_counts = {
        split.value: sum(
            record.choice == PairwiseChoice.TIE
            for record in records
            if record.split == split
        )
        for split in PreferenceSplit
    }
    warnings = []
    if not fitted.converged:
        warnings.append("Bradley-Terry optimizer reached its iteration/line-search limit")
    if agreement.fleiss_kappa < 0.4:
        warnings.append("expert agreement is below the predeclared moderate threshold")
    return PreferenceTrainingReport(
        artifact=artifact,
        split_pair_counts=split_pair_counts,
        split_tie_counts=split_tie_counts,
        reviewer_agreement=agreement,
        test_metrics=model_metrics,
        baseline_comparisons=comparisons,
        all_required_baselines_significantly_better=all(
            comparison.significantly_better for comparison in comparisons
        ),
        warnings=warnings,
    )
