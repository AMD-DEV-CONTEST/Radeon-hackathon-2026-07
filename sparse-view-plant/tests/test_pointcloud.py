from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sparse_view_plant.pointcloud import (
    PointCloudPrediction,
    extract_conflict_budget_foreground,
    save_prediction,
)


def _prediction() -> PointCloudPrediction:
    return PointCloudPrediction(
        view_ids=("a", "b"),
        points=np.asarray([[0, 0, 0], [1, 1, 1], [2, 2, 2]], dtype=np.float32),
        colors=np.asarray([[0.1, 0.2, 0.3]] * 3, dtype=np.float32),
        confidence=np.asarray([0.1, 0.5, 0.9], dtype=np.float32),
        camera_to_world=np.eye(4, dtype=np.float32)[None].repeat(2, axis=0),
        metric_scale=1.0,
        image_sizes=((64, 64), (64, 64)),
    )


def test_save_prediction_writes_all_outputs(tmp_path: Path) -> None:
    paths = save_prediction(_prediction(), tmp_path, confidence_percentile=20.0)
    assert paths["pointcloud"].is_file()
    assert paths["raw"].is_file()
    assert paths["metrics"].is_file()
    header = paths["pointcloud"].read_bytes()[:128].decode("ascii", errors="replace")
    assert "element vertex 2" in header  # bottom 20% confidence dropped


def test_save_prediction_metrics(tmp_path: Path) -> None:
    import json

    save_prediction(_prediction(), tmp_path, confidence_percentile=20.0)
    metrics = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["input_points"] == 3
    assert metrics["kept_points"] == 2
    assert metrics["view_count"] == 2
    assert metrics["model"] == "vggt"


def test_save_prediction_keeps_everything_at_zero_percentile(tmp_path: Path) -> None:
    paths = save_prediction(_prediction(), tmp_path, confidence_percentile=0.0)
    header = paths["pointcloud"].read_bytes()[:128].decode("ascii", errors="replace")
    assert "element vertex 3" in header


def test_plant_fusion_budget_requires_birefnet(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="require birefnet"):
        save_prediction(_prediction(), tmp_path, plant_fusion_budget_fraction=0.5)


def test_extract_conflict_budget_prefers_non_conflicting_view() -> None:
    yy, xx = np.mgrid[0:2, 0:2]
    views = []
    for depth in (1.0, 2.0):
        views.append(
            np.stack(
                [(xx - 0.5) * depth, (yy - 0.5) * depth, np.full_like(xx, depth)],
                axis=-1,
            )
        )
    points = np.stack(views).astype(np.float32)
    prediction = PointCloudPrediction(
        view_ids=("a", "b"),
        points=points.reshape(-1, 3),
        colors=np.ones((8, 3), dtype=np.float32),
        confidence=np.asarray([0.9] * 4 + [0.1] * 4, dtype=np.float32),
        camera_to_world=np.eye(4, dtype=np.float32)[None].repeat(2, axis=0),
        metric_scale=1.0,
        image_sizes=((2, 2), (2, 2)),
        local_points=points.reshape(-1, 3),
        patch_hw=(2, 2),
    )
    selected, _, _, stats = extract_conflict_budget_foreground(
        prediction,
        np.ones((2, 2, 2), dtype=bool),
        keep_fraction=0.5,
        device="cpu",
    )
    np.testing.assert_allclose(selected[:, 2], 2.0)
    assert stats["selected"] == 4
