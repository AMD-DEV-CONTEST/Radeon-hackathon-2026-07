"""
Local video generation pipeline with ROCm / CUDA / DirectML support.

Supports backends:
- cuda            NVIDIA GPUs
- rocm            AMD GPUs on Linux (ROCm)
- directml        AMD GPUs on Windows (DirectML via onnxruntime)
- mps             Apple Silicon (if torch supports it)
- cpu             fallback
"""

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Optional

from PIL import Image


class VideoGenerationPipeline:
    def __init__(self, device: str, backend: str, fp16: bool = True):
        self.device = device
        self.backend = backend
        self.fp16 = fp16 and backend in ("cuda", "rocm")

    async def generate_video(
        self,
        *,
        source_image_path: Path,
        prompt: str,
        width: int,
        height: int,
        num_frames: int,
        fps: int,
        seed: int,
    ) -> Path:
        # In production this would run a real diffusion pipeline on the
        # selected backend (diffusers + torch, or ComfyUI client, or an
        # onnxruntime/DirectML graph). For now, simulate success so the
        # rest of the app is end-to-end runnable.
        await asyncio.sleep(0.5)

        out_path = Path(tempfile.gettempdir()) / f"frameforge_{seed}.mp4"
        out_path.write_bytes(b"")
        return out_path
