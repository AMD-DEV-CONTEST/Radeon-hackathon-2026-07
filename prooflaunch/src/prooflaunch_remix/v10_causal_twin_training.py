from __future__ import annotations

import hashlib
import math
import random
import statistics
from dataclasses import asdict, dataclass
from typing import Iterable, Mapping, Sequence

from .v10_contracts import EvidenceClass, V10ContractError
from .v10_sft_corpus import stable_sha256


PRODUCT_KINDS = ("physical_product", "ai_agent")
MARKETS = ("us_east", "us_west", "us_central", "canada_east", "canada_west")
CONFOUNDERS = (
    "seasonality",
    "price_index",
    "channel_strength",
    "brand_momentum",
    "selection_bias",
)
CORPUS_LICENSE = "MIT"
CORPUS_LICENSE_LOCATOR = "project://LICENSE"
CORPUS_RECORD_COUNT = 1_200


@dataclass(frozen=True)
class CausalTimeSeriesRow:
    record_id: str
    product_kind: str
    product_id: str
    market: str
    day_index: int
    observed_at: str
    seasonality: float
    price_index: float
    channel_strength: float
    brand_momentum: float
    selection_bias: float
    treated: bool
    outcome: float
    propensity: float
    true_treatment_effect: float
    split: str
    evidence_class: EvidenceClass
    license_id: str
    license_locator: str
    source_locator: str

    def __post_init__(self) -> None:
        if self.product_kind not in PRODUCT_KINDS:
            raise V10ContractError("causal corpus has an unknown product kind")
        if self.market not in MARKETS:
            raise V10ContractError("causal corpus has an unknown market")
        if self.split not in {"train", "validation", "test"}:
            raise V10ContractError("causal corpus has an unknown temporal split")
        if self.evidence_class != EvidenceClass.SIMULATED:
            raise V10ContractError("project-owned causal fixture must remain simulated")
        if self.license_id != CORPUS_LICENSE or self.license_locator != CORPUS_LICENSE_LOCATOR:
            raise V10ContractError("causal fixture requires the public project license")
        if not 0.02 <= self.propensity <= 0.98:
            raise V10ContractError("causal fixture violates propensity overlap")
        if not 0 <= self.outcome <= 1:
            raise V10ContractError("causal fixture outcome must be in [0,1]")
        if self.day_index < 0:
            raise V10ContractError("causal fixture day cannot be negative")

    @property
    def digest(self) -> str:
        return stable_sha256(asdict(self))


@dataclass(frozen=True)
class Standardizer:
    means: tuple[float, ...]
    scales: tuple[float, ...]

    def transform(self, values: Sequence[float]) -> tuple[float, ...]:
        if len(values) != len(self.means):
            raise V10ContractError("feature width drift")
        return tuple(
            (float(value) - mean) / scale
            for value, mean, scale in zip(values, self.means, self.scales)
        )


@dataclass(frozen=True)
class PropensityModel:
    standardizer: Standardizer
    coefficients: tuple[float, ...]

    def predict(self, row: CausalTimeSeriesRow) -> float:
        features = (1.0, *self.standardizer.transform(_raw_features(row)))
        value = _sigmoid(_dot(self.coefficients, features))
        return min(0.98, max(0.02, value))


@dataclass(frozen=True)
class OutcomeModel:
    standardizer: Standardizer
    control_coefficients: tuple[float, ...]
    treatment_coefficients: tuple[float, ...]

    def predict(self, row: CausalTimeSeriesRow, treated: bool) -> float:
        features = (1.0, *self.standardizer.transform(_raw_features(row)))
        coefficients = self.treatment_coefficients if treated else self.control_coefficients
        return min(1.0, max(0.0, _dot(coefficients, features)))


@dataclass(frozen=True)
class CausalEstimateReport:
    evaluation_count: int
    train_count: int
    naive_difference: float
    propensity_ipw_ate: float
    doubly_robust_ate: float
    known_simulated_ate: float
    naive_absolute_error: float
    ipw_absolute_error: float
    doubly_robust_absolute_error: float
    propensity_minimum: float
    propensity_maximum: float
    treatment_rate: float
    method_order: tuple[str, ...]
    evidence_class: EvidenceClass = EvidenceClass.SIMULATED
    real_business_effect_claim_allowed: bool = False


@dataclass(frozen=True)
class HierarchicalTransferEstimate:
    target_product_kind: str
    target_profile: Mapping[str, float]
    global_prior: float
    product_kind_prior: float
    similar_market_prior: float
    transferred_effect: float
    nearest_markets: tuple[str, ...]
    source_market_count: int
    target_market_observation_count: int
    evidence_class: EvidenceClass = EvidenceClass.SIMULATED
    real_business_effect_claim_allowed: bool = False


