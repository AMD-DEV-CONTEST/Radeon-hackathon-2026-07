# -*- coding: utf-8 -*-
"""Textovid - Image generation engine (SDXL with High-Res Fix)"""

import torch
from diffusers import StableDiffusionXLPipeline
from config import (
    SDXL_BASE, IMG_WIDTH, IMG_HEIGHT, HIGHRES_SCALE,
    NUM_INFERENCE_STEPS, GUIDANCE_SCALE, MODEL_CACHE,
)
from gpu_utils import get_gpu_info

_pipe = None

def _load_pipeline():
    global _pipe
    if _pipe is not None:
        return _pipe
    info = get_gpu_info()
    print(f"[image_engine] GPU: {info['name']}  VRAM free: {info['vram_free_gb']} GB")
    print("[image_engine] Loading SDXL base pipeline ...")
    _pipe = StableDiffusionXLPipeline.from_pretrained(
        SDXL_BASE, torch_dtype=torch.float16, variant="fp16",
        cache_dir=MODEL_CACHE,
    ).to("cuda")
    _pipe.enable_attention_slicing()
    return _pipe

def generate_panel_image(prompt, negative_prompt="blurry, low quality, watermark, text, logo", seed=-1):
    base = _load_pipeline()
    generator = torch.Generator("cuda").manual_seed(
        seed if seed >= 0 else torch.randint(0, 2**32, (1,)).item())
    hi_w = int(IMG_WIDTH * HIGHRES_SCALE)
    hi_h = int(IMG_HEIGHT * HIGHRES_SCALE)
    image = base(
        prompt=prompt, negative_prompt=negative_prompt,
        num_inference_steps=NUM_INFERENCE_STEPS,
        guidance_scale=GUIDANCE_SCALE,
        width=hi_w, height=hi_h, generator=generator,
    ).images[0]
    return image, generator.initial_seed()