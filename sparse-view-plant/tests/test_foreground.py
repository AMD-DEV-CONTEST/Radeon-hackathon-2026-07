"""Tests for the mask-free deployed foreground extraction."""

from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from sparse_view_plant.images import InputImage
from sparse_view_plant.pointcloud import (
    PointCloudPrediction,
    extract_deployed_foreground,
)


def _synthetic_prediction(
    *, patch_hw: tuple[int, int] = (64, 64)
) -> PointCloudPrediction:
    grid_h, grid_w = patch_hw
    view_count = 2
    rng = np.random.default_rng(0)
    yy, xx = np.mgrid[0:grid_h, 0:grid_w]
    centre = ((xx - grid_w / 2) / (grid_w / 2)) ** 2 + (
        (yy - grid_h / 2) / (grid_h / 2)
    ) ** 2
    confidence = np.where(
        centre <= 0.4**2, rng.uniform(0.5, 0.9, (view_count, grid_h, grid_w)), 0.05
    )
    points = np.stack(
        [xx[None] * 0.01, yy[None] * 0.01, np.zeros((1, grid_h, grid_w))], axis=-1
    )
    points = np.repeat(points, view_count, axis=0).reshape(-1, 3)
    colors = np.full((view_count, grid_h, grid_w, 3), 0.5).reshape(-1, 3)
    return PointCloudPrediction(
        view_ids=("v0", "v1"),
        points=points.astype(np.float32),
        colors=colors.astype(np.float32),
        confidence=confidence.reshape(-1).astype(np.float32),
        camera_to_world=np.repeat(np.eye(4)[None], view_count, axis=0).astype(
            np.float32
        ),
        metric_scale=1.0,
        image_sizes=((1080, 1080), (1080, 1080)),
        patch_hw=patch_hw,
    )


def test_extract_drops_low_confidence_periphery() -> None:
    prediction = _synthetic_prediction()
    points, colors, confidence = extract_deployed_foreground(
        prediction, center_radius=0.7, confidence_percentile=40.0
    )
    patch_hw = prediction.patch_hw
    assert patch_hw is not None
    grid_h, grid_w = patch_hw
    per_view = grid_h * grid_w
    # Every kept pixel must come from the high-confidence central blob.
    conf_map = prediction.confidence.reshape(2, grid_h, grid_w)
    assert confidence.min() >= float(np.percentile(conf_map, 60.0))
    assert len(points) < per_view  # background pixels were dropped
    assert points.shape[1] == 3 and colors.shape[1] == 3
    assert confidence.shape == (len(points),)


def test_extract_center_prior_is_the_loose_selector() -> None:
    prediction = _synthetic_prediction()
    # Uniform high confidence everywhere: only the center prior decides.
    uniform = replace(
        prediction,
        confidence=np.full_like(prediction.confidence, 0.9),
    )
    points_loose, _, _ = extract_deployed_foreground(
        uniform, center_radius=1.5, confidence_percentile=40.0
    )
    points_tight, _, _ = extract_deployed_foreground(
        uniform, center_radius=0.4, confidence_percentile=40.0
    )
    assert len(points_loose) == uniform.points.shape[0]  # whole frame allowed
    assert len(points_tight) < len(points_loose)  # central ellipse is a real cut


def test_extract_rejects_bad_percentile() -> None:
    prediction = _synthetic_prediction()
    with pytest.raises(ValueError):
        extract_deployed_foreground(
            prediction, center_radius=0.7, confidence_percentile=100.0
        )


def test_foreground_masks_dispatches_maskfree() -> None:
    """The maskfree provider keeps central high-confidence cells and resizes."""
    from sparse_view_plant.foreground import foreground_masks

    grid_h, grid_w, view_count = 32, 32, 2
    rng = np.random.default_rng(1)
    yy, xx = np.mgrid[0:grid_h, 0:grid_w]
    centre = ((xx - grid_w / 2) / (grid_w / 2)) ** 2 + (
        (yy - grid_h / 2) / (grid_h / 2)
    ) ** 2
    confidence = (
        np.where(
            centre <= 0.5**2, rng.uniform(0.5, 0.9, (view_count, grid_h, grid_w)), 0.1
        )
        .reshape(-1)
        .astype(np.float32)
    )
    masks = foreground_masks(
        "maskfree",
        images=[],
        resolution=16,
        confidence=confidence,
        patch_hw=(grid_h, grid_w),
        view_count=view_count,
    )
    assert masks.shape == (view_count, 16, 16)
    assert masks.min() >= 0.0 and masks.max() <= 1.0
    # the central region survives at full resolution and is resized smoothly
    assert masks[:, 7:9, 7:9].mean() > 0.5


