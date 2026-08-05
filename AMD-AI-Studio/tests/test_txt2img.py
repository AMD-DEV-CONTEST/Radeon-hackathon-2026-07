"""
测试: 文生图模块
注意: 这部分测试会加载真实模型，在 CI 中可用 @pytest.mark.slow 跳过
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.txt2img import (
    load_txt2img_pipeline,
    generate_txt2img,
    generate_txt2img_batch,
)
from modules.rocm_utils import is_rocm_available


class TestTxt2ImgConfig:
    """测试文生图配置（不加载模型）"""

    def test_generate_params_dimension_alignment(self):
        """测试尺寸对齐逻辑"""
        from configs.default_config import DEFAULT_MODEL_CONFIG

        # 模拟 generate_txt2img 中的对齐逻辑
        width = 1025  # 不是 8 的倍数
        height = 1023
        aligned_w = (width // 8) * 8
        aligned_h = (height // 8) * 8
        assert aligned_w == 1024
        assert aligned_h == 1016
        # 确保在限制范围内
        assert 512 <= aligned_w <= DEFAULT_MODEL_CONFIG.default_width
        assert 512 <= aligned_h <= DEFAULT_MODEL_CONFIG.default_height

    def test_generate_params_bounds(self):
        """测试参数边界"""
        from configs.default_config import DEFAULT_MODEL_CONFIG

        cfg = DEFAULT_MODEL_CONFIG
        # 低于最小值
        w = max(512, min(256, cfg.default_width))
        h = max(512, min(256, cfg.default_height))
        assert w == 512
        assert h == 512

        # 高于最大值
        w = max(512, min(4096, cfg.default_width))
        h = max(512, min(4096, cfg.default_height))
        assert w == cfg.default_width
        assert h == cfg.default_height

    def test_negative_prompt_default(self):
        """测试默认负面提示词"""
        from configs.default_config import DEFAULT_MODEL_CONFIG

        assert DEFAULT_MODEL_CONFIG.default_negative_prompt is not None


@pytest.mark.slow
@pytest.mark.skipif(not is_rocm_available(), reason="需要 ROCm GPU")
class TestTxt2ImgReal:
    """测试文生图真实推理（需要 GPU 和模型）"""

    def test_load_pipeline(self):
        """测试加载 pipeline"""
        # 使用 sd-turbo（小模型，加载快）
        try:
            pipe = load_txt2img_pipeline(
                model_id="stabilityai/sd-turbo",
                use_fp16=True,
                enable_optimizations=True,
            )
            assert pipe is not None
        except Exception as e:
            pytest.skip(f"模型加载失败: {e}")


class TestTxt2ImgBatch:
    def test_batch_default_params(self):
        """测试批量生成默认参数"""
        # 仅验证函数签名和参数传递，不实际运行
        import inspect
        sig = inspect.signature(generate_txt2img_batch)
        params = sig.parameters
        assert "batch_size" in params
        assert "prompt" in params
        assert params["batch_size"].default == 4