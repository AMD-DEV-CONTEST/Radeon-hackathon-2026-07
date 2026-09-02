"""Tests for greedy shelter site-selection search."""

from __future__ import annotations

import pytest

from geo.urban_blocks import build_blocks, build_road_graph, extract_faces, prune_dangling
from simulator.block_scale import BlockScaleConfig, ShelterSite, build_block_layer
from simulator.site_selection import greedy_shelter_siting


def _grid_roads(n: int = 4, spacing: float = 0.002,
                lon0: float = 104.0, lat0: float = 30.6) -> list[dict]:
    features = []
    for i in range(n):
        row = [[lon0 + j * spacing, lat0 + i * spacing] for j in range(n)]
        col = [[lon0 + i * spacing, lat0 + j * spacing] for j in range(n)]
        features.append({"type": "Feature", "properties": {"highway": "residential"},
                         "geometry": {"type": "LineString", "coordinates": row}})
        features.append({"type": "Feature", "properties": {"highway": "residential"},
                         "geometry": {"type": "LineString", "coordinates": col}})
    return features


@pytest.fixture
def far_corner_layer():
    """3x3 blocks; only block 0 is within reach of the sole base shelter, so
    the far corner is genuinely unserved -- the scenario greedy siting is
    meant to fix.
    """
    graph = build_road_graph(_grid_roads(n=4))
    prune_dangling(graph)
    blocks = build_blocks(graph, extract_faces(graph), min_area_m2=1.0, max_area_m2=1e9)
    for block in blocks:
        block.population = 1000.0
    return build_block_layer(blocks), blocks


def _config():
    return BlockScaleConfig(duration_minutes=60, step_seconds=30,
                            max_shelter_distance_m=250.0,  # tight: only immediate neighbours reachable
                            mmi_evacuation_threshold=0.0, seed=1)


def test_greedy_picks_the_candidate_that_actually_helps(far_corner_layer):
    layer, blocks = far_corner_layer
    base = [ShelterSite("S0", "base", float(layer.lon[0]), float(layer.lat[0]), capacity=1e9)]
    useful = ShelterSite("CAND_FAR", "far corner", float(layer.lon[-1]), float(layer.lat[-1]), capacity=1e9)
    redundant = ShelterSite("CAND_SAME", "same spot as base", float(layer.lon[0]), float(layer.lat[0]), capacity=1e9)

    result = greedy_shelter_siting(layer, base, [redundant, useful], _config(), k=2)

    assert result.final_unserved_population < result.baseline_unserved_population
    assert [s.shelter_id for s in result.chosen] == ["CAND_FAR"]
    assert len(result.steps) == 1
    assert result.steps[0].marginal_gain > 0


def test_greedy_stops_early_when_no_candidate_helps(far_corner_layer):
    layer, blocks = far_corner_layer
    base = [ShelterSite("S0", "base", float(layer.lon[0]), float(layer.lat[0]), capacity=1e9)]
    redundant = ShelterSite("CAND_SAME", "same spot as base", float(layer.lon[0]), float(layer.lat[0]), capacity=1e9)

    result = greedy_shelter_siting(layer, base, [redundant], _config(), k=3)

    assert result.chosen == []
    assert result.final_unserved_population == pytest.approx(result.baseline_unserved_population)


def test_greedy_rejects_target_population_layers(far_corner_layer):
    layer, _ = far_corner_layer
    base = [ShelterSite("S0", "base", float(layer.lon[0]), float(layer.lat[0]), capacity=1e9)]
    bad_config = BlockScaleConfig(target_population=500)
    with pytest.raises(ValueError):
        greedy_shelter_siting(layer, base, [], bad_config, k=1)


def test_greedy_result_serialises_to_dict(far_corner_layer):
    layer, _ = far_corner_layer
    base = [ShelterSite("S0", "base", float(layer.lon[0]), float(layer.lat[0]), capacity=1e9)]
    useful = ShelterSite("CAND_FAR", "far corner", float(layer.lon[-1]), float(layer.lat[-1]), capacity=1e9)
    result = greedy_shelter_siting(layer, base, [useful], _config(), k=1)
    payload = result.to_dict()
    assert payload["chosen"][0]["shelter_id"] == "CAND_FAR"
    assert "greedy" in payload["method"]
    assert payload["total_reduction"] > 0
