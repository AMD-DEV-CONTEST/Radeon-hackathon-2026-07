from __future__ import annotations

import colorsys
import hashlib
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from PIL import Image, ImageDraw, ImageFont

from .contracts import CampaignState, CreativeAsset, CreativeBrief
from .files import safe_stem, sha256_file


PLATFORM_SIZES: dict[str, tuple[int, int]] = {
    "tiktok": (1080, 1920),
    "instagram reels": (1080, 1920),
    "reels": (1080, 1920),
    "youtube shorts": (1080, 1920),
    "shorts": (1080, 1920),
    "instagram": (1080, 1350),
    "linkedin": (1200, 1200),
    "x": (1600, 900),
}


class BackgroundProvider(Protocol):
    model_ref: str
    backend_kind: str

    def render(
        self, *, prompt: str, size: tuple[int, int], seed: int
    ) -> Image.Image: ...


@dataclass
class ProceduralBackgroundProvider:
    """Offline deterministic fallback. It is intentionally not labelled as AI."""

    model_ref: str = "prooflaunch/procedural-background-v1"
    backend_kind: str = "deterministic_fallback"

    def render(
        self, *, prompt: str, size: tuple[int, int], seed: int
    ) -> Image.Image:
        del prompt
        width, height = size
        rng = random.Random(seed)
        hue = rng.random()
        c1 = tuple(
            int(channel * 255)
            for channel in colorsys.hsv_to_rgb(hue, 0.72, 0.28)
        )
        c2 = tuple(
            int(channel * 255)
            for channel in colorsys.hsv_to_rgb((hue + 0.14) % 1, 0.62, 0.62)
        )
        image = Image.new("RGB", size)
        draw = ImageDraw.Draw(image)
        bands = max(48, min(256, height // 6))
        for band in range(bands):
            t = band / max(1, bands - 1)
            color = tuple(
                round(c1[channel] * (1 - t) + c2[channel] * t)
                for channel in range(3)
            )
            y0 = round(height * band / bands)
            y1 = round(height * (band + 1) / bands)
            draw.rectangle((0, y0, width, y1), fill=color)
        for _ in range(12):
            radius = rng.randint(max(6, width // 40), max(12, width // 7))
            x = rng.randint(-radius, width + radius)
            y = rng.randint(-radius, height + radius)
            color = (*c2, rng.randint(18, 58))
            overlay = Image.new("RGBA", size, (0, 0, 0, 0))
            ImageDraw.Draw(overlay).ellipse(
                (x - radius, y - radius, x + radius, y + radius),
                fill=color,
            )
            image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
        return image


class DiffusersBackgroundProvider:
    """Adapter for a caller-owned local Diffusers pipeline on ROCm/CUDA."""

    backend_kind = "local_generation"

    def __init__(
        self,
        pipeline: Any,
        model_ref: str,
        *,
        steps: int = 20,
        guidance_scale: float = 4.0,
        device: str = "cuda",
        release_after_render: bool = False,
    ) -> None:
        self.pipeline = pipeline
        self.model_ref = model_ref
        self.steps = steps
        self.guidance_scale = guidance_scale
        self.device = device
        self.release_after_render = release_after_render

    def render(
        self, *, prompt: str, size: tuple[int, int], seed: int
    ) -> Image.Image:
        import torch

        width, height = size
        if self.release_after_render:
            self.pipeline.to(self.device)
        generator = torch.Generator(device=self.device).manual_seed(seed)
        try:
            result = self.pipeline(
                prompt=prompt,
                width=width,
                height=height,
                num_inference_steps=self.steps,
                guidance_scale=self.guidance_scale,
                generator=generator,
            )
        finally:
            if self.release_after_render:
                self.pipeline.to("cpu")
                torch.cuda.empty_cache()
        if not getattr(result, "images", None):
            raise RuntimeError("Diffusers pipeline returned no images")
        return result.images[0].convert("RGB")


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
        if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> str:
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and draw.textlength(trial, font=font) > width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return "\n".join(lines)


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    values = []
    for channel in rgb:
        value = channel / 255
        values.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2]


def contrast_ratio(foreground: tuple[int, int, int], background: tuple[int, int, int]) -> float:
    first = _relative_luminance(foreground)
    second = _relative_luminance(background)
    light, dark = max(first, second), min(first, second)
    return (light + 0.05) / (dark + 0.05)


class IdentityLockedStudio:
    """Composites a generated background around an immutable product layer."""

    def __init__(
        self,
        background: BackgroundProvider | None = None,
        *,
        seed: int = 202607,
        canvas_overrides: dict[str, tuple[int, int]] | None = None,
        unsafe_first_pass: bool = False,
    ) -> None:
        self.background = background or ProceduralBackgroundProvider()
        self.seed = seed
        self.canvas_overrides = {
            key.lower(): value for key, value in (canvas_overrides or {}).items()
        }
        self.unsafe_first_pass = unsafe_first_pass

    def _size_for(self, platform: str) -> tuple[int, int]:
        key = platform.strip().lower()
        return self.canvas_overrides.get(key, PLATFORM_SIZES.get(key, (1080, 1080)))

    def create(self, state: CampaignState) -> list[CreativeAsset]:
        product_path = Path(state.request.product_image)
        if not product_path.is_file():
            raise FileNotFoundError(f"product image not found: {product_path}")
        assets: list[CreativeAsset] = []
        for index, brief in enumerate(state.briefs):
            asset_seed = self.seed + index
            size = self._size_for(state.request.platform)
            background = self.background.render(
                prompt=self._prompt(state, brief),
                size=size,
                seed=asset_seed,
            )
            background_path = state.output_path / f"{safe_stem(brief.id)}-background.png"
            background.save(background_path, format="PNG", optimize=False)
            assets.append(
                self._render(
                    state,
                    brief,
                    background_path=background_path,
                    seed=asset_seed,
                    safe_layout=not self.unsafe_first_pass,
                )
            )
        return assets

    def rebuild(
        self,
        state: CampaignState,
        asset: CreativeAsset,
        *,
        safe_layout: bool = True,
    ) -> CreativeAsset:
        brief_id = str(asset.metadata.get("brief_id", ""))
        brief = next((item for item in state.briefs if item.id == brief_id), None)
        if brief is None:
            raise ValueError(f"missing brief for asset {asset.id}")
        background_path = Path(str(asset.metadata.get("background_path", "")))
        if not background_path.is_file():
            raise FileNotFoundError(f"background missing for asset {asset.id}")
        return self._render(
            state,
            brief,
            background_path=background_path,
            seed=asset.seed,
            safe_layout=safe_layout,
            asset_id=asset.id,
        )

    @staticmethod
    def _prompt(state: CampaignState, brief: CreativeBrief) -> str:
        return (
            f"Premium product campaign background, no text, no logos, no product; "
            f"{brief.visual_direction}; target emotion {brief.target_emotion}."
        )

    def _render(
        self,
        state: CampaignState,
        brief: CreativeBrief,
        *,
        background_path: Path,
        seed: int,
        safe_layout: bool,
        asset_id: str | None = None,
    ) -> CreativeAsset:
        canvas = Image.open(background_path).convert("RGBA")
        width, height = canvas.size
        product_source = Path(state.request.product_image)
        source_hash = sha256_file(product_source)
        product = Image.open(product_source).convert("RGBA")
        max_product = (round(width * 0.52), round(height * 0.34))
        product.thumbnail(max_product, Image.Resampling.LANCZOS)
        product_x = round(width * 0.51 - product.width / 2)
        product_y = round(height * 0.39)
        product_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        product_layer.alpha_composite(product, (product_x, product_y))
        product_layer_path = state.output_path / f"{safe_stem(brief.id)}-product-layer.png"
        product_layer.save(product_layer_path, format="PNG", optimize=False)
        product_layer_hash = sha256_file(product_layer_path)

        composed = Image.alpha_composite(canvas, product_layer)
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        panel_color = (8, 12, 24, 232)
        text_color = (255, 255, 255)
        panel_left = round(width * 0.075)
        panel_right = round(width * (0.82 if safe_layout else 0.96))
        headline_top = round(height * 0.08)
        headline_bottom = round(height * (0.32 if safe_layout else 0.27))
        draw.rounded_rectangle(
            (panel_left, headline_top, panel_right, headline_bottom),
            radius=max(8, width // 40),
            fill=panel_color,
        )
        headline_font_px = max(18, round(width * 0.052))
        body_font_px = max(14, round(width * 0.03))
        body_font = _font(body_font_px)
        text_x = panel_left + round(width * 0.035)
        text_y = headline_top + round(height * 0.025)
        text_width = panel_right - panel_left - round(width * 0.07)
        text_bottom_limit = headline_bottom - round(height * 0.02)
        minimum_headline_px = max(12, round(min(width, height) * 0.035))
        while True:
            headline_font = _font(headline_font_px, bold=True)
            wrapped = _wrap(draw, brief.headline, headline_font, text_width)
            measured_box = draw.multiline_textbbox(
                (text_x, text_y),
                wrapped,
                font=headline_font,
                spacing=max(4, body_font_px // 3),
            )
            if (
                not safe_layout
                or measured_box[3] <= text_bottom_limit
                or headline_font_px <= minimum_headline_px
            ):
                break
            headline_font_px = max(minimum_headline_px, headline_font_px - 2)
        draw.multiline_text(
            (text_x, text_y),
            wrapped,
            font=headline_font,
            fill=text_color,
            spacing=max(4, body_font_px // 3),
        )
        cta_width = round(width * 0.42)
        cta_height = round(height * 0.075)
        cta_x = round(width * (0.075 if safe_layout else 0.69))
        cta_y = round(height * 0.77)
        cta_box = (cta_x, cta_y, cta_x + cta_width, cta_y + cta_height)
        draw.rounded_rectangle(
            cta_box,
            radius=max(8, cta_height // 3),
            fill=(255, 255, 255, 244),
        )
        draw.text(
            (cta_x + round(width * 0.025), cta_y + round(cta_height * 0.24)),
            f"Review evidence • {state.request.goal.title()}",
            font=body_font,
            fill=(8, 12, 24),
        )
        composed = Image.alpha_composite(composed, overlay)
        resolved_id = asset_id or f"AST-{brief.id.split('-')[-1]}"
        asset_path = state.output_path / f"{safe_stem(resolved_id)}.png"
        composed.convert("RGB").save(asset_path, format="PNG", optimize=False)
        measured_box = draw.multiline_textbbox(
            (text_x, text_y),
            wrapped,
            font=headline_font,
            spacing=max(4, body_font_px // 3),
        )
        estimated_text_bottom = measured_box[3]
        metadata = {
            "backend_kind": self.background.backend_kind,
            "brief_id": brief.id,
            "background_path": str(background_path),
            "canvas_size": [width, height],
            "claim_ids": list(brief.claim_ids),
            "rendered_claims": [
                claim.text for claim in state.claims if claim.id in brief.claim_ids
            ],
            "headline": brief.headline,
            "headline_box": [
                panel_left,
                headline_top,
                panel_right,
                headline_bottom,
            ],
            "headline_text_box": [
                text_x,
                text_y,
                panel_right - round(width * 0.035),
                estimated_text_bottom,
            ],
            "cta_box": list(cta_box),
            "product_box": [
                product_x,
                product_y,
                product_x + product.width,
                product_y + product.height,
            ],
            "product_source_path": str(product_source),
            "product_source_sha256": source_hash,
            "product_layer_path": str(product_layer_path),
            "product_layer_sha256": product_layer_hash,
            "layout_version": "safe-v2-adaptive-type" if safe_layout else "unsafe-v0",
            "text_contrast_ratio": round(contrast_ratio(text_color, panel_color[:3]), 3),
            "headline_font_px": headline_font_px,
            "text_overflow": estimated_text_bottom > headline_bottom,
            "platform": state.request.platform,
        }
        return CreativeAsset(
            id=resolved_id,
            path=str(asset_path),
            aspect_ratio=f"{width}:{height}",
            seed=seed,
            model_ref=self.background.model_ref,
            metadata=metadata,
        )
