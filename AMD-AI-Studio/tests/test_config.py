"""
测试: 默认配置模块
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from configs.default_config import ModelConfig, AppConfig, DEFAULT_MODEL_CONFIG, DEFAULT_APP_CONFIG


class TestModelConfig:
    def test_default_values(self):
        """测试默认配置值"""
        cfg = ModelConfig()
        assert cfg.default_width == 1024
        assert cfg.default_height == 1024
        assert cfg.default_steps == 30
        assert cfg.default_guidance_scale == 7.5
        assert cfg.use_fp16 is True
        assert cfg.enable_attention_slicing is True
        assert cfg.enable_vae_tiling is True
        assert cfg.enable_sequential_cpu_offload is True

    def test_txt2img_model_ids(self):
        """测试文生图模型 ID 配置"""
        cfg = ModelConfig()
        assert "stable-diffusion-xl-base-1.0" in cfg.txt2img_model_id
        assert cfg.txt2img_refiner_id is not None
        assert "sdxl-vae-fp16-fix" in cfg.txt2img_vae_id

    def test_img2video_model_id(self):
        """测试图生视频模型 ID"""
        cfg = ModelConfig()
        assert "stable-video-diffusion-img2vid-xt" in cfg.img2video_model_id

    def test_inpainting_model_id(self):
        """测试图像修复模型 ID"""
        cfg = ModelConfig()
        assert "inpainting" in cfg.inpainting_model_id

    def test_negative_prompt(self):
        """测试默认负面提示词"""
        cfg = ModelConfig()
        assert "blurry" in cfg.default_negative_prompt
        assert "low quality" in cfg.default_negative_prompt

    def test_vram_warning_threshold(self):
        """测试显存警告阈值"""
        cfg = ModelConfig()
        assert cfg.vram_warning_threshold_gb == 8.0

    def test_custom_config(self):
        """测试自定义配置覆盖"""
        cfg = ModelConfig(
            default_width=512,
            default_height=512,
            default_steps=20,
            use_fp16=False,
            enable_attention_slicing=False,
        )
        assert cfg.default_width == 512
        assert cfg.default_height == 512
        assert cfg.default_steps == 20
        assert cfg.use_fp16 is False
        assert cfg.enable_attention_slicing is False

    def test_singleton_default_config(self):
        """测试全局默认配置单例"""
        assert DEFAULT_MODEL_CONFIG is not None
        assert isinstance(DEFAULT_MODEL_CONFIG, ModelConfig)


class TestAppConfig:
    def test_default_values(self):
        """测试应用默认配置"""
        cfg = AppConfig()
        assert cfg.server_name == "0.0.0.0"
        assert cfg.server_port == 7860
        assert cfg.share is False
        assert cfg.debug is False
        assert cfg.output_dir == "outputs"
        assert cfg.max_image_size == 2048

    def test_custom_app_config(self):
        """测试自定义应用配置"""
        cfg = AppConfig(server_port=8080, debug=True, share=True)
        assert cfg.server_port == 8080
        assert cfg.debug is True
        assert cfg.share is True

    def test_singleton_default_app_config(self):
        """测试全局应用配置单例"""
        assert DEFAULT_APP_CONFIG is not None
        assert isinstance(DEFAULT_APP_CONFIG, AppConfig)