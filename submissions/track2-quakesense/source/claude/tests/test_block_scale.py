"""Tests for road-enclosed block extraction and the block-scale simulator.

These use a hand-built 3x3 street grid so the expected answers are known by
inspection: a 3x3 lattice of streets encloses exactly 4 square blocks.
"""

from __future__ import annotations

import json
import math

import pytest

from geo.urban_blocks import (
    blocks_from_geojson,
    build_blocks,
    build_road_graph,
    disaggregate_population,
    extract_faces,
    point_in_ring,
    prune_dangling,
    ring_metrics,
)
from simulator.block_scale import (
    BlockEvacuationSimulator,
    BlockScaleConfig,
    ShelterSite,
    build_block_layer,
    build_routing_tree,
    load_shelters_geojson,
)


# ── fixtures ────────────────────────────────────────────────────────────────

def _grid_roads(n: int = 3, spacing: float = 0.002,
                lon0: float = 104.0, lat0: float = 30.6) -> list[dict]:
    """A square lattice of streets: n x n nodes => (n-1)^2 enclosed blocks."""
    features = []
    for i in range(n):
        row = [[lon0 + j * spacing, lat0 + i * spacing] for j in range(n)]
        col = [[lon0 + i * spacing, lat0 + j * spacing] for j in range(n)]
        features.append({"type": "Feature",
                         "properties": {"highway": "residential"},
                         "geometry": {"type": "LineString", "coordinates": row}})
        features.append({"type": "Feature",
                         "properties": {"highway": "residential"},
                         "geometry": {"type": "LineString", "coordinates": col}})
    return features


@pytest.fixture
def grid_blocks():
    features = _grid_roads(n=4)
    graph = build_road_graph(features)
    prune_dangling(graph)
    faces = extract_faces(graph)
    return build_blocks(graph, faces, min_area_m2=1.0, max_area_m2=1e9), graph


# ── geometry ────────────────────────────────────────────────────────────────

def test_ring_metrics_orientation_and_area():
    # 100 m x 100 m square, counter-clockwise.
    d_lat = 100.0 / 110_540.0
    d_lon = 100.0 / (111_320.0 * math.cos(math.radians(30.6)))
    ring = [(104.0, 30.6), (104.0 + d_lon, 30.6),
            (104.0 + d_lon, 30.6 + d_lat), (104.0, 30.6 + d_lat)]
    area, lon, lat, perimeter = ring_metrics(ring)
    assert area == pytest.approx(10_000.0, rel=1e-3)
    assert perimeter == pytest.approx(400.0, rel=1e-3)
    # The projection origin is the ring's mean latitude rather than its
    # centroid, which leaves a sub-metre offset on a 100 m square.
    assert lon == pytest.approx(104.0 + d_lon / 2, abs=1e-5)
    assert lat == pytest.approx(30.6 + d_lat / 2, abs=1e-5)

    # Reversing the ring flips the sign, which is how outer faces are detected.
    assert ring_metrics(list(reversed(ring)))[0] == pytest.approx(-10_000.0, rel=1e-3)


def test_point_in_ring():
    ring = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    assert point_in_ring(0.5, 0.5, ring)
    assert not point_in_ring(1.5, 0.5, ring)
    assert not point_in_ring(-0.5, 0.5, ring)


def test_grid_yields_expected_block_count(grid_blocks):
    blocks, _ = grid_blocks
    # A 4x4 lattice of streets encloses 3x3 = 9 blocks.
    assert len(blocks) == 9
    # All blocks are the same size to within the local-projection error
    # (each ring is projected at its own mean latitude) and are bounded by
    # four residential edges.
    areas = sorted(b.area_m2 for b in blocks)
    assert areas[0] == pytest.approx(areas[-1], rel=1e-3)
    for block in blocks:
        assert sum(block.boundary_classes.values()) == 4
        assert block.boundary_classes["residential"] == 4


def test_dangling_edges_are_pruned():
    features = _grid_roads(n=3)
    # A cul-de-sac hanging off the lattice bounds no face.
    features.append({"type": "Feature",
                     "properties": {"highway": "service"},
                     "geometry": {"type": "LineString",
                                  "coordinates": [[104.0, 30.6], [103.99, 30.59]]}})
    graph = build_road_graph(features)
    before = graph.node_count()
    prune_dangling(graph)
    assert graph.node_count() < before
    blocks = build_blocks(graph, extract_faces(graph), min_area_m2=1.0, max_area_m2=1e9)
    assert len(blocks) == 4


