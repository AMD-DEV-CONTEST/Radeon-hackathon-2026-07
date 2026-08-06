from __future__ import annotations

import numpy as np
import pytest

from sparse_view_plant.rendering import (
    SH_C0,
    SH_C1,
    RenderResult,
    gaussian_covariances,
    render_gaussians,
    render_gaussians_2dgs_gsplat,
    render_metrics,
    render_points,
    select_heldout_views,
    sh_dc_to_rgb,
    sh_rest_to_rgb,
    ssim,
    transform_cameras_sim3,
    transform_gaussians_sim3,
)

IDENTITY = np.eye(4)


def _intrinsics(size: int = 100, focal: float = 500.0) -> np.ndarray:
    center = size / 2.0
    return np.asarray([[focal, 0.0, center], [0.0, focal, center], [0.0, 0.0, 1.0]])


def test_ssim_identical_is_one() -> None:
    image = np.arange(100 * 100 * 3, dtype=np.uint8).reshape(100, 100, 3)
    assert ssim(image, image) == 1.0


def test_sh_rest_to_rgb_matches_degree1_formula() -> None:
    rng = np.random.default_rng(0)
    count = 4
    sh_dc = rng.normal(size=(count, 3))
    sh_rest = rng.normal(size=(count, 3, 3))
    dirs = rng.normal(size=(count, 3)) * 2.0
    got = sh_rest_to_rgb(sh_dc, sh_rest, dirs)
    direction = dirs / np.linalg.norm(dirs, axis=1, keepdims=True)
    # gsplat spherical_harmonics layout: (M, 4, 3) with slot 0 = DC; rest
    # slots come from the channel-major (M, 3, 3) PLY layout.
    coeffs = np.concatenate([sh_dc[:, None, :], sh_rest.transpose(0, 2, 1)], axis=1)
    expected = (
        0.5
        + SH_C0 * coeffs[:, 0]
        + SH_C1
        * (
            -coeffs[:, 1] * direction[:, 1:2]
            + coeffs[:, 2] * direction[:, 2:3]
            - coeffs[:, 3] * direction[:, 0:1]
        )
    )
    np.testing.assert_allclose(got, np.clip(expected, 0.0, 1.0), atol=1e-12)


def test_degree1_with_zero_rest_matches_dc_decode() -> None:
    rgb = np.asarray([[0.1, 0.3, 0.7], [0.8, 0.2, 0.4]])
    sh_dc = (rgb - 0.5) / SH_C0
    got = sh_rest_to_rgb(sh_dc, np.zeros((2, 3, 3)), np.ones((2, 3)))
    np.testing.assert_allclose(got, sh_dc_to_rgb(sh_dc), atol=1e-12)


def test_ssim_different_images_less_than_one() -> None:
    a = np.zeros((64, 64, 3), dtype=np.uint8)
    b = np.full((64, 64, 3), 255, dtype=np.uint8)
    assert ssim(a, b) < 1.0


def test_sh_dc_to_rgb_inverts_rgb2sh() -> None:
    rng = np.random.default_rng(0)
    rgb = rng.uniform(0.0, 1.0, size=(8, 3))
    encoded = (rgb - 0.5) / SH_C0  # export convention (FreeSplatter / Splatt3R)
    decoded = sh_dc_to_rgb(encoded)
    np.testing.assert_allclose(decoded, rgb, atol=1e-12)


def test_sh_dc_to_rgb_clamps_out_of_range() -> None:
    sh_dc = np.asarray([[-10.0, 0.0, 10.0]])
    decoded = sh_dc_to_rgb(sh_dc)
    np.testing.assert_array_equal(decoded, [[0.0, 0.5, 1.0]])


def test_render_points_projects_to_expected_pixel() -> None:
    points = np.asarray([[0.0, 0.0, 10.0]])
    colors = np.asarray([[255, 0, 0]], dtype=np.uint8)
    result = render_points(points, colors, IDENTITY, _intrinsics(), (100, 100))
    assert result.covered[50, 50]
    np.testing.assert_array_equal(result.rgb[50, 50], [255, 0, 0])


def test_render_gaussians_composites_center_color() -> None:
    means = np.asarray([[0.0, 0.0, 10.0]])
    covariances = np.asarray([np.eye(3) * 0.1])
    colors = np.asarray([[1.0, 0.0, 0.0]])
    opacities = np.asarray([0.9])
    result = render_gaussians(
        means, covariances, colors, opacities, IDENTITY, _intrinsics(), (100, 100)
    )
    red, green, blue = result.rgb[50, 50]
    assert red > 200
    assert red > green and red > blue


def test_render_gaussians_2dgs_rejects_incompatible_shapes_before_gpu() -> None:
    with pytest.raises(ValueError, match="incompatible shapes"):
        render_gaussians_2dgs_gsplat(
            np.zeros((2, 3)),
            np.zeros((1, 3)),
            np.zeros((2, 4)),
            np.zeros((2, 3)),
            np.ones(2),
            IDENTITY,
            _intrinsics(),
            (100, 100),
        )


