from __future__ import annotations

import numpy as np

from sparse_view_plant.evaluation import (
    apply_sim3,
    build_reference,
    depth_edge_mask,
    estimate_sim3,
    extract_foreground_points,
    geometry_metrics,
    infer_patch_grid,
    normalize_view_ids,
    replay_mask,
    sample_points,
    voxel_downsample,
)


def _sphere_points(count: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    directions = rng.normal(size=(count, 3))
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    radii = rng.uniform(0.5, 1.0, size=(count, 1))
    return directions * radii


def test_geometry_metrics_perfect_overlap_is_zero_chamfer() -> None:
    points = _sphere_points(5000)
    reference = build_reference(points)
    metrics = geometry_metrics(points, reference)
    assert metrics["chamfer_l1"] < 1e-6
    assert metrics["fscore_1pct"] == 1.0


def test_geometry_metrics_offset_increases_chamfer() -> None:
    points = _sphere_points(5000)
    reference = build_reference(points)
    shifted = points + np.array([0.5, 0.0, 0.0])
    metrics = geometry_metrics(shifted, reference)
    # A sphere is rotationally symmetric and largely overlaps after a small
    # shift, so a modest but clearly non-zero normalized Chamfer is expected.
    assert metrics["chamfer_l1_normalized"] > 0.02


def test_voxel_downsample_and_sample_respect_limits() -> None:
    points = np.linspace(0, 10, 2000).reshape(-1, 1).repeat(3, axis=1)
    downsampled = voxel_downsample(points, voxel_size=0.5)
    assert len(downsampled) < len(points)
    sampled = sample_points(points, maximum=100, seed=0)
    assert len(sampled) == 100


def test_normalize_view_ids_strips_extensions() -> None:
    assert normalize_view_ids(None) == []
    assert normalize_view_ids(["0005_train.png", "0005_train"]) == [
        "0005_train",
        "0005_train",
    ]
    assert normalize_view_ids(["a/b/0054_train.PNG"]) == ["0054_train"]


def test_estimate_sim3_recovers_known_transform() -> None:
    rng = np.random.default_rng(1)
    source = rng.normal(size=(8, 3))
    angle = 0.7
    rotation = np.array(
        [
            [np.cos(angle), -np.sin(angle), 0],
            [np.sin(angle), np.cos(angle), 0],
            [0, 0, 1],
        ]
    )
    expected = np.eye(4)
    expected[:3, :3] = 1.7 * rotation
    expected[:3, 3] = [0.3, -0.2, 0.1]
    destination = apply_sim3(source, expected)
    recovered = estimate_sim3(source, destination)
    np.testing.assert_allclose(recovered, expected, atol=1e-9)


def test_align_points_icp_converges_to_reference() -> None:
    from sparse_view_plant.evaluation import align_points_icp

    # Use an asymmetric point set: spheres are rotationally symmetric, which
    # gives ICP a degenerate local optimum that is invisible to the metric.
    rng = np.random.default_rng(7)
    reference = rng.uniform(-1.0, 1.0, size=(8000, 3))
    angle = 0.35
    transform = np.eye(4)
    transform[:3, :3] = 1.1 * np.array(
        [
            [np.cos(angle), -np.sin(angle), 0.0],
            [np.sin(angle), np.cos(angle), 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    transform[:3, 3] = [0.4, -0.3, 0.2]
    source = apply_sim3(
        reference,
        transform,
    )
    fit = align_points_icp(source, reference)
    aligned = apply_sim3(source, fit.matrix)
    distances = np.linalg.norm(aligned - reference, axis=1)
    assert np.percentile(distances, 90) < 0.05


def test_infer_patch_grid_recovers_square_layout() -> None:
    assert infer_patch_grid(3 * 14 * 14, 3) == (14, 14)


def test_replay_mask_resizes_to_target_grid() -> None:
    mask = np.zeros((4, 4), dtype=bool)
    mask[:2, :] = True
    replayed = replay_mask(mask, (2, 2))
    assert replayed.shape == (2, 2)
    assert replayed.any() and not replayed.all()


def test_depth_edge_mask_flags_discontinuities() -> None:
    depth = np.ones((1, 8, 8))
    depth[0, 4:, 4:] = 2.0
    edges = depth_edge_mask(depth, rtol=0.03)
    assert edges[0].any()
    assert not edges[0, 1, 1]


def test_extract_foreground_points_applies_mask_and_confidence() -> None:
    grid_h, grid_w = 4, 4
    world = np.zeros((1, grid_h, grid_w, 3))
    world[0, :, :, 2] = 1.0  # flat depth: no occlusion edges
    confidence = np.full((1, grid_h, grid_w), 0.5)
    mask = np.zeros((grid_h, grid_w), dtype=bool)
    mask[1:3, 1:3] = True
    selected = extract_foreground_points(
        world.reshape(-1, 3),
        confidence.reshape(-1),
        view_ids=("a",),
        camera_to_world=np.eye(4)[None],
        masks={"a": mask},
        patch_hw=(grid_h, grid_w),
        confidence_percentile=0.0,
        depth_edge_rtol=0.5,
    )
    assert len(selected) == 4
    assert np.allclose(selected[:, 2], 1.0)
