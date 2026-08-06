from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sparse_view_plant.export import (
    write_gaussian_splat_ply,
    write_json,
    write_point_cloud_ply,
)


def test_write_point_cloud_ply_roundtrip_header(tmp_path: Path) -> None:
    path = tmp_path / "cloud.ply"
    points = np.asarray([[0, 0, 0], [1, 1, 1]], dtype=np.float32)
    colors = np.asarray([[0, 0.5, 1], [1, 0, 0]], dtype=np.float32)
    confidence = np.asarray([0.9, 0.1], dtype=np.float32)
    stats = write_point_cloud_ply(
        path,
        points,
        colors=colors,
        confidence=confidence,
    )
    assert stats == {"points": 2}
    header = path.read_bytes()[:256].decode("ascii", errors="replace")
    assert "format binary_little_endian 1.0" in header
    assert "element vertex 2" in header
    assert "property float confidence" in header


def test_write_point_cloud_ply_confidence_filter(tmp_path: Path) -> None:
    path = tmp_path / "cloud.ply"
    points = np.asarray([[i, 0, 0] for i in range(5)], dtype=np.float32)
    confidence = np.asarray([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32)
    stats = write_point_cloud_ply(
        path,
        points,
        colors=points,
        confidence=confidence,
        keep_confidence_fraction=0.8,
    )
    assert stats == {"points": 4}
    header = path.read_bytes()[:128].decode("ascii", errors="replace")
    assert "element vertex 4" in header


def test_write_point_cloud_ply_rejects_mismatched_confidence(tmp_path: Path) -> None:
    import pytest

    points = np.zeros((3, 3), dtype=np.float32)
    confidence = np.zeros(2, dtype=np.float32)
    with pytest.raises(ValueError, match="confidence"):
        write_point_cloud_ply(
            tmp_path / "cloud.ply",
            points,
            confidence=confidence,
            keep_confidence_fraction=0.8,
        )


def test_write_point_cloud_ply_roundtrips_values_with_plyfile(tmp_path: Path) -> None:
    """The payload layout must match the header (float32 xyz + uchar rgb +
    float32 confidence); a dtype-promoted column stack corrupts the readback."""
    from plyfile import PlyData

    path = tmp_path / "cloud.ply"
    points = np.asarray([[0, 0, 0], [1.5, -2.25, 3.75], [4, 5, 6]], dtype=np.float32)
    colors = np.asarray([[0, 0.5, 1], [1, 0, 0], [0.25, 0.5, 0.75]], dtype=np.float32)
    confidence = np.asarray([0.9, 0.1, 0.5], dtype=np.float32)
    write_point_cloud_ply(path, points, colors=colors, confidence=confidence)

    vertices = PlyData.read(str(path))["vertex"]
    assert vertices.count == len(points)
    read = np.stack([vertices["x"], vertices["y"], vertices["z"]], axis=1)
    np.testing.assert_allclose(read, points, atol=1e-6)


def test_write_json_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "metrics.json"
    write_json(path, {"a": 1, "b": [1, 2], "c": {"d": "x"}})
    import json

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "a": 1,
        "b": [1, 2],
        "c": {"d": "x"},
    }


