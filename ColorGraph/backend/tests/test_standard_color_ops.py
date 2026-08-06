import numpy as np
import PyOpenColorIO as ocio
import pytest
import torch

from colorgraph.grading.color import (
    ACES_WHITE,
    aces_ap1_luminance,
    acescct_to_acescg,
    acescg_to_acescct,
    apply_acescct_contrast,
    apply_acescct_highlights,
    apply_acescct_saturation,
    apply_acescct_tone,
    apply_acescg_white_balance,
    apply_asc_cdl,
    chromatic_adaptation_matrix,
    grading_white_point,
)


def _samples_to_tensor(samples: np.ndarray) -> torch.Tensor:
    return torch.from_numpy(samples.astype(np.float32)).T.unsqueeze(0).unsqueeze(2)


def _tensor_to_samples(image: torch.Tensor) -> np.ndarray:
    return image.squeeze(0).squeeze(1).T.detach().cpu().numpy()


def _xy_to_xyz(white: tuple[float, float]) -> np.ndarray:
    x, y = white
    return np.asarray([x / y, 1.0, (1.0 - x - y) / y], dtype=np.float64)


def test_asc_cdl_no_clamp_matches_ocio_and_preserves_negative_sop() -> None:
    samples = np.asarray(
        [
            [-1.0, -0.5, -0.1],
            [0.0, 0.2, 0.5],
            [0.1, 1.0, 2.0],
            [4.0, 0.7, -0.3],
        ],
        dtype=np.float32,
    )
    slope = (1.2, 0.8, 1.05)
    offset = (0.1, -0.1, 0.02)
    power = (0.5, 2.0, 1.3)
    saturation = 0.72

    actual = apply_asc_cdl(
        _samples_to_tensor(samples),
        slope=slope,
        offset=offset,
        power=power,
        saturation=saturation,
    )

    transform = ocio.CDLTransform()
    transform.setSlope(slope)
    transform.setOffset(offset)
    transform.setPower(power)
    transform.setSat(saturation)
    transform.setStyle(ocio.CDL_NO_CLAMP)
    expected = samples.copy()
    ocio.Config.CreateRaw().getProcessor(transform).getDefaultCPUProcessor().applyRGB(expected)

    assert np.allclose(_tensor_to_samples(actual), expected, rtol=0, atol=1e-4)

    negative = torch.tensor([[[[-0.5]], [[-0.25]], [[-0.1]]]])
    preserved = apply_asc_cdl(negative, power=(2.0, 2.0, 2.0))
    assert torch.equal(preserved, negative)


def test_cat16_white_balance_uses_explicit_cct_duv_and_keeps_zero_identity() -> None:
    neutral = torch.ones((1, 3, 1, 1), dtype=torch.float16)
    identity = apply_acescg_white_balance(neutral, 0.0, 0.0)
    warm = apply_acescg_white_balance(neutral, 0.5, 0.0)
    magenta = apply_acescg_white_balance(neutral, 0.0, 0.5)

    assert identity.dtype == torch.float32
    assert torch.equal(identity, neutral.float())
    assert warm[0, 0, 0, 0] > warm[0, 2, 0, 0]
    assert magenta[0, 1, 0, 0] < min(
        magenta[0, 0, 0, 0],
        magenta[0, 2, 0, 0],
    )

    destination = grading_white_point(0.35, -0.2)
    for method in ("cat16", "bradford"):
        matrix = chromatic_adaptation_matrix(
            ACES_WHITE,
            destination,
            method=method,
        )
        adapted = matrix @ _xy_to_xyz(ACES_WHITE)
        adapted /= adapted[1]
        assert np.allclose(adapted, _xy_to_xyz(destination), rtol=0, atol=2e-12)


def test_acescct_contrast_and_saturation_use_log_pivot_and_ap1_luma() -> None:
    middle_gray = acescg_to_acescct(torch.full((1, 3, 1, 1), 0.18))
    assert torch.allclose(
        apply_acescct_contrast(middle_gray, 0.8),
        middle_gray,
        rtol=0,
        atol=1e-7,
    )

    encoded = torch.tensor(
        [[[[0.2, 0.8]], [[0.4, 0.5]], [[0.7, 0.3]]]],
        dtype=torch.float32,
    )
    saturated = apply_acescct_saturation(encoded, 0.75)
    assert torch.allclose(
        aces_ap1_luminance(saturated),
        aces_ap1_luminance(encoded),
        rtol=0,
        atol=1e-7,
    )


@pytest.mark.parametrize(
    "operator",
    [
        lambda image: apply_acescct_highlights(image, -0.7),
        lambda image: apply_acescct_tone(
            image,
            shadows=-0.2,
            midtones=0.3,
            highlights=-0.6,
        ),
    ],
)
def test_acescct_tone_operators_preserve_highlight_chromaticity(operator) -> None:
    source = torch.tensor([[[[4.0]], [[1.0]], [[0.25]]]], dtype=torch.float32)
    encoded = acescg_to_acescct(source)
    adjusted = acescct_to_acescg(operator(encoded))

    source_chromaticity = source / source.sum(dim=1, keepdim=True)
    adjusted_chromaticity = adjusted / adjusted.sum(dim=1, keepdim=True)
    assert torch.allclose(
        adjusted_chromaticity,
        source_chromaticity,
        rtol=0,
        atol=2e-6,
    )


def test_encoding_aware_ops_keep_extended_gamut_finite_without_soft_clip() -> None:
    extended = torch.tensor(
        [[[[-0.2, 0.0, 0.2, 0.6, 1.2]], [[0.8] * 5], [[1.4, 1.0, 0.5, 0.1, -0.1]]]],
        dtype=torch.float32,
    )
    output = apply_acescct_tone(
        apply_acescct_highlights(
            apply_acescct_saturation(
                apply_acescct_contrast(extended, 0.4),
                0.3,
            ),
            -0.5,
        ),
        shadows=0.2,
        midtones=-0.1,
        highlights=-0.3,
    )

    assert torch.isfinite(output).all()
    assert output.min() < 0
    assert output.max() > 1
