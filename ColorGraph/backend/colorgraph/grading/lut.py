from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import numpy as np
import PyOpenColorIO as ocio
import torch
import torch.nn.functional as functional

LutInterpolation = Literal["tetrahedral", "trilinear"]
_SUPPORTED_INTERPOLATIONS = frozenset({"tetrahedral", "trilinear"})
_TETRAHEDRAL_CHUNK_SIZE = 1_048_576


class LutError(ValueError):
    pass


class CubeLutError(LutError):
    pass


@dataclass(frozen=True, slots=True)
class LutFileSignature:
    path: str
    size_bytes: int
    modified_time_ns: int
    changed_time_ns: int
    sha256: str


@dataclass(frozen=True, slots=True)
class _CubeCpuData:
    shaper_table: torch.Tensor | None
    cube_table: torch.Tensor | None
    shaper_domain_min: torch.Tensor
    shaper_domain_max: torch.Tensor
    cube_domain_min: torch.Tensor
    cube_domain_max: torch.Tensor


@dataclass(frozen=True, slots=True)
class _CubeDeviceData:
    shaper_table: torch.Tensor | None
    cube_table: torch.Tensor | None
    cube_volume: torch.Tensor | None
    shaper_domain_min: torch.Tensor
    shaper_domain_max: torch.Tensor
    cube_domain_min: torch.Tensor
    cube_domain_max: torch.Tensor


def _validate_interpolation(interpolation: str) -> LutInterpolation:
    normalized = interpolation.strip().lower()
    if normalized not in _SUPPORTED_INTERPOLATIONS:
        supported = ", ".join(sorted(_SUPPORTED_INTERPOLATIONS))
        raise LutError(f"unsupported LUT interpolation {interpolation!r}; expected {supported}")
    return normalized  # type: ignore[return-value]


@lru_cache(maxsize=256)
def _digest_file(
    path_value: str,
    modified_time_ns: int,
    changed_time_ns: int,
    size_bytes: int,
) -> str:
    del modified_time_ns, changed_time_ns, size_bytes
    digest = hashlib.sha256()
    with Path(path_value).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_signature(path: str | Path) -> LutFileSignature:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise LutError(f"LUT file does not exist: {resolved}")
    stat = resolved.stat()
    changed_time_ns = getattr(stat, "st_ctime_ns", int(stat.st_ctime * 1e9))
    return LutFileSignature(
        path=str(resolved),
        size_bytes=stat.st_size,
        modified_time_ns=stat.st_mtime_ns,
        changed_time_ns=changed_time_ns,
        sha256=_digest_file(
            str(resolved),
            stat.st_mtime_ns,
            changed_time_ns,
            stat.st_size,
        ),
    )


def _parse_vector(parts: list[str], *, count: int, label: str) -> list[float]:
    if len(parts) != count + 1:
        raise CubeLutError(f"{label} requires exactly {count} values")
    try:
        values = [float(value) for value in parts[1:]]
    except ValueError as exc:
        raise CubeLutError(f"{label} contains a non-numeric value") from exc
    if not np.isfinite(values).all():
        raise CubeLutError(f"{label} values must be finite")
    return values


