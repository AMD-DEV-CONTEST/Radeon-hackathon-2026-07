"""Experimental real Diffusers implementation for AMD Radeon through PyTorch/ROCm.

This class never falls back to mock mode. Model loading is explicit and separate
from generation. The base SDXL image-to-image path was validated on Radeon Cloud;
product analysis, copy, and product-preservation adapters remain unimplemented.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    from .model_interface import CampaignPipeline
except ImportError:  # Supports direct execution from the inference directory.
    from model_interface import CampaignPipeline


class RocmPipelineError(RuntimeError):
    """Raised when real ROCm inference prerequisites are absent."""


VALIDATED_MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
VALIDATED_MODEL_REVISION = "462165984030d82259a11f4367a4eed129e94a7b"
VALIDATED_PROMPT = (
    "Premium studio product advertisement, dark charcoal background, controlled soft rim lighting, "
    "clean commercial composition, realistic product photography, preserve the product shape, "
    "preserve the product proportions, no added text, no altered logo, polished advertising visual."
)
VALIDATED_NEGATIVE_PROMPT = (
    "deformed product, changed logo, duplicated product, unreadable text, watermark, low quality, "
    "distorted geometry, extra objects"
)


@dataclass(frozen=True)
class RocmPipelineConfig:
    model_id: str
    model_revision: str | None
    model_cache_dir: Path | None
    output_dir: Path
    device: str
    dtype: str
    local_files_only: bool
    ip_adapter_model_id: str | None
    controlnet_model_id: str | None
    width: int = 768
    height: int = 768
    steps: int = 15
    strength: float = 0.35
    guidance_scale: float = 6.5
    seed: int = 20260725

    @classmethod
    def from_environment(cls) -> "RocmPipelineConfig":
        model_id = os.getenv("MODEL_ID", "").strip() or VALIDATED_MODEL_ID
        model_revision = (
            os.getenv("MODEL_REVISION", "").strip() or VALIDATED_MODEL_REVISION
        )
        cache = os.getenv("MODEL_CACHE_DIR", "").strip()
        config = cls(
            model_id=model_id,
            model_revision=model_revision,
            model_cache_dir=Path(cache).expanduser() if cache else None,
            output_dir=Path(os.getenv("OUTPUT_DIR", "outputs")).expanduser(),
            device=os.getenv("DEVICE", "cuda"),
            dtype=os.getenv("DTYPE", "float16"),
            local_files_only=os.getenv("MODEL_LOCAL_FILES_ONLY", "true").lower() not in {"0", "false", "no"},
            ip_adapter_model_id=os.getenv("IP_ADAPTER_MODEL_ID") or None,
            controlnet_model_id=os.getenv("CONTROLNET_MODEL_ID") or None,
            width=int(os.getenv("GENERATION_WIDTH", "768")),
            height=int(os.getenv("GENERATION_HEIGHT", "768")),
            steps=int(os.getenv("GENERATION_STEPS", "15")),
            strength=float(os.getenv("GENERATION_STRENGTH", "0.35")),
            guidance_scale=float(os.getenv("GUIDANCE_SCALE", "6.5")),
            seed=int(os.getenv("GENERATION_SEED", "20260725")),
        )
        if config.width < 64 or config.height < 64:
            raise RocmPipelineError("Generation width and height must be at least 64 pixels.")
        if config.width % 8 or config.height % 8:
            raise RocmPipelineError("Generation width and height must be divisible by 8.")
        if config.steps < 1:
            raise RocmPipelineError("GENERATION_STEPS must be at least 1.")
        if not 0.0 < config.strength <= 1.0:
            raise RocmPipelineError("GENERATION_STRENGTH must be greater than 0 and at most 1.")
        if config.guidance_scale < 0:
            raise RocmPipelineError("GUIDANCE_SCALE cannot be negative.")
        return config


class RocmCampaignPipeline(CampaignPipeline):
    def __init__(
        self,
        config: RocmPipelineConfig | None = None,
        *,
        torch_module: Any | None = None,
        pipeline_factory: Any | None = None,
    ):
        self.config = config or RocmPipelineConfig.from_environment()
        self._pipeline: Any | None = None
        self._torch: Any | None = torch_module
        self._pipeline_factory = pipeline_factory
        self._model_load_seconds = 0.0

    @property
    def is_loaded(self) -> bool:
        return self._pipeline is not None

    def load_model(self) -> None:
        """Load a real local/cached image-to-image pipeline or fail clearly."""
        torch = self._torch
        if torch is None:
            try:
                import torch
            except (ImportError, OSError) as exc:
                raise RocmPipelineError(
                    "PyTorch is required for ROCm mode and could not be imported."
                ) from exc
        pipeline_factory = self._pipeline_factory
        if pipeline_factory is None:
            try:
                from diffusers import StableDiffusionXLImg2ImgPipeline
            except (ImportError, OSError) as exc:
                raise RocmPipelineError(
                    "Diffusers is required for ROCm mode and could not be imported."
                ) from exc
            pipeline_factory = StableDiffusionXLImg2ImgPipeline

        hip_version = getattr(getattr(torch, "version", None), "hip", None)
        if not hip_version:
            raise RocmPipelineError("The installed PyTorch build does not report HIP/ROCm support.")
        if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
            raise RocmPipelineError("PyTorch does not report an available ROCm GPU through torch.cuda.")
        device_name = str(torch.cuda.get_device_name(0))
        if "amd" not in device_name.lower() and "radeon" not in device_name.lower():
            raise RocmPipelineError("The available HIP device is not identified as AMD Radeon hardware.")
        if self.config.device != "cuda" and not self.config.device.startswith("cuda:"):
            raise RocmPipelineError("ROCm PyTorch devices must use DEVICE=cuda or cuda:<index>.")

        dtype = getattr(torch, self.config.dtype, None)
        if dtype is None:
            raise RocmPipelineError(f"Unsupported DTYPE: {self.config.dtype}")

        try:
            started = time.perf_counter()
            pipeline = pipeline_factory.from_pretrained(
                self.config.model_id,
                revision=self.config.model_revision,
                cache_dir=str(self.config.model_cache_dir) if self.config.model_cache_dir else None,
                torch_dtype=dtype,
                local_files_only=self.config.local_files_only,
                use_safetensors=True,
            )
            pipeline = pipeline.to(self.config.device)
            self._model_load_seconds = time.perf_counter() - started
        except Exception as exc:
            mode = "local cache" if self.config.local_files_only else "configured source"
            raise RocmPipelineError(
                f"Failed to load real model '{self.config.model_id}' from the {mode}: {exc}"
            ) from exc

        self._torch = torch
        self._pipeline = pipeline

    def analyze_product(self, image_path: Path) -> dict[str, Any]:
        if not image_path.is_file():
            raise RocmPipelineError(f"Product image does not exist: {image_path}")
        raise NotImplementedError("Real product analysis is not implemented; no result was fabricated.")

    def generate_creative_concept(
        self, analysis: dict[str, Any], brief: dict[str, Any]
    ) -> dict[str, Any]:
        raise NotImplementedError("Real creative-concept generation is not implemented.")

    def generate_ad_image(
        self,
        image_path: Path,
        concept: dict[str, Any],
        output_format: str,
        *,
        output_path: Path | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
        seed: int | None = None,
    ) -> dict[str, Any]:
        if not self.is_loaded:
            raise RocmPipelineError("Call load_model() successfully before real generation.")
        if not image_path.is_file():
            raise RocmPipelineError(f"Input image does not exist: {image_path}")
        if self.config.ip_adapter_model_id or self.config.controlnet_model_id:
            raise RocmPipelineError(
                "IP-Adapter and ControlNet are configured but not yet validated or loaded."
            )
        if self.config.width % 8 or self.config.height % 8:
            raise RocmPipelineError("Generation width and height must be divisible by 8.")

        try:
            from PIL import Image, ImageOps
        except (ImportError, OSError) as exc:
            raise RocmPipelineError("Pillow is required for real image preprocessing.") from exc

        with Image.open(image_path) as source:
            source = source.convert("RGB")
            fitted = ImageOps.contain(source, (self.config.width, self.config.height))
            input_image = Image.new(
                "RGB",
                (self.config.width, self.config.height),
                (24, 24, 28),
            )
            input_image.paste(
                fitted,
                (
                    (self.config.width - fitted.width) // 2,
                    (self.config.height - fitted.height) // 2,
                ),
            )

        torch = self._torch
        pipeline = self._pipeline
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_path or self.config.output_dir / "generated-ad.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        prompt = str(concept.get("prompt") or VALIDATED_PROMPT)
        negative_prompt = str(concept.get("negative_prompt") or VALIDATED_NEGATIVE_PROMPT)
        selected_seed = self.config.seed if seed is None else seed
        if selected_seed < 0 or selected_seed > 2**32 - 1:
            raise RocmPipelineError("Seed must be between 0 and 4294967295.")

        callback_kwargs: dict[str, Any] = {}
        if progress_callback:
            def on_step_end(
                _pipeline: Any,
                step_index: int,
                _timestep: Any,
                values: dict[str, Any],
            ) -> dict[str, Any]:
                progress_callback(step_index + 1, self.config.steps)
                return values

            callback_kwargs["callback_on_step_end"] = on_step_end

        try:
            torch.cuda.reset_peak_memory_stats()
            generator = torch.Generator(device=self.config.device).manual_seed(selected_seed)
            started = time.perf_counter()
            generated = pipeline(
                prompt=prompt,
                negative_prompt=negative_prompt,
                image=input_image,
                width=self.config.width,
                height=self.config.height,
                num_inference_steps=self.config.steps,
                strength=self.config.strength,
                guidance_scale=self.config.guidance_scale,
                generator=generator,
                num_images_per_prompt=1,
                **callback_kwargs,
            ).images[0]
            torch.cuda.synchronize()
            generation_seconds = time.perf_counter() - started
            generated.save(output_path)
            peak_allocated = int(torch.cuda.max_memory_allocated(0))
            peak_reserved = int(torch.cuda.max_memory_reserved(0))
        except Exception as exc:
            raise RocmPipelineError(
                f"Real ROCm image-to-image generation failed without fallback: {exc}"
            ) from exc

        digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
        return {
            "mode": "rocm",
            "image_path": str(output_path),
            "output_format": output_format,
            "model_id": self.config.model_id,
            "model_revision": self.config.model_revision,
            "pipeline_class": type(pipeline).__name__,
            "width": self.config.width,
            "height": self.config.height,
            "steps": self.config.steps,
            "strength": self.config.strength,
            "guidance_scale": self.config.guidance_scale,
            "seed": selected_seed,
            "model_load_seconds": self._model_load_seconds,
            "generation_seconds": generation_seconds,
            "peak_allocated_gpu_memory_bytes": peak_allocated,
            "peak_reserved_gpu_memory_bytes": peak_reserved,
            "output_sha256": digest,
            "input_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
            "gpu_device_name": str(torch.cuda.get_device_name(0)),
            "pytorch_version": str(getattr(torch, "__version__", "")),
            "hip_rocm_version": str(getattr(torch.version, "hip", "")),
            "product_preservation_validated": False,
        }

    def generate_campaign_copy(
        self, concept: dict[str, Any], brief: dict[str, Any]
    ) -> dict[str, str]:
        raise NotImplementedError("The image pipeline does not generate campaign copy.")

    def get_device_metrics(self) -> dict[str, Any]:
        if self._torch is None:
            raise RocmPipelineError("Call load_model() before requesting device metrics.")
        torch = self._torch
        index = torch.cuda.current_device()
        properties = torch.cuda.get_device_properties(index)
        metrics: dict[str, Any] = {
            "device_index": int(index),
            "device_name": torch.cuda.get_device_name(index),
            "hip_version": getattr(torch.version, "hip", None),
            "allocated_bytes": int(torch.cuda.memory_allocated(index)),
            "reserved_bytes": int(torch.cuda.memory_reserved(index)),
            "total_memory_bytes": getattr(properties, "total_memory", None),
        }
        try:
            free_bytes, total_bytes = torch.cuda.mem_get_info(index)
            metrics.update({"free_memory_bytes": int(free_bytes), "total_memory_bytes": int(total_bytes)})
        except (AttributeError, RuntimeError, OSError):
            pass
        return metrics

    def health_check(self) -> dict[str, Any]:
        try:
            import torch
        except (ImportError, OSError) as exc:
            return {"status": "fail", "mode": "rocm", "message": f"PyTorch unavailable: {exc}"}
        hip = getattr(getattr(torch, "version", None), "hip", None)
        available = bool(torch.cuda.is_available())
        return {
            "status": "ok" if hip and available else "fail",
            "mode": "rocm",
            "model_loaded": self.is_loaded,
            "hip_version": hip,
            "gpu_available": available,
            "device_count": int(torch.cuda.device_count()) if available else 0,
        }
