import math
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest

from colorgraph.domain.grade_graph import ColorSpace, MediaInfo, NodeType, TimeRange
from colorgraph.grading.color import DJI_DLOG_DGAMUT, DJI_MAVIC3_DLOG_REC709
from colorgraph.grading.official_luts import ensure_dji_mavic3_dlog_to_rec709_lut
from colorgraph.media.color_analysis import (
    COLOR_ANALYSIS_VERSION,
    _encoded_to_linear_rec709,
    _robust_trend_filter,
    analyze_frame,
    analyze_video_color,
)
from colorgraph.services.graph_builder import build_initial_graph


def _legacy_estimates(frame_bgr: np.ndarray) -> tuple[float, float]:
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    linear = _encoded_to_linear_rec709(rgb, ColorSpace.BT709_OETF, None)
    luma = np.einsum(
        "hwi,i->hw",
        linear,
        np.asarray([0.2126, 0.7152, 0.0722], dtype=np.float32),
    )
    log_average = float(np.exp(np.mean(np.log(np.clip(luma, 1e-5, None)))))
    exposure = float(np.clip(math.log2(0.18 / max(log_average, 1e-5)), -1.5, 1.5))
    neutral = np.percentile(linear.reshape(-1, 3), 70, axis=0)
    channel_mean = max(float(neutral.mean()), 1e-5)
    temperature = float(
        np.clip((neutral[2] - neutral[0]) / channel_mean * 0.55, -0.65, 0.65)
    )
    return exposure, temperature


@pytest.mark.parametrize(
    ("color_space", "encoded_middle_gray"),
    [
        (ColorSpace.SRGB, 0.46135612950044164),
        (ColorSpace.BT709_OETF, 0.4090077288641504),
        (ColorSpace.REC1886, 0.4894370895738783),
        (ColorSpace.ACESCCT, 0.41358840249244233),
    ],
)
def test_analysis_uses_explicit_input_encoding(
    color_space: ColorSpace,
    encoded_middle_gray: float,
) -> None:
    encoded = np.full((1, 1, 3), encoded_middle_gray, dtype=np.float64)
    linear = _encoded_to_linear_rec709(encoded, color_space, None)

    assert np.allclose(linear, 0.18, atol=5e-10)


def test_analysis_rejects_ambiguous_legacy_rec709() -> None:
    with pytest.raises(ValueError, match="ambiguous legacy color space"):
        _encoded_to_linear_rec709(
            np.zeros((1, 1, 3), dtype=np.float32),
            ColorSpace.REC709,
            None,
        )


@pytest.mark.parametrize("color_space", [ColorSpace.ACES2065_1, ColorSpace.ACESCG])
def test_analysis_accepts_aces_scene_linear_inputs(color_space: ColorSpace) -> None:
    encoded = np.full((1, 1, 3), 0.18, dtype=np.float32)
    linear = _encoded_to_linear_rec709(encoded, color_space, None)
    assert np.allclose(linear, 0.18, rtol=0, atol=2e-6)


def test_dark_frame_requests_positive_exposure() -> None:
    frame = np.full((120, 160, 3), 32, dtype=np.uint8)
    statistics = analyze_frame(frame, time_seconds=1.25)
    assert statistics.exposure > 0
    assert statistics.time_seconds == 1.25


def test_blue_cast_requests_warmer_balance() -> None:
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    frame[..., 0] = 180
    frame[..., 1] = 100
    frame[..., 2] = 70
    statistics = analyze_frame(frame, time_seconds=0)
    assert statistics.temperature > 0


def test_snow_is_excluded_instead_of_forced_to_middle_gray() -> None:
    frame = np.full((180, 320, 3), 235, dtype=np.uint8)
    frame[100:170, 130:210] = 100

    legacy_exposure, _ = _legacy_estimates(frame)
    statistics = analyze_frame(frame, time_seconds=0)

    assert legacy_exposure == -1.5
    assert statistics.excluded_snow_ratio > 0.85
    assert statistics.exposure_valid_sample_ratio < 0.15
    assert statistics.exposure_uncertainty > 0.7
    assert abs(statistics.exposure) < 0.1


def test_sunset_dominant_color_abstains_from_white_balance() -> None:
    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    for column in range(frame.shape[1]):
        fraction = column / (frame.shape[1] - 1)
        frame[:, column] = [
            round(25 + 25 * fraction),
            round(65 + 45 * fraction),
            round(210 + 35 * fraction),
        ]

    _, legacy_temperature = _legacy_estimates(frame)
    statistics = analyze_frame(frame, time_seconds=0)

    assert abs(legacy_temperature) > 0.6
    assert statistics.excluded_neon_ratio > 0.95
    assert statistics.white_balance_valid_sample_ratio == 0
    assert statistics.white_balance_uncertainty > 0.85
    assert abs(statistics.temperature) < 0.1


def test_night_scene_remains_low_key() -> None:
    frame = np.full((180, 320, 3), 12, dtype=np.uint8)
    frame[40:48, 40:48] = [180, 220, 255]
    frame[80:85, 200:205] = [150, 190, 255]

    legacy_exposure, _ = _legacy_estimates(frame)
    statistics = analyze_frame(frame, time_seconds=0)

    assert legacy_exposure == 1.5
    assert 0 < statistics.exposure < 0.5
    assert statistics.exposure < legacy_exposure / 3


def test_mixed_lighting_reports_white_balance_uncertainty() -> None:
    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    frame[:, :160] = [155, 125, 105]
    frame[:, 160:] = [105, 125, 155]

    statistics = analyze_frame(frame, time_seconds=0)

    assert statistics.white_balance_valid_sample_ratio == 0
    assert statistics.white_balance_uncertainty == 1
    assert abs(statistics.temperature) < 0.05
    assert (
        statistics.excluded_sky_ratio
        + statistics.excluded_dominant_color_ratio
        > 0.95
    )


