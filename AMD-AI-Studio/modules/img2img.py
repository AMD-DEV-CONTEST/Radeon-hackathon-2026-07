"""
图生图模块 - Image-to-Image
支持 SDXL img2img pipeline
"""

import logging
from typing import Optional, List

import torch
from PIL import Image
from diffusers import StableDiffusionXLImg2ImgPipeline, AutoencoderKL

from .rocm_utils import get_optimal_device, clear_gpu_cache
from .pipeline_cache import global_cache
from configs.default_config import DEFAULT_MODEL_CONFIG

logger = logging.getLogger(__name__)


def load_img2img_pipeline(
    model_id: str = None,
    use_fp16: bool = True,
) -> StableDiffusionXLImg2ImgPipeline:
    """加载图生图 pipeline"""
    model_id = model_id or DEFAULT_MODEL_CONFIG.txt2img_model_id
    cache_key = f"img2img:{model_id}"

    cached = global_cache.get(cache_key)
    if cached is not None:
        logger.info(f"使用缓存的图生图 pipeline: {model_id}")
        return cached

    logger.info(f"正在加载图生图模型: {model_id}")
    device = get_optimal_device()
    torch_dtype = torch.float16 if use_fp16 and device == "cuda" else torch.float32

    pipe = StableDiffusionXLImg2ImgPipeline.from_pretrained(
        model_id,
        torch_dtype=torch_dtype,
        variant="fp16" if use_fp16 else None,
        use_safetensors=True,
    )

    # 加载 VAE fp16 fix
    vae_id = DEFAULT_MODEL_CONFIG.txt2img_vae_id
    if vae_id:
        try:
            vae = AutoencoderKL.from_pretrained(
                vae_id, torch_dtype=torch_dtype
            )
            pipe.vae = vae
        except Exception:
            pass

    if DEFAULT_MODEL_CONFIG.enable_attention_slicing:
        pipe.enable_attention_slicing()
    if DEFAULT_MODEL_CONFIG.enable_vae_tiling:
        pipe.enable_vae_tiling()
    if DEFAULT_MODEL_CONFIG.enable_sequential_cpu_offload:
        pipe.enable_sequential_cpu_offload()
    else:
        pipe.to(device)

    global_cache.set(cache_key, pipe)
    logger.info(f"图生图模型加载完成，设备: {device}")
    return pipe


def generate_img2img(
    init_image: Image.Image,
    prompt: str,
    negative_prompt: Optional[str] = None,
    strength: float = 0.7,
    num_inference_steps: int = None,
    guidance_scale: float = None,
    seed: Optional[int] = None,
) -> Image.Image:
    """基于输入图像生成新图像"""
    cfg = DEFAULT_MODEL_CONFIG
    num_inference_steps = num_inference_steps or cfg.default_steps
    guidance_scale = guidance_scale or cfg.default_guidance_scale
    negative_prompt = negative_prompt or cfg.default_negative_prompt

    pipe = load_img2img_pipeline()

    # 预处理输入图像
    init_image = init_image.convert("RGB")
    init_width, init_height = init_image.size
    # 调整为 8 的倍数
    init_width = (init_width // 8) * 8
    init_height = (init_height // 8) * 8
    init_image = init_image.resize((init_width, init_height))

    # 随机种子
    generator = None
    if seed is not None:
        generator = torch.Generator(device="cpu").manual_seed(seed)

    logger.info(f"图生图: prompt='{prompt[:50]}...', strength={strength}, "
                f"steps={num_inference_steps}")

    with torch.no_grad():
        result = pipe(
            prompt=prompt,
            image=init_image,
            strength=strength,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            negative_prompt=negative_prompt,
            generator=generator,
        ).images[0]

    clear_gpu_cache()
    return result


def generate_style_transfer(
    init_image: Image.Image,
    style_prompt: str,
    strength: float = 0.6,
) -> Image.Image:
    """风格迁移快捷方式"""
    prompt = f"{style_prompt}, high quality, masterpiece, trending on artstation"
    return generate_img2img(
        init_image=init_image,
        prompt=prompt,
        strength=strength,
    )
