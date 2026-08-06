import colorsys
from pathlib import Path

import pytest
import torch

from colorgraph.domain.grade_graph import ColorSpace
from colorgraph.grading.color import (
    DJI_DLOG_DGAMUT,
    DJI_MAVIC3_DLOG_REC709,
    REC709_TO_SONY_SGAMUT3CINE,
    SONY_SGAMUT3CINE_TO_REC709,
    convert_color_space,
    dlog_dgamut_to_linear_rec709,
    linear_rec709_to_dlog_dgamut,
    linear_rec709_to_slog3,
    log_to_linear_rec709,
    rec1886_to_linear,
    slog3_to_linear_rec709,
)
from colorgraph.grading.official_luts import ensure_dji_mavic3_dlog_to_rec709_lut


@pytest.mark.parametrize(
    ("color_space", "expected"),
    [
        (ColorSpace.SRGB, 0.46135612950044164),
        (ColorSpace.BT709_OETF, 0.4090077288641504),
        (ColorSpace.REC1886, 0.4894370895738783),
        (ColorSpace.ACESCCT, 0.41358840249244233),
    ],
)
def test_explicit_color_encodings_match_reference_middle_gray(
    color_space: ColorSpace,
    expected: float,
) -> None:
    linear = torch.full((1, 3, 1, 1), 0.18, dtype=torch.float64)
    encoded = convert_color_space(linear, ColorSpace.LINEAR_REC709, color_space)
    decoded = convert_color_space(encoded, color_space, ColorSpace.LINEAR_REC709)

    assert encoded[0, 0, 0, 0].item() == pytest.approx(expected, abs=5e-13)
    assert torch.allclose(decoded, linear, atol=5e-12)


def test_bt709_oetf_reference_breakpoint_is_not_srgb() -> None:
    linear = torch.full((1, 3, 1, 1), 0.018, dtype=torch.float64)
    bt709 = convert_color_space(
        linear,
        ColorSpace.LINEAR_REC709,
        ColorSpace.BT709_OETF,
    )
    srgb = convert_color_space(
        linear,
        ColorSpace.LINEAR_REC709,
        ColorSpace.SRGB,
    )

    assert bt709[0, 0, 0, 0].item() == pytest.approx(0.08124794403514046, abs=1e-14)
    assert not torch.allclose(bt709, srgb)


def test_acescct_round_trip_preserves_negative_and_extended_values() -> None:
    samples = torch.tensor(
        [[[-0.01, 0.0, 0.0078125, 0.18, 2.0]]],
        dtype=torch.float64,
    ).expand(1, 3, 1, 5)
    encoded = convert_color_space(
        samples,
        ColorSpace.LINEAR_REC709,
        ColorSpace.ACESCCT,
    )
    decoded = convert_color_space(
        encoded,
        ColorSpace.ACESCCT,
        ColorSpace.LINEAR_REC709,
    )

    assert torch.allclose(decoded, samples, atol=2e-11)


def test_ambiguous_or_unknown_color_space_fails_explicitly() -> None:
    image = torch.zeros((1, 3, 1, 1))
    with pytest.raises(ValueError, match="ambiguous legacy color space"):
        convert_color_space(image, ColorSpace.REC709, ColorSpace.LINEAR_REC709)
    with pytest.raises(ValueError, match="unknown color space"):
        convert_color_space(image, "camera_magic", ColorSpace.LINEAR_REC709)
    with pytest.raises(ValueError, match="unsupported source log profile"):
        convert_color_space(
            image,
            ColorSpace.LOG,
            ColorSpace.LINEAR_REC709,
            source_log_profile="mystery_log",
        )


def test_color_space_transforms_promote_half_inputs_to_fp32() -> None:
    image = torch.tensor(
        [[[[0.01, 0.18, 0.9]], [[0.02, 0.25, 0.8]], [[0.03, 0.4, 0.7]]]],
        dtype=torch.float16,
    )

    output = convert_color_space(
        image,
        ColorSpace.BT709_OETF,
        ColorSpace.ACESCCT,
    )

    assert output.dtype == torch.float32
    assert torch.isfinite(output).all()


