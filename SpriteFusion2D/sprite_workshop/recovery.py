"""Thin domain adapter over the frozen snapping core.

Both algorithms take exactly the same path through this module; the only
difference is ``SnapConfig.algorithm``.  No per-algorithm branches are allowed
here (BACKEND_CLI_PLAN.md 8.1).

Alpha is the interesting part.  The core is RGB-only and its output size is a
detection result, so alpha cannot be pasted back afterwards.  Instead it is
resampled through the very same grid the core used, obtained from the read-only
``snap_images_with_grid`` observation (BACKEND_CLI_PLAN.md 3.1, 8.1.1).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence

import numpy as np

from .errors import OperationError, UsageError
from .model import Frame, FrameSet, Point, Rect, RgbaImage, Size, WorkshopWarning

SnapAlgorithm = Literal["optimized", "legacy_exact"]
ALGORITHMS: tuple[SnapAlgorithm, ...] = ("optimized", "legacy_exact")

ALPHA_THRESHOLD = 128


@dataclass(frozen=True, slots=True)
class RecoverySpec:
    """Everything the recover step needs, validated on construction."""

    algorithm: SnapAlgorithm = "optimized"
    device: str = "auto"
    output_scale: int = 1
    ignore_alpha: bool = False
    k_colors: int = 16
    pixel_size_override: float = 0.0
    # No force_columns/force_rows here on purpose.  Constraining the detector
    # would mean re-running the core's cell voting with different cuts, which
    # is core work, not adapter work.  The real need — "the sheet is 4 columns
    # and the recovered width does not divide by 4" — is handled downstream by
    # `split --tail crop|pad`, which reports exactly what it dropped or padded.

    def __post_init__(self) -> None:
        if self.algorithm not in ALGORITHMS:
            raise UsageError(
                "algorithm must be one of " + ", ".join(ALGORITHMS),
                algorithm=self.algorithm,
            )
        if self.output_scale != 1:
            # Scaling belongs to preview/export, never to a stored asset
            # (BACKEND_CLI_PLAN.md 5.1).
            raise UsageError(
                "project assets are always stored at 1x; scale in preview or export instead",
                output_scale=self.output_scale,
            )
        if self.k_colors < 1:
            raise UsageError(
                "k_colors must be greater than zero", k_colors=self.k_colors
            )


@dataclass(frozen=True, slots=True)
class RecoveredGrid:
    """The detected grid, carried forward so `split` need not guess."""

    column_cuts: tuple[int, ...]
    row_cuts: tuple[int, ...]

    @property
    def columns(self) -> int:
        return len(self.column_cuts) - 1

    @property
    def rows(self) -> int:
        return len(self.row_cuts) - 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "column_cuts": list(self.column_cuts),
            "row_cuts": list(self.row_cuts),
            "columns": self.columns,
            "rows": self.rows,
        }


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    frames: FrameSet
    grids: tuple[RecoveredGrid, ...]
    algorithm: SnapAlgorithm
    device: str
    elapsed_ms: float
    warnings: tuple[WorkshopWarning, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)


def recover_frames(
    images: Sequence[RgbaImage],
    spec: RecoverySpec = RecoverySpec(),
    *,
    set_id: str = "recovered",
) -> RecoveryResult:
    """Recover pixel-art images to their true 1x grid."""

    if not images:
        raise UsageError("no images to recover")

    # Imported lazily so that merely importing sprite_workshop does not pull in
    # torch; only the recover path pays that cost (FRONTEND_PLAN.md 3.1).
    import torch  # noqa: PLC0415

    from pixel_snapper_core import (  # noqa: PLC0415
        PixelSnapperError,
        SnapConfig,
        snap_images_with_grid,
    )

    config = SnapConfig(
        k_colors=spec.k_colors,
        pixel_size_override=spec.pixel_size_override,
        output_scale=1,
        algorithm=spec.algorithm,
    )
    device = None if spec.device == "auto" else spec.device

    warnings: list[WorkshopWarning] = []
    frames: list[Frame] = []
    grids: list[RecoveredGrid] = []

    started = time.perf_counter()
    for index, image in enumerate(images):
        rgb = image.array[:, :, :3].astype(np.float32) / 255.0
        tensor = torch.from_numpy(np.ascontiguousarray(rgb)).unsqueeze(0)

        try:
            outputs = snap_images_with_grid(tensor, config, device=device)
        except PixelSnapperError as exc:
            raise OperationError(
                "recovery failed",
                index=index,
                algorithm=spec.algorithm,
                reason=str(exc),
            ) from exc

        snapped, grid = outputs[0]
        rgb_u8 = (
            snapped.squeeze(0)
            .mul(255.0)
            .round()
            .clamp(0, 255)
            .to(torch.uint8)
            .cpu()
            .numpy()
        )

        column_cuts = list(grid.column_cuts)
        row_cuts = list(grid.row_cuts)
        alpha = _resample_alpha(image, column_cuts, row_cuts, spec)

        height, width = rgb_u8.shape[0], rgb_u8.shape[1]
        rgba = np.empty((height, width, 4), dtype=np.uint8)
        rgba[:, :, :3] = rgb_u8
        rgba[:, :, 3] = alpha
        recovered = RgbaImage(rgba).normalized()

        frame_id = f"{set_id}_{index:02d}" if len(images) > 1 else set_id
        frames.append(
            Frame(
                id=frame_id,
                image=recovered,
                source_size=Size(width, height),
                trim_rect=Rect(0, 0, width, height),
                trim_offset=Point(0, 0),
                anchor=Point(width // 2, height),
                label="",
                tags={},
            )
        )
        grids.append(
            RecoveredGrid(column_cuts=tuple(column_cuts), row_cuts=tuple(row_cuts))
        )

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    resolved_device = _describe_device(spec.device)

    return RecoveryResult(
        frames=FrameSet(id=set_id, frames=tuple(frames)),
        grids=tuple(grids),
        algorithm=spec.algorithm,
        device=resolved_device,
        elapsed_ms=elapsed_ms,
        warnings=tuple(warnings),
        metrics={
            "images": len(images),
            "input_sizes": [f"{img.width}x{img.height}" for img in images],
            "output_sizes": [f"{f.size.width}x{f.size.height}" for f in frames],
        },
    )


def _resample_alpha(
    image: RgbaImage,
    column_cuts: Sequence[int],
    row_cuts: Sequence[int],
    spec: RecoverySpec,
) -> np.ndarray:
    """Majority-vote alpha through the same cells the core used.

    Ties resolve to opaque: better to leave a spare pixel the user can erase
    than to eat the character outline during recovery
    (BACKEND_CLI_PLAN.md 8.1.1).
    """

    out_w = len(column_cuts) - 1
    out_h = len(row_cuts) - 1

    if spec.ignore_alpha:
        return np.full((out_h, out_w), 255, dtype=np.uint8)

    source_alpha = image.array[:, :, 3]
    if bool((source_alpha == 255).all()):
        return np.full((out_h, out_w), 255, dtype=np.uint8)

    opaque = source_alpha >= ALPHA_THRESHOLD
    height, width = opaque.shape

    # Sum opaque pixels per cell via a 2-D prefix sum so cost stays independent
    # of cell size.
    integral = np.zeros((height + 1, width + 1), dtype=np.int64)
    np.cumsum(np.cumsum(opaque.astype(np.int64), axis=0), axis=1, out=integral[1:, 1:])

    cols = np.asarray(column_cuts, dtype=np.int64)
    rows = np.asarray(row_cuts, dtype=np.int64)
    x0, x1 = cols[:-1], cols[1:]
    y0, y1 = rows[:-1], rows[1:]

    totals = (
        integral[np.ix_(y1, x1)]
        - integral[np.ix_(y0, x1)]
        - integral[np.ix_(y1, x0)]
        + integral[np.ix_(y0, x0)]
    )
    areas = np.outer(y1 - y0, x1 - x0)
    # Ties (2 * opaque == area) count as opaque.
    return np.where(totals * 2 >= areas, 255, 0).astype(np.uint8)


def _describe_device(requested: str) -> str:
    try:
        from pixel_snapper_core import runtime_description  # noqa: PLC0415

        return runtime_description(None if requested == "auto" else requested)
    except Exception:  # pragma: no cover - diagnostics must never break recovery
        return requested
