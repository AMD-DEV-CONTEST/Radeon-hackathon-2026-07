"""Seeded screening at virtual locations on one declared 1-D flow path."""

from __future__ import annotations

import math
import random
from typing import Any, Mapping, Sequence

from .analysis import ParameterRange
from .contracts import ScenarioInput
from .transport import simulate_transport


def _quantiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    def q(probability: float) -> float:
        position = probability * (len(ordered) - 1)
        low, high = math.floor(position), math.ceil(position)
        if low == high:
            return ordered[low]
        weight = position - low
        return ordered[low] * (1 - weight) + ordered[high] * weight
    return {"p05": q(0.05), "p50": q(0.5), "p95": q(0.95)}


def screen_virtual_receptors(
    payload: Mapping[str, Any],
    receptors: Sequence[Mapping[str, Any]],
    ranges: Mapping[str, ParameterRange],
    samples: int = 512,
    seed: int = 42,
) -> dict[str, Any]:
    """Propagate declared ranges to receptor summaries without regulatory interpretation."""
    if isinstance(samples, bool) or not isinstance(samples, int):
        raise ValueError("samples must be an integer")
    if samples < 20:
        raise ValueError("virtual receptor screening requires at least 20 samples")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    baseline = ScenarioInput.from_dict(payload).to_dict()
    normalized: list[tuple[str, float]] = []
    seen: set[str] = set()
    for receptor in receptors:
        receptor_id = receptor.get("receptor_id")
        if not isinstance(receptor_id, str) or not receptor_id.strip():
            raise ValueError("receptor_id must be a non-empty string")
        if receptor_id in seen:
            raise ValueError(f"duplicate receptor_id: {receptor_id}")
        seen.add(receptor_id)
        distance = float(receptor.get("distance_m", -1))
        if not math.isfinite(distance) or distance < 0:
            raise ValueError("receptor distance_m must be finite and >= 0")
        normalized.append((receptor_id, distance))
    if not normalized:
        raise ValueError("at least one receptor is required")

    generator = random.Random(seed)
    collected = {rid: {"arrival": [], "sampled_max": [], "final": []} for rid, _ in normalized}
    for _ in range(samples):
        sampled = dict(baseline)
        for name, parameter_range in ranges.items():
            sampled[name] = parameter_range.sample(generator)
        scenario = ScenarioInput.from_dict(sampled)
        params = scenario.to_transport_parameters()
        for receptor_id, distance in normalized:
            concentrations = [
                simulate_transport(params, distance, time)["concentration_bq_m3"]
                for time in scenario.evaluation_times_s
            ]
            collected[receptor_id]["arrival"].append(
                distance * params.retardation_factor / params.groundwater_velocity_m_s
            )
            collected[receptor_id]["sampled_max"].append(max(concentrations))
            collected[receptor_id]["final"].append(concentrations[-1])

    rows = []
    for receptor_id, distance in normalized:
        values = collected[receptor_id]
        rows.append({
            "receptor_id": receptor_id,
            "distance_m": distance,
            "arrival_time_s": _quantiles(values["arrival"]),
            "sampled_max_concentration_bq_m3": _quantiles(values["sampled_max"]),
            "final_concentration_bq_m3": _quantiles(values["final"]),
        })
    drivers = sorted(
        ranges,
        key=lambda name: (
            ranges[name].high / ranges[name].low
            if ranges[name].low > 0 else ranges[name].high - ranges[name].low
        ),
        reverse=True,
    )
    return {
        "screening_version": "virtual-receptors-0.4",
        "scenario_id": baseline["scenario_id"],
        "method": "independent seeded Monte Carlo on one homogeneous 1-D path",
        "samples": samples,
        "seed": seed,
        "receptors": rows,
        "declared_range_priority": drivers,
        "declared_range_priority_basis": "descending declared input-range span; characterization priority, not output-response or causal attribution",
        "missing_site_characterization": [
            "receptor connectivity to the modelled flow path",
            "site hydraulic velocity and dispersion",
            "site sorption and competing-ion chemistry",
        ],
        "limitations": [
            "Virtual receptors are points on the same homogeneous 1-D path, not mapped wells",
            "Arrival time is advective retarded travel time, not first detection time",
            "Concentration maxima are sampled_max over declared evaluation times, not optimized peaks",
            "Intervals propagate declared inputs only and are not total predictive uncertainty",
            "Screening demonstration only; no operational, safety, dose, or regulatory interpretation",
        ],
    }
