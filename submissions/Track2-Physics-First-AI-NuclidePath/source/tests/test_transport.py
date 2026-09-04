import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from nuclear_agent.transport import TransportParameters, simulate_transport


def base_params(**overrides):
    values = dict(
        initial_concentration_bq_m3=1.0e6,
        distribution_coefficient_m3_kg=0.2,
    )
    values.update(overrides)
    return TransportParameters(**values)


def test_potassium_competition_reduces_effective_kd_and_retardation():
    no_potassium = base_params(potassium_mg_l=0)
    potassium = base_params(potassium_mg_l=100)

    assert potassium.effective_distribution_coefficient_m3_kg < no_potassium.effective_distribution_coefficient_m3_kg
    assert potassium.retardation_factor < no_potassium.retardation_factor


def test_zero_distance_zero_time_preserves_source_concentration():
    result = simulate_transport(base_params(), distance_m=0, time_s=0)
    assert result["concentration_bq_m3"] == 1.0e6
    assert result["travel_time_s"] == 0.0


def test_prearrival_concentration_is_nonnegative_and_below_later_breakthrough():
    params = base_params(groundwater_velocity_m_s=1.0e-4, dispersion_m2_s=1.0e-3)
    distance = 1.0
    travel = simulate_transport(params, distance, 0)["travel_time_s"]
    prearrival = simulate_transport(params, distance, 0.1 * travel)
    later = simulate_transport(params, distance, 2.0 * travel)

    assert 0.0 <= prearrival["concentration_bq_m3"] < later["concentration_bq_m3"]


def test_constant_source_breakthrough_is_monotone_and_bounded():
    params = base_params(groundwater_velocity_m_s=1.0e-4, dispersion_m2_s=1.0e-2)
    distance = 1.0
    travel = simulate_transport(params, distance, 0)["travel_time_s"]
    concentrations = [
        simulate_transport(params, distance, factor * travel)["concentration_bq_m3"]
        for factor in (0.1, 0.5, 1.0, 2.0, 10.0)
    ]

    assert concentrations == sorted(concentrations)
    assert concentrations[-1] <= params.initial_concentration_bq_m3
    assert all(math.isfinite(value) for value in concentrations)
