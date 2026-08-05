"""Image -> 3D mesh via Hunyuan3D-2 flow-matching DiT (shape generation only).
Shape-only deliberately avoids the custom CUDA texture rasterizer, keeping the
whole pipeline pure PyTorch and therefore portable across ROCm and CUDA.
"""
from __future__ import annotations

import torch
import trimesh
from PIL import Image

from .device import empty_cache
from .presets import Preset


class ShapeGenerator:
    def __init__(self, device: torch.device):
        self.device = device
        self._pipe = None
        self._loaded_repo = None

    def load(self, repo: str, subfolder: str):
        if self._pipe is not None and self._loaded_repo == (repo, subfolder):
            return
        self.unload()
        from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline

        self._pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            repo, subfolder=subfolder, variant="fp16", use_safetensors=True
        )
        self._pipe.to(self.device)
        self._loaded_repo = (repo, subfolder)

    def unload(self):
        if self._pipe is None:
            return
        self._pipe = None
        self._loaded_repo = None
        empty_cache()

    def generate(self, image: Image.Image, preset: Preset, seed: int) -> trimesh.Trimesh:
        self.load(preset.shape_repo, preset.shape_subfolder)
        generator = torch.Generator(device=self.device.type).manual_seed(int(seed))
        mesh = self._pipe(
            image=image,
            num_inference_steps=preset.shape_steps,
            octree_resolution=preset.octree_resolution,
            num_chunks=preset.num_chunks,
            guidance_scale=preset.guidance_scale,
            generator=generator,
        )[0]
        if not isinstance(mesh, trimesh.Trimesh):
            mesh = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces)
        return mesh