def _rotz90() -> np.ndarray:
    # 90-degree rotation about +Z: x -> y, y -> -x
    return np.asarray(
        [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64
    )


def test_write_gaussian_splat_ply_header(tmp_path: Path) -> None:
    path = tmp_path / "gaussians.ply"
    means = np.asarray([[0, 0, 0], [1, 1, 1]], dtype=np.float32)
    covariances = np.broadcast_to(np.eye(3), (2, 3, 3)).astype(np.float32)
    sh_dc = np.asarray([[0.1, 0.2, 0.3]] * 2, dtype=np.float32)
    opacities = np.asarray([[0.5]] * 2, dtype=np.float32)
    stats = write_gaussian_splat_ply(path, means, covariances, sh_dc, opacities)
    assert stats == {"gaussians": 2}
    header = path.read_bytes()[:1024].decode("ascii", errors="replace")
    assert "comment quaternion_order wxyz" in header
    for prop in (
        "x",
        "y",
        "z",
        "nx",
        "ny",
        "nz",
        "f_dc_0",
        "f_dc_1",
        "f_dc_2",
        "f_rest_0",
        "f_rest_8",
        "opacity",
        "scale_0",
        "scale_1",
        "scale_2",
        "rot_0",
        "rot_1",
        "rot_2",
        "rot_3",
    ):
        assert f"property float {prop}" in header


def test_write_gaussian_splat_ply_uses_standard_wxyz_rotation(tmp_path: Path) -> None:
    path = tmp_path / "gaussians.ply"
    means = np.zeros((1, 3), dtype=np.float32)
    covariances = np.asarray([np.diag([1.0, 4.0, 9.0])], dtype=np.float32)
    write_gaussian_splat_ply(
        path,
        means,
        covariances,
        np.zeros((1, 3), dtype=np.float32),
        np.zeros((1, 1), dtype=np.float32),
    )
    from plyfile import PlyData

    ply = PlyData.read(str(path))
    vertex = ply["vertex"]
    quaternion = np.asarray(
        [
            [
                vertex["rot_0"][0],
                vertex["rot_1"][0],
                vertex["rot_2"][0],
                vertex["rot_3"][0],
            ]
        ]
    )
    assert abs(float(quaternion[0, 0])) == pytest.approx(1.0)
    np.testing.assert_allclose(quaternion[0, 1:], 0.0, atol=1e-6)


def test_write_gaussian_splat_ply_writes_sh_rest(tmp_path: Path) -> None:
    path = tmp_path / "gaussians_sh.ply"
    means = np.asarray([[0, 0, 0]], dtype=np.float32)
    covariances = np.broadcast_to(np.eye(3), (1, 3, 3)).astype(np.float32)
    sh_dc = np.asarray([[0.1, 0.2, 0.3]], dtype=np.float32)
    sh_rest = np.asarray([[[0.01, 0.02, 0.03], [0.04, 0.05, 0.06], [0.07, 0.08, 0.09]]])
    opacities = np.asarray([[0.5]], dtype=np.float32)
    write_gaussian_splat_ply(
        path, means, covariances, sh_dc, opacities, sh_rest=sh_rest
    )
    from plyfile import PlyData

    vertex = PlyData.read(str(path))["vertex"]
    rest = np.stack(
        [np.asarray(vertex[f"f_rest_{i}"]) for i in range(9)], axis=-1
    ).astype(np.float32)
    np.testing.assert_allclose(rest.reshape(1, 3, 3), sh_rest, atol=1e-6)


def test_write_gaussian_splat_ply_writes_normals(tmp_path: Path) -> None:
    path = tmp_path / "gaussians_2dgs.ply"
    means = np.asarray([[0, 0, 0], [1, 1, 1]], dtype=np.float32)
    covariances = np.broadcast_to(np.eye(3), (2, 3, 3)).astype(np.float32)
    sh_dc = np.asarray([[0.1, 0.2, 0.3]] * 2, dtype=np.float32)
    opacities = np.asarray([[0.5]] * 2, dtype=np.float32)
    normals = np.asarray([[0, 0, 1], [0, 1, 0]], dtype=np.float32)
    write_gaussian_splat_ply(
        path,
        means,
        covariances,
        sh_dc,
        opacities,
        normals=normals,
    )
    data = path.read_bytes()
    offset = data.find(b"end_header") + len(b"end_header\n")
    record = np.frombuffer(data, dtype=np.float32, offset=offset)
    # Attributes: x y z nx ny nz f_dc_0..2 f_rest_0..8 opacity scale_0..2 rot_0..3
    got = record.reshape(2, 26)[:, 3:6]
    np.testing.assert_allclose(got, normals, atol=1e-6)


def test_write_gaussian_splat_ply_rejects_bad_normals(tmp_path: Path) -> None:
    import pytest

    means = np.zeros((2, 3), dtype=np.float32)
    covariances = np.broadcast_to(np.eye(3), (2, 3, 3)).astype(np.float32)
    sh_dc = np.zeros((2, 3), dtype=np.float32)
    opacities = np.zeros((2, 1), dtype=np.float32)
    with pytest.raises(ValueError, match="normals"):
        write_gaussian_splat_ply(
            tmp_path / "g.ply",
            means,
            covariances,
            sh_dc,
            opacities,
            normals=np.zeros((3, 3), dtype=np.float32),
        )


def test_covariance_to_quaternion_scale_identity() -> None:
    from sparse_view_plant.export import _covariance_to_quaternion_scale

    quats, scales = _covariance_to_quaternion_scale(
        np.broadcast_to(np.eye(3), (1, 3, 3)).astype(np.float32)
    )
    np.testing.assert_allclose(quats[0], [0, 0, 0, 1], atol=1e-5)
    np.testing.assert_allclose(scales[0], [1, 1, 1], atol=1e-5)


def test_covariance_to_quaternion_rotated_anisotropic() -> None:
    from sparse_view_plant.export import _covariance_to_quaternion_scale

    # A covariance built from a 90-deg Z rotation plus anisotropic scales.
    covariance = _rotz90() @ np.diag([1.0, 4.0, 9.0]) @ _rotz90().T
    quats, scales = _covariance_to_quaternion_scale(covariance[None].astype(np.float32))
    np.testing.assert_allclose(scales[0], [1, 2, 3], atol=1e-5)
    # 90 deg about Z -> (x, y, z, w) = (0, 0, sin(45), cos(45))
    expected = np.asarray([0, 0, np.sqrt(0.5), np.sqrt(0.5)])
    # Quaternion sign is arbitrary; q and -q encode the same rotation.
    np.testing.assert_allclose(np.abs(quats[0]), np.abs(expected), atol=1e-5)


def test_covariance_to_quaternion_reconstructs_covariance() -> None:
    from sparse_view_plant.export import _covariance_to_quaternion_scale

    def quat_to_matrix(q: np.ndarray) -> np.ndarray:
        x, y, z, w = q
        return np.asarray(
            [
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
            ]
        )

    rng = np.random.default_rng(0)
    covariances = []
    for _ in range(50):
        matrix = rng.normal(size=(3, 3))
        covariances.append(matrix @ matrix.T + np.eye(3) * 0.01)
    covariances = np.stack(covariances)
    quats, scales = _covariance_to_quaternion_scale(covariances)
    rotations = np.stack([quat_to_matrix(q) for q in quats])
    diag = np.stack([np.diag(np.square(s)) for s in scales])
    recon = rotations @ diag @ rotations.swapaxes(1, 2)
    np.testing.assert_allclose(recon, covariances, atol=1e-5)
    np.testing.assert_allclose(np.linalg.det(rotations), 1.0, atol=1e-5)
