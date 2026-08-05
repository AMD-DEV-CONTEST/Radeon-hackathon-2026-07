"""
文生图模块 - Text-to-Image with SDXL
支持 SDXL base + refiner 两阶段生成
"""

import logging
from typing import Optional, List, Tuple
from pathlib import Path

import torch
import numpy as np
from PIL import Image
from diffusers import StableDiffusionXLPipeline, StableDiffusionXLImg2ImgPipeline

from .rocm_utils import get_optimal_device, optimize_memory, clear_gpu_cache
from .pipeline_cache import global_cache
from configs.default_config import DEFAULT_MODEL_CONFIG

logger = logging.getLogger(__name__)


def load_txt2img_pipeline(
    model_id: str = None,
    use_fp16: bool = True,
    enable_optimizations: bool = True,
) -> StableDiffusionXLPipeline:
    """加载文生图 pipeline"""
    model_id = model_id or DEFAULT_MODEL_CONFIG.txt2img_model_id
    cache_key = f"txt2img:{model_id}"

    cached = global_cache.get(cache_key)
    if cached is not None:
        logger.info(f"使用缓存的文生图 pipeline: {model_id}")
        return cached

    logger.info(f"正在加载文生图模型: {model_id}")
    device = get_optimal_device()
    torch_dtype = torch.float16 if use_fp16 and device == "cuda" else torch.float32

    # 加载 base pipeline
    pipe = StableDiffusionXLPipeline.from_pretrained(
        model_id,
        torch_dtype=torch_dtype,
        variant="fp16" if use_fp16 else None,
        use_safetensors=True,
    )

    # 加载 VAE（fp16 fix）
    vae_id = DEFAULT_MODEL_CONFIG.txt2img_vae_id
    if vae_id:
        try:
            from diffusers import AutoencoderKL
            vae = AutoencoderKL.from_pretrained(
                vae_id, torch_dtype=torch_dtype
            )
            pipe.vae = vae
            logger.info(f"已加载 VAE: {vae_id}")
        except Exception as e:
            logger.warning(f"VAE 加载失败，使用默认 VAE: {e}")

    # 应用优化
    if enable_optimizations and device == "cuda":
        if DEFAULT_MODEL_CONFIG.enable_attention_slicing:
            pipe.enable_attention_slicing()
        if DEFAULT_MODEL_CONFIG.enable_vae_tiling:
            pipe.enable_vae_tiling()
        if DEFAULT_MODEL_CONFIG.enable_sequential_cpu_offload:
            pipe.enable_sequential_cpu_offload()
        else:
            pipe.to(device)
    else:
        pipe.to(device)

    global_cache.set(cache_key, pipe)
    logger.info(f"文生图模型加载完成，设备: {device}")
    return pipe


def generate_txt2img(
    prompt: str,
    negative_prompt: Optional[str] = None,
    width: int = None,
    height: int = None,
    num_inference_steps: int = None,
    guidance_scale: float = None,
    num_images: int = 1,
    seed: Optional[int] = None,
    use_refiner: bool = False,
    refiner_steps: int = 10,
) -> List[Image.Image]:
    """生成图像"""
    cfg = DEFAULT_MODEL_CONFIG
    width = width or cfg.default_width
    height = height or cfg.default_height
    num_inference_steps = num_inference_steps or cfg.default_steps
    guidance_scale = guidance_scale or cfg.default_guidance_scale
    negative_prompt = negative_prompt or cfg.default_negative_prompt

    # 确保尺寸是 8 的倍数
    width = (width // 8) * 8
    height = (height // 8) * 8
    width = max(512, min(width, cfg.default_width))
    height = max(512, min(height, cfg.default_height))

    pipe = load_txt2img_pipeline()

    # 设置随机种子
    generator = None
    if seed is not None:
        generator = torch.Generator(device="cpu").manual_seed(seed)

    # 生成参数
    gen_kwargs = {
        "prompt": [prompt] * num_images,
        "negative_prompt": [negative_prompt] * num_images,
        "width": width,
        "height": height,
        "num_inference_steps": num_inference_steps,
        "guidance_scale": guidance_scale,
        "num_images_per_prompt": 1,
    }
    if generator is not None:
        gen_kwargs["generator"] = generator

    logger.info(f"生成参数: prompt='{prompt[:50]}...', size={width}x{height}, "
                f"steps={num_inference_steps}, guidance={guidance_scale}")

    # 执行生成
    with torch.no_grad():
        images = pipe(**gen_kwargs).images

    # Refiner 增强
    if use_refiner and DEFAULT_MODEL_CONFIG.txt2img_refiner_id:
        try:
            refiner = StableDiffusionXLImg2ImgPipeline.from_pretrained(
                DEFAULT_MODEL_CONFIG.txt2img_refiner_id,
                torch_dtype=torch.float16,
                variant="fp16",
                use_safetensors=True,
            )
            refiner.to(pipe.device)
            refiner.enable_attention_slicing()

            refined_images = []
            for img in images:
                img_resized = img.resize((width, height))
                refined = refiner(
                    prompt=prompt,
                    image=img_resized,
                    num_inference_steps=refiner_steps,
                    strength=0.3,
                    guidance_scale=guidance_scale,
                ).images[0]
                refined_images.append(refined)
            images = refined_images
        except Exception as e:
            logger.warning(f"Refiner 处理失败，使用基础输出: {e}")

    clear_gpu_cache()
    return images


def generate_txt2img_batch(
    prompt: str,
    negative_prompt: Optional[str] = None,
    width: int = None,
    height: int = None,
    num_inference_steps: int = None,
    guidance_scale: float = None,
    batch_size: int = 4,
) -> List[Image.Image]:
    """批量生成多张图像"""
    all_images = []
    for i in range(batch_size):
        seed = torch.randint(0, 2**32, (1,)).item() if i > 0 else 42
        images = generate_txt2img(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            num_images=1,
            seed=seed,
        )
        all_images.extend(images)
    return all_images
