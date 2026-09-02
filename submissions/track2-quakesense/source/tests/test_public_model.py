import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from quakesense_public.model import BlockState, Shelter, departure_cdf, egress_capacity, step_block


def test_departure_cdf_is_monotonic():
    values = [departure_cdf(t) for t in (0, 30, 60, 180, 600, 3600)]
    assert values == sorted(values)
    assert values[0] == 0.0
    assert values[-1] > 0.99


def test_egress_capacity_uses_width_and_specific_flow():
    assert egress_capacity(3.0, 30.0) == pytest.approx(117.0)


def test_step_conserves_population_and_capacity():
    state = BlockState(population=1000.0, indoors=800.0, stay_put=200.0)
    shelter = Shelter(capacity=120.0)
    for step in range(1, 31):
        step_block(
            state,
            shelter,
            time_s=step * 30.0,
            step_s=30.0,
            egress_width_m=2.5,
            participation=0.8,
        )
        assert abs(state.accounted() - 1000.0) < 1e-9
        assert shelter.occupancy <= shelter.capacity