@lru_cache(maxsize=32)
def _load_cube_cpu(signature: LutFileSignature) -> _CubeCpuData:
    path = Path(signature.path)
    lut_1d_size: int | None = None
    lut_3d_size: int | None = None
    domain_min = [0.0, 0.0, 0.0]
    domain_max = [1.0, 1.0, 1.0]
    shaper_range: tuple[float, float] | None = None
    cube_range: tuple[float, float] | None = None
    samples: list[list[float]] = []

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(),
        start=1,
    ):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        keyword = parts[0].upper()
        if keyword == "TITLE":
            continue
        if keyword == "LUT_1D_SIZE":
            if lut_1d_size is not None:
                raise CubeLutError(f"{path}:{line_number} repeats LUT_1D_SIZE")
            try:
                lut_1d_size = int(parts[1])
            except (IndexError, ValueError) as exc:
                raise CubeLutError(f"{path}:{line_number} has an invalid LUT_1D_SIZE") from exc
            continue
        if keyword == "LUT_3D_SIZE":
            if lut_3d_size is not None:
                raise CubeLutError(f"{path}:{line_number} repeats LUT_3D_SIZE")
            try:
                lut_3d_size = int(parts[1])
            except (IndexError, ValueError) as exc:
                raise CubeLutError(f"{path}:{line_number} has an invalid LUT_3D_SIZE") from exc
            continue
        if keyword == "DOMAIN_MIN":
            domain_min = _parse_vector(parts, count=3, label="DOMAIN_MIN")
            continue
        if keyword == "DOMAIN_MAX":
            domain_max = _parse_vector(parts, count=3, label="DOMAIN_MAX")
            continue
        if keyword == "LUT_1D_INPUT_RANGE":
            values = _parse_vector(parts, count=2, label="LUT_1D_INPUT_RANGE")
            shaper_range = (values[0], values[1])
            continue
        if keyword == "LUT_3D_INPUT_RANGE":
            values = _parse_vector(parts, count=2, label="LUT_3D_INPUT_RANGE")
            cube_range = (values[0], values[1])
            continue
        if len(parts) != 3:
            raise CubeLutError(f"{path}:{line_number} has unsupported .cube syntax")
        try:
            sample = [float(value) for value in parts]
        except ValueError as exc:
            raise CubeLutError(f"{path}:{line_number} has an invalid sample") from exc
        if not np.isfinite(sample).all():
            raise CubeLutError(f"{path}:{line_number} sample values must be finite")
        samples.append(sample)

    if lut_1d_size is None and lut_3d_size is None:
        raise CubeLutError(f"{path} does not declare LUT_1D_SIZE or LUT_3D_SIZE")
    if lut_1d_size is not None and lut_1d_size < 2:
        raise CubeLutError(f"{path} does not declare a valid LUT_1D_SIZE")
    if lut_3d_size is not None and lut_3d_size < 2:
        raise CubeLutError(f"{path} does not declare a valid LUT_3D_SIZE")

    one_dimensional_count = lut_1d_size or 0
    three_dimensional_count = (lut_3d_size or 0) ** 3
    expected_count = one_dimensional_count + three_dimensional_count
    if len(samples) != expected_count:
        raise CubeLutError(f"{path} contains {len(samples)} samples; expected {expected_count}")

    default_min = torch.tensor(domain_min, dtype=torch.float32)
    default_max = torch.tensor(domain_max, dtype=torch.float32)
    if torch.any(default_max <= default_min):
        raise CubeLutError(f"{path} requires DOMAIN_MAX greater than DOMAIN_MIN")

    if shaper_range is None:
        shaper_domain_min = default_min
        shaper_domain_max = default_max
    else:
        shaper_domain_min = torch.full((3,), shaper_range[0], dtype=torch.float32)
        shaper_domain_max = torch.full((3,), shaper_range[1], dtype=torch.float32)
    if cube_range is None:
        cube_domain_min = default_min
        cube_domain_max = default_max
    else:
        cube_domain_min = torch.full((3,), cube_range[0], dtype=torch.float32)
        cube_domain_max = torch.full((3,), cube_range[1], dtype=torch.float32)
    if torch.any(shaper_domain_max <= shaper_domain_min):
        raise CubeLutError(f"{path} has an invalid LUT_1D input range")
    if torch.any(cube_domain_max <= cube_domain_min):
        raise CubeLutError(f"{path} has an invalid LUT_3D input range")

    shaper_table = (
        torch.tensor(samples[:one_dimensional_count], dtype=torch.float32).contiguous()
        if lut_1d_size is not None
        else None
    )
    cube_table = (
        torch.tensor(samples[one_dimensional_count:], dtype=torch.float32)
        .reshape(lut_3d_size, lut_3d_size, lut_3d_size, 3)
        .contiguous()
        if lut_3d_size is not None
        else None
    )
    return _CubeCpuData(
        shaper_table=shaper_table,
        cube_table=cube_table,
        shaper_domain_min=shaper_domain_min,
        shaper_domain_max=shaper_domain_max,
        cube_domain_min=cube_domain_min,
        cube_domain_max=cube_domain_max,
    )


