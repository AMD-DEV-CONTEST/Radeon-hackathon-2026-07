# -*- coding: utf-8 -*-
"""Style transfer v2 — SDXL img2img with optional ControlNet structure lock.

Identity preservation strategy:
1. Sane denoising strength (default 0.4 — restyle without replacing the subject)
2. ControlNet Canny structure lock: composition, pose and features are pinned
   to the original while colors/textures restyle freely.
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from ..device import Timer, peak_memory_gb, reset_peak_memory
from ..utils import make_generator, resize_long_edge, to_rgb_white

STYLE_PRESETS: dict[str, tuple[str, str]] = {
    "Anime": (
        "anime style illustration, cel shading, clean lineart, vibrant colors, "
        "studio quality anime key visual, detailed",
        "photo, realistic, 3d, blurry, bad anatomy, extra limbs, watermark, text"),
    "Cyberpunk": (
        "cyberpunk style, neon lights, futuristic city glow, cinematic lighting, "
        "blade runner mood, high contrast, ultra detailed",
        "flat lighting, dull colors, blurry, bad anatomy, watermark, text"),
    "Watercolor": (
        "delicate watercolor painting, soft washes of color, paper texture, "
        "artistic brush strokes, gallery quality",
        "photo, realistic, harsh edges, blurry, watermark, text"),
    "Oil Painting": (
        "classical oil painting, visible impasto brushstrokes, rich colors, "
        "canvas texture, museum masterpiece",
        "photo, digital art, flat colors, blurry, watermark, text"),
    "Pixel Art": (
        "pixel art, 16-bit retro game style, crisp pixels, limited color palette, "
        "detailed sprite art",
        "photo, smooth gradients, blurry, watermark, text"),
    "Film Photo": (
        "cinematic film photography, kodak portra 400, soft grain, warm tones, "
        "shallow depth of field, professional portrait",
        "digital noise, oversaturated, blurry, watermark, text"),
}


def _canny(image: Image.Image) -> Image.Image:
    arr = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
    edges = cv2.Canny(arr, 100, 200)
    return Image.fromarray(edges).convert("RGB")


def _looks_anime(image: Image.Image) -> bool:
    """Heuristic: cel/anime art = large flat-color regions + sparse crisp
    edges. Used to warn when the user applies the Anime preset to an image
    that already IS anime (a 5-minute no-op)."""
    arr = np.asarray(image.resize((128, 128))).astype(np.float32)
    gray = arr.mean(2)
    mean = cv2.boxFilter(gray, -1, (8, 8))
    sq = cv2.boxFilter(gray * gray, -1, (8, 8))
    std = np.sqrt(np.maximum(sq - mean * mean, 0))
    flat_ratio = float((std < 6.0).mean())
    edges = cv2.Canny(arr.astype(np.uint8), 100, 200)
    edge_density = float((edges > 0).mean())
    return flat_ratio > 0.55 and edge_density < 0.12


def run_style(manager, image: Image.Image, style: str, strength: float = 0.5,
              structure_lock: bool = True, custom_prompt: str = "",
              custom_negative: str = "", steps: int = 30, guidance: float = 7.0,
              seed: int = -1, fast: bool = False):
    """Returns (result_image, perf_dict, used_seed)."""
    if image is None:
        raise ValueError("Please upload an image first.")

    prompt, negative = STYLE_PRESETS.get(style, ("", ""))
    if (custom_prompt or "").strip():
        prompt = custom_prompt
    if (custom_negative or "").strip():
        negative = custom_negative

    s = manager.settings
    work = resize_long_edge(to_rgb_white(image), s.max_working_size,
                            multiple=16, upscale_min=768)

    gen, used_seed = make_generator("cuda" if manager.info.is_gpu else "cpu", seed)
    n_steps = s.lcm_steps if fast else int(steps)
    cfg = s.lcm_guidance if fast else float(guidance)
    kwargs = dict(
        prompt=prompt, negative_prompt=negative, image=work,
        strength=float(strength), num_inference_steps=n_steps,
        guidance_scale=cfg, generator=gen,
    )

    reset_peak_memory()
    if structure_lock:
        pipe = manager.get_controlnet_img2img_pipe()
        manager.set_lcm(pipe, fast)
        with Timer() as t:
            out = pipe(control_image=_canny(work),
                       controlnet_conditioning_scale=0.65,
                       **kwargs).images[0]
        engine = "SDXL + ControlNet structure lock"
    else:
        pipe = manager.get_img2img_pipe()
        manager.set_lcm(pipe, fast)
        with Timer() as t:
            out = pipe(**kwargs).images[0]
        engine = "SDXL img2img"

    result = out.resize(image.size, Image.LANCZOS)
    # No-op detection: restyling an already-on-style image returns the input
    # nearly unchanged — say so instead of letting the user wait for nothing.
    hints = []
    if style == "Anime" and _looks_anime(work):
        hints.append("Input is already anime style — Anime preset will barely change it;"
                     "To change style, select another preset. For more variation, increase strength")
    diff_arr = np.asarray(work, dtype=np.float32)
    if out.size != work.size:  # belt & suspenders against any size snap
        diff_arr = np.asarray(work.resize(out.size, Image.BILINEAR),
                              dtype=np.float32)
    diff = float(np.abs(np.asarray(out, dtype=np.float32) - diff_arr).mean())
    if diff < 2.0 and not hints:
        hints.append("Output is almost identical to input — try increasing strength or using a more specific prompt")
    perf = {
        "Time": f"{t.elapsed:.2f} s",
        "Speed": f"{t.elapsed / max(n_steps, 1) * 1000:.0f} ms/step",
        "Peak VRAM": f"{peak_memory_gb():.2f} GB",
        "Working size": f"{work.size[0]}×{work.size[1]}",
        "Strength": strength,
        "Engine": engine,
        "Sampler": "LCM turbo" if fast and s.enable_lcm else "Standard",
        "Seed": used_seed,
    }
    if hints:
        perf["💡 Hint"] = hints[0]
    return result, perf, used_seed
