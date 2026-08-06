from __future__ import annotations

import numpy as np

from sparse_view_plant.gaussians_gsrefine import (
    pointmap_source_rays,
    pointmap_surfel_frames,
)


def test_pointmap_surfel_frames_align_flat_grid_normal_to_camera() -> None:
    yy, xx = np.mgrid[0:3, 0:4]
    grid = np.stack([xx, yy, np.full_like(xx, 2.0)], axis=-1).astype(np.float32)
    camera = np.eye(4, dtype=np.float32)[None]
    quaternions, spacing, normals, valid = pointmap_surfel_frames(
        grid.reshape(-1, 3), (3, 4), camera
    )
    assert valid.all()
    np.testing.assert_allclose(spacing, 1.0, atol=1e-6)
    # The raw cross product points +z, away from the camera at the origin, so
    # initialization flips it to -z while keeping a right-handed frame.
    np.testing.assert_allclose(
        normals, np.tile([0.0, 0.0, -1.0], (len(normals), 1)), atol=1e-6
    )
    np.testing.assert_allclose(np.linalg.norm(quaternions, axis=1), 1.0, atol=1e-6)


def test_pointmap_surfel_frames_rejects_degenerate_cells() -> None:
    points = np.zeros((4, 3), dtype=np.float32)
    _, _, _, valid = pointmap_surfel_frames(
        points, (2, 2), np.eye(4, dtype=np.float32)[None]
    )
    assert not valid.any()


def test_pointmap_source_rays_preserve_selected_cell_camera_assignment() -> None:
    poses = np.repeat(np.eye(4, dtype=np.float32)[None], 2, axis=0)
    poses[1, :3, 3] = [10.0, 0.0, 0.0]
    points = np.asarray([[0.0, 0.0, 2.0], [10.0, 2.0, 0.0]], dtype=np.float32)
    origins, directions = pointmap_source_rays(
        points, np.asarray([0, 4]), (2, 2), poses
    )
    np.testing.assert_allclose(origins, [[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]])
    np.testing.assert_allclose(directions, [[0.0, 0.0, 1.0], [0.0, 1.0, 0.0]])
