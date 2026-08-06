import os
from collections.abc import Callable
from pathlib import Path

import numpy as np
import PyOpenColorIO as ocio
import pytest
import torch

from colorgraph.grading.lut import (
    apply_cube_lut,
    apply_cube_lut_numpy,
    apply_lut,
    clear_lut_caches,
    describe_lut,
    lut_cache_info,
)


def _write_cube(
    path: Path,
    *,
    size: int,
    transform: Callable[[float, float, float], tuple[float, float, float]],
    headers: list[str] | None = None,
) -> None:
    lines = [*(headers or []), f"LUT_3D_SIZE {size}"]
    denominator = size - 1
    for blue_index in range(size):
        blue = blue_index / denominator
        for green_index in range(size):
            green = green_index / denominator
            for red_index in range(size):
                red = red_index / denominator
                output = transform(red, green, blue)
                lines.append(" ".join(f"{value:.9g}" for value in output))
    path.write_text("\n".join(lines), encoding="utf-8")


def _identity(red: float, green: float, blue: float) -> tuple[float, float, float]:
    return red, green, blue


def test_identity_cube_lut_supports_explicit_interpolation_and_numpy(tmp_path: Path) -> None:
    lut = tmp_path / "identity.cube"
    _write_cube(lut, size=2, transform=_identity)
    image = torch.tensor([[[[0.2]], [[0.5]], [[0.8]]]], dtype=torch.float32)

    for interpolation in ("tetrahedral", "trilinear"):
        assert torch.allclose(
            apply_cube_lut(image, lut, interpolation=interpolation),
            image,
            atol=1e-6,
        )
    half_output = apply_cube_lut(image.half(), lut)
    assert half_output.dtype == torch.float32
    assert torch.allclose(half_output, image, atol=2e-4)

    numpy_image = np.asarray([[[0.2, 0.5, 0.8]]], dtype=np.float32)
    assert np.allclose(
        apply_cube_lut_numpy(numpy_image, lut),
        numpy_image,
        atol=1e-6,
    )


def test_tetrahedral_cube_matches_ocio_and_differs_from_trilinear(
    tmp_path: Path,
) -> None:
    lut = tmp_path / "cross-terms.cube"
    _write_cube(
        lut,
        size=2,
        transform=lambda red, green, blue: (
            red * green,
            green * blue,
            blue * red,
        ),
    )
    image = torch.tensor([[[[0.82]], [[0.47]], [[0.19]]]], dtype=torch.float32)

    tetrahedral = apply_cube_lut(image, lut, interpolation="tetrahedral")
    trilinear = apply_cube_lut(image, lut, interpolation="trilinear")

    transform = ocio.FileTransform()
    transform.setSrc(str(lut))
    transform.setInterpolation(ocio.INTERP_TETRAHEDRAL)
    expected = image.permute(0, 2, 3, 1).numpy().copy()
    ocio.Config.CreateRaw().getProcessor(transform).getDefaultCPUProcessor().applyRGB(
        expected.reshape(-1, 3)
    )

    assert np.allclose(
        tetrahedral.permute(0, 2, 3, 1).numpy(),
        expected,
        rtol=0,
        atol=2e-6,
    )
    assert torch.max(torch.abs(tetrahedral - trilinear)).item() > 0.03


def test_combined_cube_shaper_and_3d_lut_support_extended_input_range(
    tmp_path: Path,
) -> None:
    lut = tmp_path / "shaper-and-cube.cube"
    lines = [
        "LUT_1D_SIZE 3",
        "LUT_1D_INPUT_RANGE -1 3",
        "LUT_3D_INPUT_RANGE 0 1",
        "LUT_3D_SIZE 2",
        "0 0 0",
        "0.25 0.25 0.25",
        "1 1 1",
        "0 0 0",
        "1 0 0",
        "0 1 0",
        "1 1 0",
        "0 0 1",
        "1 0 1",
        "0 1 1",
        "1 1 1",
    ]
    lut.write_text("\n".join(lines), encoding="utf-8")
    image = torch.tensor([[[[0.0]], [[1.0]], [[2.0]]]], dtype=torch.float32)

    output = apply_cube_lut(image, lut)
    ocio_samples = image.permute(0, 2, 3, 1).numpy().copy()
    ocio_transform = ocio.FileTransform(
        src=str(lut),
        interpolation=ocio.INTERP_TETRAHEDRAL,
    )
    ocio.Config.CreateRaw().getProcessor(ocio_transform).getDefaultCPUProcessor().applyRGB(
        ocio_samples.reshape(-1, 3)
    )

    assert torch.allclose(
        output,
        torch.tensor([[[[0.125]], [[0.25]], [[0.625]]]]),
        rtol=0,
        atol=1e-6,
    )
    assert np.allclose(
        output.permute(0, 2, 3, 1).numpy(),
        ocio_samples,
        rtol=0,
        atol=2e-6,
    )
    metadata = describe_lut(lut)
    assert metadata["shaper_size"] == 3
    assert metadata["cube_size"] == 2


