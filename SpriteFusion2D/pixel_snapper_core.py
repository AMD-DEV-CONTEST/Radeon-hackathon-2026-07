"""Pixel Snapper implementation for PyTorch and ROCm.

The public interface is :func:`snap_images`.  The optimized algorithm keeps the
complete image pipeline on one PyTorch device.  The legacy-exact algorithm
preserves the former NumPy implementation's observable output and accelerates
its parallel stages on the selected PyTorch device.  PyTorch ROCm builds expose
AMD accelerators through the ``cuda`` device type, so both modes use standard
PyTorch operations on HIP without a vendor-specific extension.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Sequence

import numpy as np
import torch
import torch.nn.functional as functional

_RGB_CHANNELS = 3
_DISTANCE_TILE_ELEMENTS = 16 * 1024 * 1024

SnapAlgorithm = Literal["optimized", "legacy_exact"]
_SNAP_ALGORITHMS = frozenset(("optimized", "legacy_exact"))


@dataclass(frozen=True, slots=True)
class SnapConfig:
    """Configuration for one complete snapping pipeline."""

    k_colors: int = 16
    pixel_size_override: float = 0.0
    k_seed: int = 42
    max_kmeans_iterations: int = 15
    peak_threshold_multiplier: float = 0.2
    peak_distance_filter: int = 4
    walker_search_window_ratio: float = 0.35
    walker_min_search_window: float = 2.0
    walker_strength_threshold: float = 0.5
    min_cuts_per_axis: int = 4
    fallback_target_segments: int = 64
    max_step_ratio: float = 1.8
    output_scale: int = 1
    algorithm: SnapAlgorithm = "optimized"


class PixelSnapperError(ValueError):
    """Raised when the snapping interface receives an invalid image or config."""


@dataclass(frozen=True, slots=True)
class _QuantizedFrame:
    rgb: torch.Tensor
    labels: torch.Tensor
    palette: torch.Tensor


@dataclass(frozen=True, slots=True)
class SnapGrid:
    """Detected pixel-grid cut positions for one frame.

    Both cut tuples are half-open boundaries over the *input* image, so
    ``len(column_cuts) - 1`` equals the unscaled output width and
    ``len(row_cuts) - 1`` equals the unscaled output height.  Cuts always
    describe the input-to-cell mapping and ignore ``output_scale``.
    """

    column_cuts: tuple[int, ...]
    row_cuts: tuple[int, ...]

    @property
    def output_size(self) -> tuple[int, int]:
        """Return unscaled ``(width, height)`` implied by the cuts."""

        return len(self.column_cuts) - 1, len(self.row_cuts) - 1


def snap_images(
    image: torch.Tensor,
    config: SnapConfig = SnapConfig(),
    *,
    device: torch.device | str | None = None,
) -> list[torch.Tensor]:
    """Snap a ComfyUI image batch on one device and return variable-size frames.

    ``image`` accepts ``(B,H,W,C)``, ``(B,C,H,W)``, or either layout without a
    batch dimension.  Each returned tensor has ComfyUI layout ``(1,H,W,3)``,
    float32 values in ``[0,1]``, and remains on the selected execution device.

    When ``device`` is omitted, an accelerator-resident input stays on its
    current device.  A CPU input uses the current PyTorch GPU when available;
    otherwise the identical tensor implementation runs on CPU.
    """

    return [
        frame for frame, _grid in snap_images_with_grid(image, config, device=device)
    ]


def snap_images_with_grid(
    image: torch.Tensor,
    config: SnapConfig = SnapConfig(),
    *,
    device: torch.device | str | None = None,
) -> list[tuple[torch.Tensor, SnapGrid]]:
    """Snap a batch and also report the detected grid for each frame.

    This is a read-only observation of information the pipeline already
    computes.  Frame tensors are identical to :func:`snap_images` output for
    both ``optimized`` and ``legacy_exact``; callers that need to resample a
    fourth channel through the same grid use :class:`SnapGrid`.
    """

    _validate_config(config)
    execution_device = _resolve_device(image, device)

    with torch.inference_mode():
        batch = _normalize_image_batch(image, execution_device)
        outputs: list[tuple[torch.Tensor, SnapGrid]] = []
        for frame in batch:
            snapped, grid = _snap_frame(frame, config)
            if config.output_scale > 1:
                snapped = snapped.repeat_interleave(
                    config.output_scale, dim=0
                ).repeat_interleave(config.output_scale, dim=1)
            outputs.append((snapped.to(torch.float32).div_(255.0).unsqueeze(0), grid))
        return outputs


def runtime_description(device: torch.device | str | None = None) -> str:
    """Return the active tensor runtime name for diagnostics and benchmarks."""

    selected = torch.device(device) if device is not None else _default_device()
    if selected.type != "cuda":
        return selected.type
    platform = "ROCm/HIP" if torch.version.hip is not None else "CUDA"
    return f"{platform} {torch.cuda.get_device_name(selected)}"


def _default_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda", torch.cuda.current_device())
    return torch.device("cpu")


def _resolve_device(
    image: torch.Tensor, requested: torch.device | str | None
) -> torch.device:
    if requested is not None:
        return torch.device(requested)
    if image.device.type != "cpu":
        return image.device
    return _default_device()


def _validate_config(config: SnapConfig) -> None:
    if config.algorithm not in _SNAP_ALGORITHMS:
        raise PixelSnapperError(
            f"algorithm must be one of {', '.join(sorted(_SNAP_ALGORITHMS))}"
        )
    if config.k_colors < 1:
        raise PixelSnapperError("k_colors must be greater than zero")
    if config.max_kmeans_iterations < 1:
        raise PixelSnapperError("max_kmeans_iterations must be greater than zero")
    if config.peak_distance_filter < 1:
        raise PixelSnapperError("peak_distance_filter must be at least one")
    if config.min_cuts_per_axis < 2:
        raise PixelSnapperError("min_cuts_per_axis must be at least two")
    if config.fallback_target_segments < 1:
        raise PixelSnapperError("fallback_target_segments must be positive")
    if config.max_step_ratio < 1.0:
        raise PixelSnapperError("max_step_ratio must be at least one")
    if not 1 <= config.output_scale <= 16:
        raise PixelSnapperError("output_scale must be between 1 and 16")


def _normalize_image_batch(image: torch.Tensor, device: torch.device) -> torch.Tensor:
    if image.ndim == 3:
        image = image.unsqueeze(0)
    if image.ndim != 4:
        raise PixelSnapperError(
            "image must have shape (B,H,W,C), (B,C,H,W), (H,W,C), or (C,H,W)"
        )

    if image.shape[-1] in (3, 4):
        batch = image
    elif image.shape[1] in (3, 4):
        batch = image.movedim(1, -1)
    else:
        raise PixelSnapperError("image must contain three or four channels")

    if batch.shape[0] == 0:
        raise PixelSnapperError("image batch cannot be empty")
    if batch.shape[-1] == 4:
        batch = batch[..., :3]

    height, width = int(batch.shape[1]), int(batch.shape[2])
    _validate_dimensions(width, height)
    if not bool(torch.isfinite(batch).all().item()):
        raise PixelSnapperError("image contains NaN or Inf values")

    return batch.detach().to(device=device, dtype=torch.float32).clamp(0.0, 1.0)


def _validate_dimensions(width: int, height: int) -> None:
    if width < 3 or height < 3:
        raise PixelSnapperError("image dimensions must be at least 3x3")
    if width > 10_000 or height > 10_000:
        raise PixelSnapperError("image dimensions exceed the 10000x10000 limit")


def _snap_frame(
    frame: torch.Tensor, config: SnapConfig
) -> tuple[torch.Tensor, SnapGrid]:
    height, width = int(frame.shape[0]), int(frame.shape[1])
    _validate_pixel_size(config.pixel_size_override, width, height)

    rgb_u8 = frame.mul(255.0).round_().to(torch.uint8)
    if config.algorithm == "legacy_exact":
        return _snap_frame_legacy_exact(rgb_u8, config)
    return _snap_frame_optimized(rgb_u8, config)


def _as_grid(column_cuts: torch.Tensor, row_cuts: torch.Tensor) -> SnapGrid:
    return SnapGrid(
        column_cuts=tuple(int(v) for v in column_cuts.tolist()),
        row_cuts=tuple(int(v) for v in row_cuts.tolist()),
    )


def _snap_frame_optimized(
    rgb_u8: torch.Tensor, config: SnapConfig
) -> tuple[torch.Tensor, SnapGrid]:
    height, width = int(rgb_u8.shape[0]), int(rgb_u8.shape[1])
    quantized = _quantize_frame(rgb_u8, config)
    profile_x, profile_y = _compute_profiles(quantized.rgb)

    step_x = _estimate_step_size(profile_x, config)
    step_y = _estimate_step_size(profile_y, config)
    resolved_x, resolved_y = _resolve_step_sizes(step_x, step_y, width, height, config)

    column_cuts = _locate_grid_cuts(profile_x, resolved_x, config)
    row_cuts = _locate_grid_cuts(profile_y, resolved_y, config)
    return _cell_modes(quantized, column_cuts, row_cuts), _as_grid(
        column_cuts, row_cuts
    )


def _validate_pixel_size(pixel_size: float, width: int, height: int) -> None:
    if pixel_size == 0.0:
        return
    maximum = min(width, height) / 2.0
    if not math.isfinite(pixel_size) or not 1.0 <= pixel_size <= maximum:
        raise PixelSnapperError(
            f"pixel_size_override {pixel_size:.1f} is outside [1, {maximum:.1f}]"
        )


def _pack_rgb(rgb: torch.Tensor) -> torch.Tensor:
    channels = rgb.to(torch.int32)
    return (
        torch.bitwise_left_shift(channels[..., 0], 16)
        | torch.bitwise_left_shift(channels[..., 1], 8)
        | channels[..., 2]
    )


def _unpack_rgb(packed: torch.Tensor) -> torch.Tensor:
    return torch.stack(
        (
            torch.bitwise_and(torch.bitwise_right_shift(packed, 16), 255),
            torch.bitwise_and(torch.bitwise_right_shift(packed, 8), 255),
            torch.bitwise_and(packed, 255),
        ),
        dim=1,
    ).to(torch.float32)


def _quantize_frame(rgb: torch.Tensor, config: SnapConfig) -> _QuantizedFrame:
    height, width, _ = rgb.shape
    packed = _pack_rgb(rgb).reshape(-1)
    unique, inverse, counts = torch.unique(
        packed, sorted=True, return_inverse=True, return_counts=True
    )
    points = _unpack_rgb(unique)
    weights = counts.to(torch.float32)
    cluster_count = min(config.k_colors, int(unique.numel()))

    if cluster_count == int(unique.numel()):
        palette = points.to(torch.uint8)
        labels = inverse.reshape(height, width)
        return _QuantizedFrame(palette[labels], labels, palette)

    centroids = _seed_centroids(points, weights, cluster_count, config.k_seed)
    previous = centroids

    for _ in range(config.max_kmeans_iterations):
        labels, _ = _nearest_centroids(points, centroids)
        weighted_points = points * weights.unsqueeze(1)
        sums = torch.zeros_like(centroids)
        masses = torch.zeros(cluster_count, dtype=torch.float32, device=points.device)
        sums.index_add_(0, labels, weighted_points)
        masses.index_add_(0, labels, weights)
        updated = torch.where(
            masses.unsqueeze(1) > 0,
            sums / masses.clamp_min(1.0).unsqueeze(1),
            centroids,
        )

        movement = (updated - previous).square().sum(dim=1).amax()
        centroids = updated
        if float(movement.item()) < 0.01:
            break
        previous = updated

    unique_labels, _ = _nearest_centroids(points, centroids)
    palette = centroids.round().clamp_(0.0, 255.0).to(torch.uint8)
    pixel_labels = unique_labels[inverse].reshape(height, width)
    return _QuantizedFrame(palette[pixel_labels], pixel_labels, palette)


def _seed_centroids(
    points: torch.Tensor,
    weights: torch.Tensor,
    cluster_count: int,
    seed: int,
) -> torch.Tensor:
    generator = torch.Generator(device=points.device)
    generator.manual_seed(seed)

    first = torch.multinomial(weights, 1, generator=generator).squeeze(0)
    chosen = [points[first]]
    minimum_distance = torch.full(
        (points.shape[0],),
        torch.inf,
        dtype=torch.float32,
        device=points.device,
    )

    for _ in range(1, cluster_count):
        _, distance = _nearest_centroids(points, chosen[-1].unsqueeze(0))
        minimum_distance = torch.minimum(minimum_distance, distance)
        probabilities = minimum_distance * weights
        if float(probabilities.sum().item()) == 0.0:
            probabilities = weights
        selected = torch.multinomial(probabilities, 1, generator=generator).squeeze(0)
        chosen.append(points[selected])

    return torch.stack(chosen)


def _nearest_centroids(
    points: torch.Tensor, centroids: torch.Tensor
) -> tuple[torch.Tensor, torch.Tensor]:
    cluster_count = int(centroids.shape[0])
    tile_points = max(1, _DISTANCE_TILE_ELEMENTS // max(cluster_count, 1))
    centroid_norm = centroids.square().sum(dim=1).unsqueeze(0)
    labels: list[torch.Tensor] = []
    distances: list[torch.Tensor] = []

    for point_tile in points.split(tile_points):
        distance_matrix = (
            point_tile.square().sum(dim=1, keepdim=True)
            + centroid_norm
            - 2.0 * point_tile @ centroids.transpose(0, 1)
        ).clamp_min_(0.0)
        tile_distance, tile_labels = distance_matrix.min(dim=1)
        labels.append(tile_labels)
        distances.append(tile_distance)

    return torch.cat(labels), torch.cat(distances)


def _compute_profiles(rgb: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    values = rgb.to(torch.float32)
    gray = values[..., 0] * 0.299 + values[..., 1] * 0.587 + values[..., 2] * 0.114

    column_profile = torch.zeros(gray.shape[1], dtype=torch.float32, device=gray.device)
    row_profile = torch.zeros(gray.shape[0], dtype=torch.float32, device=gray.device)
    column_profile[1:-1] = (gray[:, 2:] - gray[:, :-2]).abs().sum(dim=0)
    row_profile[1:-1] = (gray[2:, :] - gray[:-2, :]).abs().sum(dim=1)
    return column_profile, row_profile


def _estimate_step_size(profile: torch.Tensor, config: SnapConfig) -> float | None:
    maximum = profile.amax()
    if float(maximum.item()) == 0.0:
        return None

    interior = profile[1:-1]
    peak_mask = (
        (interior > maximum * config.peak_threshold_multiplier)
        & (interior > profile[:-2])
        & (interior > profile[2:])
    )

    suppression_radius = config.peak_distance_filter - 1
    if suppression_radius > 0:
        pooled = functional.max_pool1d(
            profile.view(1, 1, -1),
            kernel_size=2 * suppression_radius + 1,
            stride=1,
            padding=suppression_radius,
        ).view(-1)
        peak_mask &= interior >= pooled[1:-1]

    peaks = torch.nonzero(peak_mask, as_tuple=False).flatten() + 1
    if peaks.numel() < 2:
        return None

    differences = peaks[1:] - peaks[:-1]
    middle = int(differences.numel()) // 2 + 1
    return float(differences.kthvalue(middle).values.item())


def _resolve_step_sizes(
    step_x: float | None,
    step_y: float | None,
    width: int,
    height: int,
    config: SnapConfig,
) -> tuple[float, float]:
    if config.pixel_size_override != 0.0:
        return config.pixel_size_override, config.pixel_size_override

    if step_x is not None and step_y is not None:
        ratio = max(step_x, step_y) / min(step_x, step_y)
        shared = (
            min(step_x, step_y)
            if ratio > config.max_step_ratio
            else (step_x + step_y) / 2.0
        )
        return shared, shared
    if step_x is not None:
        return step_x, step_x
    if step_y is not None:
        return step_y, step_y

    fallback = max(min(width, height) / float(config.fallback_target_segments), 1.0)
    return fallback, fallback


def _locate_grid_cuts(
    profile: torch.Tensor, step_size: float, config: SnapConfig
) -> torch.Tensor:
    limit = int(profile.numel())
    minimum_cells = min(max(config.min_cuts_per_axis - 1, 1), limit)
    desired_cells = int(round(limit / step_size)) if step_size > 0.0 else 0
    desired_cells = min(max(desired_cells, minimum_cells), limit)

    if desired_cells == limit:
        return torch.arange(limit + 1, dtype=torch.int64, device=profile.device)
    if desired_cells == 1:
        return torch.tensor([0, limit], dtype=torch.int64, device=profile.device)

    cell_width = limit / float(desired_cells)
    targets = torch.arange(
        1, desired_cells, dtype=torch.float32, device=profile.device
    ).mul_(cell_width)
    radius = int(
        math.ceil(
            max(
                cell_width * config.walker_search_window_ratio,
                config.walker_min_search_window,
            )
        )
    )
    offsets = torch.arange(
        -radius, radius + 1, dtype=torch.int64, device=profile.device
    )
    candidates = targets.round().to(torch.int64).unsqueeze(1) + offsets.unsqueeze(0)
    valid = (candidates > 0) & (candidates < limit)
    sampled = profile[candidates.clamp(0, limit - 1)]
    sampled = sampled.masked_fill(~valid, -torch.inf)

    best_values, best_offsets = sampled.max(dim=1)
    best_positions = candidates.gather(1, best_offsets.unsqueeze(1)).squeeze(1)
    fallback_positions = targets.round().to(torch.int64).clamp_(1, limit - 1)
    selected = torch.where(
        best_values > profile.mean() * config.walker_strength_threshold,
        best_positions,
        fallback_positions,
    )
    selected = _project_strictly_increasing(selected, limit)

    endpoints = torch.tensor([0, limit], dtype=torch.int64, device=profile.device)
    return torch.cat((endpoints[:1], selected, endpoints[1:]))


def _project_strictly_increasing(positions: torch.Tensor, limit: int) -> torch.Tensor:
    count = int(positions.numel())
    rank = torch.arange(count, dtype=torch.int64, device=positions.device)
    lower = rank + 1
    upper = limit - (count - rank)
    projected = torch.maximum(torch.minimum(positions, upper), lower)
    projected = torch.cummax(projected - rank, dim=0).values + rank
    return torch.minimum(projected, upper)


def _cell_modes(
    quantized: _QuantizedFrame,
    column_cuts: torch.Tensor,
    row_cuts: torch.Tensor,
) -> torch.Tensor:
    height, width = quantized.labels.shape
    output_width = int(column_cuts.numel()) - 1
    output_height = int(row_cuts.numel()) - 1
    palette_size = int(quantized.palette.shape[0])

    columns = torch.bucketize(
        torch.arange(width, device=quantized.labels.device),
        column_cuts[1:-1],
        right=True,
    )
    rows = torch.bucketize(
        torch.arange(height, device=quantized.labels.device),
        row_cuts[1:-1],
        right=True,
    )
    cell_ids = rows.unsqueeze(1) * output_width + columns.unsqueeze(0)
    vote_keys = cell_ids.reshape(-1).to(
        torch.int64
    ) * palette_size + quantized.labels.reshape(-1)
    unique_votes, vote_counts = torch.unique(vote_keys, sorted=True, return_counts=True)
    vote_cells = torch.div(unique_votes, palette_size, rounding_mode="floor")
    vote_labels = torch.remainder(unique_votes, palette_size)

    color_space_size = 1 << 24
    palette_keys = _pack_rgb(quantized.palette).to(torch.int64)
    vote_colors = palette_keys[vote_labels]
    scores = vote_counts.to(torch.int64) * color_space_size + (
        color_space_size - 1 - vote_colors
    )
    best_scores = torch.zeros(
        output_height * output_width,
        dtype=torch.int64,
        device=quantized.labels.device,
    )
    best_scores.scatter_reduce_(0, vote_cells, scores, reduce="amax", include_self=True)
    winning_colors = (
        color_space_size - 1 - torch.remainder(best_scores, color_space_size)
    )
    return (
        _unpack_rgb(winning_colors.to(torch.int32))
        .to(torch.uint8)
        .reshape(output_height, output_width, _RGB_CHANNELS)
    )


def _snap_frame_legacy_exact(
    rgb_u8: torch.Tensor, config: SnapConfig
) -> tuple[torch.Tensor, SnapGrid]:
    """Run the former NumPy algorithm with GPU-parallel heavy stages.

    The compatibility path intentionally keeps PCG64 sampling, ordered float32
    centroid accumulation, float64 profiles, and the stateful cut walker on the
    CPU. Full-pixel distance assignment and cell voting execute on the selected
    PyTorch device. This division preserves the former observable output while
    accelerating the two dominant image-wide stages.
    """

    quantized_cpu = _legacy_quantize_exact(rgb_u8, config)
    height, width, _ = quantized_cpu.shape
    profile_x, profile_y = _legacy_compute_profiles(quantized_cpu)
    step_x = _legacy_estimate_step_size(profile_x, config)
    step_y = _legacy_estimate_step_size(profile_y, config)
    resolved_x, resolved_y = _legacy_resolve_step_sizes(
        step_x, step_y, width, height, config
    )
    raw_columns = _legacy_walk(profile_x, resolved_x, width, config)
    raw_rows = _legacy_walk(profile_y, resolved_y, height, config)
    columns, rows = _legacy_stabilize_both_axes(
        profile_x,
        profile_y,
        raw_columns,
        raw_rows,
        width,
        height,
        config,
    )

    quantized_rgb = torch.from_numpy(quantized_cpu).to(rgb_u8.device)
    packed = _pack_rgb(quantized_rgb).reshape(-1)
    unique, inverse = torch.unique(packed, sorted=True, return_inverse=True)
    palette = _unpack_rgb(unique).to(torch.uint8)
    labels = inverse.reshape(height, width)
    quantized = _QuantizedFrame(palette[labels], labels, palette)
    column_cuts = torch.tensor(columns, dtype=torch.int64, device=rgb_u8.device)
    row_cuts = torch.tensor(rows, dtype=torch.int64, device=rgb_u8.device)
    return _cell_modes(quantized, column_cuts, row_cuts), _as_grid(
        column_cuts, row_cuts
    )


def _legacy_quantize_exact(rgb: torch.Tensor, config: SnapConfig) -> np.ndarray:
    """Reproduce the former PCG64/K-Means result with GPU assignments."""

    height, width, _ = rgb.shape
    pixels_cpu = (
        rgb.detach().cpu().numpy().reshape(-1, _RGB_CHANNELS).astype(np.float32)
    )
    pixels = rgb.reshape(-1, _RGB_CHANNELS).to(torch.float32)
    pixel_count = int(pixels.shape[0])
    cluster_count = min(config.k_colors, pixel_count)
    generator = np.random.default_rng(config.k_seed)

    first_index = int(generator.integers(0, pixel_count))
    seed_indices = [first_index]
    minimum_distance = torch.full(
        (pixel_count,), torch.inf, dtype=torch.float32, device=rgb.device
    )

    for _ in range(1, cluster_count):
        distance = _legacy_distance_to_centroid(pixels, pixels[seed_indices[-1]])
        minimum_distance = torch.minimum(minimum_distance, distance)
        distance_cpu = minimum_distance.cpu().numpy()
        distance_sum = float(np.sum(distance_cpu))
        if distance_sum <= 0.0 or not math.isfinite(distance_sum):
            selected = int(generator.integers(0, pixel_count))
        else:
            selected = int(generator.choice(pixel_count, p=distance_cpu / distance_sum))
        seed_indices.append(selected)

    centroids = pixels_cpu[seed_indices].copy()
    previous_centroids = centroids.copy()

    for iteration in range(config.max_kmeans_iterations):
        labels = _legacy_assign_pixels(pixels, centroids)
        labels_cpu = labels.cpu().numpy()
        sums = np.zeros_like(centroids)
        np.add.at(sums, labels_cpu, pixels_cpu)
        counts = np.bincount(labels_cpu, minlength=cluster_count).astype(np.float32)
        nonzero = counts > 0
        centroids[nonzero] = sums[nonzero] / counts[nonzero, None]

        if iteration > 0:
            movement = np.max(np.sum((centroids - previous_centroids) ** 2, axis=1))
            if movement < 0.01:
                break
        previous_centroids = centroids.copy()

    labels = _legacy_assign_pixels(pixels, centroids).cpu().numpy()
    quantized = centroids[labels].round().clip(0, 255).astype(np.uint8)
    return quantized.reshape(height, width, _RGB_CHANNELS)


def _legacy_distance_to_centroid(
    points: torch.Tensor, centroid: torch.Tensor
) -> torch.Tensor:
    delta = points - centroid
    return delta[:, 0].square() + delta[:, 1].square() + delta[:, 2].square()


def _legacy_assign_pixels(
    pixels: torch.Tensor, centroids_cpu: np.ndarray
) -> torch.Tensor:
    centroids = torch.from_numpy(centroids_cpu).to(pixels.device)
    cluster_count = int(centroids.shape[0])
    tile_points = max(1, _DISTANCE_TILE_ELEMENTS // cluster_count)
    labels: list[torch.Tensor] = []
    for point_tile in pixels.split(tile_points):
        distance = (point_tile[:, None, 0] - centroids[None, :, 0]).square_()
        distance.add_((point_tile[:, None, 1] - centroids[None, :, 1]).square_())
        distance.add_((point_tile[:, None, 2] - centroids[None, :, 2]).square_())
        labels.append(distance.argmin(dim=1))
    return torch.cat(labels)


def _legacy_compute_profiles(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    height, width, _ = rgb.shape
    gray = (
        0.299 * rgb[:, :, 0].astype(np.float64)
        + 0.587 * rgb[:, :, 1].astype(np.float64)
        + 0.114 * rgb[:, :, 2].astype(np.float64)
    )
    column_profile = np.zeros(width, dtype=np.float64)
    row_profile = np.zeros(height, dtype=np.float64)
    column_profile[1:-1] = np.sum(np.abs(gray[:, 2:] - gray[:, :-2]), axis=0)
    row_profile[1:-1] = np.sum(np.abs(gray[2:, :] - gray[:-2, :]), axis=1)
    return column_profile, row_profile


def _legacy_estimate_step_size(profile: np.ndarray, config: SnapConfig) -> float | None:
    maximum = float(np.max(profile))
    if maximum == 0.0:
        return None
    threshold = maximum * config.peak_threshold_multiplier
    peaks = [
        index
        for index in range(1, len(profile) - 1)
        if profile[index] > threshold
        and profile[index] > profile[index - 1]
        and profile[index] > profile[index + 1]
    ]
    if len(peaks) < 2:
        return None

    clean_peaks = [peaks[0]]
    for peak in peaks[1:]:
        if peak - clean_peaks[-1] > config.peak_distance_filter - 1:
            clean_peaks.append(peak)
    if len(clean_peaks) < 2:
        return None

    differences = np.diff(clean_peaks)
    differences.sort()
    return float(differences[len(differences) // 2])


def _legacy_resolve_step_sizes(
    step_x: float | None,
    step_y: float | None,
    width: int,
    height: int,
    config: SnapConfig,
) -> tuple[float, float]:
    if config.pixel_size_override != 0.0:
        return config.pixel_size_override, config.pixel_size_override
    if step_x is not None and step_y is not None:
        ratio = step_x / step_y if step_x > step_y else step_y / step_x
        if ratio > config.max_step_ratio:
            smaller = min(step_x, step_y)
            return smaller, smaller
        average = (step_x + step_y) / 2.0
        return average, average
    if step_x is not None:
        return step_x, step_x
    if step_y is not None:
        return step_y, step_y
    fallback = min(width, height) / float(config.fallback_target_segments)
    return max(fallback, 1.0), max(fallback, 1.0)


def _legacy_walk(
    profile: np.ndarray,
    step_size: float,
    limit: int,
    config: SnapConfig,
) -> list[int]:
    cuts = [0]
    current_position = 0.0
    search_window = max(
        step_size * config.walker_search_window_ratio,
        config.walker_min_search_window,
    )
    mean_value = float(np.mean(profile))

    while current_position < limit:
        target = current_position + step_size
        if target >= limit:
            cuts.append(limit)
            break
        start = max(int(target - search_window), int(current_position + 1))
        end = min(int(target + search_window), limit)
        if end <= start:
            current_position = target
            continue
        segment = profile[start:end]
        relative = int(np.argmax(segment))
        maximum = float(segment[relative]) if segment.size else -1.0
        maximum_index = start + relative
        if maximum > mean_value * config.walker_strength_threshold:
            cuts.append(maximum_index)
            current_position = float(maximum_index)
        else:
            cuts.append(int(target))
            current_position = target
    return cuts


def _legacy_sanitize_cuts(cuts: list[int], limit: int) -> list[int]:
    normalized: list[int] = []
    has_zero = False
    has_limit = False
    for value in cuts:
        value = max(value, 0)
        if value == 0:
            has_zero = True
        if value >= limit:
            value = limit
            has_limit = True
        normalized.append(value)
    if not has_zero:
        normalized.append(0)
    if not has_limit:
        normalized.append(limit)
    return sorted(set(normalized))


def _legacy_snap_uniform_cuts(
    profile: np.ndarray,
    limit: int,
    target_step: float,
    config: SnapConfig,
    minimum_required: int,
) -> list[int]:
    if limit == 1:
        return [0, 1]
    desired_cells = (
        int(round(limit / target_step))
        if target_step > 0.0 and math.isfinite(target_step)
        else 0
    )
    desired_cells = max(desired_cells, minimum_required - 1, 1)
    desired_cells = min(desired_cells, limit)
    cell_width = limit / float(desired_cells)
    search_window = max(
        cell_width * config.walker_search_window_ratio,
        config.walker_min_search_window,
    )
    mean_value = float(np.mean(profile))
    cuts = [0]

    for index in range(1, desired_cells):
        target = cell_width * index
        previous = cuts[-1]
        if previous + 1 >= limit:
            break
        start = max(int(math.floor(target - search_window)), previous + 1, 0)
        end = min(int(math.ceil(target + search_window)), limit - 1)
        if end < start:
            start = previous + 1
            end = start
        segment = profile[start : min(end + 1, len(profile))]
        if segment.size:
            relative = int(np.argmax(segment))
            best_value = float(segment[relative])
            best_index = start + relative
        else:
            best_value = -1.0
            best_index = start
        if best_value < mean_value * config.walker_strength_threshold:
            fallback_index = int(round(target))
            if fallback_index <= previous:
                fallback_index = previous + 1
            if fallback_index >= limit:
                fallback_index = max(limit - 1, previous + 1)
            best_index = fallback_index
        cuts.append(best_index)

    if cuts[-1] != limit:
        cuts.append(limit)
    return _legacy_sanitize_cuts(cuts, limit)


def _legacy_stabilize_cuts(
    profile: np.ndarray,
    cuts: list[int],
    limit: int,
    sibling_cuts: list[int],
    sibling_limit: int,
    config: SnapConfig,
) -> list[int]:
    cuts = _legacy_sanitize_cuts(cuts, limit)
    minimum_required = min(max(config.min_cuts_per_axis, 2), limit + 1)
    axis_cells = max(len(cuts) - 1, 0)
    sibling_cells = max(len(sibling_cuts) - 1, 0)
    sibling_has_grid = (
        sibling_limit > 0
        and sibling_cells >= minimum_required - 1
        and sibling_cells > 0
    )
    steps_skewed = False
    if sibling_has_grid and axis_cells > 0:
        axis_step = limit / float(axis_cells)
        sibling_step = sibling_limit / float(sibling_cells)
        ratio = axis_step / sibling_step
        steps_skewed = (
            ratio > config.max_step_ratio or ratio < 1.0 / config.max_step_ratio
        )
    if len(cuts) >= minimum_required and not steps_skewed:
        return cuts
    if sibling_has_grid:
        target_step = sibling_limit / float(sibling_cells)
    elif config.fallback_target_segments > 1:
        target_step = limit / float(config.fallback_target_segments)
    elif axis_cells > 0:
        target_step = limit / float(axis_cells)
    else:
        target_step = float(limit)
    if not math.isfinite(target_step) or target_step <= 0.0:
        target_step = 1.0
    return _legacy_snap_uniform_cuts(
        profile, limit, target_step, config, minimum_required
    )


def _legacy_stabilize_both_axes(
    profile_x: np.ndarray,
    profile_y: np.ndarray,
    raw_columns: list[int],
    raw_rows: list[int],
    width: int,
    height: int,
    config: SnapConfig,
) -> tuple[list[int], list[int]]:
    columns = _legacy_stabilize_cuts(
        profile_x, list(raw_columns), width, raw_rows, height, config
    )
    rows = _legacy_stabilize_cuts(
        profile_y, list(raw_rows), height, raw_columns, width, config
    )
    column_step = width / float(max(len(columns) - 1, 1))
    row_step = height / float(max(len(rows) - 1, 1))
    ratio = column_step / row_step if column_step > row_step else row_step / column_step
    if ratio <= config.max_step_ratio:
        return columns, rows

    target_step = min(column_step, row_step)
    if column_step > target_step * 1.2:
        columns = _legacy_snap_uniform_cuts(
            profile_x,
            width,
            target_step,
            config,
            config.min_cuts_per_axis,
        )
    if row_step > target_step * 1.2:
        rows = _legacy_snap_uniform_cuts(
            profile_y,
            height,
            target_step,
            config,
            config.min_cuts_per_axis,
        )
    return columns, rows


__all__: Sequence[str] = (
    "PixelSnapperError",
    "SnapAlgorithm",
    "SnapConfig",
    "runtime_description",
    "snap_images",
)