def test_drop_highways_excludes_class():
    features = _grid_roads(n=3)
    graph = build_road_graph(features, drop_highways={"residential"})
    assert graph.node_count() == 0
    assert graph.ways_skipped == len(features)


def test_area_filter_removes_slivers(grid_blocks):
    blocks, graph = grid_blocks
    faces = extract_faces(graph)
    # Every block in the fixture is ~49,000 m^2, so a high floor removes all.
    assert build_blocks(graph, faces, min_area_m2=1e9, max_area_m2=1e12) == []


def test_blocks_from_geojson_roundtrip(tmp_path):
    path = tmp_path / "roads.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection",
                                "features": _grid_roads(n=3)}), encoding="utf-8")
    blocks, graph, provenance = blocks_from_geojson(path, min_area_m2=1.0)
    assert len(blocks) == 4
    assert provenance["blocks_kept"] == 4
    assert provenance["road_features"] == 6
    assert "OpenStreetMap" in provenance["attribution"]
    feature = blocks[0].to_feature()
    assert feature["geometry"]["type"] == "Polygon"
    # GeoJSON rings must be explicitly closed.
    coords = feature["geometry"]["coordinates"][0]
    assert coords[0] == coords[-1]


# ── population disaggregation ───────────────────────────────────────────────

def test_disaggregation_conserves_mass(grid_blocks):
    blocks, _ = grid_blocks
    centres = {0: (104.0025, 30.6025), 1: (104.0075, 30.6025)}
    population = {0: 1000.0, 1: 3000.0}
    result = disaggregate_population(blocks, population, centres, grid_size_deg=0.005)
    total = sum(result["assigned"].values()) + result["residual"]
    assert total == pytest.approx(4000.0, rel=1e-9)
    assert result["conservation_error"] < 1e-9


def test_disaggregation_reports_residual_for_empty_cells(grid_blocks):
    blocks, _ = grid_blocks
    # A cell far from every block keeps its population as residual rather than
    # having it smeared onto unrelated blocks.
    centres = {0: (104.0025, 30.6025), 99: (105.5, 31.5)}
    population = {0: 1000.0, 99: 500.0}
    result = disaggregate_population(blocks, population, centres, grid_size_deg=0.005)
    assert result["residual"] == pytest.approx(500.0)


def test_disaggregation_respects_suitability(grid_blocks):
    blocks, _ = grid_blocks
    centres = {0: (104.003, 30.603)}
    population = {0: 900.0}
    # Only one block is habitable; it must receive everything.
    suitability = {b.block_id: (1.0 if i == 0 else 0.0) for i, b in enumerate(blocks)}
    result = disaggregate_population(blocks, population, centres,
                                     grid_size_deg=0.05, suitability=suitability)
    assert result["assigned"][blocks[0].block_id] == pytest.approx(900.0)
    assert len(result["assigned"]) == 1


# ── routing and simulation ──────────────────────────────────────────────────

def test_routing_tree_reaches_all_blocks(grid_blocks):
    blocks, _ = grid_blocks
    layer = build_block_layer(blocks)
    config = BlockScaleConfig(max_shelter_distance_m=100_000)
    tree = build_routing_tree(layer, [0], config)
    assert (tree.shelter_index >= 0).all()
    assert tree.next_hop[0] == -1          # the shelter block is the root
    assert tree.distance_m[0] == 0.0
    assert all(tree.distance_m[i] > 0 for i in range(1, len(layer)))


def test_routing_respects_distance_cap(grid_blocks):
    blocks, _ = grid_blocks
    layer = build_block_layer(blocks)
    config = BlockScaleConfig(max_shelter_distance_m=1.0)
    tree = build_routing_tree(layer, [0], config)
    # Only the shelter block itself is within a 1 m budget.
    assert int((tree.shelter_index >= 0).sum()) == 1


