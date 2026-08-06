from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from colorgraph.config import settings
from colorgraph.domain.grade_graph import (
    ColorSpace,
    MaskAsset,
    MediaInfo,
    SpatialKind,
    TimeRange,
)
from colorgraph.grading.mask_integrity import MASK_ASSET_SCHEMA, inspect_mask_video
from colorgraph.quality import analyzer
from colorgraph.quality.banding import BANDING_METRIC_VERSION, cambi_equivalent_score
from colorgraph.quality.models import (
    AuxiliaryQualityScore,
    AuxiliaryScoreKind,
    CheckStatus,
    QualityCategory,
    QualityCheck,
)
from colorgraph.services.graph_builder import build_initial_graph


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _auxiliary(*, calibrated: bool = True) -> AuxiliaryQualityScore:
    return AuxiliaryQualityScore(
        id="dover:aesthetic",
        kind=AuxiliaryScoreKind.AESTHETIC_PREFERENCE,
        value=0.99,
        provider="dover",
        model_id="dover-domain",
        model_revision="frozen-test",
        calibration_id="landscape-v1",
        calibration_digest=_sha("landscape-v1"),
        domain_calibrated=calibrated,
        detail="Calibrated only as an auxiliary preference dimension.",
    )


def _metrics(*, banding: float, edge: float = 1.0) -> list[dict[str, float]]:
    return [
        {
            "highlight_clip": 0.0,
            "shadow_clip": 0.0,
            "oversaturation": 0.0,
            "mean_luma": 0.5,
            "edge_energy": edge,
            "banding_risk": banding,
            "non_finite_ratio": 0.0,
            "decoded_gamut_outside_ratio": 0.0,
        }
    ]


def _hard_check(*, passed: bool) -> QualityCheck:
    return QualityCheck(
        id="metadata",
        label="Metadata",
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        value=1.0 if passed else 0.0,
        threshold=1.0,
        unit="boolean",
        detail="Synthetic delivery gate.",
        category=QualityCategory.HARD_TECHNICAL,
        metric_version="test/v1",
    )


def test_cambi_equivalent_separates_smooth_posterized_and_textured_gradients() -> None:
    height, width = 180, 320
    smooth = np.tile(np.linspace(0, 1, width, dtype=np.float32), (height, 1))
    posterized = np.round(smooth * 15) / 15
    noise = np.random.default_rng(42).normal(0, 0.04, smooth.shape)
    textured = np.clip(smooth + noise, 0, 1)

    smooth_score = cambi_equivalent_score(smooth)
    posterized_score = cambi_equivalent_score(posterized)
    textured_score = cambi_equivalent_score(textured)

    assert smooth_score < 0.10
    assert posterized_score > 0.30
    assert posterized_score > smooth_score * 5
    assert textured_score < smooth_score
    assert BANDING_METRIC_VERSION == "colorgraph.cambi-equivalent/v1"


def test_delivery_checks_cover_finite_gamut_asset_pipeline_metadata_and_pts(
    tmp_path,
    monkeypatch,
) -> None:
    output = tmp_path / "output.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(
        analyzer,
        "probe_media",
        lambda _: SimpleNamespace(
            color_primaries="bt709",
            color_transfer="bt709",
            color_matrix="bt709",
            codec="h264",
            pixel_format="yuv420p",
            bit_depth=8,
        ),
    )
    monkeypatch.setattr(
        analyzer,
        "probe_frame_timings",
        lambda _: [SimpleNamespace(pts_seconds=0.0)],
    )

    checks = analyzer._delivery_checks(
        output,
        None,
        _metrics(banding=0),
        expected_frame_count=1,
    )

    by_id = {check.id: check for check in checks}
    assert {
        "finite_values",
        "output_gamut",
        "asset_integrity",
        "color_pipeline_schema",
        "metadata",
        "encoding",
        "frame_pts",
    } <= set(by_id)
    assert by_id["metadata"].status == CheckStatus.PASS
    assert by_id["frame_pts"].status == CheckStatus.PASS
    assert all(check.category == QualityCategory.HARD_TECHNICAL for check in checks)


