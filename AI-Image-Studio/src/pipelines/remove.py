# -*- coding: utf-8 -*-
"""物体 / 水印移除：优先使用 LaMa（无需提示词、速度快），不可用时回退到 SD 重绘。"""
from __future__ import annotations

from PIL import Image

from ..device import Timer, peak_memory_gb, reset_peak_memory


def run_remove(manager, image: Image.Image, mask: Image.Image, expand_px: int = 12):
    """涂抹区域内容移除。返回 (结果图, 性能信息 dict)。"""
    if image is None or mask is None:
        raise ValueError("请先上传图片并用画笔涂抹需要移除的物体或水印。")

    reset_peak_memory()
    if manager.settings.enable_lama:
        try:
            lama = manager.get_lama()
            with Timer() as t:
                result = lama(image.convert("RGB"), mask.convert("L"))
            return result, {
                "耗时": f"{t.elapsed:.2f} s",
                "峰值显存": f"{peak_memory_gb():.2f} GB" if manager.info.device.type == "cuda" else "CPU 推理",
                "引擎": "LaMa（免提示词）",
            }
        except ImportError:
            pass  # 未安装 simple-lama-inpainting，回退到 SD

    # 回退方案：用 SD 重绘模型做内容感知填充
    from .inpaint import run_inpaint
    result, info, _ = run_inpaint(
        manager, image, mask,
        prompt="clean empty background, seamless, high quality photo",
        negative_prompt="object, watermark, text, logo, person",
        steps=25, guidance=6.0, strength=1.0, seed=-1,
    )
    info["引擎"] = "Stable Diffusion 填充（LaMa 未安装时的回退方案）"
    return result, info