def test_simulation_conserves_population(grid_blocks):
    blocks, _ = grid_blocks
    for block in blocks:
        block.population = 1000.0
    layer = build_block_layer(blocks)
    config = BlockScaleConfig(duration_minutes=60, step_seconds=30,
                              max_shelter_distance_m=100_000,
                              mmi_evacuation_threshold=0.0)
    shelters = [ShelterSite("S1", "park", float(layer.lon[0]), float(layer.lat[0]),
                            capacity=1e9)]
    sim = BlockEvacuationSimulator(layer, shelters, config)
    sim.run()
    conservation = sim._conservation()
    assert conservation["relative_error"] < 1e-9
    assert sim.sheltered.sum() > 0


def test_shelter_cutoff_throttles_admission_below_full_capacity(grid_blocks):
    """The proactive-throttling lever rl/shelter_agents.py controls: setting
    shelter_cutoff below 1.0 must actually cap admitted occupancy at
    capacity * cutoff, not just be a no-op flag."""
    blocks, _ = grid_blocks
    for block in blocks:
        block.population = 2000.0
    layer = build_block_layer(blocks)
    config = BlockScaleConfig(duration_minutes=90, step_seconds=30,
                              max_shelter_distance_m=100_000,
                              mmi_evacuation_threshold=0.0)
    shelters = [ShelterSite("S1", "park", float(layer.lon[0]), float(layer.lat[0]),
                            capacity=1000.0)]
    sim = BlockEvacuationSimulator(layer, shelters, config)
    sim.shelter_cutoff[0] = 0.5
    sim.run()
    assert sim.shelter_occupancy[0] <= 500.0 + 1e-6
    assert sim._conservation()["relative_error"] < 1e-9


def test_shelter_cutoff_default_reproduces_unthrottled_behaviour(grid_blocks):
    """Default shelter_cutoff (all ones) must be behaviourally identical to
    not having the mechanism at all -- a regression guard for every existing
    (pre-cutoff) test and every already-generated city dataset."""
    blocks, _ = grid_blocks
    for block in blocks:
        block.population = 1000.0
    layer = build_block_layer(blocks)
    config = BlockScaleConfig(duration_minutes=90, step_seconds=30,
                              max_shelter_distance_m=100_000,
                              mmi_evacuation_threshold=0.0, seed=42)
    shelters = [ShelterSite("S1", "park", float(layer.lon[0]), float(layer.lat[0]),
                            capacity=1e9)]
    sim = BlockEvacuationSimulator(layer, shelters, config)
    assert (sim.shelter_cutoff == 1.0).all()
    sim.run()
    sheltered_default = float(sim.sheltered.sum())

    layer2 = build_block_layer(blocks)
    shelters2 = [ShelterSite("S1", "park", float(layer2.lon[0]), float(layer2.lat[0]),
                             capacity=1e9)]
    sim2 = BlockEvacuationSimulator(layer2, shelters2, config)
    sim2.shelter_cutoff[:] = 1.0  # explicit, should match the implicit default
    sim2.run()
    assert float(sim2.sheltered.sum()) == pytest.approx(sheltered_default)


def test_shelter_cutoff_full_status_is_reversible(grid_blocks):
    """A shelter throttled shut by a low cutoff must become reachable again
    once the cutoff is raised back up -- the reroute mechanism's "full" flag
    must track current effective capacity, not latch permanently at the
    first rejection (see rl/shelter_agents.py for why this matters: a
    one-way latch would make any proactive throttling strategy strictly
    worse than never throttling at all, which is exactly what an earlier,
    honest experiment on real Naples data found before this fix).

    Uses two shelters (not one) so that throttling S1 doesn't collapse
    routing for the whole network -- with only one shelter, marking it
    "full" leaves zero valid routing sources, which freezes every block's
    outflow network-wide and is a degenerate case in its own right, not a
    meaningful test of reversibility.
    """
    blocks, _ = grid_blocks
    for block in blocks:
        block.population = 2000.0
    layer = build_block_layer(blocks)
    config = BlockScaleConfig(duration_minutes=120, step_seconds=30,
                              max_shelter_distance_m=100_000,
                              mmi_evacuation_threshold=0.0)
    shelters = [
        ShelterSite("S1", "small", float(layer.lon[0]), float(layer.lat[0]), capacity=1000.0),
        ShelterSite("S2", "large", float(layer.lon[-1]), float(layer.lat[-1]), capacity=1e9),
    ]
    sim = BlockEvacuationSimulator(layer, shelters, config)
    sim.shelter_cutoff[0] = 0.05  # throttled hard: fills and marks full almost immediately

    # Run until S1 has actually been marked full at least once.
    for _ in range(20):
        sim.step()
        if 0 in sim._full_shelters:
            break
    assert 0 in sim._full_shelters, "fixture should reliably throttle S1 full within 20 steps"
    occupancy_while_throttled = float(sim.shelter_occupancy[0])

    # Ease the throttle back to normal and keep running; check at every step
    # rather than only at the end, since renewed demand could plausibly fill
    # S1 again later -- the property under test is that it becomes reachable
    # at all, not that it stays permanently unthrottled.
    sim.shelter_cutoff[0] = 1.0
    was_freed_at_some_point = False
    for _ in range(60):
        sim.step()
        if 0 not in sim._full_shelters:
            was_freed_at_some_point = True

    assert was_freed_at_some_point, "shelter must become reachable again once cutoff is raised and room exists"
    assert sim.shelter_occupancy[0] > occupancy_while_throttled, (
        "a freed shelter must resume admitting people, not stay stuck at its throttled occupancy")
    assert sim._conservation()["relative_error"] < 1e-9


