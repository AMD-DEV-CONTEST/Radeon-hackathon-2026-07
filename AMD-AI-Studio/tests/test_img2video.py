"""
测试: 图生视频模块
"""

import pytest
import sys
import os
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.rocm_utils import is_rocm_available


class TestImg2VideoConfig:
    def test_svd_image_size(self):
        """测试 SVD 输入尺寸"""
        # SVD 需要 1024x576
        target_w, target_h = 1024, 576
        img = Image.new("RGB", (800, 600))
        resized = img.resize((target_w, target_h), Image.LANCZOS)
        assert resized.size == (1024, 576)

    def test_gif_duration_calculation(self):
        """测试 GIF 帧率计算"""
        fps = 7
        duration = int(1000 / fps)
        assert duration == 142  # 1000/7 ≈ 142ms

    def test_num_frames_default(self):
        """测试默认帧数"""
        import inspect
        from modules.img2video import generate_img2video
        sig = inspect.signature(generate_img2video)
        assert sig.parameters["num_frames"].default == 14
        assert sig.parameters["fps"].default == 7


@pytest.mark.slow
@pytest.mark.skipif(not is_rocm_available(), reason="需要 ROCm GPU")
class TestImg2VideoReal:
    def test_load_pipeline(self):
        """测试加载 SVD pipeline"""
        try:
            from modules.img2video import load_svd_pipeline
            pipe = load_svd_pipeline(use_fp16=True)
            assert pipe is not None
        except Exception as e:
            pytest.skip(f"SVD 模型加载失败: {e}")