def _torch_dtype(dtype_value: str) -> torch.dtype:
    dtype = getattr(torch, dtype_value, None)
    if not isinstance(dtype, torch.dtype):
        raise LutError(f"unsupported LUT tensor dtype: {dtype_value}")
    return dtype


@lru_cache(maxsize=16)
def _load_cube_device(
    signature: LutFileSignature,
    device_value: str,
    dtype_value: str,
) -> _CubeDeviceData:
    cpu = _load_cube_cpu(signature)
    device = torch.device(device_value)
    dtype = _torch_dtype(dtype_value)
    shaper_table = (
        cpu.shaper_table.to(device=device, dtype=dtype) if cpu.shaper_table is not None else None
    )
    cube_table = (
        cpu.cube_table.to(device=device, dtype=dtype) if cpu.cube_table is not None else None
    )
    cube_volume = (
        cube_table.permute(3, 0, 1, 2).unsqueeze(0).contiguous() if cube_table is not None else None
    )

    def moved(vector: torch.Tensor) -> torch.Tensor:
        return vector.to(device=device, dtype=dtype).view(1, 3, 1, 1)

    return _CubeDeviceData(
        shaper_table=shaper_table,
        cube_table=cube_table,
        cube_volume=cube_volume,
        shaper_domain_min=moved(cpu.shaper_domain_min),
        shaper_domain_max=moved(cpu.shaper_domain_max),
        cube_domain_min=moved(cpu.cube_domain_min),
        cube_domain_max=moved(cpu.cube_domain_max),
    )


def _normalized(
    image: torch.Tensor,
    domain_min: torch.Tensor,
    domain_max: torch.Tensor,
) -> torch.Tensor:
    return ((image - domain_min) / (domain_max - domain_min)).clamp(0.0, 1.0)


def _apply_shaper(
    image: torch.Tensor,
    table: torch.Tensor,
    domain_min: torch.Tensor,
    domain_max: torch.Tensor,
) -> torch.Tensor:
    normalized = _normalized(image, domain_min, domain_max)
    scaled = normalized * (table.shape[0] - 1)
    lower = scaled.floor().to(torch.long)
    upper = (lower + 1).clamp_max(table.shape[0] - 1)
    fraction = scaled - lower
    channel = torch.arange(3, device=image.device).view(1, 3, 1, 1)
    lower_value = table[lower, channel]
    upper_value = table[upper, channel]
    return lower_value + (upper_value - lower_value) * fraction


def _sample_cube_vertices(
    table: torch.Tensor,
    indices: torch.Tensor,
) -> torch.Tensor:
    return table[indices[:, 2], indices[:, 1], indices[:, 0]]


def _sample_tetrahedral(
    table: torch.Tensor,
    normalized: torch.Tensor,
) -> torch.Tensor:
    batch, _, height, width = normalized.shape
    flat = normalized.permute(0, 2, 3, 1).reshape(-1, 3)
    outputs: list[torch.Tensor] = []
    table_maximum = table.shape[0] - 1
    for start in range(0, flat.shape[0], _TETRAHEDRAL_CHUNK_SIZE):
        chunk = flat[start : start + _TETRAHEDRAL_CHUNK_SIZE]
        scaled = chunk * table_maximum
        lower = scaled.floor().to(torch.long)
        upper = (lower + 1).clamp_max(table_maximum)
        fraction = scaled - lower
        sorted_fraction, order = torch.sort(fraction, dim=1, descending=True)
        first_step = functional.one_hot(order[:, 0], num_classes=3).to(torch.bool)
        second_step = first_step | functional.one_hot(
            order[:, 1],
            num_classes=3,
        ).to(torch.bool)

        first_indices = torch.where(first_step, upper, lower)
        second_indices = torch.where(second_step, upper, lower)
        corner_000 = _sample_cube_vertices(table, lower)
        corner_first = _sample_cube_vertices(table, first_indices)
        corner_second = _sample_cube_vertices(table, second_indices)
        corner_111 = _sample_cube_vertices(table, upper)
        outputs.append(
            corner_000
            + sorted_fraction[:, 0:1] * (corner_first - corner_000)
            + sorted_fraction[:, 1:2] * (corner_second - corner_first)
            + sorted_fraction[:, 2:3] * (corner_111 - corner_second)
        )
    return (
        torch.cat(outputs, dim=0).reshape(batch, height, width, 3).permute(0, 3, 1, 2).contiguous()
    )


