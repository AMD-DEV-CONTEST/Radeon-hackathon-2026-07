# -*- coding: utf-8 -*-
"""背景移除与替换：BiRefNet 高精度抠图 + 纯色/渐变/AI 生成背景替换。"""
from __future__ import annotations

import numpy as np
import torch
from PIL import Image, ImageFilter
from torchvision import transforms

from ..device import Timer, peak_memory_gb, reset_peak_memory
from ..utils import composite_on_color, hex_to_rgb

_BREF_SIZE = 1024

_transform = transforms.Compose([
    transforms.Resize((_BREF_SIZE, _BREF_SIZE)),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])


@torch.inference_mode()
def remove_bg(manager, image: Image.Image) -> tuple[Image.Image, Image.Image]:
    """BiRefNet 抠图。返回 (RGBA 前景, alpha 蒙版)。"""
    model = manager.get_bg_remover()
    img_rgb = image.convert("RGB")
    x = _transform(img_rgb).unsqueeze(0).to(manager.info.device, manager.info.dtype)
    pred = model(x)
    if isinstance(pred, (list, tuple)):
        pred = pred[-1]
    pred = torch.sigmoid(pred)
    mask = pred.squeeze().float().cpu().numpy()
    mask = (mask - mask.min()) / (mask.max() - mask.min() + 1e-8)
    mask_img = Image.fromarray((mask * 255).astype(np.uint8), "L").resize(img_rgb.size, Image.LANCZOS)

    rgba = img_rgb.convert("RGBA")
    rgba.putalpha(mask_img)
    return rgba, mask_img


def _gradient_background(size, color_top, color_bottom) -> Image.Image:
    w, h = size
    top = np.array(hex_to_rgb(color_top), dtype=np.float32)
    bottom = np.array(hex_to_rgb(color_bottom), dtype=np.float32)
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    grad = (top[None, None, :] * (1 - t) + bottom[None, None, :] * t)
    arr = np.repeat(grad, w, axis=1).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


def run_background(manager, image: Image.Image, mode: str = "透明 PNG",
                   solid_color: str = "#FFFFFF",
                   grad_top: str = "#89CFF0", grad_bottom: str = "#F0E68C",
                   ai_prompt: str = "", blur_fg_mask: int = 1):
    """背景移除 + 可选替换。返回 (结果图, 前景RGBA, 性能信息)。"""
    if image is None:
        raise ValueError("请先上传图片。")

    reset_peak_memory()
    with Timer() as t:
        rgba, alpha = remove_bg(manager, image)

    if mode == "透明 PNG":
        result = rgba
    elif mode == "纯色背景":
        result = composite_on_color(rgba, hex_to_rgb(solid_color))
    elif mode == "渐变背景":
        bg = _gradient_background(image.size, grad_top, grad_bottom)
        bg.paste(rgba, mask=alpha)
        result = bg
    elif mode == "AI 生成背景":
        # 反转蒙版：把背景区域作为重绘区，前景保留
        if blur_fg_mask > 0:
            alpha = alpha.filter(ImageFilter.GaussianBlur(blur_fg_mask))
        bg_mask = Image.eval(alpha, lambda a: 255 - a)
        from .inpaint import run_inpaint
        fg_on_grey = composite_on_color(rgba, (128, 128, 128))
        prompt = ai_prompt.strip() or "beautiful natural scenery background, soft lighting, high quality"
        result, _, _ = run_inpaint(
            manager, fg_on_grey, bg_mask,
            prompt=prompt + ", background only",
            negative_prompt="person, object in foreground, deformed",
            steps=25, guidance=7.0, strength=1.0, seed=-1)
        # 用清晰前景盖回，避免边缘被改动
        result = result.convert("RGBA")
        result.paste(rgba, mask=alpha.point(lambda a: 255 if a > 200 else 0))
        result = result.convert("RGB")
    else:
        raise ValueError(f"未知背景模式: {mode}")

    info = {
        "耗时": f"{t.elapsed:.2f} s",
        "峰值显存": f"{peak_memory_gb():.2f} GB" if manager.info.device.type == "cuda" else "CPU 推理",
        "模式": mode,
    }
    return result, rgba, info
