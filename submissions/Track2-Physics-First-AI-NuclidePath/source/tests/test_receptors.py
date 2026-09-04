import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from nuclear_agent.analysis import load_parameter_ranges
from nuclear_agent.receptors import screen_virtual_receptors


ENTRY = json.loads((Path(__file__).parents[1] / "scenarios/library/conservative_uncertainty_v1.json").read_text())


def test_virtual_receptor_screening_is_seeded_and_labels_sampled_max():
    ranges = load_parameter_ranges(ENTRY["uncertainty_ranges"])
    first = screen_virtual_receptors(ENTRY["transport"], ENTRY["receptors"], ranges, samples=32, seed=17)
    second = screen_virtual_receptors(ENTRY["transport"], ENTRY["receptors"], ranges, samples=32, seed=17)

    assert first == second
    assert first["screening_version"] == "virtual-receptors-0.4"
    assert [row["receptor_id"] for row in first["receptors"]] == ["path-25m", "path-100m"]
    near, far = first["receptors"]
    assert near["arrival_time_s"]["p50"] < far["arrival_time_s"]["p50"]
    assert "sampled_max_concentration_bq_m3" in near
    assert "peak_concentration_bq_m3" not in near
    assert first["declared_range_priority"]
    assert "dominant_sensitivity_drivers" not in first
    assert "sensitivity" not in json.dumps(first).lower()
    assert "not total predictive uncertainty" in " ".join(first["limitations"])
    assert "threshold" not in json.dumps(first).lower()


def test_virtual_receptors_reject_duplicate_ids():
    ranges = load_parameter_ranges(ENTRY["uncertainty_ranges"])
    duplicate = [ENTRY["receptors"][0], ENTRY["receptors"][0]]
    try:
        screen_virtual_receptors(ENTRY["transport"], duplicate, ranges, samples=20)
    except ValueError as exc:
        assert "duplicate receptor_id" in str(exc)
    else:
        raise AssertionError("duplicate receptor IDs should fail")


@pytest.mark.parametrize("samples", [True, 20.0, "20"])
def test_virtual_receptors_reject_non_integer_samples(samples):
    ranges = load_parameter_ranges(ENTRY["uncertainty_ranges"])
    with pytest.raises(ValueError, match="samples must be an integer"):
        screen_virtual_receptors(ENTRY["transport"], ENTRY["receptors"], ranges, samples=samples)


@pytest.mark.parametrize("seed", [True, 17.0, "17"])
def test_virtual_receptors_reject_non_integer_seed(seed):
    ranges = load_parameter_ranges(ENTRY["uncertainty_ranges"])
    with pytest.raises(ValueError, match="seed must be an integer"):
        screen_virtual_receptors(ENTRY["transport"], ENTRY["receptors"], ranges, samples=20, seed=seed)