def _sample_trilinear(
    volume: torch.Tensor,
    normalized: torch.Tensor,
) -> torch.Tensor:
    grid = normalized.permute(0, 2, 3, 1).unsqueeze(1) * 2.0 - 1.0
    return functional.grid_sample(
        volume.expand(normalized.shape[0], -1, -1, -1, -1),
        grid,
        mode="bilinear",
        padding_mode="border",
        align_corners=True,
    ).squeeze(2)


def _apply_cube_data(
    image: torch.Tensor,
    data: _CubeDeviceData,
    interpolation: LutInterpolation,
) -> torch.Tensor:
    output = image
    if data.shaper_table is not None:
        output = _apply_shaper(
            output,
            data.shaper_table,
            data.shaper_domain_min,
            data.shaper_domain_max,
        )
    if data.cube_table is None:
        return output
    normalized = _normalized(
        output,
        data.cube_domain_min,
        data.cube_domain_max,
    )
    if interpolation == "tetrahedral":
        return _sample_tetrahedral(data.cube_table, normalized)
    if data.cube_volume is None:  # pragma: no cover - dataclass invariant
        raise LutError("trilinear LUT sampling requires a 3D volume")
    return _sample_trilinear(data.cube_volume, normalized)


def _grading_image(image: torch.Tensor) -> torch.Tensor:
    if image.ndim != 4 or image.shape[1] != 3:
        raise ValueError("image must use NCHW layout with three RGB channels")
    return image if image.dtype in {torch.float32, torch.float64} else image.float()


def _apply_cube_signature(
    image: torch.Tensor,
    signature: LutFileSignature,
    interpolation: LutInterpolation,
) -> torch.Tensor:
    working = _grading_image(image)
    data = _load_cube_device(
        signature,
        str(working.device),
        str(working.dtype).removeprefix("torch."),
    )
    return _apply_cube_data(working, data, interpolation)


@lru_cache(maxsize=32)
def _load_ocio_processor(
    signature: LutFileSignature,
    interpolation: LutInterpolation,
) -> tuple[Any, str, str]:
    extension = Path(signature.path).suffix.lstrip(".").lower()
    if not ocio.FileTransform.IsFormatExtensionSupported(extension):
        raise LutError(f"OpenColorIO does not support .{extension} file transforms")
    transform = ocio.FileTransform()
    transform.setSrc(signature.path)
    transform.setDirection(ocio.TRANSFORM_DIR_FORWARD)
    transform.setInterpolation(
        ocio.INTERP_TETRAHEDRAL if interpolation == "tetrahedral" else ocio.INTERP_LINEAR
    )
    processor = ocio.Config.CreateRaw().getProcessor(transform)
    cpu_processor = processor.getDefaultCPUProcessor()
    return cpu_processor, processor.getCacheID(), cpu_processor.getCacheID()


def _apply_ocio_lut(
    image: torch.Tensor,
    signature: LutFileSignature,
    interpolation: LutInterpolation,
) -> torch.Tensor:
    working = _grading_image(image)
    cpu_processor, _, _ = _load_ocio_processor(signature, interpolation)
    samples = (
        working.detach()
        .permute(0, 2, 3, 1)
        .contiguous()
        .cpu()
        .numpy()
        .astype(np.float32, copy=True)
    )
    cpu_processor.applyRGB(samples.reshape(-1, 3))
    return (
        torch.from_numpy(samples).permute(0, 3, 1, 2).to(device=working.device, dtype=working.dtype)
    )


