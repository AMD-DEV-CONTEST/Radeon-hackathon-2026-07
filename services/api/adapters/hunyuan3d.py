"""Hunyuan3D-2 local provider for image-to-3D shape and texture generation on AMD ROCm.

Hunyuan3D-2 is a Tencent open-source two-stage pipeline:
  1. Hunyuan3DDiTFlowMatchingPipeline -> bare mesh from image/text
  2. Hunyuan3DPaintPipeline -> texture the mesh using the reference image

Reference: https://github.com/Tencent-Hunyuan/Hunyuan3D-2
"""

import logging
import os
import warnings
from pathlib import Path
from typing import List

import trimesh

from adapters.base import ThreeDProvider, MeshAsset

logger = logging.getLogger(__name__)

# Optional imports: Hunyuan3D-2 may not be installed if the user only wants 2.5D reliefs.
try:
    from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
    _HAS_SHAPEGEN = True
except ImportError:  # pragma: no cover
    _HAS_SHAPEGEN = False

try:
    from hy3dgen.texgen import Hunyuan3DPaintPipeline
    _HAS_TEXGEN = True
except ImportError:  # pragma: no cover
    _HAS_TEXGEN = False

try:
    import torch
    _HAS_TORCH = True
except ImportError:  # pragma: no cover
    _HAS_TORCH = False


def _default_cache_dir() -> str:
    return os.environ.get("HF_HOME", str(Path(__file__).resolve().parent.parent / "models" / "hf_cache"))


class Hunyuan3D2Provider(ThreeDProvider):
    """Image-to-3D provider using Tencent Hunyuan3D-2 on ROCm / CUDA.

    Texture generation requires Hunyuan3D-2's custom rasterizer / differentiable renderer.
    If those custom CUDA ops fail to compile on ROCm, the provider falls back to shape-only
    generation (bare mesh) and logs a warning.
    """

    name = "hunyuan3d_2"

    _shape_pipeline = None
    _texture_pipeline = None

    def __init__(
        self,
        shape_model_path: str = "tencent/Hunyuan3D-2",
        subfolder: str = "hunyuan3d-dit-v2-0",
        texture_model_path: str = "tencent/Hunyuan3D-2",
        device: str = "cuda",
        torch_dtype: str = "float16",
        cache_dir: str | None = None,
        enable_texture: bool = True,
    ):
        self.shape_model_path = shape_model_path
        self.subfolder = subfolder
        self.texture_model_path = texture_model_path
        self.device = device if _HAS_TORCH else "cpu"
        self.torch_dtype = torch_dtype
        self.cache_dir = cache_dir or _default_cache_dir()
        self.enable_texture = enable_texture and _HAS_TEXGEN

    def _load_shape_pipeline(self):
        if self._shape_pipeline is not None:
            return self._shape_pipeline
        if not _HAS_SHAPEGEN:
            raise RuntimeError(
                "Hunyuan3D-2 is not installed. "
                "Please run the Hunyuan3D-2 installation step in setup_rocm.sh or "
                "`pip install git+https://github.com/Tencent-Hunyuan/Hunyuan3D-2.git`."
            )
        if not _HAS_TORCH:
            raise RuntimeError("PyTorch is required for Hunyuan3D-2 inference")

        import torch

        dtype = getattr(torch, self.torch_dtype, torch.float16)
        logger.info(
            "Loading Hunyuan3D-2 shape pipeline: repo=%s subfolder=%s device=%s dtype=%s cache_dir=%s",
            self.shape_model_path,
            self.subfolder,
            self.device,
            dtype,
            self.cache_dir,
        )
        pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            self.shape_model_path,
            subfolder=self.subfolder,
            torch_dtype=dtype,
            cache_dir=self.cache_dir,
        )
        if pipe is None:
            raise RuntimeError(
                "Hunyuan3D-2 shape pipeline returned None. "
                "Check the model path / subfolder and that the model is fully downloaded."
            )
        # NOTE: Hunyuan3DDiTPipeline.to() is in-place and does NOT return self.
        pipe.to(self.device)
        self._shape_pipeline = pipe
        return pipe

    def _load_texture_pipeline(self):
        if self._texture_pipeline is not None:
            return self._texture_pipeline
        if not _HAS_TEXGEN:
            raise RuntimeError("Hunyuan3D-2 texture module is not installed")
        if not _HAS_TORCH:
            raise RuntimeError("PyTorch is required for Hunyuan3D-2 texture inference")

        import torch

        dtype = getattr(torch, self.torch_dtype, torch.float16)
        logger.info(
            "Loading Hunyuan3D-2 texture pipeline: repo=%s device=%s dtype=%s cache_dir=%s",
            self.texture_model_path,
            self.device,
            dtype,
            self.cache_dir,
        )
        pipe = Hunyuan3DPaintPipeline.from_pretrained(
            self.texture_model_path,
            torch_dtype=dtype,
            cache_dir=self.cache_dir,
        )
        if pipe is None:
            raise RuntimeError("Hunyuan3D-2 texture pipeline returned None")
        # NOTE: Hunyuan3DPaintPipeline.to() is in-place and does NOT return self.
        pipe.to(self.device)
        self._texture_pipeline = pipe
        return pipe

    def generate_3d_from_images(
        self,
        images: List[Path],
        prompt: str,
        style: str,
        output_path: Path | None = None,
        **kwargs,
    ) -> MeshAsset:
        """Generate a 3D mesh from reference image(s).

        If multiple images are provided and the model is a multi-view variant (subfolder
        ends with 'mv'), the images are passed as a {front, right, back, left} dict.
        Otherwise the first image is used for single-image generation.
        """
        if not images:
            raise ValueError("Hunyuan3D-2 requires at least one reference image")

        input_image = Path(images[0])
        if not input_image.exists():
            raise FileNotFoundError(f"Reference image not found: {input_image}")

        if len(images) > 1 and self.subfolder.endswith("mv"):
            view_names = ["front", "right", "back", "left"]
            image_input = {
                name: str(images[i])
                for i, name in enumerate(view_names)
                if i < len(images)
            }
        else:
            image_input = str(input_image)

        shape_pipe = self._load_shape_pipeline()
        mesh = shape_pipe(image=image_input)[0]

        if self.enable_texture and _HAS_TEXGEN:
            try:
                tex_pipe = self._load_texture_pipeline()
                mesh = tex_pipe(mesh, image=str(input_image))
            except Exception as exc:
                warnings.warn(
                    f"Hunyuan3D-2 texture generation failed ({exc}); returning shape-only mesh."
                )

        if output_path is None:
            output_path = input_image.parent / "model.glb"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        mesh.export(output_path)
        return MeshAsset(mesh_path=output_path)

    def generate_3d_from_text(self, prompt: str, style: str, output_path: Path | None = None, **kwargs) -> MeshAsset:
        """Text-to-3D is supported by Hunyuan3D-2 but not yet wired in this provider."""
        raise NotImplementedError("Hunyuan3D2Provider currently supports image-to-3D only")
