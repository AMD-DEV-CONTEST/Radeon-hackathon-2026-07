"""
图像编辑模块 - Inpainting / Outpainting / 局部重绘
"""

import logging
from typing import Optional
from pathlib import Path

import torch
import numpy as np
from PIL import Image, ImageDraw
from diffusers import StableDiffusionXLInpaintPipeline, AutoencoderKL

from .rocm_utils import get_optimal_device, clear_gpu_cache
from .pipeline_cache import global_cache
from configs.default_config import DEFAULT_MODEL_CONFIG

logger = logging.getLogger(__name__)


def load_inpainting_pipeline(
    model_id: str = None,
    use_fp16: bool = True,
) -> StableDiffusionXLInpaintPipeline:
    """加载图像修复 pipeline"""
    model_id = model_id or DEFAULT_MODEL_CONFIG.inpainting_model_id
    cache_key = f"inpainting:{model_id}"

    cached = global_cache.get(cache_key)
    if cached is not None:
        logger.info(f"使用缓存的修复 pipeline: {model_id}")
        return cached

    logger.info(f"正在加载图像修复模型: {model_id}")
    device = get_optimal_device()
    torch_dtype = torch.float16 if use_fp16 and device == "cuda" else torch.float32

    pipe = StableDiffusionXLInpaintPipeline.from_pretrained(
        model_id,
        torch_dtype=torch_dtype,
        variant="fp16" if use_fp16 else None,
        use_safetensors=True,
    )

    # VAE fp16 fix
    vae_id = DEFAULT_MODEL_CONFIG.txt2img_vae_id
    if vae_id:
        try:
            vae = AutoencoderKL.from_pretrained(
                vae_id, torch_dtype=torch_dtype
            )
            pipe.vae = vae
        except Exception:
            pass

    pipe.enable_attention_slicing()
    pipe.enable_vae_tiling()
    if DEFAULT_MODEL_CONFIG.enable_sequential_cpu_offload:
        pipe.enable_sequential_cpu_offload()
    else:
        pipe.to(device)

    global_cache.set(cache_key, pipe)
    logger.info(f"图像修复模型加载完成，设备: {device}")
    return pipe


def create_mask_from_box(
    width: int,
    height: int,
    box: tuple,
) -> Image.Image:
    """
    根据矩形框创建蒙版
    box: (x1, y1, x2, y2)
    """
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    draw.rectangle(box, fill=255)
    return mask


def generate_inpainting(
    init_image: Image.Image,
    mask_image: Image.Image,
    prompt: str,
    negative_prompt: Optional[str] = None,
    num_inference_steps: int = None,
    guidance_scale: float = None,
    strength: float = 0.85,
    seed: Optional[int] = None,
) -> Image.Image:
    """
    图像修复（局部重绘）
    mask_image: 白色区域为需要重新生成的区域
    """
    cfg = DEFAULT_MODEL_CONFIG
    num_inference_steps = num_inference_steps or cfg.default_steps
    guidance_scale = guidance_scale or cfg.default_guidance_scale
    negative_prompt = negative_prompt or cfg.default_negative_prompt

    pipe = load_inpainting_pipeline()

    # 预处理
    init_image = init_image.convert("RGB")
    mask_image = mask_image.convert("L")

    # 调整为 8 的倍数
    w, h = init_image.size
    w = (w // 8) * 8
    h = (h // 8) * 8
    init_image = init_image.resize((w, h))
    mask_image = mask_image.resize((w, h))

    # 确保 mask 是二值图
    mask_image = mask_image.point(lambda x: 255 if x > 128 else 0)

    generator = None
    if seed is not None:
        generator = torch.Generator(device="cpu").manual_seed(seed)

    logger.info(f"图像修复: prompt='{prompt[:50]}...', strength={strength}")

    with torch.no_grad():
        result = pipe(
            prompt=prompt,
            image=init_image,
            mask_image=mask_image,
            strength=strength,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            negative_prompt=negative_prompt,
            generator=generator,
        ).images[0]

    clear_gpu_cache()
    return result


def generate_outpainting(
    init_image: Image.Image,
    prompt: str,
    expansion_pixels: int = 128,
    direction: str = "all",
    num_inference_steps: int = None,
    seed: Optional[int] = None,
) -> Image.Image:
    """
    图像外延补全（Outpainting）
    direction: "left", "right", "top", "bottom", "all", "diagonal"
    """
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

    # 扩展画布
    w, h = init_image.size
    new_w = w + left + right
    new_h = h + top + bottom

    new_image = Image.new("RGB", (new_w, new_h), (128, 128, 128))
    new_image.paste(init_image, (left, top))

    # 创建蒙版（扩展区域为白色）
    mask = Image.new("L", (new_w, new_h), 0)
    draw = ImageDraw.Draw(mask)

    if left > 0:
        draw.rectangle([0, 0, left, new_h], fill=255)
    if right > 0:
        draw.rectangle([new_w - right, 0, new_w, new_h], fill=255)
    if top > 0:
        draw.rectangle([0, 0, new_w, top], fill=255)
    if bottom > 0:
        draw.rectangle([0, new_h - bottom, new_w, new_h], fill=255)

    return generate_inpainting(
        init_image=new_image,
        mask_image=mask,
        prompt=prompt,
        num_inference_steps=num_inference_steps,
        seed=seed,
    )