def test_sky_does_not_bias_neutral_ground_white_balance() -> None:
    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    frame[:100] = [210, 150, 90]
    frame[100:] = [110, 110, 110]

    _, legacy_temperature = _legacy_estimates(frame)
    statistics = analyze_frame(frame, time_seconds=0)

    assert legacy_temperature > 0.5
    assert statistics.excluded_sky_ratio > 0.5
    assert statistics.white_balance_valid_sample_ratio > 0.4
    assert abs(statistics.temperature) < 0.02


def test_robust_trend_filter_rejects_flicker_but_preserves_sustained_change() -> None:
    base = analyze_frame(
        np.full((120, 160, 3), 100, dtype=np.uint8),
        time_seconds=0,
    )
    samples = [replace(base, time_seconds=index * 0.5) for index in range(7)]
    uncertainties = [0.08] * len(samples)

    flicker = _robust_trend_filter(
        samples,
        [0, 0, 0, 1.2, 0, 0, 0],
        uncertainties,
        smoothing_strength=0.04,
        noise_floor=0.04,
    )
    sustained = _robust_trend_filter(
        samples,
        [0, 0, 0, 0.5, 0.5, 0.5, 0.5],
        uncertainties,
        smoothing_strength=0.04,
        noise_floor=0.04,
    )

    assert abs(float(flicker[3])) < 0.05
    assert float(sustained[2]) < 0.1
    assert float(sustained[4]) > 0.45


def test_rapid_exposure_change_produces_one_adaptive_change_point(
    tmp_path: Path,
) -> None:
    video = tmp_path / "rapid-exposure.avi"
    writer = cv2.VideoWriter(
        str(video),
        cv2.VideoWriter_fourcc(*"MJPG"),
        4,
        (160, 120),
    )
    assert writer.isOpened()
    for value in [85] * 6 + [165] * 6:
        writer.write(np.full((120, 160, 3), value, dtype=np.uint8))
    writer.release()

    analysis = analyze_video_color(
        video,
        [TimeRange(start_seconds=0, end_seconds=3)],
        sample_fps=4,
    )[0]

    assert analysis.lighting_change_points == [1.5]
    assert len(analysis.exposure_keyframes) == 4
    assert analysis.exposure_keyframes[1].time_seconds == 1.25
    assert analysis.exposure_keyframes[2].time_seconds == 1.5
    assert analysis.exposure_keyframes[1].value > 0.1
    assert analysis.exposure_keyframes[2].value < -0.4

    graph = build_initial_graph(
        project_id="analysis-evidence",
        project_name="Analysis evidence",
        media=MediaInfo(
            path=str(video),
            duration_seconds=3,
            width=160,
            height=120,
            fps=4,
            frame_count=12,
            codec="mjpeg",
        ),
        shot_ranges=[TimeRange(start_seconds=0, end_seconds=3)],
        representative_frames=[video],
        color_analyses=[analysis],
    )
    balance = next(node for node in graph.nodes if node.type == NodeType.BALANCE)
    evidence = balance.metadata["color_analysis"]

    assert graph.metadata["color_analysis_version"] == COLOR_ANALYSIS_VERSION
    assert evidence["version"] == COLOR_ANALYSIS_VERSION
    assert evidence["exposure"]["estimate_ev"] == analysis.exposure
    assert (
        evidence["exposure"]["valid_sample_ratio"]
        == analysis.exposure_valid_sample_ratio
    )
    assert evidence["exposure"]["uncertainty_ev"] == analysis.exposure_uncertainty
    assert (
        evidence["trajectory"]["method"]
        == "uncertainty_weighted_robust_trend_filter"
    )


def test_dji_dlog_mid_gray_is_analyzed_in_linear_working_space() -> None:
    frame = np.full((120, 160, 3), round(408 / 1023 * 255), dtype=np.uint8)
    statistics = analyze_frame(
        frame,
        time_seconds=0,
        input_color_space=ColorSpace.LOG,
        source_log_profile=DJI_DLOG_DGAMUT,
    )

    assert abs(statistics.exposure) < 0.05
    assert abs(statistics.mean_luma - 0.18) < 0.01


def test_mavic3_official_transform_preserves_camera_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lut = tmp_path / "identity.cube"
    lut.write_text(
        "\n".join(
            [
                "LUT_3D_SIZE 2",
                "0 0 0",
                "1 0 0",
                "0 1 0",
                "1 1 0",
                "0 0 1",
                "1 0 1",
                "0 1 1",
                "1 1 1",
            ]
        ),
        encoding="utf-8",
    )
    video = tmp_path / "bright-neutral.avi"
    writer = cv2.VideoWriter(
        str(video),
        cv2.VideoWriter_fourcc(*"MJPG"),
        4,
        (64, 48),
    )
    assert writer.isOpened()
    for _ in range(8):
        writer.write(np.full((48, 64, 3), 190, dtype=np.uint8))
    writer.release()

    monkeypatch.setenv("COLORGRAPH_DJI_MAVIC3_DLOG_LUT", str(lut))
    ensure_dji_mavic3_dlog_to_rec709_lut.cache_clear()
    try:
        analysis = analyze_video_color(
            video,
            [TimeRange(start_seconds=0, end_seconds=2)],
            sample_fps=2,
            input_color_space=ColorSpace.LOG,
            source_log_profile=DJI_MAVIC3_DLOG_REC709,
        )[0]
    finally:
        ensure_dji_mavic3_dlog_to_rec709_lut.cache_clear()

    assert analysis.exposure == 0
    assert analysis.temperature == 0
    assert analysis.tint == 0
    assert analysis.highlights == 0