_REFERENCE_SGAMUT3CINE_TO_REC709 = torch.tensor(
    [
        [1.626947409729080, -0.540138538869635, -0.086808870859445],
        [-0.178515527114877, 1.417940927464080, -0.239425400349203],
        [-0.044436115009298, -0.195919966172016, 1.240356081181313],
    ],
    dtype=torch.float64,
)
_REFERENCE_REC709_TO_SGAMUT3CINE = torch.tensor(
    [
        [0.645679477609992, 0.259114546999715, 0.095205975390293],
        [0.087529991511860, 0.759699562554070, 0.152770445934069],
        [0.036957419887524, 0.129280904766338, 0.833761675346138],
    ],
    dtype=torch.float64,
)

# BabelColor's commonly used average ColorChecker Classic sRGB values. The
# patches exercise neutrals, skin tones, foliage, sky, and saturated hues.
_COLORCHECKER_SRGB_8BIT = torch.tensor(
    [
        [115, 82, 68],
        [194, 150, 130],
        [98, 122, 157],
        [87, 108, 67],
        [133, 128, 177],
        [103, 189, 170],
        [214, 126, 44],
        [80, 91, 166],
        [193, 90, 99],
        [94, 60, 108],
        [157, 188, 64],
        [224, 163, 46],
        [56, 61, 150],
        [70, 148, 73],
        [175, 54, 60],
        [231, 199, 31],
        [187, 86, 149],
        [8, 133, 161],
        [243, 243, 242],
        [200, 200, 200],
        [160, 160, 160],
        [122, 122, 121],
        [85, 85, 85],
        [52, 52, 52],
    ],
    dtype=torch.float64,
)


def _rgb_samples_to_image(samples: torch.Tensor) -> torch.Tensor:
    return samples.T.unsqueeze(0).unsqueeze(2)


def _image_to_rgb_samples(image: torch.Tensor) -> torch.Tensor:
    return image.squeeze(0).squeeze(1).T


def _reference_linear_to_slog3(linear: torch.Tensor) -> torch.Tensor:
    safe_log_argument = ((linear + 0.01) / 0.19).clamp_min(1e-12)
    return torch.where(
        linear >= 0.01125,
        (420.0 + torch.log10(safe_log_argument) * 261.5) / 1023.0,
        (linear * (171.2102946929 - 95.0) / 0.01125 + 95.0) / 1023.0,
    )


def _reference_rec709_to_slog3(samples: torch.Tensor) -> torch.Tensor:
    linear_sgamut = samples @ _REFERENCE_REC709_TO_SGAMUT3CINE.T
    return _reference_linear_to_slog3(linear_sgamut)


def _reference_srgb_to_linear(samples: torch.Tensor) -> torch.Tensor:
    return torch.where(
        samples <= 0.04045,
        samples / 12.92,
        ((samples + 0.055) / 1.055).pow(2.4),
    )


def test_sgamut3cine_matrix_matches_sony_primaries_reference() -> None:
    actual_forward = torch.tensor(SONY_SGAMUT3CINE_TO_REC709, dtype=torch.float64)
    actual_inverse = torch.tensor(REC709_TO_SONY_SGAMUT3CINE, dtype=torch.float64)

    assert torch.allclose(actual_forward, _REFERENCE_SGAMUT3CINE_TO_REC709, atol=5e-13)
    assert torch.allclose(actual_inverse, _REFERENCE_REC709_TO_SGAMUT3CINE, atol=5e-13)


def test_slog3_official_neutral_reference_points() -> None:
    # Sony's technical summary specifies CV 95=0%, 420=18%, and rounded
    # CV 598=90% reflection for full-range 10-bit S-Log3.
    code_values = torch.tensor([95.0, 420.0, 598.0], dtype=torch.float64) / 1023.0
    encoded = code_values[:, None].expand(-1, 3)
    decoded = _image_to_rgb_samples(slog3_to_linear_rec709(_rgb_samples_to_image(encoded)))
    expected = torch.tensor([0.0, 0.18, 0.9008396704090211], dtype=torch.float64)

    assert torch.allclose(decoded, expected[:, None].expand(-1, 3), atol=5e-12)


def test_slog3_rgb_primaries_match_reference_matrix_columns() -> None:
    linear_sgamut_primaries = torch.eye(3, dtype=torch.float64)
    encoded = _reference_linear_to_slog3(linear_sgamut_primaries)
    decoded = _image_to_rgb_samples(slog3_to_linear_rec709(_rgb_samples_to_image(encoded)))
    expected = linear_sgamut_primaries @ _REFERENCE_SGAMUT3CINE_TO_REC709.T

    assert torch.allclose(decoded, expected, atol=5e-12)


