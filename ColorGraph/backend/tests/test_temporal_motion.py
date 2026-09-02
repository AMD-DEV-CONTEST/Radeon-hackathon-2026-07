from __future__ import annotations

from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from colorgraph.quality import analyzer
from colorgraph.quality.temporal_motion import (
    TEMPORAL_METRIC_VERSION,
    TemporalAnalysisConfig,
    TemporalClassification,
    analyze_temporal_frames,
    analyze_video_temporal,
)


def _bgr(luma: np.ndarray) -> np.ndarray:
    return np.round(np.repeat(luma[..., None], 3, axis=2) * 255).astype(np.uint8)


def _frame_metrics(mean_luma: float) -> dict[str, float]:
    return {
        "highlight_clip": 0.0,
        "shadow_clip": 0.0,
        "oversaturation": 0.0,
        "mean_luma": mean_luma,
        "edge_energy": 1.0,
        "banding_risk": 0.0,
        "non_finite_ratio": 0.0,
        "decoded_gamut_outside_ratio": 0.0,
    }


def test_camera_pan_and_attached_mask_are_motion_compensated() -> None:
    height, width = 96, 160
    rng = np.random.default_rng(7)
    gradient = np.linspace(0.05, 0.95, 190, dtype=np.float32)
    world = np.tile(gradient, (height, 1))
    world = np.clip(world + rng.normal(0, 0.03, world.shape), 0, 1)
    source = [_bgr(world[:, :width]), _bgr(world[:, 8 : 8 + width])]
    mask_a = np.zeros((height, width), dtype=np.float32)
    mask_b = np.zeros_like(mask_a)
    mask_a[25:72, 70:110] = 1
    mask_b[25:72, 62:102] = 1

    report = analyze_temporal_frames(
        source,
        source,
        masks={"subject": [mask_a, mask_b]},
        mask_targets={"subject": "subject"},
    )

    transition = report.transitions[0]
    mask = transition.masks[0]
    assert transition.classification == TemporalClassification.CAMERA_OR_OBJECT_MOTION
    assert report.raw_flicker_p95 > 0.035
    assert report.flicker_p95 < 0.005
    assert transition.camera_motion_x == pytest.approx(8, abs=0.25)
    assert mask.raw_mae > 0.04
    assert mask.motion_compensated_mae < 0.001
    assert mask.jitter_score < 0.01
    assert mask.motion_reduction_ratio > 0.99
    assert report.suppressed_source_change_transitions == 1


def test_mask_motion_without_source_motion_is_kept_as_jitter() -> None:
    rng = np.random.default_rng(71)
    source = _bgr(rng.random((96, 160), dtype=np.float32) * 0.60 + 0.20)
    mask_a = np.zeros((96, 160), dtype=np.float32)
    mask_b = np.zeros_like(mask_a)
    mask_a[24:72, 55:105] = 1
    mask_b[24:72, 58:108] = 1

    report = analyze_temporal_frames(
        [source, source],
        [source, source],
        masks={"subject": [mask_a, mask_b]},
        mask_targets={"subject": "subject"},
    )

    evidence = report.transitions[0].masks[0]
    assert evidence.motion_compensated_mae > 0.015
    assert evidence.boundary_mae > 0.30
    assert evidence.jitter_score > 0.15


def test_source_exposure_jump_is_not_reported_as_grade_flicker() -> None:
    rng = np.random.default_rng(19)
    base = rng.random((96, 160), dtype=np.float32) * 0.55 + 0.15
    brighter = np.clip(base * 1.30, 0, 1)

    report = analyze_temporal_frames(
        [_bgr(base), _bgr(brighter)],
        [_bgr(np.sqrt(base)), _bgr(np.sqrt(brighter))],
    )

    transition = report.transitions[0]
    assert transition.classification == TemporalClassification.SOURCE_EXPOSURE_JUMP
    assert transition.source_exposure_stops == pytest.approx(np.log2(1.3), abs=0.03)
    assert transition.exposure_uniformity > 0.90
    assert report.raw_flicker_p95 > 0.08
    assert report.flicker_p95 < 0.005


def test_local_source_luminance_change_has_region_evidence() -> None:
    rng = np.random.default_rng(4)
    first = rng.random((96, 160), dtype=np.float32) * 0.35 + 0.30
    second = first.copy()
    second[20:76, 45:115] = np.clip(
        second[20:76, 45:115] + 0.12,
        0,
        1,
    )

    report = analyze_temporal_frames(
        [_bgr(first), _bgr(second)],
        [_bgr(first), _bgr(second)],
    )

    transition = report.transitions[0]
    assert transition.classification == TemporalClassification.SOURCE_LUMINANCE_CHANGE
    assert transition.grade_flicker_score < 1e-6
    assert transition.regions
    assert transition.regions[0].kind == "source_change"


def test_local_grade_flicker_has_frame_and_region_evidence() -> None:
    rng = np.random.default_rng(5)
    source_luma = rng.random((96, 160), dtype=np.float32) * 0.60 + 0.20
    source = _bgr(source_luma)
    output_a = source.astype(np.float32) / 255.0
    output_b = output_a.copy()
    output_b[24:72, 50:110] = np.clip(
        output_b[24:72, 50:110] + 0.10,
        0,
        1,
    )

    report = analyze_temporal_frames(
        [source, source],
        [output_a, output_b],
        frame_indices=[100, 101],
        fps=25,
    )

    transition = report.transitions[0]
    assert transition.classification == TemporalClassification.GRADE_INDUCED_FLICKER
    assert transition.frame_index == 101
    assert transition.time_seconds == pytest.approx(4.04)
    assert report.flicker_p95 > 0.09
    assert transition.regions
    region = transition.regions[0]
    assert region.kind == "grade_delta"
    assert region.x == pytest.approx(50, abs=2)
    assert region.y == pytest.approx(24, abs=2)
    assert region.width == pytest.approx(60, abs=4)
    assert region.height == pytest.approx(48, abs=4)


