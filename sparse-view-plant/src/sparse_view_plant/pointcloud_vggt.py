"""Feed-forward sparse-view point-cloud stage built on VGGT (CVPR 2025).

VGGT (arXiv:2503.11651, https://github.com/facebookresearch/vggt) is a
feed-forward visual geometry transformer: a DINOv2 backbone plus alternating
self/cross-frame attention predicts per-view camera poses, intrinsics, depth,
and 3D world pointmaps from an unordered set of images in a single pass (no
COLMAP, no calibration metadata at inference). The 1B checkpoint
(``facebook/VGGT-1B``, CC-BY-NC-4.0 research weights) runs at 518px.

The model code is loaded from a source clone on ``sys.path`` rather than
installed as a dependency: point ``pointcloud.source_dir`` (or the
``VGGT_SRC`` env var) at a clone of https://github.com/facebookresearch/vggt
and ``pointcloud.ckpt_path`` (or ``VGGT_CKPT``) at the downloaded checkpoint
directory (``model.safetensors`` + ``config.json``). Outputs are structurally
identical across frontends (per-view world pointmaps, camera-to-world,
intrinsics), so the rest of the pipeline (foreground trim, gs-refine, mesh,
evaluation) consumes them unchanged. The T10 GPU has no bf16, so the
aggregator forward runs under fp16 autocast with the weights cast to fp16.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
from PIL import Image

from sparse_view_plant.config import PointCloudConfig
from sparse_view_plant.images import InputImage, load_rgb_np
from sparse_view_plant.pointcloud import PointCloudPrediction

IMG_SIZE = 518  # VGGT training resolution (patch multiple of 14)
PATCH_SIZE = 14


def _import_torch() -> Any:
    try:
        import torch
    except ImportError as error:
        raise RuntimeError(
            "torch is required for the VGGT stage; install it with "
            "`uv sync --extra gpu`"
        ) from error
    return torch


def _resolve_source_dir(config: PointCloudConfig) -> Path:
    """Locate the vggt source clone (repo root holds the namespace package)."""
    value = config.source_dir or os.environ.get("VGGT_SRC")
    if not value:
        raise RuntimeError(
            "VGGT source is required; set pointcloud.source_dir in the "
            "config or the VGGT_SRC environment variable to a clone of "
            "https://github.com/facebookresearch/vggt"
        )
    root = Path(value)
    if not (root / "vggt").is_dir():
        raise RuntimeError(
            f"invalid VGGT source directory: {root} (expected vggt/ inside)"
        )
    return root


def _resolve_checkpoint(config: PointCloudConfig) -> Path:
    """Locate the VGGT checkpoint (a directory with model.safetensors)."""
    value = config.ckpt_path or os.environ.get("VGGT_CKPT")
    if not value:
        raise RuntimeError(
            "VGGT checkpoint is required; set pointcloud.ckpt_path in the "
            "config or the VGGT_CKPT environment variable to the downloaded "
            "facebook/VGGT-1B directory"
        )
    path = Path(value)
    if not path.is_dir():
        raise RuntimeError(f"VGGT checkpoint directory not found: {path}")
    if not (path / "model.safetensors").is_file():
        raise RuntimeError(f"VGGT checkpoint missing model.safetensors in {path}")
    return path


def _to_unit_confidence(raw: np.ndarray) -> np.ndarray:
    """Map VGGT's exp(+1) point confidence to [0, 1] monotonically.

    The ``world_points_conf`` head uses ``conf_activation="expp1"``, so raw
    values are >= 1 and unbounded; higher means the model is more confident.
    Sigmoid preserves the ordering the quantile-based foreground / opacity
    filtering relies on while honoring the prediction contract that
    confidence lies in [0, 1].
    """
    return 1.0 / (1.0 + np.exp(-raw))


def preprocess_vggt(
    pil_frames: Sequence[Image.Image],
    *,
    image_size: int = IMG_SIZE,
    patch_size: int = PATCH_SIZE,
) -> Any:
    """Resize each frame to the VGGT crop-mode layout.

    Mirrors the official ``load_and_preprocess_images(mode="crop")``:
    resize so the width is ``image_size`` (height a patch multiple), then
    center-crop the height to ``image_size`` when taller. Returns the
    (S, 3, H, W) float tensor in [0, 1].
    """
    torch = _import_torch()
    if image_size % patch_size != 0:
        raise ValueError("VGGT image_size must be a multiple of the patch size")
    processed: list[Any] = []
    for frame in pil_frames:
        rgb = frame.convert("RGB")
        width, height = rgb.size
        new_width = image_size
        new_height = round(height * (new_width / width) / patch_size) * patch_size
        resized = rgb.resize((new_width, new_height), Image.Resampling.BICUBIC)
        if new_height > image_size:
            start_y = (new_height - image_size) // 2
            resized = resized.crop((0, start_y, new_width, start_y + image_size))
        array = np.asarray(resized, dtype=np.uint8)
        tensor = torch.from_numpy(array.copy()).permute(2, 0, 1).float().div_(255.0)
        processed.append(tensor)
    return torch.stack(processed)


class VGGTStage:
    """Feed-forward sparse-view point-cloud reconstruction with VGGT."""

    model_name = "vggt"

    def __init__(self, config: PointCloudConfig, *, model: Any | None = None) -> None:
        self.config = config
        self._model = model

    def _load(self) -> Any:
        """Import the vggt package, build the model, and load the checkpoint."""
        if self._model is None:
            source_root = _resolve_source_dir(self.config)
            if str(source_root) not in sys.path:
                sys.path.insert(0, str(source_root))
            from vggt.models.vggt import VGGT  # ty: ignore[unresolved-import]

            checkpoint_dir = _resolve_checkpoint(self.config)
            from safetensors.torch import load_file

            model = VGGT()  # defaults match facebook/VGGT-1B (518px, embed 1024)
            state = load_file(str(checkpoint_dir / "model.safetensors"))
            model.load_state_dict(state)
            model.eval().to(self.config.device)
            self._model = model
        return self._model

    def predict(self, images: Sequence[InputImage]) -> PointCloudPrediction:
        """Run VGGT on the images and fuse per-view pointmaps."""
        torch = _import_torch()
        model = self._load()
        pil_frames = [Image.fromarray(load_rgb_np(view.path)) for view in images]
        batch = preprocess_vggt(pil_frames, image_size=self.config.image_resolution)
        device_batch = batch.to(self.config.device)

        started = perf_counter()
        print(f"[vggt] running feed-forward on {len(images)} views…")
        amp_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        with (
            torch.inference_mode(),
            torch.autocast(device_type="cuda", dtype=amp_dtype),
        ):
            raw = model(device_batch)

        pose_enc = raw["pose_enc"].float().cpu()  # (1, S, 9)
        world_points = raw["world_points"][0].float().cpu().numpy()  # (S, H, W, 3)
        world_conf = raw["world_points_conf"][0].float().cpu().numpy()  # (S, H, W)
        grid_h, grid_w = world_points.shape[1:3]

        from vggt.utils.pose_enc import (  # ty: ignore[unresolved-import]
            pose_encoding_to_extri_intri,
        )

        extrinsics, _intrinsics = pose_encoding_to_extri_intri(  # (1,S,3,4), (1,S,3,3)
            pose_enc, (grid_h, grid_w)
        )
        extrinsics = extrinsics[0].numpy()  # world-to-camera [R | t] (OpenCV)

        rotation_w2c = extrinsics[:, :3, :3]
        translation_w2c = extrinsics[:, :3, 3]
        camera_to_world = np.tile(np.eye(4, dtype=np.float32), (len(images), 1, 1))
        camera_to_world[:, :3, :3] = rotation_w2c.transpose(0, 2, 1)
        camera_to_world[:, :3, 3] = -(
            camera_to_world[:, :3, :3] @ translation_w2c[..., None]
        )[:, :, 0]

        # Camera-space points from the predicted world pointmap.
        local_points = np.einsum(
            "shwi,sij->shwj",
            world_points - camera_to_world[:, :3, 3][:, None, None, :],
            camera_to_world[:, :3, :3],
        )

        points = world_points.reshape(-1, 3).astype(np.float32)
        colors = (
            batch.permute(0, 2, 3, 1).float().cpu().numpy().reshape(-1, 3)
        ).astype(np.float32)
        confidence = _to_unit_confidence(world_conf).reshape(-1).astype(np.float32)
        print(
            f"[vggt] fused {points.shape[0]} points from {len(images)} views "
            f"({perf_counter() - started:.1f}s)"
        )

        return PointCloudPrediction(
            view_ids=tuple(view.view_id for view in images),
            points=points,
            colors=colors,
            confidence=confidence,
            camera_to_world=camera_to_world.astype(np.float32),
            metric_scale=1.0,  # VGGT world points are scale-normalized, not metric
            image_sizes=tuple(load_rgb_np(view.path).shape[:2] for view in images),
            local_points=local_points.reshape(-1, 3).astype(np.float32),
            patch_hw=(grid_h, grid_w),
        )
