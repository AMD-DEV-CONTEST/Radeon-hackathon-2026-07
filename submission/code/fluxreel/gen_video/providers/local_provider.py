"""Image generation via local GPU inference using diffusers (FLUX models)."""

import os
import sys
import tempfile
import time
from pathlib import Path

from .base import ImageProvider


# Lazy import — only import torch/diffusers when actually used
_torch = None
_diffusers = None
_Pipeline = None


def _ensure_imports():
    global _torch, _diffusers, _Pipeline
    if _torch is not None:
        return
    import torch as _torch
    from diffusers import FluxPipeline as _Pipeline
    import diffusers as _diffusers


# Map short names to model paths on the remote server
MODEL_PATHS = {
    "schnell": "/root/FLUX.1-schnell",
    "dev": "/root/FLUX.1-dev",
    "2-dev": "/root/FLUX.2-dev",
}

# Default generation params per model variant
MODEL_PARAMS = {
    "schnell": {"steps": 4, "guidance": 0.0},
    "dev": {"steps": 28, "guidance": 3.5},
    "2-dev": {"steps": 28, "guidance": 3.5},
}


class LocalGPUProvider(ImageProvider):
    """Generate images locally using diffusers and the AMD GPU.

    Uses the FLUX models stored on the remote server at /root/FLUX.*.
    """

    def __init__(self, variant: str = "schnell"):
        if variant not in MODEL_PATHS:
            valid = list(MODEL_PATHS.keys())
            raise ValueError(f"Unknown variant '{variant}'. Valid: {valid}")
        self._variant = variant
        self._model_dir = MODEL_PATHS[variant]
        self._pipe = None
        self._loaded = False

    @property
    def name(self) -> str:
        return f"Local GPU (FLUX.{self._variant})"

    @property
    def model_name(self) -> str:
        return f"black-forest-labs/FLUX.1-{self._variant}"

    def _load_model(self):
        """Load the FLUX pipeline (lazy, on first use)."""
        if self._loaded and self._pipe is not None:
            return

        _ensure_imports()

        if not os.path.isdir(self._model_dir):
            raise RuntimeError(
                f"Model directory not found: {self._model_dir}\n"
                f"Download it first with: fluxreel download flux {self._variant}"
            )

        print(f"  Loading model from {self._model_dir}...")
        t0 = time.time()
        self._pipe = _Pipeline.from_pretrained(
            self._model_dir, torch_dtype=_torch.bfloat16
        )
        self._pipe.enable_sequential_cpu_offload()
        self._pipe.enable_attention_slicing()
        print(f"  Model loaded in {time.time() - t0:.1f}s")
        self._loaded = True

    def generate_image(self, prompt: str, scene_index: int = 0) -> str | None:
        """Generate an image using the local GPU.

        Returns path to the image file, or None on failure.
        """
        try:
            self._load_model()
        except Exception as e:
            print(f"  Error loading model: {e}")
            return None

        params = MODEL_PARAMS[self._variant]

        print(f"  Generating image (local GPU, {self._variant}, {params['steps']} steps)...")
        t0 = time.time()
        try:
            image = self._pipe(
                prompt,
                num_inference_steps=params["steps"],
                guidance_scale=params["guidance"],
                width=1024,
                height=768,  # 4:3 to match the video slide layout
            ).images[0]
            elapsed = time.time() - t0
            print(f"  Image generated in {elapsed:.1f}s")
        except Exception as e:
            print(f"  Error during inference: {e}")
            return None

        # Save to temp file
        temp_dir = Path(tempfile.mkdtemp(prefix=f"local_img_{scene_index}_"))
        out_path = str(temp_dir / f"local_scene_{scene_index:03d}.png")
        image.save(out_path)
        print(f"  Saved: {out_path}")

        # Report VRAM usage
        try:
            vram = _torch.cuda.max_memory_allocated() / 1e9
            print(f"  Max VRAM: {vram:.2f} GB")
            _torch.cuda.reset_peak_memory_stats()
        except Exception:
            pass

        return out_path