def _sigmoid(value: float) -> float:
    if value >= 0:
        term = math.exp(-value)
        return 1 / (1 + term)
    term = math.exp(value)
    return term / (1 + term)


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise V10ContractError("dot-product width drift")
    return sum(a * b for a, b in zip(left, right))


def _raw_features(row: CausalTimeSeriesRow) -> tuple[float, ...]:
    return (
        row.seasonality,
        row.price_index,
        row.channel_strength,
        row.brand_momentum,
        row.selection_bias,
        1.0 if row.product_kind == "ai_agent" else 0.0,
    )


def _fit_standardizer(rows: Sequence[CausalTimeSeriesRow]) -> Standardizer:
    if not rows:
        raise V10ContractError("standardizer requires rows")
    columns = tuple(zip(*(_raw_features(row) for row in rows)))
    means = tuple(statistics.fmean(column) for column in columns)
    scales = tuple(max(statistics.pstdev(column), 1e-6) for column in columns)
    return Standardizer(means, scales)


def _normal_equation(
    features: Sequence[Sequence[float]], targets: Sequence[float], ridge: float
) -> tuple[float, ...]:
    if not features or len(features) != len(targets):
        raise V10ContractError("linear model requires aligned rows")
    width = len(features[0])
    matrix = [[0.0 for _ in range(width)] for _ in range(width)]
    vector = [0.0 for _ in range(width)]
    for row, target in zip(features, targets):
        if len(row) != width:
            raise V10ContractError("linear feature width drift")
        for i in range(width):
            vector[i] += row[i] * target
            for j in range(width):
                matrix[i][j] += row[i] * row[j]
    for index in range(1, width):
        matrix[index][index] += ridge
    return _solve(matrix, vector)


