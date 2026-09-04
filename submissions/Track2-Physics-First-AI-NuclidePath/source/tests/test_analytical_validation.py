import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import pytest

from nuclear_agent.transport import TransportParameters, simulate_transport


SECONDS_PER_YEAR = 365.25 * 24 * 3600


def params(**overrides):
    values = {
        "initial_concentration_bq_m3": 1.0e6,
        "distribution_coefficient_m3_kg": 0.2,
        "bulk_density_kg_m3": 1700.0,
        "porosity": 0.35,
        "groundwater_velocity_m_s": 1.0e-5,
        "dispersion_m2_s": 1.0e-3,
        "half_life_years": 30.018,
    }
    values.update(overrides)
    return TransportParameters(**values)


def test_retardation_and_travel_time_match_independent_closed_form():
    p = params(potassium_mg_l=20.0, competition_coefficient_l_mg=0.01)
    expected_kd = 0.2 / (1.0 + 0.01 * 20.0)
    expected_r = 1.0 + 1700.0 * expected_kd / 0.35
    result = simulate_transport(p, distance_m=100.0, time_s=1.0)

    assert p.effective_distribution_coefficient_m3_kg == pytest.approx(expected_kd)
    assert p.retardation_factor == pytest.approx(expected_r)
    assert result["travel_time_s"] == pytest.approx(100.0 * expected_r / 1.0e-5)


def test_nonreactive_solution_matches_independent_ogata_banks_oracle():
    p = params(
        distribution_coefficient_m3_kg=0.0,
        half_life_years=1.0e30,
        dispersion_m2_s=1.0e-4,
    )
    distance = 5.0
    elapsed = 1.0e6
    v = p.groundwater_velocity_m_s
    d = p.dispersion_m2_s
    expected_fraction = 0.5 * (
        math.erfc((distance - v * elapsed) / (2.0 * math.sqrt(d * elapsed)))
        + math.exp(v * distance / d)
        * math.erfc((distance + v * elapsed) / (2.0 * math.sqrt(d * elapsed)))
    )

    result = simulate_transport(p, distance, elapsed)

    assert result["concentration_bq_m3"] == pytest.approx(
        p.initial_concentration_bq_m3 * expected_fraction, rel=1e-12
    )


def test_constant_source_boundary_is_exact_even_with_decay():
    p = params()
    elapsed = p.half_life_years * SECONDS_PER_YEAR

    result = simulate_transport(p, distance_m=0.0, time_s=elapsed)

    assert result["concentration_bq_m3"] == pytest.approx(
        p.initial_concentration_bq_m3, rel=1e-12
    )
    assert result["decay_factor"] == pytest.approx(0.5, rel=1e-12)


def test_reactive_solution_approaches_independent_steady_state_limit():
    p = params(distribution_coefficient_m3_kg=0.0, dispersion_m2_s=1.0e-4)
    distance = 1.0
    elapsed = 1.0e13
    velocity = p.groundwater_velocity_m_s
    decay_velocity = math.sqrt(
        velocity**2
        + 4.0 * p.decay_constant_s * p.retardation_factor * p.dispersion_m2_s
    )
    expected = p.initial_concentration_bq_m3 * math.exp(
        (velocity - decay_velocity) * distance / (2.0 * p.dispersion_m2_s)
    )

    result = simulate_transport(p, distance, elapsed)

    assert result["concentration_bq_m3"] == pytest.approx(expected, rel=1e-10)


def test_physical_parameters_reject_non_finite_values():
    with pytest.raises(ValueError, match="finite"):
        params(porosity=float("nan"))
    with pytest.raises(ValueError, match="finite"):
        params(dispersion_m2_s=float("inf"))
