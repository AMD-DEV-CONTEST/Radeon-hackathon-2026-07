"""ROCm / AMD GPU local inference providers for style transfer, depth estimation, and relief mesh generation.

This module is designed to gracefully degrade when torch/diffusers/transformers are not installed or
when ROCm is unavailable, so the rest of the app can still run with stubs for development.
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import List

import numpy as np
import trimesh
from PIL import Image

from adapters.base import ImageProvider, DepthProvider, ThreeDProvider, MeshAsset

# Optional imports: fail gracefully if the ROCm Python stack is not installed.
_import_errors: list[str] = []

try:
    import torch
    _HAS_TORCH = True
except Exception as exc:  # pragma: no cover
    _HAS_TORCH = False
    torch = None  # type: ignore
    _import_errors.append(f"torch: {exc}")

try:
    from diffusers import StableDiffusionImg2ImgPipeline
    _HAS_DIFFUSERS = True
except Exception as exc:  # pragma: no cover
    _HAS_DIFFUSERS = False
    _import_errors.append(f"diffusers: {exc}")

try:
    # Zero123Pipeline import path changed across diffusers versions.
    try:
        from diffusers import Zero123Pipeline  # type: ignore
    except ImportError:
        from diffusers.pipelines.zero123 import Zero123Pipeline  # type: ignore
    _HAS_ZERO123 = True
except Exception as exc:  # pragma: no cover
    _HAS_ZERO123 = False
    _import_errors.append(f"zero123: {exc}")

try:
    from transformers import pipeline
    _HAS_TRANSFORMERS = True
except Exception as exc:  # pragma: no cover
    _HAS_TRANSFORMERS = False
    _import_errors.append(f"transformers: {exc}")


if _import_errors:
    import warnings

    warnings.warn("ROCm adapter optional imports failed: " + "; ".join(_import_errors))


DEFAULT_HF_CACHE = Path(__file__).resolve().parent.parent / "models" / "hf_cache"


def rocm_available() -> bool:
    """Return True if a ROCm/HIP device is available through PyTorch."""
    if not _HAS_TORCH:
        return False
    try:
        return torch.version.hip is not None and torch.cuda.is_available()  # type: ignore
    except Exception:
        return False


def _default_cache_dir() -> str:
    return os.environ.get("HF_HOME", str(DEFAULT_HF_CACHE))


class ROCmStyleProvider(ImageProvider):
    """Local img2img style transfer using Stable Diffusion on ROCm."""

    name = "rocm_style"
    _pipe = None

    def __init__(
        self,
        model_id: str = "runwayml/stable-diffusion-v1-5",
        cache_dir: str | None = None,
        device: str = "cuda",
        max_image_size: int = 1024,
    ):
        self.model_id = model_id
        self.cache_dir = cache_dir or _default_cache_dir()
        self.device = device if rocm_available() else "cpu"
        self.max_image_size = max_image_size

    def _load_pipeline(self) -> StableDiffusionImg2ImgPipeline:
        if self._pipe is not None:
            return self._pipe
        if not _HAS_DIFFUSERS or not _HAS_TORCH:
            raise RuntimeError(
                f"diffusers and torch are required for ROCm style transfer. Import errors: {'; '.join(_import_errors)}"
            )

        dtype = torch.float16 if self.device == "cuda" else torch.float32
        pipe = StableDiffusionImg2ImgPipeline.from_pretrained(
            self.model_id,
            torch_dtype=dtype,
            cache_dir=self.cache_dir,
            safety_checker=None,
        )
        pipe = pipe.to(self.device)

        # Low-VRAM optimizations for ROCm
        if self.device == "cuda":
            try:
                pipe.enable_model_cpu_offload()
            except Exception:
                pass
            try:
                pipe.enable_vae_slicing()
            except Exception:
                pass

        self._pipe = pipe
        return pipe

    def generate_image_from_text(self, prompt: str) -> Path:
        # Text-to-image is not the primary workflow for this tool; keep the surface small.
        raise NotImplementedError("ROCmStyleProvider only supports image-to-image style transfer")

    def generate_image_from_image(
        self,
        image: Path,
        prompt: str,
        strength: float = 0.55,
        num_inference_steps: int = 20,
        guidance_scale: float = 7.5,
    ) -> Path:
        pipe = self._load_pipeline()
        init_image = Image.open(image).convert("RGB")

        # Resize to limit VRAM usage while keeping aspect ratio
        w, h = init_image.size
        if max(w, h) > self.max_image_size:
            scale = self.max_image_size / max(w, h)
            init_image = init_image.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        result = pipe(
            prompt=prompt,
            negative_prompt="blurry, low quality, distorted, watermark",
            image=init_image,
            strength=strength,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
        ).images[0]

        out_path = image.parent / "styled_preview.png"
        result.save(out_path)
        return out_path

    def _center_crop_resize(self, img: Image.Image, size: int) -> Image.Image:
        """Center-crop to a square and resize to `size` while keeping aspect ratio."""
        w, h = img.size
        if w != h:
            min_dim = min(w, h)
            left = (w - min_dim) // 2
            top = (h - min_dim) // 2
            img = img.crop((left, top, left + min_dim, top + min_dim))
        if img.size != (size, size):
            img = img.resize((size, size), Image.Resampling.LANCZOS)
        return img

    _zero123_pipe = None

    def _load_zero123_pipeline(self):
        if self._zero123_pipe is not None:
            return self._zero123_pipe
        if not _HAS_DIFFUSERS or not _HAS_TORCH or not _HAS_ZERO123:
            raise RuntimeError(
                f"Zero123 pipeline is not available. Import errors: {'; '.join(_import_errors)}"
            )

        dtype = torch.float16 if self.device == "cuda" else torch.float32  # type: ignore
        pipe = Zero123Pipeline.from_pretrained(
            "ashawkey/zero123-xl-diffusers",
            torch_dtype=dtype,
            cache_dir=self.cache_dir,
        )
        pipe = pipe.to(self.device)  # type: ignore
        if self.device == "cuda":
            try:
                pipe.enable_model_cpu_offload()
            except Exception:
                pass
        self._zero123_pipe = pipe
        return pipe

    def generate_multiview_from_image(self, image: Path, prompt: str, num_views: int = 4) -> List[Path]:
        """Generate multi-view renderings from a single front-facing image using Zero123.

        Returns 1 + num_views images: the original front view plus the generated views
        (right, back, left, ...). If Zero123 is unavailable, falls back to the input image.
        """
        if not _HAS_DIFFUSERS or not _HAS_TORCH or not _HAS_ZERO123:
            warnings.warn("Zero123 not available; falling back to single-image 3D generation")
            return [image]

        pipe = self._load_zero123_pipeline()
        init_image = Image.open(image).convert("RGB")
        init_image = self._center_crop_resize(init_image, 512)

        # Zero123 uses elevation / azimuth in degrees. Front is azimuth 0.
        views = [
            ("front", 0, 0),
            ("right", 0, 90),
            ("back", 0, 180),
            ("left", 0, 270),
        ]
        views = views[: max(1, num_views)]

        output_paths: List[Path] = []
        for name, elevation, azimuth in views:
            out = pipe(
                init_image,
                elevation=elevation,
                azimuth=azimuth,
                num_inference_steps=50,
                guidance_scale=5.0,
            ).images[0]
            out_path = image.parent / f"view_{name}.png"
            out.save(out_path)
            output_paths.append(out_path)

        return output_paths

class ROCmDepthProvider(DepthProvider):
    """Local monocular depth estimation on ROCm (Depth Anything V2)."""

    name = "rocm_depth"
    _pipe = None

    def __init__(
        self,
        model_id: str = "depth-anything/Depth-Anything-V2-Small-hf",
        cache_dir: str | None = None,
        device: str | int = "cuda",
    ):
        self.model_id = model_id
        self.cache_dir = cache_dir or _default_cache_dir()
        # transformers pipeline device: 0 for first GPU, -1 for CPU
        self.device = 0 if (device == "cuda" and rocm_available()) else -1

    def _load_pipeline(self):
        if self._pipe is not None:
            return self._pipe
        if not _HAS_TRANSFORMERS:
            raise RuntimeError(
                f"transformers is required for ROCm depth estimation. Import errors: {'; '.join(_import_errors)}"
            )

        self._pipe = pipeline(
            "depth-estimation",
            model=self.model_id,
            cache_dir=self.cache_dir,
            device=self.device,
        )
        return self._pipe

    def generate_depth_map(self, image: Path, invert: bool = False) -> Path:
        pipe = self._load_pipeline()
        result = pipe(str(image))
        depth = result["depth"]  # PIL Image in grayscale

        if invert:
            arr = 255 - np.array(depth)
            depth = Image.fromarray(arr.astype(np.uint8))

        out_path = image.parent / "depth.png"
        depth.save(out_path)
        return out_path


class ROCmReliefProvider(ThreeDProvider):
    """Generate a 2.5D printable relief mesh from a depth / height map.

    This runs entirely on CPU (trimesh/numpy) so it does not consume GPU VRAM. The depth map
    itself is produced by ROCmDepthProvider.  A full-color GLB with the original image baked
    as a texture is also exported alongside the watertight STL.
    """

    name = "rocm_relief"

    def generate_3d_from_images(
        self,
        images: List[Path],
        prompt: str,
        style: str,
        output_path: Path | None = None,
        **kwargs,
    ) -> MeshAsset:
        # For relief generation, the first image is treated as the depth/height map.
        # The second image (if present) is used as the color texture.
        depth_path = images[0]
        color_path = images[1] if len(images) > 1 else None
        return self.generate_relief_from_depth(
            depth_path, output_path=output_path, color_image=color_path, **kwargs
        )

    def generate_3d_from_text(self, prompt: str, style: str, output_path: Path | None = None) -> MeshAsset:
        raise NotImplementedError("ROCmReliefProvider requires an input depth map image")

    def generate_relief_from_depth(
        self,
        depth_path: Path,
        output_path: Path | None = None,
        color_image: Path | None = None,
        base_thickness_mm: float = 3.0,
        relief_height_mm: float = 4.0,
        invert: bool = False,
        shape: str = "rectangular",  # "rectangular" or "circular"
        size_mm: float = 80.0,
        smooth_iterations: int = 0,
    ) -> MeshAsset:
        """Convert a single-channel depth image into a watertight STL/OBJ/GLB mesh.

        Args:
            depth_path: grayscale image; brighter pixels are higher relief.
            output_path: destination file path (defaults to depth_path.parent / relief.stl).
            color_image: optional RGB image to bake as a texture on the relief GLB.
            base_thickness_mm: thickness of the flat backing plate.
            relief_height_mm: maximum height of the relief above the base.
            invert: invert the depth image before mapping to height.
            shape: "rectangular" keeps the full image, "circular" clips to an inscribed circle.
            size_mm: physical width/height of the longest image dimension in millimeters.
            smooth_iterations: optional Laplacian smoothing passes.
        """
        img = Image.open(depth_path).convert("L")
        arr = np.array(img, dtype=np.float32)
        if invert:
            arr = 255.0 - arr
        arr = arr / 255.0

        H, W = arr.shape
        # Pixel pitch so that the longest side equals size_mm.
        pixel_size = size_mm / max(H, W)

        # Top surface height map.
        z_top = base_thickness_mm + arr * relief_height_mm

        vertices = []
        uvs = []
        # Top surface vertices
        for i in range(H):
            for j in range(W):
                x = j * pixel_size
                y = (H - 1 - i) * pixel_size  # flip y so image top is front
                vertices.append([x, y, z_top[i, j]])
                uvs.append([j / (W - 1), i / (H - 1)])
        # Bottom surface vertices (z = 0)
        for i in range(H):
            for j in range(W):
                x = j * pixel_size
                y = (H - 1 - i) * pixel_size
                vertices.append([x, y, 0.0])
                uvs.append([j / (W - 1), i / (H - 1)])

        vertices = np.array(vertices, dtype=np.float32)
        uvs = np.array(uvs, dtype=np.float32)

        def vidx(i: int, j: int, top: bool = True) -> int:
            return (0 if top else H * W) + i * W + j

        faces: list[list[int]] = []

        # Top surface triangles
        for i in range(H - 1):
            for j in range(W - 1):
                faces.append([vidx(i, j), vidx(i + 1, j), vidx(i + 1, j + 1)])
                faces.append([vidx(i, j), vidx(i + 1, j + 1), vidx(i, j + 1)])

        # Bottom surface triangles (reverse winding)
        for i in range(H - 1):
            for j in range(W - 1):
                faces.append([vidx(i, j, False), vidx(i + 1, j + 1, False), vidx(i + 1, j, False)])
                faces.append([vidx(i, j, False), vidx(i, j + 1, False), vidx(i + 1, j + 1, False)])

        # Side walls
        for i in range(H - 1):
            # Left wall
            faces.append([vidx(i, 0), vidx(i + 1, 0, False), vidx(i + 1, 0)])
            faces.append([vidx(i, 0), vidx(i, 0, False), vidx(i + 1, 0, False)])
            # Right wall
            faces.append([vidx(i, W - 1), vidx(i + 1, W - 1), vidx(i + 1, W - 1, False)])
            faces.append([vidx(i, W - 1), vidx(i + 1, W - 1, False), vidx(i, W - 1, False)])

        for j in range(W - 1):
            # Front wall (image top)
            faces.append([vidx(0, j), vidx(0, j + 1), vidx(0, j + 1, False)])
            faces.append([vidx(0, j), vidx(0, j + 1, False), vidx(0, j, False)])
            # Back wall (image bottom)
            faces.append([vidx(H - 1, j), vidx(H - 1, j + 1, False), vidx(H - 1, j + 1)])
            faces.append([vidx(H - 1, j), vidx(H - 1, j, False), vidx(H - 1, j + 1, False)])

        faces = np.array(faces, dtype=np.int64)

        if shape == "circular":
            cx = (W - 1) * pixel_size / 2.0
            cy = (H - 1) * pixel_size / 2.0
            radius = min(cx, cy)
            keep = ((vertices[:, 0] - cx) ** 2 + (vertices[:, 1] - cy) ** 2) <= radius ** 2
            face_keep = keep[faces].all(axis=1)
            faces = faces[face_keep]

        mesh = trimesh.Trimesh(
            vertices=vertices,
            faces=faces,
            visual=trimesh.visual.TextureVisuals(uv=uvs),
            process=True,
        )

        if color_image is not None:
            try:
                color_img = Image.open(color_image).convert("RGB")
                # Resize to the relief grid resolution so UV maps cleanly 1:1.
                color_img = color_img.resize((W, H), Image.Resampling.LANCZOS)
                material = trimesh.visual.material.SimpleMaterial(image=color_img)
                mesh.visual.material = material
            except Exception as exc:
                warnings.warn(f"Could not bake color texture onto relief: {exc}")

        if smooth_iterations > 0:
            try:
                mesh = mesh.smoothed(iterations=smooth_iterations)
            except Exception:
                warnings.warn("Mesh smoothing failed; returning unsmoothed mesh")

        # Best-effort watertight repair (important after circular clipping).
        try:
            mesh.fill_holes()
        except Exception:
            pass

        if output_path is None:
            output_path = depth_path.parent / "relief.stl"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Always export a watertight STL for monochrome 3D printing.
        mesh.export(output_path)

        # Export a textured GLB for full-color preview / full-color printing.
        glb_path = output_path.with_suffix(".glb")
        mesh.export(glb_path)

        return MeshAsset(mesh_path=glb_path)
