#!/usr/bin/env python3
"""Radeon/ROCm storyboard generation and fail-closed editorial acceptance.

The module is self-contained so it can be embedded in an AAHJ Radeon Cloud
execution package. PyTorch and Diffusers are imported only for a real GPU run;
manifest validation, review validation, finalization, and unit tests remain
CPU-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


SCHEMA_VERSION = "aahj.amd-story-studio/v2"
REPORT_SCHEMA_VERSION = "aahj.amd-story-studio-report/v2"
REVIEW_SCHEMA_VERSION = "aahj.amd-story-studio-review/v1"
ACCEPTANCE_SCHEMA_VERSION = "aahj.amd-story-studio-acceptance/v1"
REJECTED_SCHEMA_VERSION = "aahj.amd-story-studio-rejections/v1"
_HEX_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STATUS_VALUES = {"pass", "reject", "pending"}
_CONTENT_CLASSES = {
    "reference_character",
    "hazard_only",
    "character_only",
    "character_with_adult",
}
_GENERATION_MODES = {"text_to_image", "image_to_image"}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _required_text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _optional_text(name: str, value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value.strip()


def _bounded_int(name: str, value: Any, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _bounded_float(
    name: str,
    value: Any,
    minimum: float,
    maximum: float,
) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if number < minimum or number > maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return number


def _required_bool(name: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be true or false")
    return value


def _safe_identifier(name: str, value: Any) -> str:
    text = _required_text(name, value)
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}", text):
        raise ValueError(
            f"{name} must contain only lowercase letters, digits, '.', '_' or '-'"
        )
    return text


def _mapping_get(value: Mapping[str, Any], parent: str, child: str) -> Any:
    nested = value.get(parent)
    if not isinstance(nested, Mapping):
        raise ValueError(f"{parent} must be an object")
    return nested.get(child)


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * percentile
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


@dataclass(frozen=True)
class ModelConfig:
    model_id: str
    revision: str
    dtype: str
    variant: str | None
    inference_steps: int
    guidance_scale: float
    use_safetensors: bool
    attention_slicing: bool
    warmup_images: int

    @classmethod
    def from_mapping(cls, value: Any) -> "ModelConfig":
        if not isinstance(value, Mapping):
            raise ValueError("model must be an object")
        dtype = _required_text("model.dtype", value.get("dtype", "float16"))
        if dtype not in {"float16", "bfloat16", "float32"}:
            raise ValueError("model.dtype must be float16, bfloat16 or float32")
        variant = value.get("variant")
        if variant is not None:
            variant = _required_text("model.variant", variant)
        return cls(
            model_id=_required_text("model.id", value.get("id")),
            revision=_required_text(
                "model.revision", value.get("revision", "main")
            ),
            dtype=dtype,
            variant=variant,
            inference_steps=_bounded_int(
                "model.inference_steps",
                value.get("inference_steps", 4),
                1,
                100,
            ),
            guidance_scale=_bounded_float(
                "model.guidance_scale",
                value.get("guidance_scale", 0.0),
                0.0,
                30.0,
            ),
            use_safetensors=value.get("use_safetensors", True) is not False,
            attention_slicing=value.get("attention_slicing", False) is True,
            warmup_images=_bounded_int(
                "model.warmup_images",
                value.get("warmup_images", 1),
                0,
                4,
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.model_id,
            "revision": self.revision,
            "dtype": self.dtype,
            "variant": self.variant,
            "inference_steps": self.inference_steps,
            "guidance_scale": self.guidance_scale,
            "use_safetensors": self.use_safetensors,
            "attention_slicing": self.attention_slicing,
            "warmup_images": self.warmup_images,
        }


@dataclass(frozen=True)
class Scene:
    scene_id: str
    label: str
    prompt: str
    seed: int
    variants: int
    generation_mode: str
    reference_scene_id: str | None
    strength: float | None
    content_class: str
    include_in_storyboard: bool
    required_review_checks: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Any, index: int) -> "Scene":
        if not isinstance(value, Mapping):
            raise ValueError(f"scenes[{index}] must be an object")
        generation_mode = _required_text(
            f"scenes[{index}].generation_mode",
            value.get("generation_mode", "text_to_image"),
        )
        if generation_mode not in _GENERATION_MODES:
            allowed = ", ".join(sorted(_GENERATION_MODES))
            raise ValueError(
                f"scenes[{index}].generation_mode must be one of: {allowed}"
            )
        reference_scene_id = value.get("reference_scene_id")
        strength = value.get("strength")
        if generation_mode == "image_to_image":
            reference_scene_id = _safe_identifier(
                f"scenes[{index}].reference_scene_id", reference_scene_id
            )
            strength = _bounded_float(
                f"scenes[{index}].strength",
                0.45 if strength is None else strength,
                0.05,
                0.95,
            )
        elif reference_scene_id is not None or strength is not None:
            raise ValueError(
                f"scenes[{index}] text_to_image cannot declare a reference or strength"
            )
        content_class = _required_text(
            f"scenes[{index}].content_class", value.get("content_class")
        )
        if content_class not in _CONTENT_CLASSES:
            allowed = ", ".join(sorted(_CONTENT_CLASSES))
            raise ValueError(
                f"scenes[{index}].content_class must be one of: {allowed}"
            )
        raw_checks = value.get(
            "required_review_checks",
            ["safety", "semantic", "continuity"],
        )
        if not isinstance(raw_checks, list) or not raw_checks:
            raise ValueError(
                f"scenes[{index}].required_review_checks must be a non-empty array"
            )
        checks: list[str] = []
        for check_index, raw_check in enumerate(raw_checks):
            check = _safe_identifier(
                f"scenes[{index}].required_review_checks[{check_index}]",
                raw_check,
            )
            if check not in {"safety", "semantic", "continuity"}:
                raise ValueError(
                    "required review checks are safety, semantic and continuity"
                )
            if check not in checks:
                checks.append(check)
        include = value.get("include_in_storyboard", True)
        return cls(
            scene_id=_safe_identifier(
                f"scenes[{index}].scene_id", value.get("scene_id")
            ),
            label=_required_text(f"scenes[{index}].label", value.get("label")),
            prompt=_required_text(f"scenes[{index}].prompt", value.get("prompt")),
            seed=_bounded_int(
                f"scenes[{index}].seed",
                value.get("seed"),
                0,
                2**63 - 1,
            ),
            variants=_bounded_int(
                f"scenes[{index}].variants",
                value.get("variants", 2),
                1,
                8,
            ),
            generation_mode=generation_mode,
            reference_scene_id=reference_scene_id,
            strength=strength,
            content_class=content_class,
            include_in_storyboard=_required_bool(
                f"scenes[{index}].include_in_storyboard", include
            ),
            required_review_checks=tuple(checks),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "label": self.label,
            "prompt": self.prompt,
            "seed": self.seed,
            "variants": self.variants,
            "generation_mode": self.generation_mode,
            "reference_scene_id": self.reference_scene_id,
            "strength": self.strength,
            "content_class": self.content_class,
            "include_in_storyboard": self.include_in_storyboard,
            "required_review_checks": list(self.required_review_checks),
        }


@dataclass(frozen=True)
class AssemblyConfig:
    require_single_lineage: bool
    require_modular_safety_partition: bool

    @classmethod
    def from_mapping(cls, value: Any) -> "AssemblyConfig":
        if not isinstance(value, Mapping):
            raise ValueError("assembly must be an object")
        return cls(
            require_single_lineage=_required_bool(
                "assembly.require_single_lineage",
                value.get("require_single_lineage", True),
            ),
            require_modular_safety_partition=_required_bool(
                "assembly.require_modular_safety_partition",
                value.get("require_modular_safety_partition", True),
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "require_single_lineage": self.require_single_lineage,
            "require_modular_safety_partition": (
                self.require_modular_safety_partition
            ),
        }


@dataclass(frozen=True)
class StoryStudioManifest:
    project_id: str
    title: str
    model: ModelConfig
    width: int
    height: int
    style_prompt: str
    negative_prompt: str
    scenes: tuple[Scene, ...]
    assembly: AssemblyConfig
    schema_version: str = SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, value: Any) -> "StoryStudioManifest":
        if not isinstance(value, Mapping):
            raise ValueError("manifest must be an object")
        if value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
        model = ModelConfig.from_mapping(value.get("model"))
        negative_prompt = _optional_text(
            "negative_prompt", value.get("negative_prompt", "")
        )
        if negative_prompt and model.guidance_scale <= 1.0:
            raise ValueError(
                "negative_prompt is ineffective when guidance_scale <= 1.0; "
                "use modular prompts and fail-closed review instead"
            )
        raw_scenes = value.get("scenes")
        if not isinstance(raw_scenes, list) or not raw_scenes:
            raise ValueError("scenes must be a non-empty array")
        scenes = tuple(
            Scene.from_mapping(item, index)
            for index, item in enumerate(raw_scenes)
        )
        scene_ids = [scene.scene_id for scene in scenes]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("scene_id values must be unique")
        seen: set[str] = set()
        for scene in scenes:
            if scene.reference_scene_id is not None:
                if scene.reference_scene_id not in seen:
                    raise ValueError(
                        f"scene {scene.scene_id} must reference an earlier scene"
                    )
                reference = next(
                    item
                    for item in scenes
                    if item.scene_id == scene.reference_scene_id
                )
                if reference.variants != scene.variants:
                    raise ValueError(
                        f"scene {scene.scene_id} and its reference must have "
                        "the same variant count"
                    )
            seen.add(scene.scene_id)
        width = _bounded_int(
            "canvas.width",
            _mapping_get(value, "canvas", "width"),
            256,
            2048,
        )
        height = _bounded_int(
            "canvas.height",
            _mapping_get(value, "canvas", "height"),
            256,
            2048,
        )
        if width % 8 or height % 8:
            raise ValueError("canvas width and height must be divisible by 8")
        assembly = AssemblyConfig.from_mapping(value.get("assembly", {}))
        if assembly.require_modular_safety_partition:
            for scene in scenes:
                if scene.content_class == "hazard_only" and scene.reference_scene_id:
                    raise ValueError(
                        "hazard-only scenes cannot be image-conditioned on a "
                        "character scene"
                    )
        return cls(
            project_id=_safe_identifier("project_id", value.get("project_id")),
            title=_required_text("title", value.get("title")),
            model=model,
            width=width,
            height=height,
            style_prompt=_required_text("style_prompt", value.get("style_prompt")),
            negative_prompt=negative_prompt,
            scenes=scenes,
            assembly=assembly,
        )

    @classmethod
    def from_path(cls, path: Path) -> "StoryStudioManifest":
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError(f"missing manifest: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in {path}: {exc}") from exc
        return cls.from_mapping(value)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "title": self.title,
            "model": self.model.as_dict(),
            "canvas": {"width": self.width, "height": self.height},
            "style_prompt": self.style_prompt,
            "negative_prompt": self.negative_prompt,
            "scenes": [scene.as_dict() for scene in self.scenes],
            "assembly": self.assembly.as_dict(),
        }

    @property
    def manifest_id(self) -> str:
        return sha256_bytes(canonical_json(self.as_dict()).encode("utf-8"))

    @property
    def total_images(self) -> int:
        return sum(scene.variants for scene in self.scenes)


class ImageRuntime(Protocol):
    def runtime_evidence(self) -> Mapping[str, Any]: ...

    def load(self, model: ModelConfig) -> Mapping[str, Any]: ...

    def generate_text(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        seed: int,
        width: int,
        height: int,
        inference_steps: int,
        guidance_scale: float,
    ) -> Any: ...

    def generate_image(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        reference_image: Any,
        strength: float,
        seed: int,
        width: int,
        height: int,
        inference_steps: int,
        guidance_scale: float,
    ) -> Any: ...

    def synchronize(self) -> None: ...

    def reset_peak_memory(self) -> None: ...

    def peak_memory(self) -> Mapping[str, Any]: ...


class DiffusersRocmRuntime:
    """PyTorch + Diffusers runtime with mandatory AMD ROCm evidence."""

    def __init__(self) -> None:
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("PyTorch is required for the Radeon run") from exc
        self.torch = torch
        self.text_pipeline: Any | None = None
        self.image_pipeline: Any | None = None
        self.resolved_revision: str | None = None
        self._validate_rocm()

    def _validate_rocm(self) -> None:
        torch = self.torch
        if not torch.cuda.is_available():
            raise RuntimeError("PyTorch cannot see an AMD Radeon GPU")
        hip_version = getattr(torch.version, "hip", None)
        if not isinstance(hip_version, str) or not hip_version:
            raise RuntimeError("PyTorch is not a ROCm/HIP build")
        if torch.cuda.device_count() < 1:
            raise RuntimeError("no ROCm device is available")

    def runtime_evidence(self) -> Mapping[str, Any]:
        torch = self.torch
        properties = torch.cuda.get_device_properties(0)
        return {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "torch_version": str(torch.__version__),
            "hip_version": str(torch.version.hip),
            "device_name": str(torch.cuda.get_device_name(0)),
            "device_count": int(torch.cuda.device_count()),
            "total_memory_bytes": int(properties.total_memory),
            "architecture": str(getattr(properties, "gcnArchName", "unknown")),
            "device_api": "torch.cuda backed by ROCm/HIP",
        }

    def _component_dtype(self, component: Any) -> str | None:
        if component is None:
            return None
        try:
            parameter = next(component.parameters())
        except (AttributeError, StopIteration):
            return None
        return str(parameter.dtype).removeprefix("torch.")

    def load(self, model: ModelConfig) -> Mapping[str, Any]:
        try:
            from diffusers import AutoPipelineForText2Image
            from huggingface_hub import HfApi
        except ImportError as exc:
            raise RuntimeError(
                "Diffusers and huggingface-hub are required; install "
                "requirements-amd-hackathon.txt into the ROCm Python environment"
            ) from exc

        revision = model.revision
        if not _HEX_REVISION.fullmatch(revision):
            revision = str(
                HfApi().model_info(model.model_id, revision=revision).sha
            )
        if not _HEX_REVISION.fullmatch(revision):
            raise RuntimeError(
                "Hugging Face did not resolve an immutable model revision"
            )

        requested_dtype = getattr(self.torch, model.dtype)
        kwargs: dict[str, Any] = {
            "revision": revision,
            "torch_dtype": requested_dtype,
            "use_safetensors": model.use_safetensors,
        }
        if model.variant is not None:
            kwargs["variant"] = model.variant

        started = time.monotonic()
        pipeline = AutoPipelineForText2Image.from_pretrained(
            model.model_id,
            **kwargs,
        )
        pipeline.to("cuda")
        # Keep the VAE in the model's loaded dtype. SDXL performs any required
        # decode-time upcast together with the latent cast; eagerly converting
        # only the VAE produces a Half-input/float-bias mismatch on ROCm.
        pipeline.set_progress_bar_config(disable=True)
        if model.attention_slicing:
            pipeline.enable_attention_slicing()
        self.synchronize()
        elapsed = time.monotonic() - started
        self.text_pipeline = pipeline
        self.resolved_revision = revision

        component_dtypes = {
            "unet": self._component_dtype(getattr(pipeline, "unet", None)),
            "text_encoder": self._component_dtype(
                getattr(pipeline, "text_encoder", None)
            ),
            "text_encoder_2": self._component_dtype(
                getattr(pipeline, "text_encoder_2", None)
            ),
            "vae": self._component_dtype(getattr(pipeline, "vae", None)),
        }
        core_values = [
            value
            for key, value in component_dtypes.items()
            if key != "vae" and value is not None
        ]
        verified_core_dtype = bool(core_values) and all(
            value == model.dtype for value in core_values
        )
        return {
            "resolved_revision": revision,
            "load_seconds": round(elapsed, 6),
            "requested_dtype": model.dtype,
            "component_dtypes": component_dtypes,
            "verified_core_dtype": verified_core_dtype,
            "vae_upcast_is_explicit": component_dtypes["vae"] == "float32",
        }

    def _base_kwargs(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        seed: int,
        width: int,
        height: int,
        inference_steps: int,
        guidance_scale: float,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "prompt": prompt,
            "generator": self.torch.Generator(device="cuda").manual_seed(seed),
            "width": width,
            "height": height,
            "num_inference_steps": inference_steps,
            "guidance_scale": guidance_scale,
        }
        if negative_prompt:
            kwargs["negative_prompt"] = negative_prompt
        return kwargs

    def generate_text(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        seed: int,
        width: int,
        height: int,
        inference_steps: int,
        guidance_scale: float,
    ) -> Any:
        if self.text_pipeline is None:
            raise RuntimeError("model pipeline is not loaded")
        kwargs = self._base_kwargs(
            prompt=prompt,
            negative_prompt=negative_prompt,
            seed=seed,
            width=width,
            height=height,
            inference_steps=inference_steps,
            guidance_scale=guidance_scale,
        )
        with self.torch.inference_mode():
            result = self.text_pipeline(**kwargs)
        if not getattr(result, "images", None):
            raise RuntimeError("Diffusers returned no images")
        return result.images[0]

    def generate_image(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        reference_image: Any,
        strength: float,
        seed: int,
        width: int,
        height: int,
        inference_steps: int,
        guidance_scale: float,
    ) -> Any:
        if self.text_pipeline is None:
            raise RuntimeError("model pipeline is not loaded")
        if self.image_pipeline is None:
            try:
                from diffusers import AutoPipelineForImage2Image
            except ImportError as exc:
                raise RuntimeError("Diffusers image-to-image support is missing") from exc
            self.image_pipeline = AutoPipelineForImage2Image.from_pipe(
                self.text_pipeline
            )
            self.image_pipeline.set_progress_bar_config(disable=True)
        kwargs = self._base_kwargs(
            prompt=prompt,
            negative_prompt=negative_prompt,
            seed=seed,
            width=width,
            height=height,
            inference_steps=inference_steps,
            guidance_scale=guidance_scale,
        )
        kwargs.update({"image": reference_image, "strength": strength})
        with self.torch.inference_mode():
            result = self.image_pipeline(**kwargs)
        if not getattr(result, "images", None):
            raise RuntimeError("Diffusers returned no images")
        return result.images[0]

    def synchronize(self) -> None:
        self.torch.cuda.synchronize()

    def reset_peak_memory(self) -> None:
        self.torch.cuda.empty_cache()
        self.torch.cuda.reset_peak_memory_stats(0)

    def peak_memory(self) -> Mapping[str, Any]:
        return {
            "max_memory_allocated_bytes": int(
                self.torch.cuda.max_memory_allocated(0)
            ),
            "max_memory_reserved_bytes": int(
                self.torch.cuda.max_memory_reserved(0)
            ),
        }


def _combined_prompt(manifest: StoryStudioManifest, scene: Scene) -> str:
    return f"{scene.prompt.strip()}, {manifest.style_prompt.strip()}"


def _save_image(image: Any, path: Path, metadata: Mapping[str, str]) -> None:
    try:
        from PIL.PngImagePlugin import PngInfo
    except ImportError as exc:
        raise RuntimeError("Pillow is required to save generated images") from exc
    info = PngInfo()
    for key, value in sorted(metadata.items()):
        info.add_text(key, value)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", pnginfo=info, optimize=False)


def _load_reference(path: Path, width: int, height: int) -> Any:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RuntimeError("Pillow is required for image-to-image generation") from exc
    with Image.open(path) as source:
        return ImageOps.fit(source.convert("RGB"), (width, height))


def _write_contact_sheet(
    records: Sequence[Mapping[str, Any]],
    output_directory: Path,
    destination: Path,
) -> None:
    try:
        from PIL import Image, ImageDraw, ImageOps
    except ImportError as exc:
        raise RuntimeError("Pillow is required to create the contact sheet") from exc
    columns = min(3, max(1, len(records)))
    tile_width = 320
    label_height = 34
    opened: list[Any] = []
    try:
        tiles: list[Any] = []
        for record in records:
            image = Image.open(output_directory / str(record["output"])).convert("RGB")
            opened.append(image)
            tile_height = max(1, round(image.height * tile_width / image.width))
            fitted = ImageOps.fit(image, (tile_width, tile_height))
            tile = Image.new("RGB", (tile_width, label_height + tile_height), "white")
            draw = ImageDraw.Draw(tile)
            draw.text(
                (6, 8),
                f'{record["scene_id"]} · lineage {record["lineage"]}',
                fill="black",
            )
            tile.paste(fitted, (0, label_height))
            tiles.append(tile)
        rows = (len(tiles) + columns - 1) // columns
        tile_height = max(tile.height for tile in tiles)
        sheet = Image.new(
            "RGB",
            (columns * tile_width, rows * tile_height),
            "white",
        )
        for index, tile in enumerate(tiles):
            x = (index % columns) * tile_width
            y = (index // columns) * tile_height
            sheet.paste(tile, (x, y))
        destination.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(destination, format="PNG", optimize=False)
    finally:
        for image in opened:
            image.close()


def _candidate_id(scene_id: str, lineage: int) -> str:
    return f"{scene_id}.lineage-{lineage:02d}"


def _technical_acceptance(
    manifest: StoryStudioManifest,
    runtime_evidence: Mapping[str, Any],
    model_evidence: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    checks = {
        "rocm_hip_reported": bool(runtime_evidence.get("hip_version")),
        "radeon_device_reported": "radeon"
        in str(runtime_evidence.get("device_name", "")).lower(),
        "immutable_model_revision": bool(
            _HEX_REVISION.fullmatch(
                str(model_evidence.get("resolved_revision", ""))
            )
        ),
        "requested_core_dtype_verified": bool(
            model_evidence.get("verified_core_dtype")
        ),
        "expected_candidate_count": len(records) == manifest.total_images,
        "all_outputs_hash_recorded": all(
            _SHA256.fullmatch(str(record.get("output_sha256", "")))
            for record in records
        ),
    }
    return {
        "status": "pass" if all(checks.values()) else "reject",
        "checks": checks,
    }


def _review_template(
    manifest: StoryStudioManifest,
    report: Mapping[str, Any],
) -> dict[str, Any]:
    scene_by_id = {scene.scene_id: scene for scene in manifest.scenes}
    decisions = []
    for record in report["outputs"]:
        scene = scene_by_id[str(record["scene_id"])]
        decisions.append(
            {
                "candidate_id": record["candidate_id"],
                "scene_id": record["scene_id"],
                "lineage": record["lineage"],
                "output_sha256": record["output_sha256"],
                "technical": "pass",
                "safety": "pending",
                "semantic": "pending",
                "continuity": "pending",
                "selected": False,
                "reasons": [],
                "required_checks": list(scene.required_review_checks),
            }
        )
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "manifest_id": manifest.manifest_id,
        "run_report_id": report["report_id"],
        "reviewer": "",
        "reviewed_at": None,
        "decisions": decisions,
    }


def run_story_studio(
    manifest: StoryStudioManifest,
    output_directory: Path,
    *,
    runtime: ImageRuntime | None = None,
) -> Path:
    runtime = runtime or DiffusersRocmRuntime()
    output_directory = output_directory.expanduser().resolve()
    if output_directory.exists() and any(output_directory.iterdir()):
        raise ValueError(f"output directory must be empty: {output_directory}")
    output_directory.mkdir(parents=True, exist_ok=True)

    started_wall = datetime.now(timezone.utc)
    runtime_evidence = dict(runtime.runtime_evidence())
    model_evidence = dict(runtime.load(manifest.model))
    runtime.reset_peak_memory()

    warmup_records: list[dict[str, Any]] = []
    first_scene = manifest.scenes[0]
    first_prompt = _combined_prompt(manifest, first_scene)
    for warmup_index in range(manifest.model.warmup_images):
        seed = first_scene.seed + 10_000_000 + warmup_index
        runtime.synchronize()
        warmup_started = time.monotonic()
        image = runtime.generate_text(
            prompt=first_prompt,
            negative_prompt=manifest.negative_prompt,
            seed=seed,
            width=manifest.width,
            height=manifest.height,
            inference_steps=manifest.model.inference_steps,
            guidance_scale=manifest.model.guidance_scale,
        )
        runtime.synchronize()
        elapsed = time.monotonic() - warmup_started
        relative = Path("evidence") / f"warmup-{warmup_index + 1:02d}.png"
        destination = output_directory / relative
        _save_image(
            image,
            destination,
            {
                "aahj_manifest_id": manifest.manifest_id,
                "aahj_purpose": "unmeasured-warmup",
                "aahj_seed": str(seed),
            },
        )
        warmup_records.append(
            {
                "seed": seed,
                "elapsed_seconds": round(elapsed, 6),
                "output": relative.as_posix(),
                "output_sha256": sha256_file(destination),
                "size_bytes": destination.stat().st_size,
            }
        )

    records: list[dict[str, Any]] = []
    candidate_paths: dict[str, Path] = {}
    measured_started = time.monotonic()
    for scene in manifest.scenes:
        prompt = _combined_prompt(manifest, scene)
        for lineage in range(1, scene.variants + 1):
            seed = scene.seed + lineage - 1
            reference_path: Path | None = None
            runtime.synchronize()
            started = time.monotonic()
            if scene.generation_mode == "text_to_image":
                image = runtime.generate_text(
                    prompt=prompt,
                    negative_prompt=manifest.negative_prompt,
                    seed=seed,
                    width=manifest.width,
                    height=manifest.height,
                    inference_steps=manifest.model.inference_steps,
                    guidance_scale=manifest.model.guidance_scale,
                )
            else:
                assert scene.reference_scene_id is not None
                reference_id = _candidate_id(scene.reference_scene_id, lineage)
                reference_path = candidate_paths.get(reference_id)
                if reference_path is None:
                    raise RuntimeError(
                        f"missing generated reference candidate: {reference_id}"
                    )
                reference_image = _load_reference(
                    reference_path,
                    manifest.width,
                    manifest.height,
                )
                try:
                    image = runtime.generate_image(
                        prompt=prompt,
                        negative_prompt=manifest.negative_prompt,
                        reference_image=reference_image,
                        strength=float(scene.strength),
                        seed=seed,
                        width=manifest.width,
                        height=manifest.height,
                        inference_steps=manifest.model.inference_steps,
                        guidance_scale=manifest.model.guidance_scale,
                    )
                finally:
                    close = getattr(reference_image, "close", None)
                    if callable(close):
                        close()
            runtime.synchronize()
            elapsed = time.monotonic() - started
            candidate_id = _candidate_id(scene.scene_id, lineage)
            relative = Path("candidates") / f"{candidate_id}.png"
            destination = output_directory / relative
            _save_image(
                image,
                destination,
                {
                    "aahj_candidate_id": candidate_id,
                    "aahj_content_class": scene.content_class,
                    "aahj_lineage": str(lineage),
                    "aahj_manifest_id": manifest.manifest_id,
                    "aahj_prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
                    "aahj_scene_id": scene.scene_id,
                    "aahj_seed": str(seed),
                },
            )
            candidate_paths[candidate_id] = destination
            records.append(
                {
                    "candidate_id": candidate_id,
                    "scene_id": scene.scene_id,
                    "label": scene.label,
                    "lineage": lineage,
                    "seed": seed,
                    "generation_mode": scene.generation_mode,
                    "reference_candidate_id": (
                        _candidate_id(scene.reference_scene_id, lineage)
                        if scene.reference_scene_id is not None
                        else None
                    ),
                    "strength": scene.strength,
                    "content_class": scene.content_class,
                    "include_in_storyboard": scene.include_in_storyboard,
                    "prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
                    "negative_prompt_sha256": (
                        sha256_bytes(manifest.negative_prompt.encode("utf-8"))
                        if manifest.negative_prompt
                        else None
                    ),
                    "negative_prompt_applied": bool(manifest.negative_prompt),
                    "elapsed_seconds": round(elapsed, 6),
                    "output": relative.as_posix(),
                    "output_sha256": sha256_file(destination),
                    "size_bytes": destination.stat().st_size,
                }
            )
    runtime.synchronize()
    measured_seconds = time.monotonic() - measured_started

    contact_sheet = output_directory / "contact-sheet.png"
    _write_contact_sheet(records, output_directory, contact_sheet)
    ended_wall = datetime.now(timezone.utc)
    candidate_times = [float(record["elapsed_seconds"]) for record in records]
    technical = _technical_acceptance(
        manifest,
        runtime_evidence,
        model_evidence,
        records,
    )
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "manifest_id": manifest.manifest_id,
        "project_id": manifest.project_id,
        "title": manifest.title,
        "plan_id": os.environ.get("AAHJ_PLAN_ID"),
        "package_id": os.environ.get("AAHJ_PACKAGE_ID"),
        "started_at": started_wall.isoformat(),
        "completed_at": ended_wall.isoformat(),
        "model": {**manifest.model.as_dict(), **model_evidence},
        "runtime": runtime_evidence,
        "performance": {
            "candidate_count": len(records),
            "warmup_count": len(warmup_records),
            "warmup_seconds": round(
                sum(item["elapsed_seconds"] for item in warmup_records),
                6,
            ),
            "measured_inference_seconds": round(measured_seconds, 6),
            "mean_candidate_seconds": round(
                statistics.fmean(candidate_times) if candidate_times else 0.0,
                6,
            ),
            "median_candidate_seconds": round(
                statistics.median(candidate_times) if candidate_times else 0.0,
                6,
            ),
            "p95_candidate_seconds": round(
                _percentile(candidate_times, 0.95),
                6,
            ),
            "candidates_per_minute": round(
                (len(records) * 60.0 / measured_seconds)
                if measured_seconds > 0
                else 0.0,
                6,
            ),
            **dict(runtime.peak_memory()),
        },
        "warmup": warmup_records,
        "outputs": records,
        "contact_sheet": {
            "path": contact_sheet.relative_to(output_directory).as_posix(),
            "sha256": sha256_file(contact_sheet),
            "size_bytes": contact_sheet.stat().st_size,
        },
        "acceptance": {
            "technical": technical,
            "safety": {"status": "pending"},
            "semantic": {"status": "pending"},
            "continuity": {"status": "pending"},
            "overall": "pending" if technical["status"] == "pass" else "reject",
        },
    }
    report_without_id = dict(report)
    report["report_id"] = sha256_bytes(
        canonical_json(report_without_id).encode("utf-8")
    )
    report_path = output_directory / "run-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    review_path = output_directory / "review-template.json"
    review_path.write_text(
        json.dumps(_review_template(manifest, report), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return report_path


def _load_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {label} {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _verify_report_id(report: Mapping[str, Any]) -> None:
    report_id = report.get("report_id")
    if not isinstance(report_id, str):
        raise ValueError("run report has no report_id")
    without_id = dict(report)
    without_id.pop("report_id", None)
    expected = sha256_bytes(canonical_json(without_id).encode("utf-8"))
    if report_id != expected:
        raise ValueError("run report identity does not match its contents")


def _decision_status(decision: Mapping[str, Any], name: str) -> str:
    value = decision.get(name)
    if value not in _STATUS_VALUES:
        raise ValueError(
            f"decision {decision.get('candidate_id')} has invalid {name} status"
        )
    return str(value)


def _write_final_storyboard(
    selected: Sequence[tuple[Scene, Mapping[str, Any], Path]],
    destination: Path,
) -> None:
    try:
        from PIL import Image, ImageDraw, ImageOps
    except ImportError as exc:
        raise RuntimeError("Pillow is required to assemble the storyboard") from exc
    included = [item for item in selected if item[0].include_in_storyboard]
    if not included:
        raise ValueError("no selected scenes are included in the storyboard")
    tile_width = 512
    tile_height = 512
    header_height = 48
    gap = 16
    canvas = Image.new(
        "RGB",
        (
            gap + len(included) * (tile_width + gap),
            header_height + tile_height + gap,
        ),
        "white",
    )
    draw = ImageDraw.Draw(canvas)
    for index, (scene, _record, path) in enumerate(included):
        x = gap + index * (tile_width + gap)
        draw.text((x, 16), scene.label, fill="black")
        with Image.open(path) as source:
            image = ImageOps.fit(source.convert("RGB"), (tile_width, tile_height))
            canvas.paste(image, (x, header_height))
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, format="PNG", optimize=False)


def finalize_storyboard(
    manifest: StoryStudioManifest,
    run_report_path: Path,
    review_path: Path,
    output_directory: Path,
) -> Path:
    run_report_path = run_report_path.expanduser().resolve()
    review_path = review_path.expanduser().resolve()
    output_directory = output_directory.expanduser().resolve()
    if output_directory.exists() and any(output_directory.iterdir()):
        raise ValueError(f"output directory must be empty: {output_directory}")
    report = _load_json(run_report_path, "run report")
    review = _load_json(review_path, "review")
    _verify_report_id(report)
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise ValueError("unsupported run report schema")
    if report.get("manifest_id") != manifest.manifest_id:
        raise ValueError("run report does not belong to this manifest")
    technical = report.get("acceptance", {}).get("technical", {})
    if not isinstance(technical, Mapping) or technical.get("status") != "pass":
        raise ValueError("technical acceptance must pass before finalization")
    if review.get("schema_version") != REVIEW_SCHEMA_VERSION:
        raise ValueError("unsupported review schema")
    if review.get("manifest_id") != manifest.manifest_id:
        raise ValueError("review does not belong to this manifest")
    if review.get("run_report_id") != report.get("report_id"):
        raise ValueError("review does not belong to this run report")
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("reviewer is required")
    reviewed_at = review.get("reviewed_at")
    if not isinstance(reviewed_at, str) or not reviewed_at.strip():
        raise ValueError("reviewed_at is required")

    raw_records = report.get("outputs")
    raw_decisions = review.get("decisions")
    if not isinstance(raw_records, list) or not isinstance(raw_decisions, list):
        raise ValueError("run outputs and review decisions must be arrays")
    records = {
        str(record.get("candidate_id")): record
        for record in raw_records
        if isinstance(record, Mapping)
    }
    decisions = {
        str(decision.get("candidate_id")): decision
        for decision in raw_decisions
        if isinstance(decision, Mapping)
    }
    if set(records) != set(decisions):
        raise ValueError("review decisions must exactly cover run candidates")

    run_root = run_report_path.parent
    scene_by_id = {scene.scene_id: scene for scene in manifest.scenes}
    selected: list[tuple[Scene, Mapping[str, Any], Path]] = []
    rejected: list[dict[str, Any]] = []
    for candidate_id, record in records.items():
        decision = decisions[candidate_id]
        if decision.get("output_sha256") != record.get("output_sha256"):
            raise ValueError(f"review hash mismatch for {candidate_id}")
        if decision.get("technical") != "pass":
            raise ValueError(f"technical status changed for {candidate_id}")
        scene_id = str(record.get("scene_id"))
        scene = scene_by_id.get(scene_id)
        if scene is None:
            raise ValueError(f"unknown scene in run report: {scene_id}")
        statuses = {
            name: _decision_status(decision, name)
            for name in ("safety", "semantic", "continuity")
        }
        reasons = decision.get("reasons", [])
        if not isinstance(reasons, list) or any(
            not isinstance(item, str) or not item.strip() for item in reasons
        ):
            raise ValueError(f"reasons for {candidate_id} must be text entries")
        selected_flag = decision.get("selected")
        if not isinstance(selected_flag, bool):
            raise ValueError(f"selected for {candidate_id} must be true or false")
        output_path = run_root / str(record.get("output"))
        if not output_path.is_file():
            raise ValueError(f"missing candidate image: {output_path}")
        if sha256_file(output_path) != record.get("output_sha256"):
            raise ValueError(f"candidate image hash mismatch: {candidate_id}")
        if selected_flag:
            for required in scene.required_review_checks:
                if statuses[required] != "pass":
                    raise ValueError(
                        f"selected candidate {candidate_id} has not passed {required}"
                    )
            selected.append((scene, record, output_path))
        else:
            if not reasons:
                raise ValueError(
                    f"non-selected candidate {candidate_id} requires a reason"
                )
            rejected.append(
                {
                    "candidate_id": candidate_id,
                    "scene_id": scene_id,
                    "lineage": record.get("lineage"),
                    "output_sha256": record.get("output_sha256"),
                    "statuses": statuses,
                    "reasons": reasons,
                }
            )

    selected_by_scene: dict[str, tuple[Scene, Mapping[str, Any], Path]] = {}
    for item in selected:
        scene_id = item[0].scene_id
        if scene_id in selected_by_scene:
            raise ValueError(f"multiple candidates selected for scene {scene_id}")
        selected_by_scene[scene_id] = item
    missing_scenes = [
        scene.scene_id
        for scene in manifest.scenes
        if scene.scene_id not in selected_by_scene
    ]
    if missing_scenes:
        raise ValueError(
            "one candidate must be selected for every scene: "
            + ", ".join(missing_scenes)
        )
    ordered_selected = [
        selected_by_scene[scene.scene_id] for scene in manifest.scenes
    ]
    lineages = {int(item[1]["lineage"]) for item in ordered_selected}
    if manifest.assembly.require_single_lineage and len(lineages) != 1:
        raise ValueError("selected candidates must use one consistent lineage")

    output_directory.mkdir(parents=True, exist_ok=True)
    selected_directory = output_directory / "selected"
    selected_directory.mkdir(parents=True, exist_ok=True)
    selected_records: list[dict[str, Any]] = []
    copied: list[tuple[Scene, Mapping[str, Any], Path]] = []
    for scene, record, source in ordered_selected:
        destination = selected_directory / f"{scene.scene_id}.png"
        shutil.copyfile(source, destination)
        copied.append((scene, record, destination))
        selected_records.append(
            {
                "candidate_id": record["candidate_id"],
                "scene_id": scene.scene_id,
                "lineage": record["lineage"],
                "source_sha256": record["output_sha256"],
                "output": destination.relative_to(output_directory).as_posix(),
                "output_sha256": sha256_file(destination),
            }
        )

    storyboard = output_directory / "accepted-storyboard.png"
    _write_final_storyboard(copied, storyboard)
    rejected_path = output_directory / "rejected-candidates.json"
    rejected_path.write_text(
        json.dumps(
            {
                "schema_version": REJECTED_SCHEMA_VERSION,
                "manifest_id": manifest.manifest_id,
                "run_report_id": report["report_id"],
                "images_embedded": False,
                "candidates": rejected,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    acceptance: dict[str, Any] = {
        "schema_version": ACCEPTANCE_SCHEMA_VERSION,
        "manifest_id": manifest.manifest_id,
        "run_report_id": report["report_id"],
        "reviewer": reviewer.strip(),
        "reviewed_at": reviewed_at.strip(),
        "technical": "pass",
        "safety": "pass",
        "semantic": "pass",
        "continuity": "pass",
        "overall": "pass",
        "single_lineage": sorted(lineages),
        "selected": selected_records,
        "rejected_candidate_count": len(rejected),
        "storyboard": {
            "path": storyboard.relative_to(output_directory).as_posix(),
            "sha256": sha256_file(storyboard),
            "size_bytes": storyboard.stat().st_size,
        },
        "rejected_evidence": {
            "path": rejected_path.relative_to(output_directory).as_posix(),
            "sha256": sha256_file(rejected_path),
        },
    }
    without_id = dict(acceptance)
    acceptance["acceptance_id"] = sha256_bytes(
        canonical_json(without_id).encode("utf-8")
    )
    acceptance_path = output_directory / "acceptance-report.json"
    acceptance_path.write_text(
        json.dumps(acceptance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return acceptance_path


def _dump(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AAHJ Radeon Story Studio generator and acceptance gate"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate")
    validate.add_argument("manifest", type=Path)

    run = sub.add_parser("run")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)

    finalize = sub.add_parser("finalize")
    finalize.add_argument("--manifest", type=Path, required=True)
    finalize.add_argument("--run-report", type=Path, required=True)
    finalize.add_argument("--review", type=Path, required=True)
    finalize.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    try:
        manifest = StoryStudioManifest.from_path(args.manifest)
        if args.command == "validate":
            _dump(
                {
                    "schema_version": manifest.schema_version,
                    "manifest_id": manifest.manifest_id,
                    "project_id": manifest.project_id,
                    "scenes": len(manifest.scenes),
                    "total_images": manifest.total_images,
                    "model_id": manifest.model.model_id,
                    "reference_conditioned_scenes": sum(
                        scene.generation_mode == "image_to_image"
                        for scene in manifest.scenes
                    ),
                }
            )
            return 0
        if args.command == "run":
            report = run_story_studio(manifest, args.output)
            _dump(json.loads(report.read_text(encoding="utf-8")))
            return 0
        if args.command == "finalize":
            acceptance = finalize_storyboard(
                manifest,
                args.run_report,
                args.review,
                args.output,
            )
            _dump(json.loads(acceptance.read_text(encoding="utf-8")))
            return 0
        raise AssertionError(args.command)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
