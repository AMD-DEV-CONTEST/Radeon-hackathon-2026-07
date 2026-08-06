from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
import torch
from PIL import Image

from colorgraph.devices import TorchComputeBackend
from colorgraph.domain.grade_graph import TimeRange
from colorgraph.vision.depth import DepthMaskProvider, ShotDepthCalibrator
from colorgraph.vision.video_depth_shadow import (
    OfficialVideoDepthAnythingRunner,
    audit_video_depth_installation,
    load_video_depth_manifest,
    run_video_depth_shadow,
)


class _FakeDepthProcessor:
    def __call__(self, **_: object) -> dict[str, torch.Tensor]:
        return {"pixel_values": torch.zeros((1, 3, 8, 12), dtype=torch.float32)}


class _FakeDepthModel:
    def __init__(self) -> None:
        self.calls = 0
        self.config = SimpleNamespace(_commit_hash="fake-depth-revision")

    def __call__(self, **_: object) -> SimpleNamespace:
        base = torch.linspace(0, 1, 96, dtype=torch.float32).reshape(1, 8, 12)
        base = base * 0.5 - 3.0 if self.calls else base * 2.0 + 5.0
        self.calls += 1
        return SimpleNamespace(predicted_depth=base)


class _StableShotRunner:
    def __init__(self) -> None:
        self.shot_lengths: list[int] = []

    def infer_shot(self, frames_rgb: np.ndarray, fps: float) -> np.ndarray:
        assert fps == 4
        self.shot_lengths.append(len(frames_rgb))
        height, width = frames_rgb.shape[1:3]
        base = np.linspace(0.1, 1.1, width, dtype=np.float32)
        base = np.broadcast_to(base, (height, width)).copy()
        return np.stack([base + index * 0.002 for index in range(len(frames_rgb))])


def _write_video(path: Path) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        4,
        (12, 8),
    )
    assert writer.isOpened()
    for index in range(8):
        writer.write(np.full((8, 12, 3), 30 + index * 20, dtype=np.uint8))
    writer.release()


def test_shot_calibrator_aligns_scale_shift_without_per_frame_percentiles() -> None:
    calibrator = ShotDepthCalibrator()
    calibrator.reset("shot_001")
    base = np.linspace(0, 1, 96, dtype=np.float32).reshape(8, 12)

    first = calibrator.calibrate(base * 2 + 5)
    second = calibrator.calibrate(base * 0.5 - 3)

    assert np.allclose(
        first.normalized_near_score,
        second.normalized_near_score,
        atol=1e-5,
    )
    assert second.scale == pytest.approx(4.0, rel=1e-5)
    assert second.alignment_residual < 1e-6
    assert 0 < second.uncertainty < 0.1
    assert first.shot_quantiles == second.shot_quantiles


def test_flat_depth_reports_uncertainty_instead_of_perfect_confidence() -> None:
    calibrated = ShotDepthCalibrator().calibrate(
        np.full((8, 12), 4.0, dtype=np.float32)
    )

    assert calibrated.uncertainty >= 0.9
    assert np.all(calibrated.normalized_near_score == 0)


def test_frame_fallback_persists_shot_scale_and_uncertainty_evidence() -> None:
    provider = DepthMaskProvider(
        TorchComputeBackend("cpu"),
        model_revision="a" * 40,
    )
    provider.__dict__["_processor_and_model"] = (
        _FakeDepthProcessor(),
        _FakeDepthModel(),
    )
    assert provider.model_revision == "a" * 40
    provider.reset_shot("shot_001")
    image = Image.fromarray(np.full((8, 12, 3), 128, dtype=np.uint8), mode="RGB")

    first = provider.predict_many(image, ["depth_near"])["depth_near"]
    second = provider.predict_many(image, ["depth_near"])["depth_near"]

    assert np.allclose(first.mask, second.mask, atol=1e-5)
    assert 0 < second.confidence < 1
    assert second.metadata["calibration_scope"] == "shot"
    assert second.metadata["shot_id"] == "shot_001"
    assert second.metadata["confidence_is_accuracy"] is False
    assert second.metadata["model_revision"] == "fake-depth-revision"
    assert second.metadata["scale"] == pytest.approx(4.0, rel=1e-5)
    assert second.score_semantics == "one_minus_temporal_scale_uncertainty"