def test_foreground_masks_rejects_unknown_provider() -> None:
    from sparse_view_plant.foreground import foreground_masks

    with pytest.raises(ValueError, match="unknown foreground mask provider"):
        foreground_masks("nope", images=[], resolution=16)


def test_foreground_masks_loads_sibling_mask_files(tmp_path) -> None:
    from sparse_view_plant.foreground import foreground_masks

    rgb_dir = tmp_path / "images" / "rgb"
    mask_dir = tmp_path / "images" / "mask"
    rgb_dir.mkdir(parents=True)
    mask_dir.mkdir()
    image_path = rgb_dir / "view.png"
    Image.new("RGB", (8, 8)).save(image_path)
    mask = np.zeros((8, 8), dtype=np.uint8)
    mask[2:6, 2:6] = 255
    Image.fromarray(mask).save(mask_dir / "view.png.png")
    result = foreground_masks("file", [InputImage("view", image_path)], resolution=8)
    assert result.shape == (1, 8, 8)
    assert result.sum() == 16


def test_grid_trim_mask_maskfree_is_grid_aligned() -> None:
    """The grid trim keeps the same cells as the image-space maskfree mask."""
    from sparse_view_plant.foreground import grid_trim_mask

    grid_h, grid_w, view_count = 32, 32, 2
    rng = np.random.default_rng(2)
    yy, xx = np.mgrid[0:grid_h, 0:grid_w]
    centre = ((xx - grid_w / 2) / (grid_w / 2)) ** 2 + (
        (yy - grid_h / 2) / (grid_h / 2)
    ) ** 2
    confidence = (
        np.where(
            centre <= 0.4**2, rng.uniform(0.6, 0.9, (view_count, grid_h, grid_w)), 0.05
        )
        .reshape(-1)
        .astype(np.float32)
    )
    trim = grid_trim_mask(
        "maskfree",
        images=[],
        confidence=confidence,
        patch_hw=(grid_h, grid_w),
        view_count=view_count,
    )
    assert trim.shape == (view_count, grid_h, grid_w)
    assert set(np.unique(trim)) <= {0.0, 1.0}
    # cells near the center and high confidence survive; corners do not
    assert trim[:, grid_h // 2, grid_w // 2].all()
    assert not trim[:, 0, 0].any()


def test_grid_trim_mask_rejects_unknown_provider() -> None:
    from sparse_view_plant.foreground import grid_trim_mask

    with pytest.raises(ValueError, match="unknown grid trim provider"):
        grid_trim_mask("nope", images=[], patch_hw=(32, 32))


def test_birefnet_empty_view_gets_cross_view_fallback() -> None:
    """An empty salient mask is replaced by the mean of the other views."""
    from sparse_view_plant.foreground import _fill_empty_masks

    resolution = 32
    rng = np.random.default_rng(3)
    masks = rng.random((3, resolution, resolution)) > 0.7
    masks[1] = 0.0  # view 1 fails
    masks = masks.astype(np.float32)
    filled, count = _fill_empty_masks(masks)
    assert count == 1
    assert filled.shape == masks.shape
    assert filled[1].mean() > 0.0  # the failed view is now supervised
    assert (filled[[0, 2]] == masks[[0, 2]]).all()  # healthy views untouched


def test_birefnet_all_empty_falls_back_to_central_ellipse() -> None:
    """When every view fails, the central-ellipse prior keeps supervision on."""
    from sparse_view_plant.foreground import _fill_empty_masks

    resolution = 32
    masks = np.zeros((2, resolution, resolution), dtype=np.float32)
    filled, count = _fill_empty_masks(masks)
    assert count == 2
    assert filled.mean() > 0.0
    # the fallback is centred and symmetric
    assert filled[0, resolution // 2, resolution // 2] > 0.0
    assert filled[0, 0, 0] == 0.0
