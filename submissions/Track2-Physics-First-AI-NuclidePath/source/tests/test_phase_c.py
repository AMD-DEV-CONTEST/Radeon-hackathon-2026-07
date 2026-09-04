import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
import pytest
from nuclear_agent.source_terms import MaintainedBoundary, FiniteDurationBoundary, InstantaneousPulse, ConstantRateRelease, PiecewiseLinearSeries
from nuclear_agent.path_network import Segment, PathNetwork

def test_maintained_boundary_matches_legacy_constant_source():
    source = MaintainedBoundary(5.0)
    assert [source.value_at(t) for t in (0, 1, 100)] == [5.0, 5.0, 5.0]
    assert source.integrated_input(2, 6) == 20.0

def test_finite_boundary_is_superposition_window():
    source = FiniteDurationBoundary(4.0, 3.0)
    assert [source.value_at(t) for t in (0, 3, 3.1)] == [4.0, 4.0, 0.0]
    assert source.integrated_input(2, 8) == 4.0

def test_pulse_preserves_mass_without_mass_to_concentration_conversion():
    pulse = InstantaneousPulse(12.0, time_s=5.0)
    assert pulse.integrated_input(0, 10) == 12.0
    assert pulse.quantity_unit == "mass_per_area"
    assert pulse.value_at(5.0) == 0.0

def test_constant_rate_mass_normalization_and_finite_duration():
    release = ConstantRateRelease(3.0, duration_s=4.0)
    assert release.integrated_input(0, 10) == 12.0
    assert release.value_at(4.0) == 3.0
    assert release.value_at(4.01) == 0.0

def test_piecewise_linear_is_continuous_and_integrates_trapezoids():
    series = PiecewiseLinearSeries((0.0, 2.0, 4.0), (0.0, 4.0, 0.0))
    assert series.value_at(1.0) == 2.0
    assert series.integrated_input(0, 4) == 8.0
    with pytest.raises(ValueError): PiecewiseLinearSeries((0, 1, 1), (0, 2, 3))

def segment(name):
    return Segment(name, 10, .3, 1700, 1e-5, 1e-5, sorption={"Cs-137": .2})

def test_network_is_immutable_acyclic_and_receptor_connected():
    a,b = segment("a"), segment("b")
    network = PathNetwork((a,b), (("a","b"),), {"well":"b"})
    assert tuple(s.segment_id for s in network.path_to_receptor("well")) == ("a", "b")
    with pytest.raises(TypeError): network.receptors["x"] = "a"
    with pytest.raises(ValueError): PathNetwork((a,b), (("a","b"),("b","a"),))

def test_network_rejects_unknown_receptor_segment():
    with pytest.raises(ValueError): PathNetwork((segment("a"),), receptors={"well":"missing"})

def test_network_rejects_empty_duplicate_edges_and_ambiguous_merges():
    a,b,c = segment("a"),segment("b"),segment("c")
    with pytest.raises(ValueError): PathNetwork(())
    with pytest.raises(ValueError): PathNetwork((a,b), (("a","b"),("a","b")))
    with pytest.raises(ValueError, match="multiple incoming"):
        PathNetwork((a,b,c), (("a","c"),("b","c")))

@pytest.mark.parametrize("factory", [
    lambda: MaintainedBoundary(1, version="wrong"),
    lambda: FiniteDurationBoundary(1, 1, quantity_unit=""),
    lambda: ConstantRateRelease(1, 1, quantity_unit=""),
])
def test_source_contract_version_and_units_fail_closed(factory):
    with pytest.raises(ValueError): factory()
