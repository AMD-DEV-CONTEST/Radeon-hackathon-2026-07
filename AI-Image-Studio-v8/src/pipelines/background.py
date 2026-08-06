# -*- coding: utf-8 -*-
"""Background replace v2 — BiRefNet cutout + solid/gradient/AI backdrop.

AI mode generates a FULL-FRAME background with SDXL txt2img at the exact
image size, then composites the crisp foreground on top. No ghosting, no
uncovered areas.
"""
from __future__ import annotations

from PIL import Image, ImageFilter

from ..birefnet import cutout
from ..device import Timer, peak_memory_gb, reset_peak_memory
from ..utils import hex_to_rgb, make_generator, resize_long_edge

BG_NEGATIVE = ("people, person, human, character, face, blurry, low quality, "
               "watermark, text, logo, signature")

# SDXL-native resolution buckets. Generating at an extreme aspect (e.g. a
# 473×1024 phone-screen slice) makes the model tile and stripe — generate in
# the closest native bucket, then cover-crop to the real frame.
_NATIVE_BUCKETS = [(1024, 1024), (1152, 864), (1216, 832), (1344, 768),
                   (864, 1152), (832, 1216), (768, 1344)]


def _native_bucket(w: int, h: int) -> tuple[int, int]:
    import math
    r = math.log(w / h)
    return min(_NATIVE_BUCKETS, key=lambda b: abs(math.log(b[0] / b[1]) - r))


def _cover_crop(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Resize so `size` is fully covered, then center-crop — no distortion."""
    tw, th = size
    scale = max(tw / img.width, th / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)),
                     Image.LANCZOS)
    x0 = (img.width - tw) // 2
    y0 = (img.height - th) // 2
    return img.crop((x0, y0, x0 + tw, y0 + th))


def _solid_bg(size, hex_color: str) -> Image.Image:
    return Image.new("RGB", size, hex_to_rgb(hex_color))


def _gradient_bg_fast(size, top_hex, bottom_hex) -> Image.Image:
    import numpy as np
    w, h = size
    top = np.array(hex_to_rgb(top_hex), dtype=np.float32)
    bottom = np.array(hex_to_rgb(bottom_hex), dtype=np.float32)
    r = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    arr = (top[None, None, :] * (1 - r) + bottom[None, None, :] * r)
    arr = np.repeat(arr, w, axis=1).astype(np.uint8)
    return Image.fromarray(arr)


def _composite(fg_rgba: Image.Image, bg: Image.Image,
               feather: float = 1.0) -> Image.Image:
    """Paste fg onto bg with a lightly feathered alpha edge. Exact-size,
    single paste — no ghosting.

    The matte's semi-transparent rim carries pixels of the ORIGINAL
    backdrop — pasted onto a new scene they read as a pale halo (v8
    acceptance: dark ring around the subject). Erode the alpha by 1 px
    before feathering so the rim comes from the subject, not the old
    backdrop."""
    bg = bg.resize(fg_rgba.size, Image.LANCZOS).convert("RGB")
    alpha = fg_rgba.split()[3]
    alpha = alpha.filter(ImageFilter.MinFilter(3))   # 1 px erode: de-halo
    if feather > 0:
        alpha = alpha.filter(ImageFilter.GaussianBlur(feather))
    out = bg.copy()
    out.paste(fg_rgba.convert("RGB"), (0, 0), alpha)
    return out


def run_background(manager, image: Image.Image, mode: str = "Transparent PNG",
                   solid: str = "#FFFFFF", grad_top: str = "#89CFF0",
                   grad_bottom: str = "#F0E68C", ai_prompt: str = "",
                   steps: int = 30, seed: int = -1, fast: bool = False):
    """Returns (result, fg_rgba, perf_dict)."""
    if image is None:
        raise ValueError("Please upload an image first.")

    reset_peak_memory()
    with Timer() as t_matte:
        fg, alpha = cutout(manager, image)
    matte_s = t_matte.elapsed

    W, H = image.size
    if mode == "Transparent PNG":
        result = fg
        gen_s = 0.0
    elif mode == "Solid color":
        result = _composite(fg, _solid_bg((W, H), solid))
        gen_s = 0.0
    elif mode == "Gradient":
        result = _composite(fg, _gradient_bg_fast((W, H), grad_top, grad_bottom))
        gen_s = 0.0
    elif mode == "AI-generated":
        if not (ai_prompt or "").strip():
            raise ValueError("Enter a prompt describing the desired background scene.")
        s = manager.settings
        pipe = manager.get_txt2img_pipe()
        manager.set_lcm(pipe, fast)
        bg_size = resize_long_edge(image, s.max_working_size, multiple=16,
                                   upscale_min=768).size
        gen, used_seed = make_generator("cuda" if manager.info.is_gpu else "cpu", seed)
        n_steps = s.lcm_steps if fast else int(steps)
        cfg = s.lcm_guidance if fast else 7.0
        # Generate in the closest SDXL-native aspect bucket (extreme aspects
        # stripe/tile), then cover-crop to the real frame.
        bucket = _native_bucket(*bg_size)
        with Timer() as t_gen:
            bg = pipe(
                prompt=ai_prompt if "empty scene" in ai_prompt else
                       ai_prompt + ", empty scene, no people, no characters, "
                       "cohesive soft lighting, high quality, detailed",
                negative_prompt=BG_NEGATIVE,
                width=bucket[0], height=bucket[1],
                num_inference_steps=n_steps, guidance_scale=cfg,
                generator=gen,
            ).images[0]
        bg = _cover_crop(bg, bg_size)
        result = _composite(fg, bg)
        gen_s = t_gen.elapsed
    else:
        raise ValueError(f"Unknown mode: {mode}")

    perf = {
        "Matting time": f"{matte_s:.2f} s",
        "Background gen time": f"{gen_s:.2f} s" if gen_s else "—",
        "Peak VRAM": f"{peak_memory_gb():.2f} GB",
        "Output size": f"{result.size[0]}×{result.size[1]}",
    }
    return result, fg, perf
