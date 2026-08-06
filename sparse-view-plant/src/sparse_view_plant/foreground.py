"""Mask-free / learned foreground masks for pipeline supervision.

Two providers share the same interface (``masks(images, resolution)``):

- ``maskfree``: central-ellipse + per-view confidence quantile on the frontend
  pointmap grid (mirrors ``pointcloud.extract_deployed_foreground``). No
  extra weights; the ellipse encodes the phenotyping assumption that the
  plant is centered.
- ``birefnet``: BiRefNet (https://github.com/zhengpeng7/birefnet) salient
  foreground from the cached Hub checkpoint
  (``ZhengPeng7/BiRefNet``, 220M params, fp16 weights; runs on CUDA/ROCm
  GPUs with fp16 support). Loads lazily; ~0.4s per 512px image on a T10.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from PIL import Image

from sparse_view_plant.images import InputImage, load_rgb_np

BIREFNET_REPO = "ZhengPeng7/BiRefNet"
BIREFNET_RESOLUTION = 512
# Views whose salient mask covers less than this fraction of pixels are
# treated as BiRefNet failures and get the cross-view fallback mask.
MIN_FOREGROUND_FRACTION = 0.01
# Radius (fraction of the half-frame) of the central-ellipse prior used when
# every view's salient mask is empty; matches the phenotyping assumption that
# the plant is centered and roughly fills ~10% of the frame.
FALLBACK_ELLIPSE_RADIUS = 0.35


def maskfree_masks(
    confidence: np.ndarray,
    patch_hw: tuple[int, int] | np.ndarray,
    view_count: int,
    *,
    center_radius: float = 0.7,
    confidence_percentile: float = 40.0,
    resolution: int,
) -> np.ndarray:
    """Central-ellipse + per-view confidence quantile masks (grid -> image)."""
    grid_h, grid_w = int(patch_hw[0]), int(patch_hw[1])
    total = confidence.shape[0]
    if total % view_count != 0:
        raise ValueError("flattened confidence is not divisible by view count")
    per_view = total // view_count
    if per_view != grid_h * grid_w:
        raise ValueError("patch_hw does not match the flattened confidence count")
    grid = confidence.reshape(view_count, grid_h, grid_w)
    yy, xx = np.mgrid[0:grid_h, 0:grid_w]
    centre = ((xx - grid_w / 2.0) / (grid_w / 2.0)) ** 2 + (
        (yy - grid_h / 2.0) / (grid_h / 2.0)
    ) ** 2
    keep = np.broadcast_to(
        centre[None] <= center_radius**2, (view_count, grid_h, grid_w)
    ).copy()
    thresholds = np.percentile(
        grid, 100.0 - confidence_percentile, axis=(1, 2), keepdims=True
    )
    keep &= grid >= thresholds
    keep &= np.isfinite(grid)
    masks = np.asarray(keep, dtype=np.float32)
    out = np.empty((view_count, resolution, resolution), dtype=np.float32)
    for view_index in range(view_count):
        image = Image.fromarray((masks[view_index] * 255).astype(np.uint8))
        resized = image.resize((resolution, resolution), Image.Resampling.BILINEAR)
        out[view_index] = np.asarray(resized, dtype=np.float32) / 255.0
    return out


def _load_birefnet(device: str) -> Any:
    from transformers import AutoModelForImageSegmentation

    model = AutoModelForImageSegmentation.from_pretrained(
        BIREFNET_REPO, trust_remote_code=True
    )
    model.to(device).half().eval()
    return model


def _center_ellipse_mask(resolution: int) -> np.ndarray:
    """Binary central-ellipse mask at ``resolution`` (plant-centred prior)."""
    yy, xx = np.mgrid[0:resolution, 0:resolution]
    ellipse = ((xx - resolution / 2.0) / (resolution / 2.0)) ** 2 + (
        (yy - resolution / 2.0) / (resolution / 2.0)
    ) ** 2
    return (ellipse <= FALLBACK_ELLIPSE_RADIUS**2).astype(np.float32)


def _fill_empty_masks(masks: np.ndarray) -> tuple[np.ndarray, int]:
    """Replace empty views with a cross-view fallback; returns (masks, filled)."""
    fractions = masks.reshape(len(masks), -1).mean(axis=1)
    empty = fractions < MIN_FOREGROUND_FRACTION
    if not empty.any():
        return masks, 0
    valid = masks[~empty]
    if len(valid) > 0:
        fill = (valid.mean(axis=0) > 0.5).astype(np.float32)
    else:
        fill = _center_ellipse_mask(masks.shape[-1])
    result = masks.copy()
    result[empty] = fill
    return result, int(empty.sum())


_birefnet_model: Any = None
_birefnet_device: str = ""


def birefnet_masks(
    images: Sequence[InputImage],
    device: str = "cuda",
    *,
    resolution: int = BIREFNET_RESOLUTION,
    threshold: float = 0.5,
) -> np.ndarray:
    """Salient foreground masks for the input views (V, resolution, resolution)."""
    global _birefnet_model, _birefnet_device
    if _birefnet_model is None or _birefnet_device != device:
        _birefnet_model = _load_birefnet(device)
        _birefnet_device = device
    import torch
    from torchvision import transforms

    transform = transforms.Compose(
        [
            transforms.Resize((resolution, resolution)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ]
    )
    tensors = []
    for view in images:
        rgb = Image.fromarray(load_rgb_np(view.path)).convert("RGB")
        tensors.append(transform(rgb))
    batch = torch.stack(tensors).half().to(device)
    with torch.no_grad():
        preds = _birefnet_model(batch)[-1].sigmoid().cpu().float()
    masks = preds[:, 0].numpy().astype(np.float32)
    if threshold > 0.0:
        masks = (masks > threshold).astype(np.float32)
    # BiRefNet occasionally returns an empty salient mask for low-contrast or
    # dark views (observed: bean_1 0001_train). Without a fallback that view
    # silently loses all foreground supervision, so its Gaussians stay dark.
    # Substitute the mean of the other views' masks (the plant is centred
    # across views), or a central-ellipse prior when all views are empty.
    masks, filled = _fill_empty_masks(masks)
    if filled:
        print(
            f"[birefnet] empty salient mask for {filled} view(s); "
            "using cross-view fallback"
        )
    return masks


def file_masks(images: Sequence[InputImage], *, resolution: int) -> np.ndarray:
    """Load experiment-only masks from a sibling ``mask/`` directory.

    This provider is for supervised upper-bound experiments. The deployed
    inference path must use an image-derived provider such as BiRefNet.
    """
    masks: list[np.ndarray] = []
    for view in images:
        path = view.path.parent.parent / "mask" / f"{view.view_id}.png.png"
        if not path.is_file():
            raise FileNotFoundError(f"foreground mask does not exist: {path}")
        resized = (
            Image.open(path)
            .convert("L")
            .resize((resolution, resolution), Image.Resampling.NEAREST)
        )
        masks.append((np.asarray(resized) >= 128).astype(np.float32))
    return np.stack(masks)


def foreground_masks(
    provider: str,
    images: Sequence[InputImage],
    resolution: int,
    *,
    confidence: np.ndarray | None = None,
    patch_hw: tuple[int, int] | np.ndarray | None = None,
    view_count: int | None = None,
    center_radius: float = 0.7,
    confidence_percentile: float = 40.0,
    device: str = "cuda",
) -> np.ndarray:
    """Dispatch to a mask provider: ``maskfree``, ``birefnet``, or ``file``.

    Both providers return ``(view_count, resolution, resolution)`` float32
    masks in {0, 1}. The maskfree provider needs the flattened per-view frontend
    confidence grid plus ``patch_hw`` and ``view_count``; BiRefNet only needs
    the input images.
    """
    if provider == "maskfree":
        if confidence is None or patch_hw is None or view_count is None:
            raise ValueError(
                "maskfree foreground provider needs confidence, patch_hw, "
                "and view_count"
            )
        return maskfree_masks(
            confidence,
            patch_hw,
            view_count,
            center_radius=center_radius,
            confidence_percentile=confidence_percentile,
            resolution=resolution,
        )
    if provider == "birefnet":
        return birefnet_masks(images, device=device, resolution=resolution)
    if provider == "file":
        return file_masks(images, resolution=resolution)
    raise ValueError(f"unknown foreground mask provider: {provider}")


def grid_trim_mask(
    provider: str,
    images: Sequence[InputImage],
    *,
    confidence: np.ndarray | None = None,
    patch_hw: tuple[int, int] | np.ndarray | None = None,
    view_count: int | None = None,
    device: str = "cuda",
) -> np.ndarray:
    """Binary (view_count, grid_h, grid_w) trim mask aligned to the pointmap grid.

    The fused pointmap is the flattened per-view grid (view-major,
    grid-major); this mask labels each grid cell foreground, so a cloud can be
    trimmed without reprojection. ``maskfree`` keeps central-ellipse cells at
    or above the per-view confidence quantile; ``birefnet`` runs the salient
    foreground model at its native 512px and downsamples to the grid.
    """
    if patch_hw is None:
        raise ValueError("grid_trim_mask needs patch_hw")
    grid_h, grid_w = int(patch_hw[0]), int(patch_hw[1])
    if provider == "maskfree":
        if confidence is None or view_count is None:
            raise ValueError("maskfree grid trim needs confidence and view_count")
        masks = maskfree_masks(
            confidence,
            patch_hw,
            view_count,
            resolution=grid_h,
        )
        return (masks > 0.5).astype(np.float32)
    if provider == "birefnet":
        masks = birefnet_masks(images, device=device, resolution=512)
        out = np.empty((masks.shape[0], grid_h, grid_w), dtype=np.float32)
        for view_index in range(masks.shape[0]):
            resized = Image.fromarray(
                (masks[view_index] * 255).astype(np.uint8)
            ).resize((grid_w, grid_h), Image.Resampling.BILINEAR)
            out[view_index] = np.asarray(resized, dtype=np.float32) / 255.0
        return (out > 0.5).astype(np.float32)
    if provider == "file":
        masks = file_masks(images, resolution=grid_h)
        if grid_w == grid_h:
            return masks
        out = np.empty((len(masks), grid_h, grid_w), dtype=np.float32)
        for view_index, mask in enumerate(masks):
            resized = Image.fromarray((mask * 255).astype(np.uint8)).resize(
                (grid_w, grid_h), Image.Resampling.NEAREST
            )
            out[view_index] = np.asarray(resized, dtype=np.float32) / 255.0
        return out
    raise ValueError(f"unknown grid trim provider: {provider}")
