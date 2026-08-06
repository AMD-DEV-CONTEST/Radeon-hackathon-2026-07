# -*- coding: utf-8 -*-
"""Image / mask utilities for AI-Image-Studio v2."""
from __future__ import annotations

import numpy as np
import torch
from PIL import Image, ImageFilter


# ------------------------------------------------------------ conversion

def to_rgb_white(img: Image.Image) -> Image.Image:
    """Convert any image to RGB, compositing transparency onto WHITE."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
        canvas.paste(rgba, mask=rgba.split()[3])
        return canvas
    return img.convert("RGB")


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = (hex_color or "#FFFFFF").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except Exception:
        return 255, 255, 255


# ------------------------------------------------------------- geometry

def resize_long_edge(img: Image.Image, max_size: int, multiple: int = 8,
                     upscale_min: int = 0) -> Image.Image:
    """Resize so the long edge == max_size (shrink only). If upscale_min > 0,
    also enlarge images whose long edge is below upscale_min (to upscale_min).
    Result dimensions are rounded to `multiple`."""
    w, h = img.size
    long_edge = max(w, h)
    scale = 1.0
    if long_edge > max_size:
        scale = max_size / long_edge
    elif upscale_min and long_edge < upscale_min:
        scale = upscale_min / long_edge
    if scale != 1.0:
        nw = max(multiple, int(round(w * scale)) // multiple * multiple)
        nh = max(multiple, int(round(h * scale)) // multiple * multiple)
        img = img.resize((nw, nh), Image.LANCZOS)
    elif w % multiple or h % multiple:
        # Pass-through still must honor `multiple`: SDXL snaps non-conforming
        # dims internally and returns a slightly different size, which crashed
        # the style pipeline's no-op diff (1018→1016 broadcast error).
        nw = max(multiple, round(w / multiple) * multiple)
        nh = max(multiple, round(h / multiple) * multiple)
        img = img.resize((nw, nh), Image.LANCZOS)
    return img


def pad_to_multiple(img: Image.Image, multiple: int = 8):
    """Pad bottom/right to a multiple of `multiple`. Returns (img, orig_size)."""
    w, h = img.size
    nw = (w + multiple - 1) // multiple * multiple
    nh = (h + multiple - 1) // multiple * multiple
    if (nw, nh) == (w, h):
        return img, (w, h)
    canvas = Image.new(img.mode, (nw, nh), 0 if img.mode == "L" else (128, 128, 128))
    canvas.paste(img, (0, 0))
    return canvas, (w, h)


def crop_back(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    return img.crop((0, 0, size[0], size[1]))


# ---------------------------------------------------------------- masks

def dilate_mask(mask: Image.Image, px: int) -> Image.Image:
    if px <= 0:
        return mask
    return mask.filter(ImageFilter.MaxFilter(px * 2 + 1))


def blur_mask(mask: Image.Image, radius: float = 8.0) -> Image.Image:
    """Feather mask edges for seamless blending."""
    return mask.filter(ImageFilter.GaussianBlur(radius))


def mask_bbox(mask: Image.Image, thr: int = 16):
    """Bounding box (x0, y0, x1, y1) of the masked (white) area, or None."""
    a = np.asarray(mask)
    ys, xs = np.where(a > thr)
    if len(ys) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def expand_bbox(bbox, img_size, pad: int):
    x0, y0, x1, y1 = bbox
    w, h = img_size
    return (max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad))


def editor_to_image_mask(editor_value, expand_px: int = 8):
    """Gradio ImageEditor value -> (RGB image, L mask). White = edit region."""
    if editor_value is None:
        return None, None
    if isinstance(editor_value, dict):
        bg = editor_value.get("background")
        layers = editor_value.get("layers") or []
    else:
        bg, layers = editor_value, []
    if bg is None:
        return None, None
    image = to_rgb_white(bg)
    if not layers:
        return image, Image.new("L", image.size, 0)
    layer = layers[0].convert("RGBA")
    if layer.size != image.size:
        layer = layer.resize(image.size, Image.NEAREST)
    alpha = np.asarray(layer.split()[3])
    mask = Image.fromarray(np.where(alpha > 16, 255, 0).astype(np.uint8), "L")
    if expand_px > 0:
        mask = dilate_mask(mask, expand_px)
    return image, mask


# ---------------------------------------------------------------- misc

def make_generator(device: str, seed: int):
    if seed is None or int(seed) < 0:
        return None, torch.seed()
    gen_device = "cuda" if (device == "cuda" and torch.cuda.is_available()) else "cpu"
    return torch.Generator(gen_device).manual_seed(int(seed)), int(seed)
