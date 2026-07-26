# -*- coding: utf-8 -*-
"""风格迁移：基于 img2img 的艺术风格重构，内置风格预设，支持批量处理。"""
from __future__ import annotations

from PIL import Image

from ..device import Timer, peak_memory_gb, reset_peak_memory
from ..utils import crop_back, make_generator, pad_to_multiple, resize_long_edge

STYLE_PRESETS = {
    "日系动漫": {
        "prompt": "anime style, cel shading, vibrant colors, clean lineart, high quality illustration, masterpiece",
        "negative": "photo, realistic, blurry, low quality, watermark, text",
        "strength": 0.65,
    },
    "赛博朋克": {
        "prompt": "cyberpunk style, neon lights, futuristic city, glowing edges, cinematic lighting, highly detailed",
        "negative": "blurry, low quality, dull colors, watermark, text",
        "strength": 0.7,
    },
    "水彩画": {
        "prompt": "delicate watercolor painting, soft washes, paper texture, artistic, gentle colors, masterpiece",
        "negative": "photo, sharp edges, digital, watermark, text",
        "strength": 0.6,
    },
    "油画": {
        "prompt": "classical oil painting, visible brushstrokes, rich texture, dramatic lighting, museum quality",
        "negative": "photo, flat, digital, watermark, text",
        "strength": 0.6,
    },
    "复古胶片": {
        "prompt": "vintage film photography, 35mm film grain, faded warm tones, nostalgic, kodak portra style",
        "negative": "digital, oversaturated, watermark, text",
        "strength": 0.45,
    },
    "像素艺术": {
        "prompt": "pixel art, 16-bit retro game style, limited color palette, crisp pixels, detailed sprite art",
        "negative": "blurry, smooth gradients, photo, watermark, text",
        "strength": 0.7,
    },
}


def run_style(manager, image: Image.Image, style_name: str,
              custom_prompt: str = "", custom_negative: str = "",
              strength: float | None = None, steps: int = 25,
              guidance: float = 7.5, seed: int = -1, fast: bool = False,
              lora_ref: str = "", lora_scale: float = 0.8):
    """对单张图执行风格迁移。返回 (结果图, 性能信息, 实际 seed)。

    fast=True 启用 LCM 极速模式；lora_ref 可指定自定义 LoRA（HF ID 或本地路径）。
    """
    if image is None:
        raise ValueError("请先上传图片。")
    preset = STYLE_PRESETS.get(style_name, {})
    prompt = custom_prompt.strip() or preset.get("prompt", style_name)
    negative = custom_negative.strip() or preset.get("negative", "blurry, low quality, watermark, text")
    strength = float(strength) if strength else float(preset.get("strength", 0.6))

    max_size = manager.settings.max_diffusion_size
    orig_size = image.size
    work_img = resize_long_edge(image.convert("RGB"), max_size, multiple=8)
    work_img, unpadded_size = pad_to_multiple(work_img, 8)

    pipe = manager.get_img2img_pipe()
    from ..lora_tools import apply_user_lora, lcm_call_kwargs, set_lcm
    set_lcm(pipe, manager.settings, fast)
    lora_msg = apply_user_lora(pipe, lora_ref, lora_scale)
    if fast:
        steps = lcm_call_kwargs(manager.settings)["num_inference_steps"]
        guidance = lcm_call_kwargs(manager.settings)["guidance_scale"]

    gen = make_generator(manager.info.device, seed)
    reset_peak_memory()
    with Timer() as t:
        out = pipe(
            prompt=prompt,
            negative_prompt=negative,
            image=work_img,
            strength=min(0.95, max(0.05, strength)),
            num_inference_steps=int(steps),
            guidance_scale=float(guidance),
            generator=gen,
        ).images[0]
    out = crop_back(out, unpadded_size)
    if out.size != orig_size:
        out = out.resize(orig_size, Image.LANCZOS)

    used_seed = gen.initial_seed()
    info = {
        "耗时": f"{t.elapsed:.2f} s",
        "峰值显存": f"{peak_memory_gb():.2f} GB" if manager.info.device.type == "cuda" else "CPU 推理",
        "风格": style_name,
        "重绘幅度": f"{strength:.2f}",
        "采样模式": "LCM 极速" if fast else "标准",
        "LoRA": lora_msg,
        "Seed": str(used_seed),
    }
    return out, info, used_seed


def run_style_batch(manager, images, style_name, custom_prompt="", custom_negative="",
                    strength=None, steps=25, guidance=7.5, seed=-1, fast=False,
                    lora_ref="", lora_scale=0.8):
    """批量风格迁移，返回 [(结果图, 文件名)], 汇总性能信息。"""
    results, total_time, count = [], 0.0, 0
    for i, img in enumerate(images or []):
        if img is None:
            continue
        out, info, _ = run_style(manager, img, style_name, custom_prompt,
                                 custom_negative, strength, steps, guidance,
                                 seed if seed >= 0 else -1, fast=fast,
                                 lora_ref=lora_ref, lora_scale=lora_scale)
        results.append(out)
        total_time += float(info["耗时"].rstrip(" s"))
        count += 1
    summary = {"处理数量": str(count), "总耗时": f"{total_time:.2f} s",
               "平均单张": f"{total_time / count:.2f} s" if count else "-"}
    return results, summary
