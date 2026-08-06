import gc
import time
from datetime import datetime
from typing import Optional, Tuple

import torch
from diffusers import (
    DDIMScheduler,
    DPMSolverMultistepScheduler,
    EulerAncestralDiscreteScheduler,
    EulerDiscreteScheduler,
    LMSDiscreteScheduler,
    StableDiffusionXLPipeline,
)
from PIL import Image

from database_vscode import OUTPUT_DIR

MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"

SCHEDULERS = {
    "euler_a": (EulerAncestralDiscreteScheduler, "Fast and creative"),
    "euler": (EulerDiscreteScheduler, "Consistent and deterministic"),
    "ddim": (DDIMScheduler, "Classic high-quality sampler"),
    "dpm++": (DPMSolverMultistepScheduler, "Efficient final-quality sampler"),
    "lms": (LMSDiscreteScheduler, "Stable and predictable"),
}


class SDXLGenerator:
    def __init__(self):
        self.pipe = None
        self.device = None
        self.dtype = None
        self.current_scheduler = "euler_a"

    def load_model(self) -> str:
        if self.pipe is not None:
            return "SDXL is already loaded and ready."

        if not torch.cuda.is_available():
            return (
                "CUDA GPU was not detected, so SDXL was not loaded on CPU. "
                "Run this project in Google Colab with T4 GPU enabled, then click Load SDXL Image Model again."
            )

        try:
            self.device = torch.device("cuda")
            self.dtype = torch.float16
            print(f"Loading {MODEL_ID} on {self.device} with {self.dtype}")

            self.pipe = StableDiffusionXLPipeline.from_pretrained(
                MODEL_ID,
                torch_dtype=self.dtype,
                use_safetensors=True,
                variant="fp16",
                low_cpu_mem_usage=True,
            )

            self.pipe.enable_attention_slicing()
            self.pipe.enable_vae_slicing()

            try:
                self.pipe.enable_xformers_memory_efficient_attention()
                print("xFormers enabled")
            except Exception:
                print("xFormers not available. Continuing without it.")

            self.pipe = self.pipe.to(self.device)
            return f"SDXL loaded successfully on {self.device}."
        except Exception as e:
            self.pipe = None
            return f"Failed to load model: {str(e)}"

    def set_scheduler(self, name: str):
        if name not in SCHEDULERS or self.pipe is None:
            return
        scheduler_class, _ = SCHEDULERS[name]
        self.pipe.scheduler = scheduler_class.from_config(self.pipe.scheduler.config)
        self.current_scheduler = name

    def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 768,
        height: int = 768,
        steps: int = 25,
        guidance_scale: float = 7.5,
        seed: Optional[int] = None,
        scheduler: str = "euler_a",
    ) -> Tuple[Image.Image, dict]:
        if self.pipe is None:
            raise RuntimeError("Model is not loaded. Click Load SDXL Image Model first.")
        if not prompt or not prompt.strip():
            raise ValueError("Prompt cannot be empty.")

        self.set_scheduler(scheduler)
        if seed is None:
            seed = torch.randint(0, 2**32, (1,)).item()

        width = (int(width) // 8) * 8
        height = (int(height) // 8) * 8
        generator = torch.Generator(device=self.device).manual_seed(int(seed))

        start = time.time()
        with torch.inference_mode():
            result = self.pipe(
                prompt=prompt,
                negative_prompt=negative_prompt or None,
                width=width,
                height=height,
                num_inference_steps=int(steps),
                guidance_scale=float(guidance_scale),
                generator=generator,
            )

        gen_time = round(time.time() - start, 2)
        self._cleanup()
        metadata = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "steps": int(steps),
            "guidance_scale": float(guidance_scale),
            "scheduler": scheduler,
            "seed": int(seed),
            "generation_time": gen_time,
            "device": str(self.device),
        }
        return result.images[0], metadata

    def save_image(self, image: Image.Image, metadata: dict, user_id: int) -> str:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"sdxl_{user_id}_{timestamp}_s{metadata['seed']}.png"
        filepath = OUTPUT_DIR / filename
        image.save(filepath)
        return str(filepath)

    def _cleanup(self):
        gc.collect()
        if self.device and self.device.type == "cuda":
            torch.cuda.empty_cache()