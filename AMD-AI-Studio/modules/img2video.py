"""
图生视频模块 - Image-to-Video with Stable Video Diffusion
"""

import logging
import tempfile
from typing import Optional
from pathlib import Path

import torch
import numpy as np
from PIL import Image
from diffusers import StableVideoDiffusionPipeline
from diffusers.utils import export_to_video

from .rocm_utils import get_optimal_device, clear_gpu_cache
from .pipeline_cache import global_cache
from configs.default_config import DEFAULT_MODEL_CONFIG

logger = logging.getLogger(__name__)


def load_svd_pipeline(
    model_id: str = None,
    use_fp16: bool = True,
) -> StableVideoDiffusionPipeline:
    """加载 Stable Video Diffusion pipeline"""
    model_id = model_id or DEFAULT_MODEL_CONFIG.img2video_model_id
    cache_key = f"img2video:{model_id}"

    cached = global_cache.get(cache_key)
    if cached is not None:
        logger.info(f"使用缓存的图生视频 pipeline: {model_id}")
        return cached

    logger.info(f"正在加载图生视频模型: {model_id}")
    device = get_optimal_device()
    torch_dtype = torch.float16 if use_fp16 and device == "cuda" else torch.float32

    pipe = StableVideoDiffusionPipeline.from_pretrained(
        model_id,
        torch_dtype=torch_dtype,
        variant="fp16" if use_fp16 else None,
        use_safetensors=True,
    )

    # 内存优化
    pipe.enable_attention_slicing()
    if DEFAULT_MODEL_CONFIG.enable_sequential_cpu_offload:
        pipe.enable_sequential_cpu_offload()
    elif device == "cuda":
        pipe.enable_model_cpu_offload()
    else:
        pipe.to(device)

    global_cache.set(cache_key, pipe)
    logger.info(f"图生视频模型加载完成，设备: {device}")
    return pipe


def generate_img2video(
    init_image: Image.Image,
    num_frames: int = 14,
    num_inference_steps: int = 25,
    decode_chunk_size: int = 8,
    fps: int = 7,
    seed: Optional[int] = None,
    output_path: Optional[str] = None,
) -> str:
    """
    从输入图像生成视频
    返回视频文件路径
    """
    pipe = load_svd_pipeline()

    # 预处理 - SVD 需要 1024x576 输入
    init_image = init_image.convert("RGB")
    target_w, target_h = 1024, 576
    init_image = init_image.resize((target_w, target_h), Image.LANCZOS)

    # 随机种子
    generator = None
    if seed is not None:
        generator = torch.Generator(device="cpu").manual_seed(seed)
    else:
        generator = torch.Generator(device="cpu").manual_seed(42)

    logger.info(f"图生视频: frames={num_frames}, steps={num_inference_steps}, fps={fps}")

    with torch.no_grad():
        frames = pipe(
            image=init_image,
            num_frames=num_frames,
            num_inference_steps=num_inference_steps,
            decode_chunk_size=decode_chunk_size,
            generator=generator,
        ).frames[0]

    # 导出视频
    if output_path is None:
        output_dir = Path("outputs/videos")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(output_dir / "svd_output.mp4")

    export_to_video(frames, output_path, fps=fps)
    logger.info(f"视频已保存: {output_path}")

    clear_gpu_cache()
    return output_path


def generate_img2video_gif(
    init_image: Image.Image,
    num_frames: int = 14,
    num_inference_steps: int = 25,
    fps: int = 7,
    seed: Optional[int] = None,
    output_path: Optional[str] = None,
) -> str:
    """
    从输入图像生成 GIF
    返回 GIF 文件路径
    """
    pipe = load_svd_pipeline()

    init_image = init_image.convert("RGB")
    init_image = init_image.resize((1024, 576), Image.LANCZOS)

    generator = torch.Generator(device="cpu").manual_seed(seed or 42)

    with torch.no_grad():
        frames = pipe(
            image=init_image,
            num_frames=num_frames,
            num_inference_steps=num_inference_steps,
            decode_chunk_size=8,
            generator=generator,
        ).frames[0]

    # 转为 PIL 列表并保存 GIF
    pil_frames = [Image.fromarray(f) for f in frames]

    if output_path is None:
        output_dir = Path("outputs/gifs")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(output_dir / "svd_output.gif")

    duration = int(1000 / fps)
    pil_frames[0].save(
        output_path,
        save_all=True,
        append_images=pil_frames[1:],
        duration=duration,
        loop=0,
    )
    logger.info(f"GIF 已保存: {output_path}")

    clear_gpu_cache()
    return output_path