def test_report_separates_hard_failures_risks_and_aesthetic_preferences(
    tmp_path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.mp4"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"source")
    output.write_bytes(b"output")
    samples = iter(
        [
            (_metrics(banding=0.0, edge=1.0), 0.2),
            (_metrics(banding=0.40, edge=0.5), 0.2),
        ]
    )
    monkeypatch.setattr(analyzer, "_sample_video", lambda *args, **kwargs: next(samples))
    monkeypatch.setattr(
        analyzer,
        "_mask_artifact_metrics",
        lambda *args, **kwargs: {
            "mask_jitter": 0.0,
            "mask_halo": 0.0,
            "sky_banding": 0.0,
        },
    )
    monkeypatch.setattr(
        analyzer,
        "_delivery_checks",
        lambda *args, **kwargs: [_hard_check(passed=False)],
    )

    report = analyzer.analyze_video_quality(
        source,
        output,
        auxiliary_scores=[_auxiliary()],
    )

    assert report.schema_version == "colorgraph.quality-report/v2"
    assert report.hard_checks_passed is False
    assert report.technical_hard_failures == ["metadata"]
    assert {"structure_loss", "banding_risk"} <= set(report.perceptual_risks)
    assert report.aesthetic_preferences[0].id == "dover:aesthetic"
    assert report.aesthetic_preferences[0].value == 0.99
    assert report.technical_score < 100
    assert report.perceptual_risk_score < 100
    assert "技术硬检查未通过" in report.summary


def test_perceptual_failure_does_not_masquerade_as_delivery_failure(
    tmp_path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.mp4"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"source")
    output.write_bytes(b"output")
    samples = iter(
        [
            (_metrics(banding=0.0), 0.2),
            (_metrics(banding=0.40), 0.2),
        ]
    )
    monkeypatch.setattr(analyzer, "_sample_video", lambda *args, **kwargs: next(samples))
    monkeypatch.setattr(
        analyzer,
        "_mask_artifact_metrics",
        lambda *args, **kwargs: {
            "mask_jitter": 0.0,
            "mask_halo": 0.0,
            "sky_banding": 0.0,
        },
    )
    monkeypatch.setattr(
        analyzer,
        "_delivery_checks",
        lambda *args, **kwargs: [_hard_check(passed=True)],
    )

    report = analyzer.analyze_video_quality(source, output)

    assert report.hard_checks_passed is True
    assert report.technical_hard_failures == []
    assert report.perceptual_risks == ["banding_risk"]
    assert "感知风险需复核" in report.summary


def test_uncalibrated_auxiliary_model_score_is_rejected(
    tmp_path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.mp4"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"source")
    output.write_bytes(b"output")
    samples = iter(
        [
            (_metrics(banding=0.0), 0.2),
            (_metrics(banding=0.0), 0.2),
        ]
    )
    monkeypatch.setattr(analyzer, "_sample_video", lambda *args, **kwargs: next(samples))
    monkeypatch.setattr(
        analyzer,
        "_mask_artifact_metrics",
        lambda *args, **kwargs: {
            "mask_jitter": 0.0,
            "mask_halo": 0.0,
            "sky_banding": 0.0,
        },
    )
    monkeypatch.setattr(
        analyzer,
        "_delivery_checks",
        lambda *args, **kwargs: [_hard_check(passed=True)],
    )

    with pytest.raises(ValueError, match="domain calibration"):
        analyzer.analyze_video_quality(
            source,
            output,
            auxiliary_scores=[_auxiliary(calibrated=False)],
        )


def test_mask_artifact_metrics_normalize_source_to_delivery_resolution(
    tmp_path,
    monkeypatch,
) -> None:
    mask_root = tmp_path / "sky-mask"
    mask_root.mkdir()
    source = tmp_path / "source-4k.mp4"
    output = tmp_path / "output-1080p.mp4"
    source.write_bytes(b"source")
    output.write_bytes(b"output")

    source_frame = np.full((216, 384, 3), 96, dtype=np.uint8)
    output_frame = np.full((108, 192, 3), 112, dtype=np.uint8)
    mask = np.full((216, 384), 255, dtype=np.uint8)
    for frame_index in range(3):
        assert cv2.imwrite(
            str(mask_root / f"{frame_index:06d}.png"),
            mask,
        )

    class _Capture:
        def __init__(self, frame: np.ndarray, fps: float) -> None:
            self.frame = frame
            self.fps = fps
            self.requested_frames: list[int] = []

        def get(self, property_id: int) -> float:
            return self.fps if property_id == cv2.CAP_PROP_FPS else 0.0

        def set(self, property_id: int, value: float) -> bool:
            if property_id == cv2.CAP_PROP_POS_FRAMES:
                self.requested_frames.append(round(value))
            return True

        def read(self) -> tuple[bool, np.ndarray]:
            return True, self.frame.copy()

        def release(self) -> None:
            return None

    captures: dict[str, _Capture] = {}

    def open_capture(path: str) -> _Capture:
        key = str(path)
        capture = _Capture(
            source_frame if key == str(source) else output_frame,
            4.0 if key == str(source) else 2.0,
        )
        captures[key] = capture
        return capture

    monkeypatch.setattr(analyzer.cv2, "VideoCapture", open_capture)
    graph = SimpleNamespace(
        shots=[],
        media=SimpleNamespace(frame_count=3),
        masks=[
            SimpleNamespace(
                id="mask_sky",
                target="sky",
                path=str(mask_root),
                frame_count=3,
            )
        ],
    )

    metrics = analyzer._mask_artifact_metrics(source, output, graph)

    assert set(metrics) == {
        "mask_jitter",
        "mask_halo",
        "sky_banding",
        "mask_frames_decoded",
        "mask_transition_samples",
        "sky_mask_samples",
        "sky_boundary_samples",
        "sky_banding_samples",
    }
    assert all(np.isfinite(value) and value >= 0 for value in metrics.values())
    assert metrics["mask_frames_decoded"] == 3
    assert metrics["mask_transition_samples"] == 2
    assert metrics["sky_mask_samples"] == 3
    assert metrics["sky_banding_samples"] == 3
    assert captures[str(source)].requested_frames == [0, 1, 2]
    assert captures[str(output)].requested_frames == [0, 0, 1]
    assert (
        analyzer._resize_frame_to_delivery(
            source_frame,
            width=192,
            height=108,
        ).shape
        == output_frame.shape
    )


def test_mask_artifact_metrics_decode_retained_ffv1_when_pngs_are_removed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    frame_count = 4
    fps = 5.0
    width = 64
    height = 36
    sequence_root = tmp_path / "sky-mask"
    sequence_root.mkdir()
    for frame_index in range(frame_count):
        mask = np.zeros((height, width), dtype=np.uint16)
        mask[:, : 24 + frame_index * 3] = 65535
        assert cv2.imwrite(
            str(sequence_root / f"{frame_index:06d}.png"),
            mask,
        )

    video_path = tmp_path / "sky-mask.mkv"
    encoded = subprocess.run(
        [
            settings.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(sequence_root / "%06d.png"),
            "-c:v",
            "ffv1",
            "-level",
            "3",
            "-pix_fmt",
            "gray16le",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert encoded.returncode == 0, encoded.stderr
    inspection = inspect_mask_video(
        video_path,
        expected_frame_count=frame_count,
        expected_width=width,
        expected_height=height,
        expected_fps=fps,
        expected_pixel_format="gray16le",
    )
    for path in sequence_root.glob("*.png"):
        path.unlink()

    source = tmp_path / "source.mp4"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"source")
    output.write_bytes(b"output")
    graph = build_initial_graph(
        project_id="ffv1-quality",
        project_name="FFV1 Quality",
        media=MediaInfo(
            path=str(source),
            duration_seconds=frame_count / fps,
            width=width,
            height=height,
            fps=fps,
            frame_count=frame_count,
            codec="h264",
            input_color_space=ColorSpace.BT709_OETF,
        ),
        shot_ranges=[
            TimeRange(
                start_seconds=0,
                end_seconds=frame_count / fps,
            )
        ],
        representative_frames=[tmp_path / "representative.jpg"],
    )
    graph.masks = [
        MaskAsset(
            id="mask_sky",
            kind=SpatialKind.SEMANTIC,
            target="sky",
            path=str(sequence_root),
            frame_count=frame_count,
            metadata={
                "schema": MASK_ASSET_SCHEMA,
                "target": "sky",
                "target_aliases": ["sky", "mask_sky"],
                "file_pattern": None,
                "storage": {
                    "primary": "ffv1_video",
                    "sequence_format": "png",
                    "sample_dtype": "uint16",
                    "bit_depth": 16,
                    "quantization_levels": 65536,
                    "maximum_quantization_error": 0.5 / 65535,
                    "preferred_decode": "video_ffmpeg",
                    "sequence_retained": False,
                    "video_pixel_format": "gray16le",
                },
                "frame_count": frame_count,
                "file_count": 0,
                "width": width,
                "height": height,
                "fps": fps,
                "sequence_sha256": None,
                "video_path": str(video_path),
                "video_sha256": inspection.sha256,
                "decode_verified": True,
                "missing_frame_policy": "error",
            },
        )
    ]

    source_frame = np.full((height, width, 3), 96, dtype=np.uint8)
    output_frame = np.full((height, width, 3), 112, dtype=np.uint8)

    class _Capture:
        def __init__(self, frame: np.ndarray) -> None:
            self.frame = frame

        def get(self, property_id: int) -> float:
            return fps if property_id == cv2.CAP_PROP_FPS else 0.0

        def set(self, _property_id: int, _value: float) -> bool:
            return True

        def read(self) -> tuple[bool, np.ndarray]:
            return True, self.frame.copy()

        def release(self) -> None:
            return None

    monkeypatch.setattr(
        analyzer.cv2,
        "VideoCapture",
        lambda path: _Capture(source_frame if str(path) == str(source) else output_frame),
    )

    metrics = analyzer._mask_artifact_metrics(source, output, graph)

    assert not list(sequence_root.glob("*.png"))
    assert metrics["mask_frames_decoded"] == frame_count
    assert metrics["mask_transition_samples"] == frame_count - 1
    assert metrics["sky_mask_samples"] == frame_count
    assert metrics["sky_boundary_samples"] == frame_count
    assert metrics["sky_banding_samples"] == frame_count
    assert metrics["mask_jitter"] > 0