def test_video_shadow_runs_per_shot_and_preserves_float_depth(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.avi"
    output = tmp_path / "video-depth-shadow.npz"
    _write_video(source)
    runner = _StableShotRunner()

    result = run_video_depth_shadow(
        source,
        [
            TimeRange(start_seconds=0, end_seconds=1),
            TimeRange(start_seconds=1, end_seconds=2),
        ],
        output,
        runner,
    )

    assert runner.shot_lengths == [4, 4]
    assert result.mode == "shadow"
    assert result.model_license == "Apache-2.0"
    assert result.float_depth_preserved
    assert result.frame_count == 8
    assert len(result.shot_statistics) == 2
    assert max(item.uncertainty_p95 for item in result.shot_statistics) < 0.1
    with np.load(output, allow_pickle=False) as payload:
        assert payload["inverse_depth"].dtype == np.float32
        assert payload["inverse_depth"].shape == (8, 8, 12)
        assert payload["normalized_near_score"].shape == (8, 8, 12)
        assert payload["uncertainty"].shape == (8,)
        assert payload["shot_index"].tolist() == [0, 0, 0, 0, 1, 1, 1, 1]


def test_shot_normalization_is_more_stable_than_per_frame_percentiles() -> None:
    base = np.linspace(0, 1, 100, dtype=np.float32).reshape(10, 10)
    frames = []
    for size in (1, 3, 5, 7):
        frame = base.copy()
        frame[:size, :size] = 4.0
        frames.append(frame)
    sequence = np.stack(frames)
    legacy = np.stack(
        [
            np.clip(
                (frame - np.percentile(frame, 2))
                / (np.percentile(frame, 98) - np.percentile(frame, 2)),
                0,
                1,
            )
            for frame in sequence
        ]
    )
    q05, q95 = np.percentile(sequence, (5, 95))
    shot_stable = np.clip((sequence - q05) / (q95 - q05), 0, 1)
    static_region = np.s_[..., 8:, 8:]
    legacy_change = float(
        np.mean(np.abs(np.diff(legacy[static_region], axis=0)))
    )
    stable_change = float(
        np.mean(np.abs(np.diff(shot_stable[static_region], axis=0)))
    )

    assert stable_change < legacy_change


def test_manifest_allows_only_apache_small_checkpoint() -> None:
    manifest = load_video_depth_manifest()

    assert manifest.encoder == "vits"
    assert manifest.license == "Apache-2.0"
    assert manifest.checkpoint.filename == "video_depth_anything_vits.pth"
    assert manifest.checkpoint.size_bytes == 116440756
    assert manifest.checkpoint.sha256 == (
        "13379300b739e659f076a59d52e9801bd8d38c541a7e71f73bbca4dcfb013609"
    )
    assert set(manifest.disallowed_default_variants) == {"vitb", "vitl"}


def test_missing_official_installation_stays_unavailable(tmp_path: Path) -> None:
    audit = audit_video_depth_installation(
        tmp_path / "missing-repository",
        tmp_path / "video_depth_anything_vitb.pth",
    )

    assert not audit.available
    assert not audit.source_commit_matches
    assert not audit.apache_license_present
    assert not audit.checkpoint_hash_matches
    assert any("repository is missing" in issue for issue in audit.issues)
    assert any("Small/vits" in issue for issue in audit.issues)

    with pytest.raises(RuntimeError, match="failed audit"):
        OfficialVideoDepthAnythingRunner(
            tmp_path / "missing-repository",
            tmp_path / "video_depth_anything_vitb.pth",
        )
