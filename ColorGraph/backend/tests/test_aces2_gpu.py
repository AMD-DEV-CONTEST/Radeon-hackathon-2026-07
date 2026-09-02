from __future__ import annotations

import numpy as np
import pytest
import torch

from colorgraph.grading.aces2_gpu import (
    apply_aces2_output_transform,
    apply_ocio_color_space_gpu,
)
from colorgraph.grading.ocio_pipeline import (
    ACES2_SDR_VIEW,
    OCIO_ACES2065_1,
    _color_processor,
    _display_processor,
)


@pytest.mark.parametrize(
    ("display", "encoding"),
    (
        ("sRGB - Display", "srgb"),
        ("Rec.1886 Rec.709 - Display", "rec1886"),
    ),
)
def test_torch_aces2_matches_frozen_ocio_gpu_processor_math(
    display: str,
    encoding: str,
) -> None:
    random = np.random.default_rng(20260731)
    samples = np.concatenate(
        (
            np.asarray(
                [
                    [0.0, 0.0, 0.0],
                    [0.18, 0.18, 0.18],
                    [1.0, 1.0, 1.0],
                    [16.0, 4.0, 0.5],
                    [-0.1, 0.2, 2.0],
                ],
                dtype=np.float32,
            ),
            np.exp2(random.uniform(-8.0, 6.0, size=(1024, 3))).astype(np.float32),
        )
    )
    processor = _display_processor(OCIO_ACES2065_1, display, ACES2_SDR_VIEW)
    expected = samples.copy()
    processor.getDefaultCPUProcessor().applyRGB(expected)
    image = torch.from_numpy(samples.T.copy()).unsqueeze(0).unsqueeze(2)

    actual = (
        apply_aces2_output_transform(
            image,
            processor=processor,
            encoding=encoding,  # type: ignore[arg-type]
        )
        .squeeze(0)
        .squeeze(1)
        .T.numpy()
    )

    assert np.isfinite(actual).all()
    assert np.max(np.abs(actual - expected)) <= 8e-5


@pytest.mark.parametrize(
    "source",
    (
        "Linear Rec.709 (sRGB)",
        "sRGB Encoded Rec.709 (sRGB)",
        "ACES2065-1",
        "ACEScg",
        "ACEScct",
        "S-Log3 S-Gamut3.Cine",
        "D-Log D-Gamut",
    ),
)
def test_native_torch_input_transforms_match_frozen_ocio_shader(
    source: str,
) -> None:
    random = np.random.default_rng(20260731)
    samples = random.uniform(-0.05, 1.2, size=(2048, 3)).astype(np.float32)
    processor = _color_processor(
        source,
        OCIO_ACES2065_1,
    )
    expected = samples.copy()
    processor.getDefaultCPUProcessor().applyRGB(expected)
    image = torch.from_numpy(samples.T.copy()).unsqueeze(0).unsqueeze(2)

    actual = (
        apply_ocio_color_space_gpu(
            image,
            source,
            OCIO_ACES2065_1,
        )
        .squeeze(0)
        .squeeze(1)
        .T.numpy()
    )

    assert np.isfinite(actual).all()
    # OCIO's generated GPU shader is FP32. Highly saturated log samples may
    # cancel large matrix terms, so compare at sub-code-value display precision.
    assert np.allclose(actual, expected, rtol=4e-6, atol=8e-4)