def test_shelter_reopen_requires_hysteresis_margin_not_bare_crossing(grid_blocks):
    """Reopening a full shelter must require effective capacity to clear
    occupancy by ``shelter_reopen_hysteresis`` x nominal capacity, not just
    cross it by an epsilon. Without this margin, a shelter whose cutoff
    hovers near its own occupancy setpoint (e.g. an admission controller
    nudging cutoff by small steps every epoch) flips full/not-full on every
    adjustment, and each flip forces an expensive network-wide reroute --
    the reroute-thrashing negative result this project reported once the
    one-way latch bug was fixed (see rl/shelter_agents.py).

    Demand is set to zero (``participation_high=participation_low=0``) so
    ``shelter_occupancy`` cannot change during ``step()`` for any reason
    other than the mechanism under test; this isolates the exact margin
    boundary from how quickly occupancy happens to grow in a live run.
    """
    blocks, _ = grid_blocks
    for block in blocks:
        block.population = 2000.0
    layer = build_block_layer(blocks)
    config = BlockScaleConfig(duration_minutes=120, step_seconds=30,
                              max_shelter_distance_m=100_000,
                              participation_high=0.0, participation_low=0.0,
                              shelter_reopen_hysteresis=0.05)
    shelters = [
        ShelterSite("S1", "small", float(layer.lon[0]), float(layer.lat[0]), capacity=1000.0),
        ShelterSite("S2", "large", float(layer.lon[-1]), float(layer.lat[-1]), capacity=1e9),
    ]
    sim = BlockEvacuationSimulator(layer, shelters, config)
    assert sim.will_evacuate.sum() == 0, "fixture must produce zero demand so occupancy stays exactly as set below"

    sim.shelter_occupancy[0] = 960.0
    sim.shelters[0].occupants = 960.0
    sim._full_shelters.add(0)

    # Effective capacity 970 clears occupancy (960) by only 10 -- less than
    # the 50-unit (5% of 1000) hysteresis margin. Must stay full.
    sim.shelter_cutoff[0] = 0.97
    sim.step()
    assert 0 in sim._full_shelters, "a bare crossing within the hysteresis margin must not reopen the shelter"
    assert sim.shelter_occupancy[0] == 960.0

    # Effective capacity 1049 clears occupancy (960) by 89 -- past the
    # margin. Must reopen.
    sim.shelter_cutoff[0] = 1.049
    sim.step()
    assert 0 not in sim._full_shelters, "clearing effective capacity past the margin must reopen the shelter"


def test_full_shelter_triggers_reroute(grid_blocks):
    blocks, _ = grid_blocks
    for block in blocks:
        block.population = 1000.0
    layer = build_block_layer(blocks)
    config = BlockScaleConfig(duration_minutes=90, step_seconds=30,
                              max_shelter_distance_m=100_000,
                              mmi_evacuation_threshold=0.0)
    shelters = [
        ShelterSite("S1", "small", float(layer.lon[0]), float(layer.lat[0]), capacity=50.0),
        ShelterSite("S2", "large", float(layer.lon[-1]), float(layer.lat[-1]), capacity=1e9),
    ]
    sim = BlockEvacuationSimulator(layer, shelters, config)
    sim.run()
    assert sim._reroute_events, "filling a shelter must trigger a reroute"
    assert sim.shelter_occupancy[0] == pytest.approx(50.0, rel=1e-6)
    # People turned away from the small shelter must still reach the large one.
    assert sim.shelter_occupancy[1] > 0
    assert sim._conservation()["relative_error"] < 1e-9


