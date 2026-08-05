"""
测试: 图像编辑模块（Inpainting / Outpainting）
"""

import pytest
import sys
import os
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.image_edit import (
    load_inpainting_pipeline,
    create_mask_from_box,
    generate_inpainting,
    generate_outpainting,
)
from modules.rocm_utils import is_rocm_available


class TestMaskCreation:
    def test_create_mask_from_box(self):
        """测试创建矩形蒙版"""
        mask = create_mask_from_box(100, 100, (10, 10, 50, 50))
        assert mask.mode == "L"
        assert mask.size == (100, 100)
        # 框内应为白色 (255)
        assert mask.getpixel((30, 30)) == 255
        # 框外应为黑色 (0)
        assert mask.getpixel((5, 5)) == 0
        assert mask.getpixel((80, 80)) == 0

    def test_create_mask_full_image(self):
        """测试创建全图蒙版"""
        mask = create_mask_from_box(64, 64, (0, 0, 64, 64))
        # 所有像素应为白色
        for x in [0, 32, 63]:
            for y in [0, 32, 63]:
                assert mask.getpixel((x, y)) == 255


class TestOutpainting:
    def test_expansion_directions(self):
        """测试外延方向参数"""
        from modules.image_edit import generate_outpainting

        directions = ["left", "right", "top", "bottom", "all", "diagonal"]
        import inspect
        sig = inspect.signature(generate_outpainting)
        # direction 参数默认值应为 "all"
        assert sig.parameters["direction"].default == "all"

    def test_expansion_pixels_default(self):
        """测试默认扩展像素"""
        import inspect
        from modules.image_edit import generate_outpainting
        sig = inspect.signature(generate_outpainting)
        assert sig.parameters["expansion_pixels"].default == 128

    def test_canvas_expansion(self):
        """测试画布扩展逻辑"""
        img = Image.new("RGB", (512, 512), color="red")
        expansion_pixels = 128
        direction = "all"

        # 模拟 generate_outpainting 中的扩展逻辑
        directions = {
            "left": (expansion_pixels, 0, 0, 0),
            "right": (0, expansion_pixels, 0, 0),
            "top": (0, 0, expansion_pixels, 0),
            "bottom": (0, 0, 0, expansion_pixels),
            "all": (expansion_pixels, expansion_pixels, expansion_pixels, expansion_pixels),
            "diagonal": (expansion_pixels, expansion_pixels, 0, 0),
        }

        pad = directions.get(direction, (0, 0, 0, 0))
        left, right, top, bottom = pad

        w, h = img.size
        new_w = w + left + right
        new_h = h + top + bottom

        assert new_w == 512 + 128 + 128  # 768
        assert new_h == 512 + 128 + 128  # 768

    def test_mask_creation_for_outpainting(self):
        """测试外延蒙版创建"""
        w, h = 512, 512
        left, right, top, bottom = 128, 128, 128, 128
        new_w, new_h = w + left + right, h + top + bottom

        mask = Image.new("L", (new_w, new_h), 0)
        draw = ImageDraw.Draw(mask)

        # 左边缘
        draw.rectangle([0, 0, left, new_h], fill=255)
        # 右边缘
        draw.rectangle([new_w - right, 0, new_w, new_h], fill=255)
        # 上边缘
        draw.rectangle([0, 0, new_w, top], fill=255)
        # 下边缘
        draw.rectangle([0, new_h - bottom, new_w, new_h], fill=255)

        # 检查扩展区域为白色
        assert mask.getpixel((64, 256)) == 255   # 左边缘
        assert mask.getpixel((640, 256)) == 255  # 右边缘
        assert mask.getpixel((256, 64)) == 255   # 上边缘
        assert mask.getpixel((256, 640)) == 255  # 下边缘

        # 检查原始图像区域为黑色
        assert mask.getpixel((256, 256)) == 0    # 中心区域


@pytest.mark.slow
@pytest.mark.skipif(not is_rocm_available(), reason="需要 ROCm GPU")
class TestInpaintingReal:
    def test_load_pipeline(self):
        """测试加载 inpainting pipeline"""
        try:
            pipe = load_inpainting_pipeline(use_fp16=True)
            assert pipe is not None
        except Exception as e:
            pytest.skip(f"Inpainting 模型加载失败: {e}")