def test_cloud_or_water_motion_is_separated_using_region_evidence() -> None:
    height, width = 96, 160
    rng = np.random.default_rng(11)
    first = np.full((height, width), 0.45, dtype=np.float32)
    second = first.copy()
    water_a = cv2.GaussianBlur(
        rng.random((40, width), dtype=np.float32),
        (0, 0),
        2,
    )
    water_b = np.roll(water_a, 5, axis=1)
    water_b = np.clip(water_b + rng.normal(0, 0.10, water_b.shape), 0, 1)
    first[56:] = 0.10 + 0.70 * water_a
    second[56:] = 0.10 + 0.70 * water_b
    water_mask = np.zeros((height, width), dtype=np.float32)
    water_mask[54:] = 1

    report = analyze_temporal_frames(
        [_bgr(first), _bgr(second)],
        [_bgr(first), _bgr(second)],
        masks={"water": [water_mask, water_mask]},
        mask_targets={"water": "water"},
    )

    transition = report.transitions[0]
    assert transition.classification == TemporalClassification.CLOUD_OR_WATER_MOTION
    assert transition.source_motion_residual_p95 > 0.08
    assert transition.grade_flicker_score < 1e-6
    assert any("water" in region.overlapping_mask_targets for region in transition.regions)


def test_hard_cut_transition_is_preserved_as_excluded_evidence() -> None:
    black = np.zeros((64, 96, 3), dtype=np.uint8)
    white = np.full_like(black, 255)

    report = analyze_temporal_frames(
        [black, white],
        [black, white],
        frame_indices=[10, 20],
        cut_frame_indices={15},
    )

    assert report.analyzed_transitions == 0
    assert report.excluded_cut_transitions == 1
    assert report.transitions[0].classification == TemporalClassification.HARD_CUT
    assert report.transitions[0].excluded is True


def test_video_temporal_pairs_different_frame_rates_by_timestamp(
    monkeypatch,
) -> None:
    source_path = "source-4fps.mp4"
    output_path = "output-2fps.mp4"

    def frames(values: list[int]) -> list[np.ndarray]:
        return [np.full((32, 32, 3), value, dtype=np.uint8) for value in values]

    streams = {
        source_path: (4.0, frames([0, 25, 50, 75, 100])),
        output_path: (2.0, frames([0, 50, 100])),
    }

    class _Capture:
        def __init__(self, fps: float, stream_frames: list[np.ndarray]) -> None:
            self.fps = fps
            self.frames = stream_frames
            self.index = 0

        def isOpened(self) -> bool:
            return True

        def get(self, property_id: int) -> float:
            return self.fps if property_id == cv2.CAP_PROP_FPS else 0.0

        def read(self) -> tuple[bool, np.ndarray | None]:
            if self.index >= len(self.frames):
                return False, None
            frame = self.frames[self.index]
            self.index += 1
            return True, frame.copy()

        def release(self) -> None:
            return None

    monkeypatch.setattr(
        "colorgraph.quality.temporal_motion.cv2.VideoCapture",
        lambda path: _Capture(*streams[str(path)]),
    )

    report = analyze_video_temporal(
        source_path,
        output_path,
        sample_fps=2,
        config=TemporalAnalysisConfig(analysis_width=32),
    )

    assert report.sampled_frames == 3
    assert [item.frame_index for item in report.transitions] == [2, 4]
    assert [item.time_seconds for item in report.transitions] == pytest.approx([0.5, 1.0])
    assert all(
        item.raw_source_mean_delta == pytest.approx(item.raw_output_mean_delta)
        for item in report.transitions
    )


def test_quality_report_uses_motion_compensated_metric_and_keeps_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    source_path = tmp_path / "source.mp4"
    output_path = tmp_path / "output.mp4"
    source_path.write_bytes(b"source")
    output_path.write_bytes(b"output")
    frame = np.full((64, 96, 3), 96, dtype=np.uint8)
    brighter = np.clip(frame.astype(np.float32) / 255.0 + 0.08, 0, 1)
    evidence = analyze_temporal_frames(
        [frame, frame],
        [frame, brighter],
    )
    samples = iter(
        [
            ([_frame_metrics(0.38), _frame_metrics(0.38)], 0.2),
            ([_frame_metrics(0.38), _frame_metrics(0.46)], 0.2),
        ]
    )
    monkeypatch.setattr(analyzer, "_sample_video", lambda *args, **kwargs: next(samples))
    monkeypatch.setattr(analyzer, "analyze_video_temporal", lambda *args, **kwargs: evidence)
    monkeypatch.setattr(
        analyzer,
        "_mask_artifact_metrics",
        lambda *args, **kwargs: {
            "mask_jitter": 0.0,
            "mask_halo": 0.0,
            "sky_banding": 0.0,
        },
    )
    monkeypatch.setattr(analyzer, "_delivery_checks", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        analyzer,
        "probe_media",
        lambda _: SimpleNamespace(),
    )

    report = analyzer.analyze_video_quality(source_path, output_path)
    check = next(item for item in report.checks if item.id == "temporal_flicker")

    assert report.temporal_evidence == evidence
    assert check.metric_version == TEMPORAL_METRIC_VERSION
    assert check.value == pytest.approx(evidence.flicker_p95)
    assert report.metrics["raw_flicker_p95"] == pytest.approx(evidence.raw_flicker_p95)
