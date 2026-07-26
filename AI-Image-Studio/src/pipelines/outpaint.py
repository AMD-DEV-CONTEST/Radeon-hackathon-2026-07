# -*- coding: utf-8 -*-
"""智能扩图（Outpainting）：向四个方向延展画布并由 AI 补全内容。"""
from __future__ import annotations

from PIL import Image

from ..device import Timer, peak_memory_gb, reset_peak_memory
from ..utils import crop_back, make_generator, make_outpaint_canvas, pad_to_multiple, resize_long_edge

DEFAULT_NEGATIVE = "blurry, low quality, deformed, watermark, text, seam, artifacts"


def run_outpaint(manager, image: Image.Image,
                 left: int, right: int, top: int, bottom: int,
                 prompt: str, negative_prompt: str = DEFAULT_NEGATIVE,
                 steps: int = 28, guidance: float = 7.0, seed: int = -1,
                 fast: bool = False):
    """按像素外扩画布并生成延展内容。返回 (结果图, 性能信息, 实际 seed)。"""
    if image is None:
        raise ValueError("请先上传图片。")
    left, right, top, bottom = map(lambda v: max(0, int(v)), (left, right, top, bottom))
    if left + right + top + bottom == 0:
        raise ValueError("请至少在一个方向上设置大于 0 的扩展像素。")
    if not prompt.strip():
        prompt = "seamless extended scenery, high quality, detailed"

    canvas, mask = make_outpaint_canvas(image.convert("RGB"), left, right, top, bottom)
    orig_size = canvas.size
    max_size = manager.settings.max_diffusion_size
    work_img = resize_long_edge(canvas, max_size, multiple=8)
    work_mask = mask.resize(work_img.size, Image.NEAREST)
    work_img, unpadded_size = pad_to_multiple(work_img, 8)
    work_mask, _ = pad_to_multiple(work_mask, 8)

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
            strength=1.0,
            generator=gen,
        ).images[0]
    out = crop_back(out, unpadded_size)
    if out.size != orig_size:
        out = out.resize(orig_size, Image.LANCZOS)

    used_seed = gen.initial_seed()
    info = {
        "耗时": f"{t.elapsed:.2f} s",
        "峰值显存": f"{peak_memory_gb():.2f} GB" if manager.info.device.type == "cuda" else "CPU 推理",
        "输出尺寸": f"{out.width}×{out.height}",
        "采样模式": "LCM 极速" if fast else "标准",
        "Seed": str(used_seed),
    }
    return out, info, used_seed
