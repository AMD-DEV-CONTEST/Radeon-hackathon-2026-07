"""Fail-closed calibration and hold-out gates for the Cs exchange model.

This module is deliberately separate from the canonical transport model and
from the PHREEQC runner.  It provides the data contract and the arithmetic
needed to *prepare* a calibration.  It never turns demonstration data into
site evidence, and it never changes a PHREEQC or transport result.

The fitted model is a transparent log-linear screening surrogate for apparent
Kd.  It is a calibration instrument, not a thermodynamic PHREEQC database.
Promotion requires traceable measured data, an explicit group-disjoint
calibration/hold-out split, and a passing acceptance policy.  Synthetic test
fixtures are always blocked from scientific promotion.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
import math
import statistics
from typing import Any, Mapping, Sequence


DATASET_SCHEMA = "nuclidepath-cs-exchange-observations-1"
REPORT_SCHEMA = "nuclidepath-cs-exchange-validation-1"
MODEL_SCHEMA = "log-linear-multication-cs-kd-1"
COMPETITOR_IONS = ("K", "Na", "Ca", "Mg")
ALLOWED_DATA_STATUSES = ("synthetic_test_only", "measured_traceable")


class ScientificValidationError(ValueError):
    """Raised when a dataset, model, or validation result is unsafe to use."""


class ScientificValidationGateError(ScientificValidationError):
    """Raised when a caller requests promotion that the evidence cannot support."""


def _keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ScientificValidationError(
            f"{label} contains unsupported keys: {', '.join(sorted(unknown))}"
        )


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScientificValidationError(f"{label} must be a non-empty string")
    return value.strip()


def _number(value: Any, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScientificValidationError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ScientificValidationError(f"{label} must be finite")
    if minimum is not None and number < minimum:
        raise ScientificValidationError(f"{label} must be >= {minimum}")
    return number


def _positive(value: Any, label: str) -> float:
    number = _number(value, label, minimum=0.0)
    if number <= 0.0:
        raise ScientificValidationError(f"{label} must be > 0")
    return number


def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ScientificValidationError(f"{label} must be a list of strings")
    result = tuple(_string(item, f"{label} entry") for item in value)
    if not result:
        raise ScientificValidationError(f"{label} must not be empty")
    if len(set(result)) != len(result):
        raise ScientificValidationError(f"{label} must not contain duplicates")
    return result


@dataclass(frozen=True)
class Observation:
    """One equilibrium/column observation with explicit units.

    Concentrations are mmol/kgw, CEC is mmolc/kg dry medium, Cs is mol/kgw,
    and Kd is m3/kg.  Missing competitor measurements are not interpreted as
    zero: all four competitor keys must be present and zero must be explicit.
    """

    observation_id: str
    group_id: str
    mineral: str
    cec_mmolc_kg: float
    cs_mol_kgw: float
    competitors_mmol_kgw: Mapping[str, float]
    kd_m3_kg: float

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], index: int) -> "Observation":
        if not isinstance(value, Mapping):
            raise ScientificValidationError(f"observations[{index}] must be an object")
        allowed = {
            "observation_id", "group_id", "mineral", "cec_mmolc_kg",
            "cs_mol_kgw", "competitors_mmol_kgw", "kd_m3_kg",
        }
        _keys(value, allowed, f"observations[{index}]")
        competitors = value.get("competitors_mmol_kgw")
        if not isinstance(competitors, Mapping):
            raise ScientificValidationError(
                f"observations[{index}].competitors_mmol_kgw must be an object"
            )
        if set(competitors) != set(COMPETITOR_IONS):
            raise ScientificValidationError(
                "competitors_mmol_kgw must contain K, Na, Ca and Mg explicitly"
            )
        parsed_competitors = {
            ion: _number(competitors[ion], f"observations[{index}].{ion}", minimum=0.0)
            for ion in COMPETITOR_IONS
        }
        return cls(
            observation_id=_string(value.get("observation_id"), f"observations[{index}].observation_id"),
            group_id=_string(value.get("group_id"), f"observations[{index}].group_id"),
            mineral=_string(value.get("mineral"), f"observations[{index}].mineral"),
            cec_mmolc_kg=_positive(value.get("cec_mmolc_kg"), f"observations[{index}].cec_mmolc_kg"),
            cs_mol_kgw=_positive(value.get("cs_mol_kgw"), f"observations[{index}].cs_mol_kgw"),
            competitors_mmol_kgw=parsed_competitors,
            kd_m3_kg=_positive(value.get("kd_m3_kg"), f"observations[{index}].kd_m3_kg"),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "group_id": self.group_id,
            "mineral": self.mineral,
            "cec_mmolc_kg": self.cec_mmolc_kg,
            "cs_mol_kgw": self.cs_mol_kgw,
            "competitors_mmol_kgw": {
                ion: self.competitors_mmol_kgw[ion] for ion in COMPETITOR_IONS
            },
            "kd_m3_kg": self.kd_m3_kg,
        }


@dataclass(frozen=True)
class ObservationDataset:
    dataset_id: str
    data_status: str
    provenance: Mapping[str, str]
    observations: tuple[Observation, ...]
    calibration_group_ids: tuple[str, ...]
    holdout_group_ids: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ObservationDataset":
        if not isinstance(value, Mapping):
            raise ScientificValidationError("dataset must be an object")
        _keys(value, {
            "schema", "dataset_id", "data_status", "provenance",
            "observations", "split",
        }, "dataset")
        if value.get("schema") != DATASET_SCHEMA:
            raise ScientificValidationError("unsupported observation dataset schema")
        dataset_id = _string(value.get("dataset_id"), "dataset_id")
        data_status = _string(value.get("data_status"), "data_status")
        if data_status not in ALLOWED_DATA_STATUSES:
            raise ScientificValidationError(
                f"data_status must be one of {ALLOWED_DATA_STATUSES}"
            )

        provenance = value.get("provenance")
        if not isinstance(provenance, Mapping):
            raise ScientificValidationError("provenance must be an object")
        _keys(provenance, {
            "source", "license", "method", "units", "retrieved_at", "permission",
            "dataset_sha256",
        }, "provenance")
        required_provenance = ("source", "license", "method", "units", "retrieved_at", "permission")
        parsed_provenance = {
            key: _string(provenance.get(key), f"provenance.{key}")
            for key in required_provenance
        }
        if data_status == "measured_traceable" and parsed_provenance["permission"] not in {
            "documented", "public",
        }:
            raise ScientificValidationError(
                "measured_traceable data require documented or public permission"
            )
        if data_status == "measured_traceable":
            # Review finding: a self-declared data_status must not be enough to
            # promote a model. Require a public, independently checkable source
            # URL and a dataset digest so the claim is verifiable, not merely
            # asserted. Without both, the data cannot be treated as measured.
            source = parsed_provenance["source"]
            if not source.startswith(("https://", "http://")):
                raise ScientificValidationError(
                    "measured_traceable data require a public http(s) provenance.source URL"
                )
            dataset_sha256 = provenance.get("dataset_sha256")
            if not isinstance(dataset_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", dataset_sha256):
                raise ScientificValidationError(
                    "measured_traceable data require provenance.dataset_sha256 (64 hex chars)"
                )
            method = parsed_provenance["method"].lower()
            if not any(token in method for token in ("experiment", "measure", "field", "laboratory", "lab ", "batch")):
                raise ScientificValidationError(
                    "measured_traceable data require an experimental/measurement method description"
                )

        raw_observations = value.get("observations")
        if isinstance(raw_observations, (str, bytes)) or not isinstance(raw_observations, Sequence):
            raise ScientificValidationError("observations must be a non-empty list")
        observations = tuple(
            Observation.from_mapping(item, index)
            for index, item in enumerate(raw_observations)
        )
        if not observations:
            raise ScientificValidationError("observations must not be empty")
        observation_ids = [item.observation_id for item in observations]
        if len(set(observation_ids)) != len(observation_ids):
            raise ScientificValidationError("observation_id values must be unique")
        groups = {item.group_id for item in observations}
        if len(groups) < 2:
            raise ScientificValidationError("at least two independent groups are required")

        split = value.get("split")
        if not isinstance(split, Mapping):
            raise ScientificValidationError("split must be an object")
        _keys(split, {"calibration_group_ids", "holdout_group_ids"}, "split")
        calibration_groups = _string_tuple(split.get("calibration_group_ids"), "calibration_group_ids")
        holdout_groups = _string_tuple(split.get("holdout_group_ids"), "holdout_group_ids")
        if set(calibration_groups) & set(holdout_groups):
            raise ScientificValidationError("calibration and hold-out groups must be disjoint")
        if set(calibration_groups) | set(holdout_groups) != groups:
            raise ScientificValidationError(
                "calibration and hold-out groups must cover every observation group"
            )
        return cls(
            dataset_id=dataset_id,
            data_status=data_status,
            provenance=parsed_provenance,
            observations=observations,
            calibration_group_ids=calibration_groups,
            holdout_group_ids=holdout_groups,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": DATASET_SCHEMA,
            "dataset_id": self.dataset_id,
            "data_status": self.data_status,
            "provenance": dict(self.provenance),
            "observations": [item.to_payload() for item in self.observations],
            "split": {
                "calibration_group_ids": list(self.calibration_group_ids),
                "holdout_group_ids": list(self.holdout_group_ids),
            },
        }

    def calibration_observations(self) -> tuple[Observation, ...]:
        allowed = set(self.calibration_group_ids)
        return tuple(item for item in self.observations if item.group_id in allowed)

    def holdout_observations(self) -> tuple[Observation, ...]:
        allowed = set(self.holdout_group_ids)
        return tuple(item for item in self.observations if item.group_id in allowed)


def deterministic_group_split(
    observations: Sequence[Observation],
    dataset_id: str,
    *,
    holdout_fraction: float = 0.2,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return a reproducible, group-disjoint ``(calibration, holdout)`` split."""

    fraction = _number(holdout_fraction, "holdout_fraction", minimum=0.0)
    if not 0.0 < fraction < 1.0:
        raise ScientificValidationError("holdout_fraction must be between zero and one")
    groups = sorted({item.group_id for item in observations})
    if len(groups) < 2:
        raise ScientificValidationError("at least two groups are required for a hold-out")
    ranked = sorted(
        groups,
        key=lambda group: hashlib.sha256(f"{dataset_id}\0{group}".encode()).hexdigest(),
    )
    holdout_count = max(1, min(len(groups) - 1, math.ceil(len(groups) * fraction)))
    holdout = tuple(sorted(ranked[:holdout_count]))
    calibration = tuple(sorted(set(groups) - set(holdout)))
    return calibration, holdout


