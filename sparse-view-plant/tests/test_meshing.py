"""Tests for the dependency-light voxel-surface meshing module."""

from collections import Counter

import numpy as np
import pytest

from sparse_view_plant.meshing import implicit_voxel_mesh, voxel_surface_mesh


def _solid_block(size: int = 8) -> tuple[np.ndarray, float]:
    gx, gy, gz = np.mgrid[0:size, 0:size, 0:size]
    points = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1).astype(float) + 0.5
    diagonal = float(np.linalg.norm(points.max(axis=0) - points.min(axis=0)))
    return points, diagonal


def test_solid_block_is_closed_and_outward() -> None:
    size = 8
    points, diagonal = _solid_block(size)
    vertices, faces = voxel_surface_mesh(
        points, voxel_fraction=1.0 / diagonal, dilate=0
    )
    # A solid (size)^3 voxel block has 6 * size^2 quads -> 12 * size^2 triangles.
    assert faces.shape == (12 * size * size, 3)
    # Every undirected edge is shared by exactly two faces (watertight).
    edges: Counter[tuple[int, int]] = Counter()
    for tri in faces:
        for a, b in ((0, 1), (1, 2), (2, 0)):
            edges[tuple(sorted((tri[a], tri[b])))] += 1
    assert set(edges.values()) == {2}
    # All face normals point away from the block centre.
    centre = points.mean(axis=0)
    for tri in faces:
        a, b, c = (vertices[index] for index in tri)
        normal = np.cross(b - a, c - a)
        assert np.dot(normal, (a + b + c) / 3.0 - centre) > 0.0


def test_sparse_plant_cloud_stays_in_frame() -> None:
    rng = np.random.default_rng(0)
    stem = rng.normal(size=(5000, 3)) * [0.4, 2.0, 0.4]
    leaves = rng.normal(size=(5000, 3)) * [1.0, 0.6, 0.8] + [0, 0.5, 0]
    cloud = np.concatenate([stem, leaves])
    vertices, faces = voxel_surface_mesh(cloud, voxel_fraction=0.02, dilate=0)
    assert len(vertices) > 100
    assert len(faces) > 100
    assert vertices.shape[1] == 3 and faces.shape[1] == 3
    diagonal = float(np.linalg.norm(cloud.max(axis=0) - cloud.min(axis=0)))
    voxel_size = diagonal * 0.02
    # Vertex corners sit at voxel-cell corners, so they enclose the cloud
    # within one voxel of tolerance.
    assert (vertices.min(axis=0) >= cloud.min(axis=0) - voxel_size).all()
    assert (vertices.max(axis=0) <= cloud.max(axis=0) + voxel_size).all()


def test_rejects_degenerate_clouds() -> None:
    with pytest.raises(ValueError):
        voxel_surface_mesh(np.zeros((3, 3)))
    with pytest.raises(ValueError):
        voxel_surface_mesh(np.zeros((4, 3)))


def test_implicit_block_is_closed_and_oriented() -> None:
    points, diagonal = _solid_block(5)
    vertices, faces = implicit_voxel_mesh(
        points,
        voxel_fraction=1.0 / diagonal,
        closing=0,
        minimum_component_voxels=1,
        smooth_sigma=0.0,
        level=0.5,
    )
    edges: Counter[tuple[int, int]] = Counter()
    for triangle in faces:
        for a, b in ((0, 1), (1, 2), (2, 0)):
            edges[tuple(sorted((triangle[a], triangle[b])))] += 1
    assert set(edges.values()) == {2}
    centre = points.mean(axis=0)
    outward = 0
    for triangle in faces:
        a, b, c = (vertices[index] for index in triangle)
        normal = np.cross(b - a, c - a)
        outward += np.dot(normal, (a + b + c) / 3.0 - centre) > 0.0
    assert outward == len(faces)


def test_implicit_mesh_removes_tiny_floater() -> None:
    points, _ = _solid_block(5)
    floater = np.asarray([[20.5, 20.5, 20.5]])
    cloud = np.concatenate([points, floater])
    cloud_diagonal = float(np.linalg.norm(cloud.max(axis=0) - cloud.min(axis=0)))
    vertices, _ = implicit_voxel_mesh(
        cloud,
        voxel_fraction=1.0 / cloud_diagonal,
        closing=0,
        minimum_component_voxels=2,
        smooth_sigma=0.0,
        level=0.5,
    )
    assert vertices.max() < 10.0