def test_render_gaussians_covariance_roundtrip_is_psd() -> None:
    scales = np.asarray([[0.1, 0.2, 0.3]])
    quaternions = np.asarray([[0.0, 0.0, 0.0, 1.0]])
    covariances = gaussian_covariances(scales, quaternions)
    np.testing.assert_allclose(covariances[0], np.diag([0.01, 0.04, 0.09]))


def test_transform_gaussians_sim3_rotates_and_scales_anisotropy() -> None:
    means = np.asarray([[1.0, 0.0, 0.0]])
    scales = np.asarray([[1.0, 2.0, 3.0]])
    quaternions = np.asarray([[0.0, 0.0, 0.0, 1.0]])
    covariances = gaussian_covariances(scales, quaternions)
    matrix = np.asarray(
        [
            [0.0, -2.0, 0.0, 4.0],
            [2.0, 0.0, 0.0, 5.0],
            [0.0, 0.0, 2.0, 6.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    got_means, got_covariances, got_scales, got_quaternions = transform_gaussians_sim3(
        means, covariances, scales, quaternions, matrix
    )
    np.testing.assert_allclose(got_means, [[4.0, 7.0, 6.0]], atol=1e-12)
    np.testing.assert_allclose(got_scales, [[2.0, 4.0, 6.0]], atol=1e-12)
    np.testing.assert_allclose(
        gaussian_covariances(got_scales, got_quaternions),
        got_covariances,
        atol=1e-12,
    )
    np.testing.assert_allclose(np.diag(got_covariances[0]), [16.0, 4.0, 36.0])


def test_transform_cameras_sim3_does_not_scale_rotation() -> None:
    cameras = np.eye(4)[None]
    cameras[0, :3, 3] = [1.0, 0.0, 0.0]
    matrix = np.asarray(
        [
            [0.0, -2.0, 0.0, 4.0],
            [2.0, 0.0, 0.0, 5.0],
            [0.0, 0.0, 2.0, 6.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    transformed = transform_cameras_sim3(cameras, matrix)[0]
    np.testing.assert_allclose(transformed[:3, 3], [4.0, 7.0, 6.0])
    np.testing.assert_allclose(transformed[:3, :3].T @ transformed[:3, :3], np.eye(3))


def test_render_metrics_psnr_matches_formula() -> None:
    target = np.zeros((4, 4, 3), dtype=np.uint8)
    render = RenderResult(
        rgb=np.full((4, 4, 3), 16, dtype=np.uint8),
        depth=np.ones((4, 4), dtype=np.float32),
        covered=np.ones((4, 4), dtype=bool),
        visible_points=1,
        input_points=1,
    )
    metrics = render_metrics(
        render, target, np.ones((4, 4), dtype=bool), minimum_covered=1
    )
    assert metrics["psnr"] is not None
    expected = 10.0 * np.log10(255.0**2 / 16.0**2)
    assert abs(float(metrics["psnr"]) - float(expected)) < 1e-6


def test_render_metrics_background_composite_reports_bg_variants() -> None:
    target = np.full((4, 4, 3), 200, dtype=np.uint8)  # bright background
    alpha = np.ones((4, 4), dtype=np.float32) * 0.0  # nothing covered
    render = RenderResult(
        rgb=np.zeros((4, 4, 3), dtype=np.uint8),  # black splat render
        depth=np.ones((4, 4), dtype=np.float32),
        covered=np.zeros((4, 4), dtype=bool),
        visible_points=0,
        input_points=1,
        alpha=alpha,
    )
    metrics = render_metrics(
        render,
        target,
        np.ones((4, 4), dtype=bool),
        minimum_covered=1,
        background_rgb=np.array([200.0, 200.0, 200.0]),
    )
    # With an opaque background the composited image matches the target.
    ssim_bg = metrics["ssim_bg"]
    psnr_full_bg = metrics["psnr_full_bg"]
    assert isinstance(ssim_bg, (int, float))
    assert isinstance(psnr_full_bg, (int, float))
    assert float(ssim_bg) == pytest.approx(1.0, abs=1e-6)
    assert float(psnr_full_bg) > 60.0
    # Legacy black-background variants are still reported.
    legacy_ssim = metrics["ssim"]
    assert isinstance(legacy_ssim, (int, float))
    assert float(legacy_ssim) < float(ssim_bg)


def test_select_heldout_views_excludes_inputs() -> None:
    def _camera(index: int) -> tuple[np.ndarray, np.ndarray, tuple[int, int]]:
        c2w = np.eye(4)
        c2w[:3, 3] = [float(index), 0.0, 1.0]
        return c2w, np.eye(3), (10, 10)

    cameras = {f"v{index}": _camera(index) for index in range(8)}
    chosen = select_heldout_views(cameras, exclude=("v0", "v1"), count=3, seed=0)
    assert len(chosen) == 3
    assert set(chosen).isdisjoint({"v0", "v1"})