@dataclass(frozen=True)
class ModelSpec:
    ions: tuple[str, ...]
    ion_scales_mmol_kgw: Mapping[str, float]
    cec_scale_mmolc_kg: float
    ridge_lambda: float = 1.0e-8

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ModelSpec":
        if not isinstance(value, Mapping):
            raise ScientificValidationError("model specification must be an object")
        _keys(value, {"schema", "ions", "ion_scales_mmol_kgw", "cec_scale_mmolc_kg", "ridge_lambda"}, "model")
        if value.get("schema") != MODEL_SCHEMA:
            raise ScientificValidationError("unsupported calibration model schema")
        ions = _string_tuple(value.get("ions"), "model.ions")
        if any(ion not in COMPETITOR_IONS for ion in ions):
            raise ScientificValidationError("model.ions contains an unsupported competitor")
        scales = value.get("ion_scales_mmol_kgw")
        if not isinstance(scales, Mapping) or set(scales) != set(ions):
            raise ScientificValidationError("ion scales must exactly match model.ions")
        parsed_scales = {
            ion: _positive(scales[ion], f"model.ion_scales_mmol_kgw.{ion}")
            for ion in ions
        }
        return cls(
            ions=ions,
            ion_scales_mmol_kgw=parsed_scales,
            cec_scale_mmolc_kg=_positive(value.get("cec_scale_mmolc_kg"), "model.cec_scale_mmolc_kg"),
            ridge_lambda=_number(value.get("ridge_lambda", 1.0e-8), "model.ridge_lambda", minimum=0.0),
        )

    @property
    def feature_names(self) -> tuple[str, ...]:
        return ("intercept",) + tuple(f"log1p_{ion}" for ion in self.ions) + ("log_cec",)

    def feature_vector(self, observation: Observation) -> tuple[float, ...]:
        values = [1.0]
        for ion in self.ions:
            values.append(math.log1p(
                observation.competitors_mmol_kgw[ion] / self.ion_scales_mmol_kgw[ion]
            ))
        values.append(math.log(observation.cec_mmolc_kg / self.cec_scale_mmolc_kg))
        if not all(math.isfinite(value) for value in values):
            raise ScientificValidationError("model feature vector is non-finite")
        return tuple(values)

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": MODEL_SCHEMA,
            "ions": list(self.ions),
            "ion_scales_mmol_kgw": dict(self.ion_scales_mmol_kgw),
            "cec_scale_mmolc_kg": self.cec_scale_mmolc_kg,
            "ridge_lambda": self.ridge_lambda,
        }


