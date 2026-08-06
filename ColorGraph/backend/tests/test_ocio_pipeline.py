import json
from pathlib import Path

import numpy as np
import PyOpenColorIO as ocio
import pytest
import torch

from colorgraph.domain.grade_graph import ColorSpace
from colorgraph.grading.color import (
    DJI_DLOG_DGAMUT,
    SONY_SLOG3_SGAMUT3CINE,
)
from colorgraph.grading.ocio_pipeline import (
    ACES2_SDR_VIEW,
    OCIO_ACES2065_1,
    OCIO_ACESCG,
    OCIO_CONFIG_NAME,
    acescg_to_output,
    apply_ocio_color_space,
    input_to_acescg,
    ocio_config,
    ocio_pipeline_metadata,
    resolve_display_target,
)

FIXTURE = Path(__file__).parent / "fixtures" / "color" / "golden_color_v1.json"


def _samples_to_tensor(samples: list[list[float]]) -> torch.Tensor:
    return torch.tensor(samples, dtype=torch.float32).T.unsqueeze(0).unsqueeze(2)


def _tensor_to_samples(image: torch.Tensor) -> np.ndarray:
    return image.squeeze(0).squeeze(1).T.detach().cpu().numpy()


def test_ocio_runtime_is_pinned_to_the_official_aces2_studio_config() -> None:
    config = ocio_config()
    assert ocio.__version__ == "2.5.2"
    assert config.getName() == OCIO_CONFIG_NAME
    assert "S-Log3 S-Gamut3.Cine" in config.getColorSpaceNames()
    assert "D-Log D-Gamut" in config.getColorSpaceNames()
    assert "ACEScg" in config.getColorSpaceNames()


def test_camera_inputs_use_official_ocio_transforms_via_aces2065_1() -> None:
    cases = [
        (SONY_SLOG3_SGAMUT3CINE, "S-Log3 S-Gamut3.Cine", 420.0 / 1023.0),
        (DJI_DLOG_DGAMUT, "D-Log D-Gamut", 0.398764),
    ]
    config = ocio_config()
    for profile, ocio_input, code_value in cases:
        source = _samples_to_tensor([[code_value, code_value, code_value]])
        actual = input_to_acescg(
            source.half(),
            ColorSpace.LOG,
            source_log_profile=profile,
        )

        expected = _tensor_to_samples(source.half().float()).copy()
        config.getProcessor(
            ocio_input,
            OCIO_ACES2065_1,
        ).getDefaultCPUProcessor().applyRGB(expected)
        config.getProcessor(
            OCIO_ACES2065_1,
            OCIO_ACESCG,
        ).getDefaultCPUProcessor().applyRGB(expected)

        assert actual.dtype == torch.float32
        assert np.allclose(_tensor_to_samples(actual), expected, rtol=0, atol=2e-6)


def test_aces2_output_matches_the_frozen_reference_processor() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    reference = fixture["aces2_output_reference"]
    samples = [sample["input_aces2065_1"] for sample in reference["samples"]]
    expected = np.asarray(
        [sample["output_srgb_display"] for sample in reference["samples"]],
        dtype=np.float32,
    )
    aces2065_1 = _samples_to_tensor(samples)
    acescg = apply_ocio_color_space(
        aces2065_1,
        OCIO_ACES2065_1,
        OCIO_ACESCG,
    )
    actual = acescg_to_output(
        acescg,
        ColorSpace.SRGB,
        display=reference["display"],
        view=reference["view"],
    )
    assert np.allclose(
        _tensor_to_samples(actual),
        expected,
        rtol=0,
        atol=fixture["tolerances"]["cpu_float32_absolute"],
    )


def test_display_encoding_and_pipeline_metadata_are_explicit() -> None:
    target = resolve_display_target(ColorSpace.REC1886)
    assert target.display == "Rec.1886 Rec.709 - Display"
    assert target.view == ACES2_SDR_VIEW

    metadata = ocio_pipeline_metadata(
        ColorSpace.LOG,
        source_log_profile=SONY_SLOG3_SGAMUT3CINE,
        output_space=ColorSpace.REC1886,
    )
    assert metadata["config"] == OCIO_CONFIG_NAME
    assert metadata["interchange_space"] == OCIO_ACES2065_1
    assert metadata["scene_linear_space"] == OCIO_ACESCG
    assert metadata["creative_space"] == "ACEScct"
    assert set(metadata["processor_cache_ids"]) == {
        "input_to_interchange",
        "interchange_to_working",
        "working_to_interchange",
        "output",
    }

    with pytest.raises(ValueError, match="requires display"):
        resolve_display_target(
            ColorSpace.SRGB,
            display="Rec.1886 Rec.709 - Display",
        )