def apply_lut(
    image: torch.Tensor,
    path: str | Path,
    *,
    interpolation: str = "tetrahedral",
) -> torch.Tensor:
    """Apply a .cube, CLF, or CTF transform with explicit interpolation."""
    selected = _validate_interpolation(interpolation)
    signature = _file_signature(path)
    extension = Path(signature.path).suffix.lower()
    if extension == ".cube":
        return _apply_cube_signature(image, signature, selected)
    if extension in {".clf", ".ctf"}:
        return _apply_ocio_lut(image, signature, selected)
    raise LutError("supported LUT extensions are .cube, .clf, and .ctf")


def apply_cube_lut(
    image: torch.Tensor,
    path: str | Path,
    *,
    interpolation: str = "tetrahedral",
) -> torch.Tensor:
    signature = _file_signature(path)
    if Path(signature.path).suffix.lower() != ".cube":
        raise CubeLutError("apply_cube_lut requires a .cube file")
    return _apply_cube_signature(
        image,
        signature,
        _validate_interpolation(interpolation),
    )


def apply_lut_numpy(
    image: np.ndarray,
    path: str | Path,
    *,
    interpolation: str = "tetrahedral",
) -> np.ndarray:
    if image.ndim != 3 or image.shape[-1] != 3:
        raise ValueError("image must use HWC layout with three RGB channels")
    tensor = torch.from_numpy(image.astype(np.float32, copy=False)).permute(2, 0, 1).unsqueeze(0)
    return (
        apply_lut(tensor, path, interpolation=interpolation)
        .squeeze(0)
        .permute(1, 2, 0)
        .detach()
        .cpu()
        .numpy()
    )


def apply_cube_lut_numpy(
    image: np.ndarray,
    path: str | Path,
    *,
    interpolation: str = "tetrahedral",
) -> np.ndarray:
    if Path(path).suffix.lower() != ".cube":
        raise CubeLutError("apply_cube_lut_numpy requires a .cube file")
    return apply_lut_numpy(image, path, interpolation=interpolation)


def describe_lut(
    path: str | Path,
    *,
    interpolation: str = "tetrahedral",
) -> dict[str, object]:
    selected = _validate_interpolation(interpolation)
    signature = _file_signature(path)
    extension = Path(signature.path).suffix.lower()
    result: dict[str, object] = {
        "path": signature.path,
        "extension": extension,
        "size_bytes": signature.size_bytes,
        "modified_time_ns": signature.modified_time_ns,
        "sha256": signature.sha256,
        "interpolation": selected,
    }
    if extension == ".cube":
        data = _load_cube_cpu(signature)
        result.update(
            {
                "shaper_size": (
                    int(data.shaper_table.shape[0]) if data.shaper_table is not None else None
                ),
                "cube_size": (
                    int(data.cube_table.shape[0]) if data.cube_table is not None else None
                ),
            }
        )
    elif extension in {".clf", ".ctf"}:
        _, processor_cache_id, cpu_processor_cache_id = _load_ocio_processor(
            signature,
            selected,
        )
        result.update(
            {
                "processor_cache_id": processor_cache_id,
                "cpu_processor_cache_id": cpu_processor_cache_id,
            }
        )
    else:
        raise LutError("supported LUT extensions are .cube, .clf, and .ctf")
    return result


def clear_lut_caches() -> None:
    _load_ocio_processor.cache_clear()
    _load_cube_device.cache_clear()
    _load_cube_cpu.cache_clear()
    _digest_file.cache_clear()


def lut_cache_info() -> dict[str, dict[str, int | None]]:
    return {
        "digests": _digest_file.cache_info()._asdict(),
        "parsed_cube": _load_cube_cpu.cache_info()._asdict(),
        "device_cube": _load_cube_device.cache_info()._asdict(),
        "ocio_processor": _load_ocio_processor.cache_info()._asdict(),
    }
