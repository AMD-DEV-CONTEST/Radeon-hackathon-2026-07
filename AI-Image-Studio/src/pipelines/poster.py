# -*- coding: utf-8 -*-
"""AI 海报批量生成：文生图 → 超分放大 → 模板文字排版，一键批量出图。

适用场景：电商主图、活动海报、内容封面。生成与排版解耦，
文字层使用 PIL 精确渲染（支持中文），避免扩散模型出字的乱码问题。
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..device import Timer, peak_memory_gb, reset_peak_memory
from ..utils import make_generator

# 预设尺寸：生成分辨率 → 超分 2x 后输出分辨率
POSTER_SIZES = {
    "竖版海报 2:3（1024×1536）": (512, 768),
    "方形主图 1:1（1024×1024）": (512, 512),
    "横版封面 16:9（1536×864）": (768, 432),
}

_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
]


def find_cjk_font() -> str | None:
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def _font(size: int) -> ImageFont.FreeTypeFont:
    path = find_cjk_font()
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def _scrim(size, direction: str = "bottom") -> Image.Image:
    """生成半透明渐变衬底，保证文字可读性。"""
    w, h = size
    scrim = Image.new("L", (1, h), 0)
    for y in range(h):
        t = y / h
        if direction == "bottom":
            a = int(180 * max(0.0, (t - 0.45) / 0.55) ** 1.5)
        else:
            a = int(180 * max(0.0, (0.55 - t) / 0.55) ** 1.5)
        scrim.putpixel((0, y), a)
    scrim = scrim.resize((w, h))
    black = Image.new("RGB", (w, h), (10, 12, 20))
    black.putalpha(scrim)
    return black


def compose_poster(bg: Image.Image, title: str, subtitle: str = "",
                   tag: str = "", layout: str = "底部横幅") -> Image.Image:
    """在背景图上叠加渐变衬底与文字排版。"""
    img = bg.convert("RGB")
    w, h = img.size
    direction = "bottom" if layout != "顶部标题" else "top"
    img.paste(_scrim((w, h), direction), (0, 0), _scrim((w, h), direction))

    draw = ImageDraw.Draw(img)
    title_font = _font(max(24, h // 14))
    sub_font = _font(max(16, h // 30))
    tag_font = _font(max(14, h // 36))

    if layout == "顶部标题":
        y = int(h * 0.08)
        anchor = "ma"
    elif layout == "居中大标题":
        y = int(h * 0.5)
        anchor = "mm"
    else:
        y = int(h * 0.72)
        anchor = "ma"

    cx = w // 2
    if title:
        draw.text((cx, y), title, font=title_font, fill=(255, 255, 255),
                  anchor=anchor, stroke_width=max(1, h // 400), stroke_fill=(0, 0, 0))
        y += title_font.size + int(h * 0.035)
    if subtitle:
        draw.text((cx, y), subtitle, font=sub_font, fill=(235, 235, 235),
                  anchor=anchor, stroke_width=1, stroke_fill=(0, 0, 0))
        y += sub_font.size + int(h * 0.025)
    if tag:
        tw = draw.textlength(tag, font=tag_font)
        pad = int(h * 0.012)
        ty = y + pad * 2
        draw.rounded_rectangle([cx - tw / 2 - pad * 2, ty - pad, cx + tw / 2 + pad * 2,
                                ty + tag_font.size + pad], radius=pad * 1.5,
                               fill=(255, 200, 60))
        draw.text((cx, ty), tag, font=tag_font, fill=(20, 20, 20), anchor="ma")
    return img


def run_poster_batch(manager, prompt: str, negative: str, size_name: str,
                     title: str, subtitle: str, tag: str, layout: str,
                     count: int = 2, steps: int = 25, guidance: float = 7.5,
                     seed: int = -1, do_upscale: bool = True, fast: bool = False,
                     lora_ref: str = "", lora_scale: float = 0.8):
    """批量生成海报。返回 (海报列表, 性能信息)。

    fast=True 启用 LCM 极速模式；lora_ref 可指定自定义风格 LoRA。
    """
    if not prompt.strip():
        raise ValueError("请填写画面描述提示词。")
    count = max(1, min(8, int(count)))
    gw, gh = POSTER_SIZES[size_name]

    pipe = manager.get_txt2img_pipe()
    from ..lora_tools import apply_user_lora, lcm_call_kwargs, set_lcm
    set_lcm(pipe, manager.settings, fast)
    lora_msg = apply_user_lora(pipe, lora_ref, lora_scale)
    if fast:
        steps = lcm_call_kwargs(manager.settings)["num_inference_steps"]
        guidance = lcm_call_kwargs(manager.settings)["guidance_scale"]

    upscaler = manager.get_upscaler("fast") if do_upscale else None

    reset_peak_memory()
    posters, base_seed = [], int(seed)
    with Timer() as t:
        for i in range(count):
            s = base_seed if base_seed >= 0 else -1
            gen = make_generator(manager.info.device, s)
            bg = pipe(prompt=prompt,
                      negative_prompt=negative or "blurry, low quality, watermark, text, logo",
                      width=gw, height=gh, num_inference_steps=int(steps),
                      guidance_scale=float(guidance), generator=gen).images[0]
            used = gen.initial_seed()
            if base_seed < 0:
                base_seed = used + 1  # 批量时种子顺延
            if upscaler is not None:
                bg = upscaler.upscale_image(bg, target_scale=2.0)
            posters.append(compose_poster(bg, title, subtitle, tag, layout))

    info = {
        "生成数量": f"{count} 张",
        "总耗时": f"{t.elapsed:.2f} s",
        "平均单张": f"{t.elapsed / count:.2f} s",
        "峰值显存": f"{peak_memory_gb():.2f} GB" if manager.info.device.type == "cuda" else "CPU 推理",
        "输出尺寸": f"{posters[0].width}×{posters[0].height}",
        "采样模式": "LCM 极速" if fast else "标准",
        "LoRA": lora_msg,
        "流程": "文生图 → 2× 超分 → 模板排版" if do_upscale else "文生图 → 模板排版",
    }
    return posters, info
