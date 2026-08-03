from __future__ import annotations

import secrets
from datetime import datetime
from pathlib import Path

import torch
from diffusers import (
    StableDiffusionImg2ImgPipeline,
    StableDiffusionPipeline,
)
from PIL import Image

from configs.config import DEVICE, MODEL_NAME, OUTPUT_DIR
from utils.timer import Timer


class ImageGenerator:
    def __init__(self) -> None:
        if not torch.cuda.is_available():
            raise RuntimeError(
                "No AMD ROCm GPU was detected. Please check "
                "torch.cuda.is_available()."
            )

        self.device = DEVICE
        self.model_name = MODEL_NAME
        self.gpu_name = torch.cuda.get_device_name(0)

        properties = torch.cuda.get_device_properties(0)
        self.total_vram_gb = properties.total_memory / (1024**3)

        print("=" * 60)
        print("Loading diffusion model...")
        print(f"Model: {self.model_name}")
        print(f"GPU: {self.gpu_name}")
        print(f"VRAM: {self.total_vram_gb:.2f} GB")
        print("=" * 60)

        self.pipe = StableDiffusionPipeline.from_pretrained(
            self.model_name,
            torch_dtype=torch.float16,
            use_safetensors=True,
        ).to(self.device)

        self.img2img_pipe = StableDiffusionImg2ImgPipeline(
            vae=self.pipe.vae,
            text_encoder=self.pipe.text_encoder,
            tokenizer=self.pipe.tokenizer,
            unet=self.pipe.unet,
            scheduler=self.pipe.scheduler,
            safety_checker=self.pipe.safety_checker,
            feature_extractor=self.pipe.feature_extractor,
            image_encoder=getattr(self.pipe, "image_encoder", None),
            requires_safety_checker=False,
        ).to(self.device)

        self.pipe.set_progress_bar_config(disable=True)
        self.img2img_pipe.set_progress_bar_config(disable=True)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        print("Text-to-Image and Image-to-Image loaded successfully!")

    @staticmethod
    def _get_seed(seed: int | float | None) -> int:
        if seed is None or int(seed) < 0:
            return secrets.randbelow(2_147_483_647)

        return int(seed)

    @staticmethod
    def _prepare_reference_image(
        image: Image.Image,
        width: int,
        height: int,
    ) -> Image.Image:
        if image is None:
            raise ValueError("Please upload a reference image first.")

        image = image.convert("RGB")
        return image.resize(
            (int(width), int(height)),
            Image.Resampling.LANCZOS,
        )

    @staticmethod
    def _save_image(
        image: Image.Image,
        mode: str,
        seed: int,
    ) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        save_path = OUTPUT_DIR / f"radeon_{mode}_{timestamp}_seed{seed}.png"
        image.save(save_path, format="PNG")
        return save_path

    def generate(
        self,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        steps: int,
        guidance_scale: float,
        seed: int,
    ) -> dict:
        if not prompt.strip():
            raise ValueError("The prompt cannot be empty.")

        actual_seed = self._get_seed(seed)
        torch_generator = torch.Generator(device=self.device).manual_seed(
            actual_seed
        )

        with torch.inference_mode():
            with Timer() as timer:
                result = self.pipe(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    width=int(width),
                    height=int(height),
                    num_inference_steps=int(steps),
                    guidance_scale=float(guidance_scale),
                    generator=torch_generator,
                )

        image = result.images[0]
        save_path = self._save_image(image, "text2img", actual_seed)
        return self._build_result(
            image=image,
            save_path=save_path,
            timer_cost=timer.cost,
            seed=actual_seed,
            width=width,
            height=height,
            steps=steps,
            mode="Text-to-Image",
        )

    def generate_batch(
        self,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        steps: int,
        guidance_scale: float,
        seed: int,
        batch_size: int,
    ) -> dict:
        """Generate multiple candidates from one prompt using adjacent seeds."""
        if not prompt.strip():
            raise ValueError("The prompt cannot be empty.")

        batch_size = int(batch_size)
        if batch_size < 2 or batch_size > 4:
            raise ValueError("Batch generation supports between 2 and 4 images.")

        base_seed = self._get_seed(seed)
        seeds = [base_seed + index for index in range(batch_size)]
        generators = [
            torch.Generator(device=self.device).manual_seed(current_seed)
            for current_seed in seeds
        ]

        with torch.inference_mode():
            with Timer() as timer:
                result = self.pipe(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    width=int(width),
                    height=int(height),
                    num_inference_steps=int(steps),
                    guidance_scale=float(guidance_scale),
                    num_images_per_prompt=batch_size,
                    generator=generators,
                )

        saved_items = []
        for index, image in enumerate(result.images):
            current_seed = seeds[index]
            save_path = self._save_image(
                image=image,
                mode=f"batch_{index + 1}",
                seed=current_seed,
            )
            saved_items.append(
                {
                    "image": image,
                    "path": str(save_path),
                    "seed": current_seed,
                    "index": index + 1,
                }
            )

        return {
            "items": saved_items,
            "time": round(timer.cost, 2),
            "base_seed": base_seed,
            "width": int(width),
            "height": int(height),
            "steps": int(steps),
            "batch_size": batch_size,
            "mode": "Batch Text-to-Image",
            "gpu_name": self.gpu_name,
            "vram_gb": round(self.total_vram_gb, 2),
        }

    def transform(
        self,
        reference_image: Image.Image,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        steps: int,
        guidance_scale: float,
        strength: float,
        seed: int,
    ) -> dict:
        if reference_image is None:
            raise ValueError("Please upload a reference image first.")
        if not prompt.strip():
            raise ValueError("Please enter an image-to-image instruction.")

        strength = float(strength)
        if strength <= 0.0 or strength > 1.0:
            raise ValueError("Strength must be greater than 0 and no more than 1.")

        prepared_image = self._prepare_reference_image(
            reference_image,
            width,
            height,
        )
        actual_seed = self._get_seed(seed)
        torch_generator = torch.Generator(device=self.device).manual_seed(
            actual_seed
        )

        with torch.inference_mode():
            with Timer() as timer:
                result = self.img2img_pipe(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    image=prepared_image,
                    strength=strength,
                    num_inference_steps=int(steps),
                    guidance_scale=float(guidance_scale),
                    generator=torch_generator,
                )

        image = result.images[0]
        save_path = self._save_image(image, "img2img", actual_seed)
        return self._build_result(
            image=image,
            save_path=save_path,
            timer_cost=timer.cost,
            seed=actual_seed,
            width=width,
            height=height,
            steps=steps,
            mode="Image-to-Image",
            strength=strength,
        )

    def _build_result(
        self,
        image: Image.Image,
        save_path: Path,
        timer_cost: float,
        seed: int,
        width: int,
        height: int,
        steps: int,
        mode: str,
        strength: float | None = None,
    ) -> dict:
        result = {
            "image": image,
            "path": str(save_path),
            "time": round(timer_cost, 2),
            "seed": seed,
            "width": int(width),
            "height": int(height),
            "steps": int(steps),
            "mode": mode,
            "gpu_name": self.gpu_name,
            "vram_gb": round(self.total_vram_gb, 2),
        }

        if strength is not None:
            result["strength"] = round(float(strength), 2)

        return result
