# -*- coding: utf-8 -*-
"""Asset split v2 — one character image -> transparent layer + completed
background layer, exported as a layered PSD + asset pack."""
from __future__ import annotations

import io
import os
import time
import zipfile

import numpy as np
from PIL import Image

from ..birefnet import cutout
from ..device import Timer, peak_memory_gb, reset_peak_memory
from ..utils import dilate_mask, mask_bbox, to_rgb_white


def _crop_to_content(fg: Image.Image, margin: int = 16):
    """Crop to the alpha bounding box; returns (cropped, (left, top)) offset."""
    bbox = mask_bbox(fg.split()[3])
    if bbox is None:
        return fg, (0, 0)
    x0, y0, x1, y1 = bbox
    x0, y0 = max(0, x0 - margin), max(0, y0 - margin)
    x1, y1 = min(fg.width, x1 + margin), min(fg.height, y1 + margin)
    return fg.crop((x0, y0, x1, y1)), (x0, y0)


def _smooth_fill_streaks(filled: np.ndarray, hole: np.ndarray) -> np.ndarray:
    """LaMa smears streaks into large holes; in naturally smooth areas (sky,
    walls) that reads as a ghost of the erased subject. Split the hole into
    horizontal bands; where the texture JUST OUTSIDE the band is smooth,
    flatten the band's fill with a heavy gaussian — smooth surroundings
    imply the hole content should be smooth too. Textured bands (sea,
    grass) keep LaMa's synthesized detail. (A global flat-field subtraction
    was tried and reverted: it re-sculpted a dark silhouette.)"""
    import cv2
    H, W = hole.shape
    out = filled.copy()
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    gray = cv2.cvtColor(filled, cv2.COLOR_RGB2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(gx * gx + gy * gy)
    for i in range(8):
        y0, y1 = i * H // 8, (i + 1) * H // 8
        band = np.zeros_like(hole)
        band[y0:y1] = hole[y0:y1]
        if band.sum() < 500:
            continue
        ring = (cv2.dilate(band.astype(np.uint8), kernel, iterations=3) > 0) & ~band
        if ring.sum() < 200:
            continue
        if float(np.median(mag[ring])) > 7.0:
            continue  # textured surroundings: keep LaMa's fill as-is
        # heavy gaussian (not bilateral): the ghost is a BROAD brightness
        # drift that edge-preserving filters keep — sky/walls are genuinely
        # flat, so flatten them for real
        sigma = max(15.0, W / 40.0)
        smooth = cv2.GaussianBlur(filled, (0, 0), sigma).astype(np.float32)
        m = cv2.GaussianBlur(band.astype(np.float32), (0, 0), 4)[..., None]
        out = (out.astype(np.float32) * (1 - m) + smooth * m).astype(np.uint8)
    return out


def _fill_background(manager, image: Image.Image, alpha: Image.Image) -> Image.Image:
    """Erase the subject and complete the background (LaMa, SDXL fallback).

    The matte is thresholded generously (a>16 catches hair wisps and the
    semi-transparent halo) and then dilated well beyond the silhouette —
    a tight mask is exactly what leaves a ghost person in the filled
    background. LaMa still leaves a faint halo RING just outside the hole
    (anti-aliased subject pixels blended into the border), so the filled
    image gets a final cv2.inpaint pass over that ring band — the v8
    acceptance requires a background with zero trace of the subject."""
    import cv2
    import numpy as np
    hard = np.where(np.asarray(alpha) > 16, 255, 0).astype(np.uint8)
    hole = dilate_mask(Image.fromarray(hard, "L"),
                       int(manager.settings.split_fill_dilate))
    try:
        lama = manager.get_lama()
        filled = lama(image, hole)
    except Exception:
        from ..utils import blur_mask, resize_long_edge, make_generator
        s = manager.settings
        pipe = manager.get_inpaint_pipe()
        manager.set_lcm(pipe, False)
        work = resize_long_edge(image, s.max_working_size, multiple=16,
                                upscale_min=768)
        soft = blur_mask(hole.resize(work.size, Image.NEAREST), 6.0)
        gen, _ = make_generator("cuda" if manager.info.is_gpu else "cpu", -1)
        out = pipe(
            prompt="empty background, seamless texture, high quality",
            negative_prompt="people, person, character, object, watermark, text",
            image=work, mask_image=soft, strength=1.0,
            num_inference_steps=30, guidance_scale=7.0, generator=gen,
        ).images[0]
        return out.resize(image.size, Image.LANCZOS)
    # ring-band cleanup: 4-28 px outside the hard silhouette still holds
    # halo pixels; inpaint that band from the surrounding filled texture.
    # LaMa pads to its own grid — normalize back to the source size first
    # or cv2.inpaint rejects the shape mismatch.
    if filled.size != image.size:
        filled = filled.resize(image.size, Image.LANCZOS)
    k = max(3, image.width // 128)
    band_inner = cv2.dilate(hard, np.ones((3, 3), np.uint8), iterations=2)
    band_outer = cv2.dilate(hard, np.ones((3, 3), np.uint8),
                            iterations=max(4, k))
    band = cv2.subtract(band_outer, band_inner)
    arr = np.asarray(filled.convert("RGB"))
    cleaned = cv2.inpaint(arr, band, 5, cv2.INPAINT_NS)
    # NOTE: LaMa's fill keeps a faint wispy haze in big smooth regions; every
    # automatic flattening we tried re-sculpted a visible silhouette, so we
    # ship LaMa's fill as-is after the ring cleanup (verified least-bad).
    return Image.fromarray(cleaned)


def _export_psd(bg: Image.Image, fg: Image.Image, offset, out_dir) -> str:
    """Layered PSD: full-canvas background + character at its original position."""
    from psd_tools import PSDImage
    psd = PSDImage.new("RGBA", bg.size)
    psd.create_pixel_layer(bg.convert("RGBA"), name="background", top=0, left=0)
    psd.create_pixel_layer(fg.convert("RGBA"), name="character",
                           top=int(offset[1]), left=int(offset[0]))
    path = out_dir / f"asset_split_{int(time.time())}.psd"
    psd.save(str(path))
    return str(path)


def _export_zip(bg: Image.Image, fg: Image.Image, out_dir) -> str:
    path = out_dir / f"asset_pack_{int(time.time())}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, img in [("character_transparent.png", fg),
                          ("background_completed.png", bg)]:
            buf = io.BytesIO()
            img.save(buf, "PNG")
            zf.writestr(name, buf.getvalue())
    return str(path)


def run_split(manager, image: Image.Image, fill_bg: bool = True,
              margin: int = 16):
    """Returns (character_rgba, background, [files], perf_dict)."""
    if image is None:
        raise ValueError("Please upload an image first.")
    rgb = to_rgb_white(image)

    reset_peak_memory()
    with Timer() as t_matte:
        fg, alpha = cutout(manager, rgb)
        character, offset = _crop_to_content(fg, int(margin))

    fill_s = 0.0
    if fill_bg:
        with Timer() as t_fill:
            background = _fill_background(manager, rgb, alpha)
        fill_s = t_fill.elapsed
    else:
        background = rgb

    out_dir = manager.settings.output_dir
    files = []
    psd_note = "PSD"
    try:
        files.append(_export_psd(background, character, offset, out_dir))
    except Exception as e:
        psd_note = f"PSD failed ({type(e).__name__})"
    files.append(_export_zip(background, character, out_dir))

    perf = {
        "Matting time": f"{t_matte.elapsed:.2f} s",
        "Background fill time": f"{fill_s:.2f} s" if fill_bg else "—",
        "Peak VRAM": f"{peak_memory_gb():.2f} GB",
        "Character size": f"{character.size[0]}×{character.size[1]}",
        "Export": f"{psd_note} + PNG asset pack",
    }
    return character, background, files, perf