def test_unserved_blocks_do_not_evacuate(grid_blocks):
    blocks, _ = grid_blocks
    for block in blocks:
        block.population = 1000.0
    layer = build_block_layer(blocks)
    config = BlockScaleConfig(duration_minutes=30, max_shelter_distance_m=1.0,
                              mmi_evacuation_threshold=0.0)
    shelters = [ShelterSite("S1", "park", float(layer.lon[0]), float(layer.lat[0]),
                            capacity=1e9)]
    sim = BlockEvacuationSimulator(layer, shelters, config)
    sim.run()
    payload = sim.to_dict(include_blocks=False)
    assert payload["totals"]["unserved_blocks"] == len(layer) - 1
    assert payload["totals"]["unserved_population"] > 0
    assert sim._conservation()["relative_error"] < 1e-9


def test_clearance_time_is_distance_sensitive(grid_blocks):
    """Halving walking speed must lengthen clearance, not leave it unchanged.

    This is the regression guard for the transit-time constraint: without it,
    the queue advanced one hop per time step regardless of hop length, and
    clearance time was an artefact of ``step_seconds``.
    """
    def clearance(speed: float) -> float | None:
        for block in grid_blocks[0]:
            block.population = 1000.0
        layer = build_block_layer(grid_blocks[0])
        config = BlockScaleConfig(duration_minutes=240, step_seconds=30,
                                  free_flow_speed_mps=speed,
                                  max_shelter_distance_m=100_000,
                                  mmi_evacuation_threshold=0.0)
        shelters = [ShelterSite("S1", "park", float(layer.lon[0]), float(layer.lat[0]),
                                capacity=1e9)]
        sim = BlockEvacuationSimulator(layer, shelters, config)
        sim.run()
        return sim.clearance_time_min(0.9)

    fast = clearance(1.34)
    slow = clearance(0.67)
    assert fast is not None and slow is not None
    assert slow > fast


def test_sample_rendered_agents_have_consistent_timing(grid_blocks):
    blocks, _ = grid_blocks
    for block in blocks:
        block.population = 1000.0
    layer = build_block_layer(blocks)
    config = BlockScaleConfig(duration_minutes=90, step_seconds=30,
                              max_shelter_distance_m=100_000,
                              mmi_evacuation_threshold=0.0)
    shelters = [ShelterSite("S1", "park", float(layer.lon[0]), float(layer.lat[0]),
                            capacity=1e9)]
    sim = BlockEvacuationSimulator(layer, shelters, config)
    sim.run()

    agents = sim.sample_rendered_agents(500, seed=7)
    assert len(agents) == 500
    for a in agents:
        assert a["route"][0] == pytest.approx(
            [round(float(layer.lon[layer.block_ids.index(a["home_block"])]), 6),
             round(float(layer.lat[layer.block_ids.index(a["home_block"])]), 6)])
        assert a["route"][-1] == pytest.approx([float(layer.lon[0]), float(layer.lat[0])], abs=1e-4)
        assert a["depart_s"] is not None
        if a["arrive_s"] is not None:
            assert a["arrive_s"] >= a["depart_s"]
        assert a["shelter_id"] == "S1"

    # Every point represents a slice of real simulated population, and those
    # slices should sum back to (approximately) the evacuating cohort.
    total_represented = sum(a["represented_population"] for a in agents)
    assert total_represented == pytest.approx(float(sim.will_evacuate.sum()), rel=0.05)


