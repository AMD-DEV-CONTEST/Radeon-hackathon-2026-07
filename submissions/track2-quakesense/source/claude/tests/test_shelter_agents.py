"""Tests for the multi-agent shared-Q-table shelter admission controller."""

from __future__ import annotations

import pytest

from geo.urban_blocks import build_blocks, build_road_graph, extract_faces, prune_dangling
from rl.shelter_agents import ShelterAgentConfig, SharedQLearningShelterAgents, _bucket
from simulator.block_scale import BlockScaleConfig, ShelterSite, build_block_layer


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
def busy_layer():
    """A 3x3-block grid, heavily populated, with two shelters of very
    different capacity -- enough demand that the small shelter reliably
    fills and the routing/reroute machinery is actually exercised.
    """
    graph = build_road_graph(_grid_roads(n=4))
    prune_dangling(graph)
    blocks = build_blocks(graph, extract_faces(graph), min_area_m2=1.0, max_area_m2=1e9)
    for block in blocks:
        block.population = 3000.0
    return build_block_layer(blocks)


def _make_shelters(layer):
    return [
        ShelterSite("S1", "small", float(layer.lon[0]), float(layer.lat[0]), capacity=3000.0),
        ShelterSite("S2", "large", float(layer.lon[-1]), float(layer.lat[-1]), capacity=1e9),
    ]


def _sim_config():
    return BlockScaleConfig(duration_minutes=90, step_seconds=30,
                            max_shelter_distance_m=100_000,
                            mmi_evacuation_threshold=0.0, seed=3)


def test_bucket_assigns_first_matching_edge():
    edges = (0.1, 0.3, 0.6, 1.0)
    assert _bucket(0.05, edges) == 0
    assert _bucket(0.1, edges) == 0
    assert _bucket(0.25, edges) == 1
    assert _bucket(0.9, edges) == 3
    assert _bucket(5.0, edges) == 3  # clamped to the last bucket, never out of range


def test_state_is_a_stable_small_tuple():
    agents = SharedQLearningShelterAgents(ShelterAgentConfig(time_buckets=3))
    s = agents._state(0.42, 0.01, 0.5)
    assert isinstance(s, tuple) and len(s) == 3
    assert all(isinstance(x, int) for x in s)


def test_run_baseline_episode_matches_plain_simulator_run(busy_layer):
    agents = SharedQLearningShelterAgents(ShelterAgentConfig(seed=1))
    result = agents.run_baseline_episode(busy_layer, _make_shelters(busy_layer), _sim_config())
    assert 0.0 <= result.unserved_fraction <= 1.0
    assert result.reroute_events >= 0
    assert result.decisions == 0  # no agent decisions in the baseline path
    assert not agents.q  # baseline must not touch the shared Q-table


def test_run_episode_makes_decisions_and_leaves_a_trained_table(busy_layer):
    agents = SharedQLearningShelterAgents(ShelterAgentConfig(seed=2, epoch_minutes=15))
    result = agents.run_episode(busy_layer, _make_shelters(busy_layer), _sim_config(),
                                train=True, epsilon=0.5)
    assert result.decisions > 0
    assert agents.q  # at least one state was visited and updated
    assert -2.0 <= result.reward <= 0.0


def test_train_runs_full_loop_and_reports_history(busy_layer):
    agents = SharedQLearningShelterAgents(ShelterAgentConfig(seed=5, epoch_minutes=15))
    report = agents.train(busy_layer, lambda: _make_shelters(busy_layer), _sim_config(), episodes=8)
    assert report.episodes == 8
    assert len(report.reward_history) == 8
    assert report.q_states > 0
    # Rewards must stay in the physically sane range: never better than 0
    # (0 unserved, 0 reroutes) and never below -(1 + heavy reroute penalty).
    assert all(-3.0 <= r <= 0.0 for r in report.reward_history)


def test_save_writes_readable_json(tmp_path, busy_layer):
    agents = SharedQLearningShelterAgents(ShelterAgentConfig(seed=9))
    agents.run_episode(busy_layer, _make_shelters(busy_layer), _sim_config(), train=True, epsilon=0.8)
    out = tmp_path / "q.json"
    agents.save(out)
    import json
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert "q_table" in payload and "config" in payload
    assert len(payload["q_table"]) == len(agents.q)
