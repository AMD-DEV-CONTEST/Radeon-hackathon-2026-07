"""Text -> image via SDXL-Turbo (open weights, runs local on ROCm or CUDA).
Lazy-loaded so the app starts fast and image-input runs never pay for it.
"""
from __future__ import annotations

import torch
from PIL import Image

from .device import empty_cache
from .presets import PROMPT_STYLE_SUFFIX

SDXL_TURBO = "stabilityai/sdxl-turbo"


class ImageGenerator:
    def __init__(self, device: torch.device):
        self.device = device
        self._pipe = None

    def load(self):
        if self._pipe is not None:
            return
        from diffusers import AutoPipelineForText2Image

        dtype = torch.float16 if self.device.type == "cuda" else torch.float32
        self._pipe = AutoPipelineForText2Image.from_pretrained(
            SDXL_TURBO, torch_dtype=dtype, variant="fp16", use_safetensors=True
        )
        self._pipe.to(self.device)
        self._pipe.set_progress_bar_config(disable=True)

    def unload(self):
        if self._pipe is None:
            return
        self._pipe = None
        empty_cache()

    def generate(self, prompt: str, size: int = 768, steps: int = 4,
                 seed: int | None = None, stylize: bool = True) -> Image.Image:
        self.load()
        full_prompt = prompt.strip() + (PROMPT_STYLE_SUFFIX if stylize else "")
        generator = None
        if seed is not None:
            generator = torch.Generator(device=self.device.type).manual_seed(int(seed))
        # SDXL-Turbo is guidance-distilled: guidance_scale must be 0.
        out = self._pipe(
            prompt=full_prompt,
            num_inference_steps=steps,
            guidance_scale=0.0,
            width=size,
            height=size,
            generator=generator,
        )
        return out.images[0]
