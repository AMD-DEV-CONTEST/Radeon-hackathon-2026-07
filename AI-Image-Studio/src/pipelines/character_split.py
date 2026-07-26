# -*- coding: utf-8 -*-
"""AI 角色素材拆分：单张角色图 → 透明图层 + 背景层 + 分层 PSD。

适用场景：Live2D 前处理、2.5D 创作、角色素材库建设。
- 抠图：BiRefNet 高精度分割
- 背景补全：LaMa / SD 填充（可选）
- 导出：透明 PNG（内容自适应裁切）+ 背景 PNG + 分层 PSD + 打包 ZIP
"""
from __future__ import annotations

import os
import tempfile
import zipfile

import numpy as np
from PIL import Image, ImageFilter

from ..device import Timer, peak_memory_gb, reset_peak_memory
from .background import remove_bg


def _crop_to_content(rgba: Image.Image, margin: int = 16) -> Image.Image:
    """按 alpha 通道内容包围盒裁切，四周留白 margin 像素。"""
    alpha = np.asarray(rgba.split()[3])
    ys, xs = np.where(alpha > 8)
    if len(ys) == 0:
        return rgba
    y0, y1 = max(0, ys.min() - margin), min(rgba.height, ys.max() + margin + 1)
    x0, x1 = max(0, xs.min() - margin), min(rgba.width, xs.max() + margin + 1)
    return rgba.crop((x0, y0, x1, y1))


def _write_psd(path: str, layers: list[tuple[str, Image.Image]]) -> None:
    """layers: [(名称, 图像)]，自下而上排列。图层名须为 ASCII（PSD 规范限制）。"""
    from psd_tools import PSDImage
    from psd_tools.api.layers import PixelLayer
    w, h = layers[0][1].size
    psd = PSDImage.new("RGB", (w, h))
    for name, img in layers:
        psd.append(PixelLayer.frompil(img, psd, name, 0, 0))
    psd.save(path)


def run_character_split(manager, image: Image.Image, fill_background: bool = True,
                        margin: int = 16):
    """执行角色素材拆分。

    返回 (角色预览RGBA, 背景预览, PSD路径, ZIP路径, 性能信息)。
    """
    if image is None:
        raise ValueError("请先上传角色图片。")
    image = image.convert("RGB")

    reset_peak_memory()
    with Timer() as t:
        rgba, alpha = remove_bg(manager, image)

        # 背景层：可选 AI 补全（抹除角色后的完整背景）
        if fill_background:
            from .remove import run_remove
            bg_mask = alpha.filter(ImageFilter.MaxFilter(15))  # 略微扩张确保覆盖边缘
            background, _ = run_remove(manager, image, bg_mask)
        else:
            background = image.copy()

    character = _crop_to_content(rgba, margin=int(margin))

    # 导出文件
    out_dir = tempfile.mkdtemp(prefix="chara_split_")
    chara_png = os.path.join(out_dir, "character_rgba.png")
    bg_png = os.path.join(out_dir, "background.png")
    psd_path = os.path.join(out_dir, "character_layers.psd")
    zip_path = os.path.join(out_dir, "character_assets.zip")

    character.save(chara_png)
    background.save(bg_png)
    files = [chara_png, bg_png]
    try:
        _write_psd(psd_path, [("Background", background), ("Character_RGBA", rgba)])
        files.append(psd_path)
    except ImportError:
        psd_path = None  # psd-tools 未安装时仅导出 PNG
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, os.path.basename(f))

    info = {
        "耗时": f"{t.elapsed:.2f} s",
        "峰值显存": f"{peak_memory_gb():.2f} GB" if manager.info.device.type == "cuda" else "CPU 推理",
        "角色素材尺寸": f"{character.width}×{character.height}",
        "PSD 导出": "成功" if psd_path else "跳过（未安装 psd-tools）",
        "背景补全": "AI 填充" if fill_background else "关闭",
    }
    return character, background, psd_path, zip_path, info