def _solve_linear_system(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    size = len(rhs)
    augmented = [row[:] + [rhs[index]] for index, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= 1.0e-12:
            raise ScientificValidationError("calibration design matrix is rank deficient")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor:
                augmented[row] = [
                    left - factor * right
                    for left, right in zip(augmented[row], augmented[column])
                ]
    result = [augmented[index][-1] for index in range(size)]
    if not all(math.isfinite(value) for value in result):
        raise ScientificValidationError("calibration coefficients are non-finite")
    return result


@dataclass(frozen=True)
class CalibrationModel:
    spec: ModelSpec
    coefficients: tuple[float, ...]
    calibration_observation_count: int
    calibration_group_ids: tuple[str, ...]

    def predict_log10_kd(self, observation: Observation) -> float:
        features = self.spec.feature_vector(observation)
        prediction = sum(coefficient * feature for coefficient, feature in zip(self.coefficients, features))
        if not math.isfinite(prediction):
            raise ScientificValidationError("predicted log10(Kd) is non-finite")
        return prediction

    def predict_kd(self, observation: Observation) -> float:
        try:
            value = 10.0 ** self.predict_log10_kd(observation)
        except OverflowError as exc:
            raise ScientificValidationError("predicted Kd overflows") from exc
        if not math.isfinite(value) or value <= 0.0:
            raise ScientificValidationError("predicted Kd is not positive and finite")
        return value

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": "nuclidepath-cs-exchange-calibration-model-1",
            "model_spec": self.spec.to_payload(),
            "feature_names": list(self.spec.feature_names),
            "coefficients": {
                name: value for name, value in zip(self.spec.feature_names, self.coefficients)
            },
            "calibration_observation_count": self.calibration_observation_count,
            "calibration_group_ids": list(self.calibration_group_ids),
        }


def fit_calibration_model(dataset: ObservationDataset, spec: ModelSpec) -> CalibrationModel:
    observations = dataset.calibration_observations()
    feature_count = len(spec.feature_names)
    if len(observations) <= feature_count:
        raise ScientificValidationError(
            f"calibration split needs more than {feature_count} observations"
        )
    matrix = [[0.0 for _ in range(feature_count)] for _ in range(feature_count)]
    rhs = [0.0 for _ in range(feature_count)]
    for observation in observations:
        features = spec.feature_vector(observation)
        target = math.log10(observation.kd_m3_kg)
        for row in range(feature_count):
            rhs[row] += features[row] * target
            for column in range(feature_count):
                matrix[row][column] += features[row] * features[column]
    for index in range(1, feature_count):
        matrix[index][index] += spec.ridge_lambda
    coefficients = _solve_linear_system(matrix, rhs)
    return CalibrationModel(
        spec=spec,
        coefficients=tuple(coefficients),
        calibration_observation_count=len(observations),
        calibration_group_ids=dataset.calibration_group_ids,
    )


def _metrics(model: CalibrationModel, observations: Sequence[Observation]) -> dict[str, Any]:
    if not observations:
        raise ScientificValidationError("cannot evaluate an empty observation split")
    errors: list[float] = []
    relative_errors: list[float] = []
    grouped: dict[str, list[float]] = defaultdict(list)
    for observation in observations:
        predicted_log = model.predict_log10_kd(observation)
        observed_log = math.log10(observation.kd_m3_kg)
        error = abs(predicted_log - observed_log)
        predicted = model.predict_kd(observation)
        relative = abs(predicted - observation.kd_m3_kg) / observation.kd_m3_kg
        errors.append(error)
        relative_errors.append(relative)
        grouped[observation.group_id].append(error)
    rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
    group_rmse = {
        group: math.sqrt(sum(error * error for error in values) / len(values))
        for group, values in sorted(grouped.items())
    }
    result = {
        "count": len(observations),
        "group_count": len(grouped),
        "rmse_log10": rmse,
        "mae_log10": statistics.fmean(errors),
        "max_abs_log10": max(errors),
        "median_relative_error": statistics.median(relative_errors),
        "max_relative_error": max(relative_errors),
        "group_rmse_log10": group_rmse,
    }
    if not all(math.isfinite(float(value)) for key, value in result.items() if key != "group_rmse_log10"):
        raise ScientificValidationError("validation metrics are non-finite")
    return result


@dataclass(frozen=True)
class AcceptancePolicy:
    min_holdout_observations: int = 2
    min_holdout_groups: int = 1
    max_rmse_log10: float = 0.25
    max_max_relative_error: float = 1.0
    max_group_rmse_log10: float | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "AcceptancePolicy":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise ScientificValidationError("acceptance policy must be an object")
        _keys(value, {
            "min_holdout_observations", "min_holdout_groups", "max_rmse_log10",
            "max_max_relative_error", "max_group_rmse_log10",
        }, "acceptance")
        min_observations = _number(value.get("min_holdout_observations", 2), "acceptance.min_holdout_observations", minimum=1.0)
        min_groups = _number(value.get("min_holdout_groups", 1), "acceptance.min_holdout_groups", minimum=1.0)
        if not min_observations.is_integer() or not min_groups.is_integer():
            raise ScientificValidationError("minimum hold-out counts must be integers")
        optional_group = value.get("max_group_rmse_log10")
        return cls(
            min_holdout_observations=int(min_observations),
            min_holdout_groups=int(min_groups),
            max_rmse_log10=_number(value.get("max_rmse_log10", 0.25), "acceptance.max_rmse_log10", minimum=0.0),
            max_max_relative_error=_number(value.get("max_max_relative_error", 1.0), "acceptance.max_max_relative_error", minimum=0.0),
            max_group_rmse_log10=None if optional_group is None else _number(optional_group, "acceptance.max_group_rmse_log10", minimum=0.0),
        )

    def evaluate(self, holdout_metrics: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
        failures: list[str] = []
        if holdout_metrics["count"] < self.min_holdout_observations:
            failures.append("hold-out observation count below policy")
        if holdout_metrics["group_count"] < self.min_holdout_groups:
            failures.append("hold-out group count below policy")
        if holdout_metrics["rmse_log10"] > self.max_rmse_log10:
            failures.append("hold-out RMSE exceeds policy")
        if holdout_metrics["max_relative_error"] > self.max_max_relative_error:
            failures.append("hold-out maximum relative error exceeds policy")
        if self.max_group_rmse_log10 is not None and any(
            value > self.max_group_rmse_log10
            for value in holdout_metrics["group_rmse_log10"].values()
        ):
            failures.append("hold-out group RMSE exceeds policy")
        return not failures, tuple(failures)

    def to_payload(self) -> dict[str, Any]:
        return {
            "min_holdout_observations": self.min_holdout_observations,
            "min_holdout_groups": self.min_holdout_groups,
            "max_rmse_log10": self.max_rmse_log10,
            "max_max_relative_error": self.max_max_relative_error,
            "max_group_rmse_log10": self.max_group_rmse_log10,
        }


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_validation_report(
    dataset: ObservationDataset,
    spec: ModelSpec,
    *,
    acceptance: AcceptancePolicy | None = None,
) -> dict[str, Any]:
    policy = acceptance or AcceptancePolicy()
    model = fit_calibration_model(dataset, spec)
    calibration_metrics = _metrics(model, dataset.calibration_observations())
    holdout_metrics = _metrics(model, dataset.holdout_observations())
    holdout_passed, policy_failures = policy.evaluate(holdout_metrics)
    data_eligible = dataset.data_status == "measured_traceable"
    reasons = list(policy_failures)
    if not data_eligible:
        reasons.append("synthetic or unverified data cannot promote a scientific model")
    promotion_granted = data_eligible and holdout_passed
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "dataset": {
            "dataset_id": dataset.dataset_id,
            "data_status": dataset.data_status,
            "provenance": dict(dataset.provenance),
            "observation_count": len(dataset.observations),
            "calibration_group_ids": list(dataset.calibration_group_ids),
            "holdout_group_ids": list(dataset.holdout_group_ids),
        },
        "model": model.to_payload(),
        "acceptance": policy.to_payload(),
        "metrics": {
            "calibration": calibration_metrics,
            "holdout": holdout_metrics,
        },
        "holdout_passed": holdout_passed,
        "promotion": {
            "granted": promotion_granted,
            "evidence_level": "EXPERIMENTALLY_VALIDATED" if promotion_granted else "NOT_PROMOTED",
            "scope": "empirical multi-cation apparent-Kd calibration only",
            "reasons": reasons,
        },
    }
    report["report_sha256"] = _canonical_hash(report)
    return report


def require_experimental_validation(report: Mapping[str, Any]) -> None:
    promotion = report.get("promotion")
    if not isinstance(promotion, Mapping) or promotion.get("granted") is not True:
        reasons = promotion.get("reasons", ()) if isinstance(promotion, Mapping) else ("missing promotion record",)
        raise ScientificValidationGateError(
            "experimental validation gate is closed: " + "; ".join(str(reason) for reason in reasons)
        )


def verify_validation_report(report: Mapping[str, Any]) -> None:
    """Verify the report's canonical digest before it is consumed downstream."""

    if not isinstance(report, Mapping) or report.get("schema") != REPORT_SCHEMA:
        raise ScientificValidationError("unsupported validation report schema")
    expected = report.get("report_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ScientificValidationError("validation report digest is missing")
    payload = dict(report)
    payload.pop("report_sha256", None)
    actual = _canonical_hash(payload)
    if not hmac.compare_digest(expected, actual):
        raise ScientificValidationError("validation report digest mismatch")


def load_json_dataset(path: str) -> ObservationDataset:
    with open(path, "r", encoding="utf-8") as handle:
        value = json.load(handle)
    return ObservationDataset.from_mapping(value)
