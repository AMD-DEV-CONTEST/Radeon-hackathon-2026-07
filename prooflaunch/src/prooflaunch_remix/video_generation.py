from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from PIL import Image

from .mission import MissionError


@dataclass(frozen=True)
class VideoIdentityReport:
    passed: bool
    product_layer_sha256: str
    frame_product_hashes: tuple[str, ...]
    frame_count: int
    product_box: tuple[int, int, int, int]


def _pixel_hash(image: Image.Image) -> str:
    normalized = image.convert("RGBA")
    return hashlib.sha256(normalized.tobytes()).hexdigest()


def _masked_rgb_hash(image: Image.Image, mask: Image.Image) -> str:
    rgb = image.convert("RGB")
    alpha = mask.convert("L")
    rgb_data = (
        rgb.get_flattened_data() if hasattr(rgb, "get_flattened_data") else rgb.getdata()
    )
    alpha_data = (
        alpha.get_flattened_data()
        if hasattr(alpha, "get_flattened_data")
        else alpha.getdata()
    )
    selected = bytearray()
    for pixel, opacity in zip(rgb_data, alpha_data):
        if opacity == 255:
            selected.extend(pixel)
    if not selected:
        raise MissionError("product layer has no opaque identity pixels")
    return hashlib.sha256(bytes(selected)).hexdigest()


class IdentityLockedVideoComposer:
    """Composites the exact product layer after generation on every frame."""

    def compose(
        self,
        *,
        generated_frames: Iterable[Image.Image],
        product_layer: Image.Image,
        normalized_box: tuple[float, float, float, float],
    ) -> tuple[tuple[Image.Image, ...], VideoIdentityReport]:
        frames = tuple(frame.convert("RGBA") for frame in generated_frames)
        if not frames:
            raise MissionError("video generator returned no frames")
        width, height = frames[0].size
        if any(frame.size != (width, height) for frame in frames):
            raise MissionError("all video frames must have the same dimensions")
        x1 = round(normalized_box[0] * width)
        y1 = round(normalized_box[1] * height)
        x2 = round(normalized_box[2] * width)
        y2 = round(normalized_box[3] * height)
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise MissionError("product box is outside the video canvas")
        layer = product_layer.convert("RGBA").resize(
            (x2 - x1, y2 - y1),
            Image.Resampling.LANCZOS,
        )
        layer_mask = layer.getchannel("A")
        layer_sha256 = _pixel_hash(layer)
        expected_identity_hash = _masked_rgb_hash(layer, layer_mask)
        composited: list[Image.Image] = []
        product_hashes: list[str] = []
        for frame in frames:
            result = frame.copy()
            result.alpha_composite(layer, (x1, y1))
            product_hashes.append(
                _masked_rgb_hash(result.crop((x1, y1, x2, y2)), layer_mask)
            )
            composited.append(result)
        passed = all(item == expected_identity_hash for item in product_hashes)
        return (
            tuple(composited),
            VideoIdentityReport(
                passed=passed,
                product_layer_sha256=layer_sha256,
                frame_product_hashes=tuple(product_hashes),
                frame_count=len(composited),
                product_box=(x1, y1, x2, y2),
            ),
        )


class DiffusersLTXVideoProvider:
    """Adapter around a caller-owned local Diffusers LTX video pipeline."""

    def __init__(
        self,
        pipeline,
        *,
        model_ref: str = (
            "Lightricks/LTX-Video:ltxv-2b-0.9.8-distilled.safetensors"
        ),
        steps: int = 8,
        fps: int = 24,
        exporter: Callable | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.model_ref = model_ref
        self.steps = steps
        self.fps = fps
        self.exporter = exporter

    def generate(
        self,
        *,
        prompt: str,
        conditioning_image: Image.Image,
        output_path: str | Path,
        seed: int,
        num_frames: int = 97,
        negative_prompt: str = "warped product, changed logo, illegible text",
    ) -> dict:
        import torch

        if not 9 <= num_frames <= 257:
            raise MissionError("LTX frame count must be between 9 and 257")
        generator = torch.Generator(device="cuda").manual_seed(seed)
        result = self.pipeline(
            image=conditioning_image.convert("RGB"),
            prompt=prompt,
            negative_prompt=negative_prompt,
            num_frames=num_frames,
            num_inference_steps=self.steps,
            generator=generator,
        )
        frames = result.frames[0]
        if not frames:
            raise MissionError("LTX pipeline returned no frames")
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        exporter = self.exporter
        if exporter is None:
            from diffusers.utils import export_to_video

            exporter = export_to_video
        exporter(frames, str(output), fps=self.fps)
        if not output.is_file() or output.stat().st_size == 0:
            raise MissionError("video export did not create a non-empty file")
        return {
            "path": str(output),
            "model_ref": self.model_ref,
            "seed": seed,
            "steps": self.steps,
            "fps": self.fps,
            "frame_count": len(frames),
        }
