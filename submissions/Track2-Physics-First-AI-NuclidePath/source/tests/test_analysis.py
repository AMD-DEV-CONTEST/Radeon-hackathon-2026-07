import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import pytest

from nuclear_agent.analysis import ParameterRange, run_sensitivity, run_uncertainty


PAYLOAD = {
    "scenario_id": "analysis-demo",
    "initial_concentration_bq_m3": 1.0e6,
    "distance_m": 100.0,
    "evaluation_times_s": [0.0, 5.0e9, 1.0e10],
    "distribution_coefficient_m3_kg": 0.2,
    "bulk_density_kg_m3": 1700.0,
    "porosity": 0.35,
    "groundwater_velocity_m_s": 1.0e-5,
    "dispersion_m2_s": 1.0e-3,
    "potassium_mg_l": 20.0,
    "competition_coefficient_l_mg": 0.01,
    "half_life_years": 30.018,
}


def ranges():
    return {
        "distribution_coefficient_m3_kg": ParameterRange(
            low=0.2,
            high=5.0,
            distribution="log_uniform",
            classification="literature-range",
            source="PNNL-16531",
        ),
        "groundwater_velocity_m_s": ParameterRange(
            low=1.0e-6,
            high=1.0e-4,
            distribution="log_uniform",
            classification="demonstration-range",
            source="Demonstration bracket; site measurement required",
        ),
        "potassium_mg_l": ParameterRange(
            low=0.0,
            high=40.0,
            distribution="uniform",
            classification="demonstration-range",
            source="Sensitivity scenario",
        ),
    }


def test_parameter_range_requires_provenance_and_valid_bounds():
    with pytest.raises(ValueError, match="source"):
        ParameterRange(0.0, 1.0, "uniform", "demonstration-range", "")
    with pytest.raises(ValueError, match="low"):
        ParameterRange(2.0, 1.0, "uniform", "demonstration-range", "source")


def test_sensitivity_preserves_provenance_and_expected_monotonicity():
    result = run_sensitivity(PAYLOAD, ranges())

    assert set(result["parameters"]) == set(ranges())
    kd = result["parameters"]["distribution_coefficient_m3_kg"]
    velocity = result["parameters"]["groundwater_velocity_m_s"]
    assert kd["high"]["travel_time_s"] > kd["low"]["travel_time_s"]
    assert velocity["high"]["travel_time_s"] < velocity["low"]["travel_time_s"]
    assert kd["range"]["source"] == "PNNL-16531"


def test_uncertainty_is_seeded_reproducible_and_has_ordered_quantiles():
    first = run_uncertainty(PAYLOAD, ranges(), samples=128, seed=42)
    second = run_uncertainty(PAYLOAD, ranges(), samples=128, seed=42)

    assert first == second
    assert first["samples"] == 128
    assert first["seed"] == 42
    for summary in first["metrics"].values():
        assert summary["p05"] <= summary["p50"] <= summary["p95"]
        assert summary["min"] <= summary["p05"]
        assert summary["p95"] <= summary["max"]
    assert first["parameter_ranges"]["potassium_mg_l"]["classification"] == "demonstration-range"