def _solve(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> tuple[float, ...]:
    width = len(vector)
    work = [list(row) + [float(target)] for row, target in zip(matrix, vector)]
    if len(work) != width or any(len(row) != width + 1 for row in work):
        raise V10ContractError("linear system is not square")
    for column in range(width):
        pivot = max(range(column, width), key=lambda row: abs(work[row][column]))
        if abs(work[pivot][column]) < 1e-10:
            raise V10ContractError("linear system is singular")
        work[column], work[pivot] = work[pivot], work[column]
        scale = work[column][column]
        work[column] = [value / scale for value in work[column]]
        for row in range(width):
            if row == column:
                continue
            factor = work[row][column]
            work[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(work[row], work[column])
            ]
    return tuple(row[-1] for row in work)


def generate_causal_time_series(seed: int = 20_260_801) -> tuple[CausalTimeSeriesRow, ...]:
    rows: list[CausalTimeSeriesRow] = []
    for kind_index, product_kind in enumerate(PRODUCT_KINDS):
        for market_index, market in enumerate(MARKETS):
            product_id = f"{product_kind}-{market}"
            market_offset = (market_index - 2) * 0.035
            for day in range(120):
                seasonality = math.sin(2 * math.pi * day / 30 + market_index * 0.3)
                price_index = 0.05 * math.cos(2 * math.pi * day / 21) + market_offset
                channel_strength = ((day * 7 + market_index * 11) % 37) / 36 - 0.5
                brand_momentum = (day / 119 - 0.5) + kind_index * 0.12
                selection_bias = math.sin((day + 3 * market_index) / 11) * 0.4
                logit = (
                    -0.15
                    + 0.55 * seasonality
                    - 1.15 * price_index
                    + 0.85 * channel_strength
                    + 0.95 * brand_momentum
                    + 0.75 * selection_bias
                    + 0.25 * kind_index
                )
                propensity = min(0.98, max(0.02, _sigmoid(logit)))
                row_seed = int(
                    hashlib.sha256(f"{seed}:{product_kind}:{market}:{day}".encode()).hexdigest()[:16],
                    16,
                )
                rng = random.Random(row_seed)
                treated = rng.random() < propensity
                true_effect = (
                    0.075
                    + 0.035 * kind_index
                    + 0.012 * channel_strength
                    + 0.008 * market_index
                )
                baseline = (
                    0.24
                    + 0.045 * seasonality
                    - 0.16 * price_index
                    + 0.08 * channel_strength
                    + 0.11 * brand_momentum
                    + 0.09 * selection_bias
                    + 0.025 * kind_index
                    + market_offset
                )
                noise = rng.gauss(0, 0.018)
                outcome = min(0.98, max(0.01, baseline + true_effect * treated + noise))
                split = "train" if day < 80 else "validation" if day < 100 else "test"
                record_id = f"twin-{kind_index}-{market_index}-{day:03d}"
                rows.append(
                    CausalTimeSeriesRow(
                        record_id=record_id,
                        product_kind=product_kind,
                        product_id=product_id,
                        market=market,
                        day_index=day,
                        observed_at=f"2026-{(day // 28) + 1:02d}-{(day % 28) + 1:02d}T00:00:00Z",
                        seasonality=round(seasonality, 9),
                        price_index=round(price_index, 9),
                        channel_strength=round(channel_strength, 9),
                        brand_momentum=round(brand_momentum, 9),
                        selection_bias=round(selection_bias, 9),
                        treated=treated,
                        outcome=round(outcome, 9),
                        propensity=round(propensity, 9),
                        true_treatment_effect=round(true_effect, 9),
                        split=split,
                        evidence_class=EvidenceClass.SIMULATED,
                        license_id=CORPUS_LICENSE,
                        license_locator=CORPUS_LICENSE_LOCATOR,
                        source_locator=f"project://data/v10_causal_twin_timeseries/rows.jsonl#{record_id}",
                    )
                )
    if len(rows) != CORPUS_RECORD_COUNT or len({row.record_id for row in rows}) != CORPUS_RECORD_COUNT:
        raise V10ContractError("causal fixture count drift")
    return tuple(rows)


def fit_propensity_model(
    rows: Sequence[CausalTimeSeriesRow], *, epochs: int = 1_200, learning_rate: float = 0.08
) -> PropensityModel:
    if len(rows) < 100 or epochs < 1 or not 0 < learning_rate <= 1:
        raise V10ContractError("invalid propensity training profile")
    standardizer = _fit_standardizer(rows)
    feature_rows = [
        (1.0, *standardizer.transform(_raw_features(row)))
        for row in rows
    ]
    coefficients = [0.0 for _ in feature_rows[0]]
    for _ in range(epochs):
        gradient = [0.0 for _ in coefficients]
        for features, row in zip(feature_rows, rows):
            residual = _sigmoid(_dot(coefficients, features)) - float(row.treated)
            for index, value in enumerate(features):
                gradient[index] += residual * value
        count = len(rows)
        for index in range(len(coefficients)):
            penalty = 0.0 if index == 0 else 0.002 * coefficients[index]
            coefficients[index] -= learning_rate * (gradient[index] / count + penalty)
    return PropensityModel(standardizer, tuple(coefficients))


def fit_outcome_model(rows: Sequence[CausalTimeSeriesRow]) -> OutcomeModel:
    if len(rows) < 100:
        raise V10ContractError("outcome model requires at least 100 rows")
    standardizer = _fit_standardizer(rows)
    control = [row for row in rows if not row.treated]
    treatment = [row for row in rows if row.treated]
    if len(control) < 20 or len(treatment) < 20:
        raise V10ContractError("outcome model lacks treatment overlap")

    def design(selected: Sequence[CausalTimeSeriesRow]) -> list[tuple[float, ...]]:
        return [(1.0, *standardizer.transform(_raw_features(row))) for row in selected]

    return OutcomeModel(
        standardizer=standardizer,
        control_coefficients=_normal_equation(design(control), [row.outcome for row in control], 0.01),
        treatment_coefficients=_normal_equation(design(treatment), [row.outcome for row in treatment], 0.01),
    )


def evaluate_estimators(
    training_rows: Sequence[CausalTimeSeriesRow],
    evaluation_rows: Sequence[CausalTimeSeriesRow],
) -> CausalEstimateReport:
    if not training_rows or not evaluation_rows:
        raise V10ContractError("causal evaluation requires train and evaluation rows")
    if max(row.day_index for row in training_rows) >= min(row.day_index for row in evaluation_rows):
        raise V10ContractError("causal evaluation requires a strict temporal holdout")
    if any(row.evidence_class != EvidenceClass.SIMULATED for row in (*training_rows, *evaluation_rows)):
        raise V10ContractError("fixture evidence class drift")
    propensity_model = fit_propensity_model(training_rows)
    outcome_model = fit_outcome_model(training_rows)
    treated_outcomes = [row.outcome for row in evaluation_rows if row.treated]
    control_outcomes = [row.outcome for row in evaluation_rows if not row.treated]
    if not treated_outcomes or not control_outcomes:
        raise V10ContractError("evaluation lacks treatment overlap")
    naive = statistics.fmean(treated_outcomes) - statistics.fmean(control_outcomes)
    ipw_terms: list[float] = []
    dr_terms: list[float] = []
    propensities: list[float] = []
    for row in evaluation_rows:
        propensity = propensity_model.predict(row)
        propensities.append(propensity)
        mu1 = outcome_model.predict(row, True)
        mu0 = outcome_model.predict(row, False)
        treatment = float(row.treated)
        ipw_terms.append(treatment * row.outcome / propensity - (1 - treatment) * row.outcome / (1 - propensity))
        dr_terms.append(
            mu1
            - mu0
            + treatment * (row.outcome - mu1) / propensity
            - (1 - treatment) * (row.outcome - mu0) / (1 - propensity)
        )
    ipw = statistics.fmean(ipw_terms)
    dr = statistics.fmean(dr_terms)
    truth = statistics.fmean(row.true_treatment_effect for row in evaluation_rows)
    return CausalEstimateReport(
        evaluation_count=len(evaluation_rows),
        train_count=len(training_rows),
        naive_difference=round(naive, 9),
        propensity_ipw_ate=round(ipw, 9),
        doubly_robust_ate=round(dr, 9),
        known_simulated_ate=round(truth, 9),
        naive_absolute_error=round(abs(naive - truth), 9),
        ipw_absolute_error=round(abs(ipw - truth), 9),
        doubly_robust_absolute_error=round(abs(dr - truth), 9),
        propensity_minimum=round(min(propensities), 9),
        propensity_maximum=round(max(propensities), 9),
        treatment_rate=round(sum(row.treated for row in evaluation_rows) / len(evaluation_rows), 9),
        method_order=("naive_correlation", "estimated_propensity_ipw", "aipw_doubly_robust"),
    )


def _profile(rows: Sequence[CausalTimeSeriesRow]) -> dict[str, float]:
    return {
        name: statistics.fmean(float(getattr(row, name)) for row in rows)
        for name in CONFOUNDERS
    }


def _profile_distance(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    if set(left) != set(CONFOUNDERS) or set(right) != set(CONFOUNDERS):
        raise V10ContractError("cold-start profile requires all confounders")
    return math.sqrt(sum((float(left[name]) - float(right[name])) ** 2 for name in CONFOUNDERS))


def hierarchical_cold_start_transfer(
    rows: Sequence[CausalTimeSeriesRow],
    *,
    target_product_kind: str,
    target_profile: Mapping[str, float],
    nearest_count: int = 2,
) -> HierarchicalTransferEstimate:
    if target_product_kind not in PRODUCT_KINDS or nearest_count not in {1, 2, 3}:
        raise V10ContractError("invalid cold-start target")
    if any(row.split != "train" for row in rows):
        raise V10ContractError("cold-start transfer must fit on training rows only")
    global_prior = statistics.fmean(row.true_treatment_effect for row in rows)
    kind_rows = [row for row in rows if row.product_kind == target_product_kind]
    kind_prior = statistics.fmean(row.true_treatment_effect for row in kind_rows)
    market_rows: dict[str, list[CausalTimeSeriesRow]] = {
        market: [row for row in kind_rows if row.market == market]
        for market in MARKETS
    }
    ranked = sorted(
        (
            (_profile_distance(_profile(selected), target_profile), market, selected)
            for market, selected in market_rows.items()
            if selected
        ),
        key=lambda item: (item[0], item[1]),
    )[:nearest_count]
    weights = [1 / max(distance, 1e-6) for distance, _, _ in ranked]
    similar_prior = sum(
        weight * statistics.fmean(row.true_treatment_effect for row in selected)
        for weight, (_, _, selected) in zip(weights, ranked)
    ) / sum(weights)
    transferred = 0.20 * global_prior + 0.35 * kind_prior + 0.45 * similar_prior
    return HierarchicalTransferEstimate(
        target_product_kind=target_product_kind,
        target_profile={name: float(target_profile[name]) for name in CONFOUNDERS},
        global_prior=round(global_prior, 9),
        product_kind_prior=round(kind_prior, 9),
        similar_market_prior=round(similar_prior, 9),
        transferred_effect=round(transferred, 9),
        nearest_markets=tuple(market for _, market, _ in ranked),
        source_market_count=len(ranked),
        target_market_observation_count=0,
    )


def corpus_digest(rows: Iterable[CausalTimeSeriesRow]) -> str:
    return stable_sha256([asdict(row) for row in rows])
