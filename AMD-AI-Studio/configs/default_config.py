"""
AMD AI Studio 默认配置
"""

from dataclasses import dataclass, field
from typing import Optional, Dict


@dataclass
class ModelConfig:
    """模型配置"""
    # === 文生图模型 ===
    txt2img_model_id: str = "stabilityai/stable-diffusion-xl-base-1.0"
    txt2img_refiner_id: Optional[str] = "stabilityai/stable-diffusion-xl-refiner-1.0"
    txt2img_vae_id: Optional[str] = "madebyollin/sdxl-vae-fp16-fix"

    # === 图生视频模型 ===
    img2video_model_id: str = "stabilityai/stable-video-diffusion-img2vid-xt"

    # === 图像修复模型 ===
    inpainting_model_id: str = "diffusers/stable-diffusion-xl-1.0-inpainting-0.1"

    # === 推理参数默认值 ===
    default_width: int = 1024
    default_height: int = 1024
    default_steps: int = 30
    default_guidance_scale: float = 7.5
    default_negative_prompt: str = "blurry, low quality, distorted, ugly, bad anatomy"

    # === 性能优化 ===
    enable_model_cpu_offload: bool = False
    enable_sequential_cpu_offload: bool = True
    enable_attention_slicing: bool = True
    enable_vae_tiling: bool = True
    use_fp16: bool = True

    # === 显存限制（GB），超过时自动启用优化 ===
    vram_warning_threshold_gb: float = 8.0


@dataclass
class AppConfig:
    """应用配置"""
    server_name: str = "0.0.0.0"
    server_port: int = 7860
    share: bool = False
    debug: bool = False
    output_dir: str = "outputs"
    max_image_size: int = 2048


DEFAULT_MODEL_CONFIG = ModelConfig()
DEFAULT_APP_CONFIG = AppConfig()
