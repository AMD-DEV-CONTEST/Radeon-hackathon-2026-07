# -*- coding: utf-8 -*-
"""全局配置：所有参数均可通过环境变量覆盖（前缀 AISTUDIO_）。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except ValueError:
        return default


@dataclass
class Settings:
    """运行配置。环境变量优先级高于默认值。

    常用环境变量：
        AISTUDIO_DEVICE          cuda / cpu（默认自动检测，ROCm 下 PyTorch 映射为 cuda）
        AISTUDIO_DTYPE           fp16 / bf16 / fp32（默认 GPU=fp16, CPU=fp32）
        AISTUDIO_LOW_VRAM        1 开启低显存模式（模型用完即卸 + CPU offload）
        AISTUDIO_MAX_DIFFUSION   扩散模型最长边工作分辨率（默认 768）
        AISTUDIO_MODEL_DIR       本地权重目录（默认 ./models）
        AISTUDIO_ENABLE_STYLE    0 可关闭风格迁移（避免下载 SD1.5 底模）
        AISTUDIO_ENABLE_LAMA     0 可关闭 LaMa 物体移除
        AISTUDIO_ENABLE_BREF     0 可关闭 BiRefNet 背景移除
    """

    device: str = field(default_factory=lambda: os.environ.get("AISTUDIO_DEVICE", "auto"))
    dtype: str = field(default_factory=lambda: os.environ.get("AISTUDIO_DTYPE", "auto"))
    low_vram: bool = field(default_factory=lambda: _env_bool("AISTUDIO_LOW_VRAM", False))
    max_diffusion_size: int = field(default_factory=lambda: _env_int("AISTUDIO_MAX_DIFFUSION", 768))
    model_dir: str = field(default_factory=lambda: os.environ.get("AISTUDIO_MODEL_DIR", "./models"))

    # 模型 ID（可替换为本地路径或镜像站 ID）
    inpaint_model_id: str = field(default_factory=lambda: os.environ.get(
        "AISTUDIO_INPAINT_MODEL", "stable-diffusion-v1-5/stable-diffusion-inpainting"))
    img2img_model_id: str = field(default_factory=lambda: os.environ.get(
        "AISTUDIO_IMG2IMG_MODEL", "stable-diffusion-v1-5/stable-diffusion-v1-5"))
    birefnet_model_id: str = field(default_factory=lambda: os.environ.get(
        "AISTUDIO_BIREFNET_MODEL", "ZhengPeng7/BiRefNet"))

    enable_style: bool = field(default_factory=lambda: _env_bool("AISTUDIO_ENABLE_STYLE", True))
    enable_lama: bool = field(default_factory=lambda: _env_bool("AISTUDIO_ENABLE_LAMA", True))
    enable_birefnet: bool = field(default_factory=lambda: _env_bool("AISTUDIO_ENABLE_BREF", True))

    # LCM-LoRA 极速生成（25 步 → 4~8 步）
    enable_lcm: bool = field(default_factory=lambda: _env_bool("AISTUDIO_ENABLE_LCM", True))
    lcm_lora_id: str = field(default_factory=lambda: os.environ.get(
        "AISTUDIO_LCM_LORA", "latent-consistency/lcm-lora-sdv1-5"))
    lcm_steps: int = field(default_factory=lambda: _env_int("AISTUDIO_LCM_STEPS", 6))

    # 视频超分限制（防止超长任务）
    max_video_seconds: float = field(default_factory=lambda: float(os.environ.get("AISTUDIO_MAX_VIDEO_SECONDS", "30")))
    max_video_height: int = field(default_factory=lambda: _env_int("AISTUDIO_MAX_VIDEO_HEIGHT", 720))

    # 超分权重文件名（位于 model_dir 内，由 scripts/download_models.py 下载）
    esrgan_fast_weight: str = "RealESR_general_x4v3.pth"      # SRVGGNetCompact，轻量高速（默认）
    esrgan_hq_weight: str = "RealESRGAN_x4plus.pth"           # RRDBNet，高画质
    # 人像修复权重
    gfpgan_weight: str = "GFPGANv1.4.pth"                     # GFPGAN 修复网络
    yunet_weight: str = "face_detection_yunet_2023mar.onnx"   # YuNet 人脸检测

    # Gradio 服务
    server_name: str = field(default_factory=lambda: os.environ.get("AISTUDIO_HOST", "0.0.0.0"))
    server_port: int = field(default_factory=lambda: _env_int("AISTUDIO_PORT", 7860))
    share: bool = field(default_factory=lambda: _env_bool("AISTUDIO_SHARE", False))


settings = Settings()