def test_slog3_preserves_negative_and_extended_range_codes() -> None:
    code_values = torch.tensor([-0.1, 0.0, 1.0, 1.1], dtype=torch.float64)
    encoded = code_values[:, None].expand(-1, 3)
    decoded = _image_to_rgb_samples(slog3_to_linear_rec709(_rgb_samples_to_image(encoded)))
    expected = torch.tensor(
        [-0.02912500219221417, -0.014023695936443719, 38.42093433720254, 94.58877925753886],
        dtype=torch.float64,
    )

    assert torch.allclose(decoded, expected[:, None].expand(-1, 3), rtol=1e-12, atol=1e-12)


def test_slog3_colorchecker_matches_reference_transform() -> None:
    srgb = _COLORCHECKER_SRGB_8BIT / 255.0
    expected_linear_rec709 = _reference_srgb_to_linear(srgb)
    encoded = _reference_rec709_to_slog3(expected_linear_rec709)
    decoded = _image_to_rgb_samples(slog3_to_linear_rec709(_rgb_samples_to_image(encoded)))

    assert torch.allclose(decoded, expected_linear_rec709, atol=5e-12)


def test_slog3_hue_sweep_matches_reference_forward_and_inverse() -> None:
    linear_rec709 = torch.tensor(
        [colorsys.hsv_to_rgb(hue / 360.0, 0.75, 0.60) for hue in range(0, 360, 15)],
        dtype=torch.float64,
    )
    expected_encoded = _reference_rec709_to_slog3(linear_rec709)
    actual_encoded = _image_to_rgb_samples(
        linear_rec709_to_slog3(_rgb_samples_to_image(linear_rec709))
    )
    decoded = _image_to_rgb_samples(slog3_to_linear_rec709(_rgb_samples_to_image(expected_encoded)))

    assert torch.allclose(actual_encoded, expected_encoded, atol=5e-12)
    assert torch.allclose(decoded, linear_rec709, atol=5e-12)


def test_slog3_round_trip_is_stable() -> None:
    image = torch.tensor(
        [[[[0.02, 0.18, 0.72]], [[0.03, 0.20, 0.55]], [[0.01, 0.16, 0.42]]]],
        dtype=torch.float32,
    )
    encoded = linear_rec709_to_slog3(image)
    decoded = slog3_to_linear_rec709(encoded)
    assert torch.allclose(decoded, image, atol=2e-4)


def test_dji_dlog_round_trip_is_stable() -> None:
    image = torch.tensor(
        [[[[0.05, 0.18, 0.55]], [[0.06, 0.20, 0.45]], [[0.04, 0.16, 0.35]]]],
        dtype=torch.float32,
    )
    encoded = linear_rec709_to_dlog_dgamut(image)
    decoded = dlog_dgamut_to_linear_rec709(encoded)
    assert torch.allclose(decoded, image, atol=8e-4)


def test_dji_dlog_whitepaper_neutral_anchors() -> None:
    code_values = torch.tensor([408 / 1023, 586 / 1023], dtype=torch.float32)
    encoded = code_values.view(1, 1, 1, 2).expand(1, 3, 1, 2)
    decoded = log_to_linear_rec709(encoded, DJI_DLOG_DGAMUT)

    assert torch.allclose(decoded[0, :, 0, 0], torch.full((3,), 0.18), atol=0.002)
    assert torch.allclose(decoded[0, :, 0, 1], torch.full((3,), 0.90), atol=0.006)


def test_mavic3_official_profile_uses_supplied_rec709_lut(
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
    monkeypatch.setenv("COLORGRAPH_DJI_MAVIC3_DLOG_LUT", str(lut))
    ensure_dji_mavic3_dlog_to_rec709_lut.cache_clear()
    image = torch.tensor([[[[0.2]], [[0.5]], [[0.8]]]], dtype=torch.float32)
    try:
        decoded = log_to_linear_rec709(image, DJI_MAVIC3_DLOG_REC709)
    finally:
        ensure_dji_mavic3_dlog_to_rec709_lut.cache_clear()

    assert torch.allclose(decoded, rec1886_to_linear(image), atol=1e-5)
