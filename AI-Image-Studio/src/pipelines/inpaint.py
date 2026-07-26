# -*- coding: utf-8 -*-
"""局部重绘（Inpainting）：按遮罩 + 文本提示重绘图像局部区域。"""
from __future__ import annotations

from PIL import Image

from ..device import Timer, peak_memory_gb, reset_peak_memory
from ..utils import crop_back, make_generator, pad_to_multiple, resize_long_edge

DEFAULT_NEGATIVE = "blurry, low quality, deformed, watermark, text, bad anatomy, artifacts"


def run_inpaint(manager, image: Image.Image, mask: Image.Image,
                prompt: str, negative_prompt: str = DEFAULT_NEGATIVE,
                steps: int = 25, guidance: float = 7.0, strength: float = 1.0,
                seed: int = -1, fast: bool = False):
    """执行局部重绘。返回 (结果图, 性能信息 dict, 实际使用的 seed)。

    流程：工作分辨率缩放 → 8 像素对齐 → 扩散重绘 → 还原到原尺寸。
    fast=True 时启用 LCM-LoRA 极速模式（4~8 步，速度提升 3~5 倍）。
    """
    if image is None or mask is None:
        raise ValueError("请先上传图片并用画笔涂抹需要重绘的区域。")
    if not prompt.strip():
        prompt = "high quality, detailed, seamless"

    max_size = manager.settings.max_diffusion_size
    orig_size = image.size
    work_img = resize_long_edge(image, max_size, multiple=8)
    work_mask = mask.resize(work_img.size, Image.NEAREST)
    work_img, unpadded_size = pad_to_multiple(work_img, 8)
    work_mask, _ = pad_to_multiple(work_mask.convert("L"), 8)

    pipe = manager.get_inpaint_pipe()
    from ..lora_tools import lcm_call_kwargs, set_lcm
    set_lcm(pipe, manager.settings, fast)
    if fast:
        steps = lcm_call_kwargs(manager.settings)["num_inference_steps"]
        guidance = lcm_call_kwargs(manager.settings)["guidance_scale"]

    gen = make_generator(manager.info.device, seed)
    reset_peak_memory()
    with Timer() as t:
        out = pipe(
            prompt=prompt,
            negative_prompt=negative_prompt,
            image=work_img,
            mask_image=work_mask,
            num_inference_steps=int(steps),
            guidance_scale=float(guidance),
            strength=float(strength),
            generator=gen,
        ).images[0]
    out = crop_back(out, unpadded_size)
    if out.size != orig_size:
        out = out.resize(orig_size, Image.LANCZOS)

    used_seed = gen.initial_seed()
    info = {
        "耗时": f"{t.elapsed:.2f} s",
        "速度": f"{t.elapsed / max(1, int(steps)) * 1000:.0f} ms/step",
        "峰值显存": f"{peak_memory_gb():.2f} GB" if manager.info.device.type == "cuda" else "CPU 推理",
        "工作分辨率": f"{work_img.width}×{work_img.height}",
        "采样模式": "LCM 极速" if fast else "标准",
        "Seed": str(used_seed),
    }
    return out, info, used_seed