def test_sample_rendered_agents_progress_at_horizon_is_bounded(grid_blocks):
    blocks, _ = grid_blocks
    for block in blocks:
        block.population = 1000.0
    layer = build_block_layer(blocks)
    # A short horizon guarantees most points are still in transit at the end.
    config = BlockScaleConfig(duration_minutes=3, step_seconds=30,
                              max_shelter_distance_m=100_000,
                              mmi_evacuation_threshold=0.0)
    shelters = [ShelterSite("S1", "park", float(layer.lon[-1]), float(layer.lat[-1]),
                            capacity=1e9)]
    sim = BlockEvacuationSimulator(layer, shelters, config)
    sim.run()
    agents = sim.sample_rendered_agents(200, seed=11)
    stuck = [a for a in agents if a["arrive_s"] is None]
    assert stuck, "a 3-minute horizon should leave most points still in transit"
    for a in stuck:
        assert 0.0 <= a["progress_at_horizon"] <= 1.0
        if len(a["route"]) == 1:
            assert a["progress_at_horizon"] == 0.0


def test_sample_rendered_agents_unserved_never_arrive(grid_blocks):
    blocks, _ = grid_blocks
    for block in blocks:
        block.population = 1000.0
    layer = build_block_layer(blocks)
    config = BlockScaleConfig(duration_minutes=20, max_shelter_distance_m=1.0,
                              mmi_evacuation_threshold=0.0)
    shelters = [ShelterSite("S1", "park", float(layer.lon[0]), float(layer.lat[0]),
                            capacity=1e9)]
    sim = BlockEvacuationSimulator(layer, shelters, config)
    sim.run()
    agents = sim.sample_rendered_agents(200, seed=3)
    unserved_home_blocks = {layer.block_ids[i] for i in range(len(layer))
                            if sim.unserved_mask[i]}
    unserved_agents = [a for a in agents if a["home_block"] in unserved_home_blocks]
    assert unserved_agents, "fixture should place at least one sampled agent in an unserved block"
    assert all(a["arrive_s"] is None for a in unserved_agents)


def test_load_shelters_geojson_uses_type_based_defaults_not_one_flat_number(tmp_path):
    payload = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "properties": {"name": "Central Park", "shelter_type": "park", "capacity": ""},
             "geometry": {"type": "Point", "coordinates": [14.2, 40.85]}},
            {"type": "Feature",
             "properties": {"name": "General Hospital", "shelter_type": "hospital", "capacity": ""},
             "geometry": {"type": "Point", "coordinates": [14.21, 40.86]}},
            {"type": "Feature",
             "properties": {"name": "Mystery POI", "capacity": ""},
             "geometry": {"type": "Point", "coordinates": [14.22, 40.87]}},
            {"type": "Feature",
             "properties": {"name": "Official Shelter", "capacity": 12345},
             "geometry": {"type": "Point", "coordinates": [14.23, 40.88]}},
        ],
    }
    path = tmp_path / "shelters.geojson"
    path.write_text(json.dumps(payload), encoding="utf-8")

    sites = load_shelters_geojson(path, BlockScaleConfig())
    by_name = {s.name: s for s in sites}

    assert by_name["Central Park"].capacity == pytest.approx(5_000.0)
    assert by_name["General Hospital"].capacity == pytest.approx(500.0)
    # A park and a hospital must not collapse to the same assumed number.
    assert by_name["Central Park"].capacity != by_name["General Hospital"].capacity
    assert "park" in by_name["Central Park"].provenance
    assert "hospital" in by_name["General Hospital"].provenance

    # No usable type at all still falls back to the flat default, unchanged.
    assert by_name["Mystery POI"].capacity == pytest.approx(20_000.0)

    # A real recorded capacity is never overridden by a type default.
    assert by_name["Official Shelter"].capacity == pytest.approx(12345.0)
    assert by_name["Official Shelter"].provenance == "recorded capacity"


def test_payload_declares_assumptions_and_evidence_class(grid_blocks):
    blocks, _ = grid_blocks
    layer = build_block_layer(blocks)
    config = BlockScaleConfig(duration_minutes=5)
    shelters = [ShelterSite("S1", "park", float(layer.lon[0]), float(layer.lat[0]),
                            capacity=1e6)]
    sim = BlockEvacuationSimulator(layer, shelters, config)
    sim.run()
    payload = sim.to_dict(include_blocks=False)
    assert "Synthetic" in payload["evidence_class"]
    assert payload["assumptions"]["specific_flow_persons_per_m_per_s"] > 0
    assert payload["assumptions"]["known_gaps"]
    assert "not a validated GMPE" in payload["assumptions"]["mmi_attenuation"]
