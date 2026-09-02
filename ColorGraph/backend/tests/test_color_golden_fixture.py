import json
from pathlib import Path

import numpy as np
import PyOpenColorIO as ocio
import pytest
import torch

from colorgraph.domain.grade_graph import ColorSpace
from colorgraph.evaluation.manifest import (
    load_gold_set_manifest,
    validate_gold_set_files,
)
from colorgraph.grading.color import (
    SONY_SGAMUT3CINE_TO_REC709,
    convert_color_space,
    slog3_to_linear_rec709,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures"


def _color_fixture() -> dict:
    return json.loads(
        (FIXTURE_ROOT / "color" / "golden_color_v1.json").read_text(
            encoding="utf-8"
        )
    )


def test_frozen_color_fixture_matches_standard_transfer_references() -> None:
    fixture = _color_fixture()
    linear = torch.full(
        (1, 3, 1, 1),
        fixture["middle_gray_linear"],
        dtype=torch.float64,
    )
    for color_space in (
        ColorSpace.SRGB,
        ColorSpace.BT709_OETF,
        ColorSpace.REC1886,
        ColorSpace.ACESCCT,
    ):
        encoded = convert_color_space(
            linear,
            ColorSpace.LINEAR_REC709,
            color_space,
        )
        expected = fixture["middle_gray_encodings"][color_space.value]
        assert encoded[0, 0, 0, 0].item() == pytest.approx(
            expected,
            abs=fixture["tolerances"]["float64_absolute"],
        )

    breakpoint = fixture["bt709_breakpoint"]
    encoded_breakpoint = convert_color_space(
        torch.full((1, 3, 1, 1), breakpoint["linear"], dtype=torch.float64),
        ColorSpace.LINEAR_REC709,
        ColorSpace.BT709_OETF,
    )
    assert encoded_breakpoint[0, 0, 0, 0].item() == pytest.approx(
        breakpoint["encoded"],
        abs=1e-14,
    )


def test_frozen_aces2_output_matches_official_ocio_processor() -> None:
    fixture = _color_fixture()
    reference = fixture["aces2_output_reference"]

    assert reference["status"] == "frozen"
    assert ocio.__version__ == reference["ocio_version"]

    config = ocio.Config.CreateFromBuiltinConfig(reference["config"])
    assert config.getCacheID() == reference["config_cache_id"]
    processor = config.getProcessor(
        reference["input_color_space"],
        reference["display"],
        reference["view"],
        ocio.TRANSFORM_DIR_FORWARD,
    )
    assert processor.getCacheID() == reference["processor_cache_id"]

    cpu = processor.getDefaultCPUProcessor()
    actual = np.asarray(
        [
            cpu.applyRGB(sample["input_aces2065_1"])
            for sample in reference["samples"]
        ],
        dtype=np.float64,
    )
    expected = np.asarray(
        [
            sample["output_srgb_display"]
            for sample in reference["samples"]
        ],
        dtype=np.float64,
    )
    assert np.allclose(
        actual,
        expected,
        rtol=0,
        atol=fixture["tolerances"]["cpu_float32_absolute"],
    )


def test_frozen_sony_vectors_cover_matrix_neutrals_and_extended_range() -> None:
    fixture = _color_fixture()
    assert np.allclose(
        np.asarray(SONY_SGAMUT3CINE_TO_REC709),
        np.asarray(fixture["sony_sgamut3cine_to_rec709"]),
        atol=5e-13,
    )
    points = (
        fixture["sony_slog3_neutral_points"]
        + fixture["sony_slog3_extended_points"]
    )
    codes = [
        (
            point["normalized_code"]
            if "normalized_code" in point
            else point["code_value_10bit"] / 1023
        )
        for point in points
    ]
    encoded = torch.tensor(codes, dtype=torch.float64).view(1, 1, 1, -1)
    encoded = encoded.expand(1, 3, 1, -1)
    decoded = slog3_to_linear_rec709(encoded)[0, 0, 0]
    expected = torch.tensor(
        [point["linear_reflectance"] for point in points],
        dtype=torch.float64,
    )
    assert torch.allclose(
        decoded,
        expected,
        atol=fixture["tolerances"]["float64_absolute"],
        rtol=1e-12,
    )


@pytest.mark.parametrize("bit_depth", [10, 12])
def test_frozen_ramps_round_trip_without_losing_codes(bit_depth: int) -> None:
    fixture = _color_fixture()
    ramp_spec = next(
        item
        for item in fixture["procedural_signals"]["ramps"]
        if item["bit_depth"] == bit_depth
    )
    levels = ramp_spec["levels"]
    ramp = torch.linspace(0, 1, levels, dtype=torch.float32).view(1, 1, 1, -1)
    ramp = ramp.expand(1, 3, 1, -1)

    encoded = convert_color_space(
        ramp,
        ColorSpace.LINEAR_REC709,
        ColorSpace.BT709_OETF,
    )
    decoded = convert_color_space(
        encoded,
        ColorSpace.BT709_OETF,
        ColorSpace.LINEAR_REC709,
    )

    assert torch.max(torch.abs(decoded - ramp)).item() <= fixture["tolerances"][
        "cpu_float32_absolute"
    ]
    projected = torch.round(decoded[0, 0, 0] * (levels - 1)).to(torch.int32)
    assert torch.unique(projected).numel() == levels


def test_checked_in_procedural_gold_manifest_is_self_consistent() -> None:
    root = FIXTURE_ROOT / "evaluation" / "gold_set_v1"
    manifest = load_gold_set_manifest(root / "manifest.json")
    validate_gold_set_files(manifest, root)

    assert {item.split.value for item in manifest.items} == {
        "train",
        "calibration",
        "test",
    }
    assert all(
        item.frozen
        for item in manifest.items
        if item.split.value == "test"
    )