@pytest.mark.parametrize("size", [33, 65])
def test_identity_cube_sizes_33_and_65_preserve_hdr_domain(
    tmp_path: Path,
    size: int,
) -> None:
    lut = tmp_path / f"identity-{size}.cube"
    _write_cube(
        lut,
        size=size,
        headers=["DOMAIN_MIN -1 -1 -1", "DOMAIN_MAX 4 4 4"],
        transform=lambda red, green, blue: (
            red * 5 - 1,
            green * 5 - 1,
            blue * 5 - 1,
        ),
    )
    image = torch.tensor(
        [[[[-0.5, 0.0, 3.8]], [[2.0, 4.0, -1.0]], [[4.0, 1.5, 0.25]]]],
        dtype=torch.float32,
    )

    output = apply_cube_lut(image, lut)

    assert torch.allclose(output, image, rtol=0, atol=2e-5)
    assert describe_lut(lut)["cube_size"] == size


def test_cube_cache_keys_device_dtype_and_invalidates_replaced_file(
    tmp_path: Path,
) -> None:
    clear_lut_caches()
    lut = tmp_path / "replaceable.cube"
    _write_cube(lut, size=2, transform=_identity)
    image = torch.tensor([[[[0.2]], [[0.5]], [[0.8]]]], dtype=torch.float32)

    original_metadata = describe_lut(lut)
    first = apply_cube_lut(image, lut)
    first_cache = lut_cache_info()
    repeated = apply_cube_lut(image, lut)
    repeated_cache = lut_cache_info()
    double_output = apply_cube_lut(image.double(), lut)
    dtype_cache = lut_cache_info()

    assert torch.equal(first, repeated)
    assert double_output.dtype == torch.float64
    assert repeated_cache["device_cube"]["hits"] > first_cache["device_cube"]["hits"]
    assert dtype_cache["device_cube"]["misses"] > repeated_cache["device_cube"]["misses"]

    previous_stat = lut.stat()
    _write_cube(
        lut,
        size=2,
        transform=lambda red, green, blue: (
            1.0 - red,
            1.0 - green,
            1.0 - blue,
        ),
    )
    current_stat = lut.stat()
    os.utime(
        lut,
        ns=(
            current_stat.st_atime_ns,
            max(current_stat.st_mtime_ns, previous_stat.st_mtime_ns + 1_000_000),
        ),
    )

    replaced = apply_cube_lut(image, lut)
    replaced_metadata = describe_lut(lut)
    assert torch.allclose(replaced, 1.0 - image, rtol=0, atol=1e-6)
    assert replaced_metadata["sha256"] != original_metadata["sha256"]


@pytest.mark.parametrize(
    ("format_name", "extension"),
    [
        ("Academy/ASC Common LUT Format", "clf"),
        ("Color Transform Format", "ctf"),
    ],
)
def test_clf_and_ctf_use_cached_ocio_file_processors(
    tmp_path: Path,
    format_name: str,
    extension: str,
) -> None:
    transform = ocio.GroupTransform()
    transform.appendTransform(ocio.ExponentTransform(value=[2.0, 2.0, 2.0, 1.0]))
    path = tmp_path / f"square.{extension}"
    transform.write(format_name, str(path))
    image = torch.tensor([[[[0.2]], [[0.5]], [[0.8]]]], dtype=torch.float32)

    output = apply_lut(image, path, interpolation="tetrahedral")
    metadata = describe_lut(path)

    assert torch.allclose(output, image.square(), rtol=0, atol=7e-6)
    assert metadata["processor_cache_id"]
    assert metadata["cpu_processor_cache_id"]
