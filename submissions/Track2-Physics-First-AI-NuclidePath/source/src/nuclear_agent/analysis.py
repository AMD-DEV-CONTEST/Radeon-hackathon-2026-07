"""Deterministic sensitivity and seeded uncertainty analysis."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Any, Mapping

from .contracts import ScenarioInput
from .transport import simulate_transport


_ALLOWED_PARAMETERS = frozenset(
    {
        "distribution_coefficient_m3_kg",
        "bulk_density_kg_m3",
        "porosity",
        "groundwater_velocity_m_s",
        "dispersion_m2_s",
        "potassium_mg_l",
        "competition_coefficient_l_mg",
        "half_life_years",
    }
)
_DISTRIBUTIONS = frozenset({"uniform", "log_uniform", "triangular"})
_CLASSIFICATIONS = frozenset(
    {"site-measured-range", "literature-range", "demonstration-range"}
)


@dataclass(frozen=True)
class ParameterRange:
    low: float
    high: float
    distribution: str
    classification: str
    source: str

    def __post_init__(self) -> None:
        if not math.isfinite(self.low) or not math.isfinite(self.high):
            raise ValueError("range bounds must be finite")
        if self.low > self.high:
            raise ValueError("range low must be <= high")
        if self.distribution not in _DISTRIBUTIONS:
            raise ValueError(f"unsupported distribution: {self.distribution}")
        if self.distribution == "log_uniform" and self.low <= 0:
            raise ValueError("log_uniform range low must be > 0")
        if self.classification not in _CLASSIFICATIONS:
            raise ValueError(f"unsupported classification: {self.classification}")
        if not self.source.strip():
            raise ValueError("range source must not be empty")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ParameterRange":
        required = {"low", "high", "distribution", "classification", "source"}
        missing = required - set(payload)
        if missing:
            raise ValueError(f"missing range field: {sorted(missing)[0]}")
        unknown = set(payload) - required
        if unknown:
            raise ValueError(f"unknown range field: {sorted(unknown)[0]}")
        return cls(
            low=float(payload["low"]),
            high=float(payload["high"]),
            distribution=str(payload["distribution"]),
            classification=str(payload["classification"]),
            source=str(payload["source"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "low": self.low,
            "high": self.high,
            "distribution": self.distribution,
            "classification": self.classification,
            "source": self.source,
        }

    def sample(self, generator: random.Random) -> float:
        if self.low == self.high:
            return self.low
        if self.distribution == "uniform":
            return generator.uniform(self.low, self.high)
        if self.distribution == "triangular":
            return generator.triangular(self.low, self.high, (self.low + self.high) / 2)
        log_low, log_high = math.log(self.low), math.log(self.high)
        return math.exp(generator.uniform(log_low, log_high))


def load_parameter_ranges(payload: Mapping[str, Any]) -> dict[str, ParameterRange]:
    ranges: dict[str, ParameterRange] = {}
    for name, value in payload.items():
        if name not in _ALLOWED_PARAMETERS:
            raise ValueError(f"unsupported uncertainty parameter: {name}")
        if not isinstance(value, Mapping):
            raise ValueError(f"range for {name} must be an object")
        ranges[name] = ParameterRange.from_dict(value)
    if not ranges:
        raise ValueError("at least one parameter range is required")
    return ranges


def _validate_ranges(ranges: Mapping[str, ParameterRange]) -> None:
    if not ranges:
        raise ValueError("at least one parameter range is required")
    unknown = set(ranges) - _ALLOWED_PARAMETERS
    if unknown:
        raise ValueError(f"unsupported uncertainty parameter: {sorted(unknown)[0]}")


def _summary(payload: Mapping[str, Any]) -> dict[str, float]:
    scenario = ScenarioInput.from_dict(payload)
    params = scenario.to_transport_parameters()
    points = [
        {"time_s": time_s, **simulate_transport(params, scenario.distance_m, time_s)}
        for time_s in scenario.evaluation_times_s
    ]
    peak = max(points, key=lambda point: point["concentration_bq_m3"])
    final = points[-1]
    return {
        "effective_kd_m3_kg": params.effective_distribution_coefficient_m3_kg,
        "retardation_factor": params.retardation_factor,
        "travel_time_s": final["travel_time_s"],
        "sampled_max_concentration_bq_m3": peak["concentration_bq_m3"],
        "final_concentration_bq_m3": final["concentration_bq_m3"],
    }


def run_sensitivity(
    payload: Mapping[str, Any], ranges: Mapping[str, ParameterRange]
) -> dict[str, Any]:
    """Run deterministic low/baseline/high one-at-a-time sensitivity cases."""
    baseline = ScenarioInput.from_dict(payload).to_dict()
    _validate_ranges(ranges)
    parameters: dict[str, Any] = {}
    for name, parameter_range in ranges.items():
        low_payload = dict(baseline)
        high_payload = dict(baseline)
        low_payload[name] = parameter_range.low
        high_payload[name] = parameter_range.high
        parameters[name] = {
            "range": parameter_range.to_dict(),
            "baseline_value": baseline[name],
            "low": _summary(low_payload),
            "baseline": _summary(baseline),
            "high": _summary(high_payload),
        }
    return {
        "analysis_version": "sensitivity-0.2",
        "scenario_id": baseline["scenario_id"],
        "method": "one-at-a-time low/baseline/high",
        "parameters": parameters,
        "warning": "Screening sensitivity only; parameter correlations are not represented",
    }


def _quantile(sorted_values: list[float], probability: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = probability * (len(sorted_values) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def run_uncertainty(
    payload: Mapping[str, Any],
    ranges: Mapping[str, ParameterRange],
    samples: int = 512,
    seed: int = 42,
) -> dict[str, Any]:
    """Propagate declared independent ranges with reproducible Monte Carlo."""
    baseline = ScenarioInput.from_dict(payload).to_dict()
    _validate_ranges(ranges)
    if samples < 20:
        raise ValueError("uncertainty analysis requires at least 20 samples")
    generator = random.Random(seed)
    collected: dict[str, list[float]] = {}
    for _ in range(samples):
        sampled_payload = dict(baseline)
        for name, parameter_range in ranges.items():
            sampled_payload[name] = parameter_range.sample(generator)
        summary = _summary(sampled_payload)
        for metric, value in summary.items():
            collected.setdefault(metric, []).append(value)

    metrics = {}
    for metric, values in collected.items():
        ordered = sorted(values)
        metrics[metric] = {
            "min": ordered[0],
            "p05": _quantile(ordered, 0.05),
            "p50": _quantile(ordered, 0.50),
            "p95": _quantile(ordered, 0.95),
            "max": ordered[-1],
        }
    return {
        "analysis_version": "uncertainty-0.2",
        "scenario_id": baseline["scenario_id"],
        "method": "independent seeded Monte Carlo",
        "samples": samples,
        "seed": seed,
        "parameter_ranges": {
            name: parameter_range.to_dict()
            for name, parameter_range in ranges.items()
        },
        "metrics": metrics,
        "assumptions": [
            "Declared parameter distributions are sampled independently",
            "Ranges classified as demonstration are not site-calibrated",
            "Quantiles describe model-input uncertainty, not total predictive uncertainty",
        ],
    }


def run_morris(payload: Mapping[str, Any], ranges: Mapping[str, ParameterRange], *, trajectories: int = 8, levels: int = 4, seed: int = 42) -> dict[str, Any]:
    """Deterministic Morris elementary effects on final concentration.

    Outputs raw effects plus mean absolute (mu_star) and mean signed (mu) effects;
    these are screening sensitivities, not importance probabilities.
    """
    if (isinstance(trajectories,bool) or not isinstance(trajectories,int) or trajectories < 1
            or isinstance(levels,bool) or not isinstance(levels,int) or levels < 2
            or isinstance(seed,bool) or not isinstance(seed,int)):
        raise ValueError("integer trajectories >= 1, levels >= 2 and seed required")
    baseline = ScenarioInput.from_dict(payload).to_dict(); _validate_ranges(ranges)
    names = tuple(ranges)
    rng = random.Random(seed); effects = {n: [] for n in names}
    for _ in range(trajectories):
        point = dict(baseline)
        for n, r in ranges.items(): point[n] = r.low + (r.high-r.low) * rng.randrange(levels)/(levels-1)
        order = list(names); rng.shuffle(order)
        y0 = _summary(point)["final_concentration_bq_m3"]
        for n in order:
            r = ranges[n]; span = r.high-r.low
            if span == 0: continue
            direction = 1 if point[n] < r.high else -1
            nxt = dict(point); nxt[n] = point[n] + direction*span/(levels-1)
            y1 = _summary(nxt)["final_concentration_bq_m3"]
            effects[n].append((y1-y0)/(direction*span/(levels-1)))
            point, y0 = nxt, y1
    summary = {n: {"mu": sum(v)/len(v), "mu_star": sum(abs(x) for x in v)/len(v), "sigma": (sum((x-sum(v)/len(v))**2 for x in v)/len(v))**0.5, "effects": v} for n,v in effects.items() if v}
    return {"analysis_version":"morris-0.1", "scenario_id":baseline["scenario_id"], "method":"Morris elementary effects", "trajectories":trajectories, "levels":levels, "seed":seed, "parameters":summary, "warning":"Elementary effects distinguish local screening sensitivity from input-range span; no causal attribution or interaction decomposition is claimed."}
