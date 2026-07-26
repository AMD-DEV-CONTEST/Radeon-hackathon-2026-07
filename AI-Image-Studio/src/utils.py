# -*- coding: utf-8 -*-
"""图像与遮罩处理工具。"""
from __future__ import annotations

import numpy as np
import torch
from PIL import Image, ImageFilter

try:
    import cv2
    _HAS_CV2 = True
except Exception:  # pragma: no cover
    _HAS_CV2 = False


def resize_long_edge(img: Image.Image, max_size: int, multiple: int = 8) -> Image.Image:
    """等比缩放使最长边 <= max_size，且宽高均为 multiple 的整数倍（扩散模型要求）。"""
    w, h = img.size
    scale = min(1.0, max_size / max(w, h))
    nw = max(multiple, int(w * scale) // multiple * multiple)
    nh = max(multiple, int(h * scale) // multiple * multiple)
    if (nw, nh) == (w, h):
        return img
    return img.resize((nw, nh), Image.LANCZOS)


def editor_to_image_mask(editor_value, expand_px: int = 8, blur_px: int = 0):
    """从 Gradio ImageEditor 的返回值提取背景图与用户涂抹的遮罩。

    返回 (image RGB, mask L)。mask 中白色(255)表示待重绘区域。
    未涂抹时返回 None 作为 mask，由调用方提示用户。
    """
    if editor_value is None:
        return None, None
    if isinstance(editor_value, dict):
        bg = editor_value.get("background")
        layers = editor_value.get("layers") or []
    else:  # 兼容直接传入 PIL 的情况
        bg, layers = editor_value, []
    if bg is None:
        return None, None
    image = bg.convert("RGB")

    if not layers:
        return image, None
    # 合并所有涂抹图层的 alpha 通道
    alpha = np.zeros((image.height, image.width), dtype=np.uint8)
    for layer in layers:
        if layer is None:
            continue
        la = np.asarray(layer.convert("RGBA"))[..., 3]
        if la.shape != alpha.shape:
            la_img = Image.fromarray(la).resize(image.size, Image.NEAREST)
            la = np.asarray(la_img)
        alpha = np.maximum(alpha, la)
    if alpha.max() == 0:
        return image, None

    mask = Image.fromarray(np.where(alpha > 20, 255, 0).astype(np.uint8), mode="L")
    if expand_px > 0:
        mask = dilate_mask(mask, expand_px)
    if blur_px > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(blur_px))
    return image, mask


def dilate_mask(mask: Image.Image, px: int) -> Image.Image:
    """向外扩张遮罩边缘 px 像素，避免重绘残留描边。"""
    arr = np.asarray(mask)
    if _HAS_CV2:
        kernel = np.ones((max(1, px * 2 + 1),) * 2, np.uint8)
        arr = cv2.dilate(arr, kernel, iterations=1)
    else:
        arr = np.asarray(mask.filter(ImageFilter.MaxFilter(px * 2 + 1)))
    return Image.fromarray(arr, mode="L")


def make_outpaint_canvas(img: Image.Image, left: int, right: int, top: int, bottom: int):
    """按像素外扩画布。返回 (新画布, 遮罩[白色=新生成区域])。"""
    w, h = img.size
    nw, nh = w + left + right, h + top + bottom
    canvas = Image.new("RGB", (nw, nh), (128, 128, 128))
    canvas.paste(img, (left, top))
    mask = Image.new("L", (nw, nh), 255)
    mask.paste(0, (left, top, left + w, top + h))
    # 边缘向内羽化一点，保证接缝自然
    mask = dilate_mask(mask, 4)
    return canvas, mask


def pad_to_multiple(img: Image.Image, multiple: int = 8):
    """将图像右下补齐到 multiple 的整数倍。返回 (补齐图, 原尺寸)。"""
    w, h = img.size
    nw = (w + multiple - 1) // multiple * multiple
    nh = (h + multiple - 1) // multiple * multiple
    if (nw, nh) == (w, h):
        return img, (w, h)
    out = Image.new(img.mode, (nw, nh))
    out.paste(img, (0, 0))
    return out, (w, h)


def crop_back(img: Image.Image, size) -> Image.Image:
    return img.crop((0, 0, size[0], size[1]))


def make_generator(device: torch.device, seed: int) -> torch.Generator:
    seed = int(seed)
    if seed < 0:
        seed = int(torch.seed() % (2**31))
    try:
        return torch.Generator(device=device).manual_seed(seed)
    except Exception:
        return torch.Generator().manual_seed(seed)


def hex_to_rgb(hex_color: str):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def composite_on_color(rgba: Image.Image, color) -> Image.Image:
    bg = Image.new("RGB", rgba.size, color)
    bg.paste(rgba, mask=rgba.split()[3])
    return bg
