from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from PIL import (
    Image,
    ImageEnhance,
    ImageFilter,
    ImageOps,
)

from configs.config import OUTPUT_DIR


class ImageEnhancer:
    """
    Radeon AI Creative Studio 图片增强模块。

    当前版本使用稳定的本地图像处理方案：
    - 自动对比度
    - 亮度增强
    - 色彩增强
    - 锐度增强
    - Unsharp Mask 细节增强
    - 高质量尺寸放大
    """

    def __init__(self) -> None:
        OUTPUT_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

    @staticmethod
    def _validate_factor(
        value: float,
        name: str,
        minimum: float = 0.0,
        maximum: float = 3.0,
    ) -> float:
        value = float(value)

        if value < minimum or value > maximum:
            raise ValueError(
                f"{name}必须在 {minimum} 到 {maximum} 之间。"
            )

        return value

    @staticmethod
    def _parse_upscale_factor(
        upscale_factor: str | int | float,
    ) -> int:
        """
        支持传入：
        1
        2
        4
        "1×"
        "2×"
        "4×"
        """
        text = str(upscale_factor)
        text = text.replace("×", "")
        text = text.replace("x", "")
        text = text.strip()

        factor = int(float(text))

        if factor not in (1, 2, 4):
            raise ValueError(
                "放大倍数只支持 1×、2× 或 4×。"
            )

        return factor

    @staticmethod
    def _save_image(
        image: Image.Image,
    ) -> Path:
        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S_%f"
        )

        filename = (
            f"radeon_enhanced_{timestamp}.png"
        )

        save_path = OUTPUT_DIR / filename

        image.save(
            save_path,
            format="PNG",
            optimize=True,
        )

        return save_path

    def enhance(
        self,
        image: Image.Image,
        brightness: float = 1.0,
        contrast: float = 1.08,
        color: float = 1.05,
        sharpness: float = 1.25,
        upscale_factor: str | int | float = 1,
        auto_contrast: bool = True,
        detail_enhance: bool = True,
    ) -> dict:
        if image is None:
            raise ValueError("请先上传需要增强的图片。")

        brightness = self._validate_factor(
            brightness,
            "亮度",
        )

        contrast = self._validate_factor(
            contrast,
            "对比度",
        )

        color = self._validate_factor(
            color,
            "色彩强度",
        )

        sharpness = self._validate_factor(
            sharpness,
            "锐度",
        )

        scale = self._parse_upscale_factor(
            upscale_factor
        )

        start_time = time.perf_counter()

        original = image.convert("RGB")
        enhanced = original.copy()

        if auto_contrast:
            enhanced = ImageOps.autocontrast(
                enhanced,
                cutoff=1,
            )

        if brightness != 1.0:
            enhanced = ImageEnhance.Brightness(
                enhanced
            ).enhance(brightness)

        if contrast != 1.0:
            enhanced = ImageEnhance.Contrast(
                enhanced
            ).enhance(contrast)

        if color != 1.0:
            enhanced = ImageEnhance.Color(
                enhanced
            ).enhance(color)

        if sharpness != 1.0:
            enhanced = ImageEnhance.Sharpness(
                enhanced
            ).enhance(sharpness)

        if detail_enhance:
            enhanced = enhanced.filter(
                ImageFilter.UnsharpMask(
                    radius=1.5,
                    percent=125,
                    threshold=3,
                )
            )

        if scale > 1:
            target_width = enhanced.width * scale
            target_height = enhanced.height * scale

            enhanced = enhanced.resize(
                (
                    target_width,
                    target_height,
                ),
                Image.Resampling.LANCZOS,
            )

            # 放大后进行一次较轻的细节恢复。
            enhanced = enhanced.filter(
                ImageFilter.UnsharpMask(
                    radius=1.2,
                    percent=105,
                    threshold=3,
                )
            )

        elapsed = time.perf_counter() - start_time

        save_path = self._save_image(enhanced)

        return {
            "original": original,
            "image": enhanced,
            "path": str(save_path),
            "time": round(elapsed, 3),
            "original_width": original.width,
            "original_height": original.height,
            "width": enhanced.width,
            "height": enhanced.height,
            "scale": scale,
            "brightness": brightness,
            "contrast": contrast,
            "color": color,
            "sharpness": sharpness,
            "auto_contrast": bool(auto_contrast),
            "detail_enhance": bool(detail_enhance),
            "mode": "Image Enhancement",
        }
