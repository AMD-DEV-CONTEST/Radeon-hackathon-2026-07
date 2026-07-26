# -*- coding: utf-8 -*-
"""电商一键工作流：产品图 → 抠图 → 白底主图 → AI 场景图 → 排版海报。

一次点击产出整套电商素材，全程复用现有能力：
BiRefNet 抠图 + SD 场景生成 + Real-ESRGAN 超分 + PIL 排版。
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

from ..device import Timer, peak_memory_gb, reset_peak_memory
from .background import remove_bg
from .poster import POSTER_SIZES, compose_poster


def _place_on_canvas(rgba: Image.Image, canvas_size, fill=(255, 255, 255),
                     ratio: float = 0.7):
    """把透明产品图按比例缩放居中放到画布上。返回 (画布, 产品alpha画布)。"""
    cw, ch = canvas_size
    alpha = rgba.split()[3]
    bbox = alpha.getbbox()
    if bbox:
        rgba = rgba.crop(bbox)
    scale = min(cw * ratio / rgba.width, ch * ratio / rgba.height)
    nw, nh = max(1, int(rgba.width * scale)), max(1, int(rgba.height * scale))
    product = rgba.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (cw, ch), fill)
    px, py = (cw - nw) // 2, (ch - nh) // 2
    canvas.paste(product, (px, py), product)
    alpha_canvas = Image.new("L", (cw, ch), 0)
    alpha_canvas.paste(product.split()[3], (px, py))
    return canvas, alpha_canvas, (px, py, product)


def run_ecommerce(manager, image: Image.Image, scene_prompt: str,
                  title: str, subtitle: str, size_name: str = "方形主图 1:1（1024×1024）",
                  scene_count: int = 2, do_upscale: bool = True, fast: bool = False):
    """电商素材一键生成。返回 (素材列表, 性能信息)。

    产出顺序：白底主图 ×1 + AI 场景图 ×N + 排版海报 ×N。
    """
    if image is None:
        raise ValueError("请先上传产品图片。")
    scene_count = max(1, min(4, int(scene_count)))
    gw, gh = POSTER_SIZES[size_name]

    reset_peak_memory()
    with Timer() as t:
        # 1. 抠图
        rgba, alpha = remove_bg(manager, image)

        # 2. 白底主图（标准电商白底图）
        main_img, _, _ = _place_on_canvas(rgba, (gw * 2, gh * 2), ratio=0.78)
        results = [("白底主图", main_img)]

        # 3. AI 场景图：灰底画布 + 产品 → 反转 alpha 做遮罩 → 场景重绘 → 贴回产品
        scene_desc = scene_prompt.strip() or "modern minimalist product photography, marble surface, soft studio lighting, depth of field"
        base_canvas, prod_alpha, (px, py, product) = _place_on_canvas(
            rgba, (gw, gh), fill=(128, 128, 128), ratio=0.62)
        bg_mask = Image.eval(prod_alpha, lambda a: 255 - a)
        bg_mask = bg_mask.filter(ImageFilter.GaussianBlur(3))

        from .inpaint import run_inpaint
        posters_prompt = ", commercial product photography, professional lighting, shadow, high quality"
        upscaler = manager.get_upscaler("fast") if do_upscale else None

        for i in range(scene_count):
            scene, _, _ = run_inpaint(
                manager, base_canvas, bg_mask,
                prompt=scene_desc + posters_prompt,
                negative_prompt="blurry, low quality, watermark, text, deformed product",
                steps=25, guidance=7.0, strength=1.0, seed=-1, fast=fast)
            # 产品清晰贴回（硬边缘），保持商品本体不变形
            scene.paste(product, (px, py), product)
            if upscaler is not None:
                scene = upscaler.upscale_image(scene, target_scale=2.0)
            results.append((f"AI 场景图 {i + 1}", scene))
            # 4. 排版海报
            poster = compose_poster(scene, title, subtitle, layout="底部横幅")
            results.append((f"海报 {i + 1}", poster))

    images = [img for _, img in results]
    info = {
        "产出素材": f"白底主图 ×1 + 场景图 ×{scene_count} + 海报 ×{scene_count}",
        "总耗时": f"{t.elapsed:.2f} s",
        "峰值显存": f"{peak_memory_gb():.2f} GB" if manager.info.device.type == "cuda" else "CPU 推理",
        "流程": "抠图 → 白底主图 → AI 场景 → 2× 超分 → 排版",
        "采样模式": "LCM 极速" if fast else "标准",
    }
    return images, info
