"""Run one measured image-to-image inference on a real PyTorch ROCm GPU.

This script has no CPU path and no mock path. It resolves an exact model commit,
loads one Diffusers image-to-image pipeline, and permits at most one
reduced-memory retry of the same model after a genuine GPU out-of-memory error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import platform
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence, TypeVar

SDXL_MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
SD15_MODEL_ID = "stable-diffusion-v1-5/stable-diffusion-v1-5"
AUTO_SDXL_THRESHOLD_BYTES = 16 * 1024**3
DIRECT_SDXL_COMFORT_BYTES = 20 * 1024**3
FIXED_SEED = 20260725

PROMPT = (
    "Premium studio product advertisement, dark charcoal background, controlled soft rim lighting, "
    "clean commercial composition, realistic product photography, preserve the product shape, "
    "preserve the product proportions, no added text, no altered logo, polished advertising visual."
)
NEGATIVE_PROMPT = (
    "deformed product, changed logo, duplicated product, unreadable text, watermark, low quality, "
    "distorted geometry, extra objects"
)


class SmokeTestError(RuntimeError):
    """Expected refusal or real-inference failure."""


@dataclass(frozen=True)
class RuntimeInfo:
    device_name: str
    gpu_count: int
    total_gpu_memory_bytes: int | None
    pytorch_version: str
    hip_version: str


@dataclass(frozen=True)
class GenerationSettings:
    model_key: str
    model_id: str
    resolved_revision: str
    width: int
    height: int
    steps: int
    strength: float
    guidance_scale: float
    seed: int


@dataclass
class AttemptResult:
    pipeline_class: str
    model_load_seconds: float
    generation_seconds: float
    peak_allocated_bytes: int | None
    peak_reserved_bytes: int | None
    cpu_offload_used: bool
    attention_slicing_used: bool


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def configure_logging(output_dir: Path) -> tuple[logging.Logger, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "generation.log"
    logger = logging.getLogger("brandpilot.radeon_smoke_test")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)sZ %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger, log_path


def require_rocm(torch_module: Any) -> RuntimeInfo:
    hip_version = getattr(getattr(torch_module, "version", None), "hip", None)
    if not hip_version:
        raise SmokeTestError("PyTorch does not report torch.version.hip; refusing non-ROCm execution.")
    if not bool(torch_module.cuda.is_available()):
        raise SmokeTestError("torch.cuda.is_available() is false; refusing CPU execution.")
    gpu_count = int(torch_module.cuda.device_count())
    if gpu_count < 1:
        raise SmokeTestError("PyTorch reports no GPU devices; refusing CPU execution.")
    device_name = str(torch_module.cuda.get_device_name(0))
    try:
        total_memory = int(torch_module.cuda.get_device_properties(0).total_memory)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        total_memory = None
    return RuntimeInfo(
        device_name=device_name,
        gpu_count=gpu_count,
        total_gpu_memory_bytes=total_memory,
        pytorch_version=str(getattr(torch_module, "__version__", "unknown")),
        hip_version=str(hip_version),
    )


def select_model(model_choice: str, total_memory_bytes: int | None) -> tuple[str, str]:
    if model_choice == "sdxl":
        return "sdxl", SDXL_MODEL_ID
    if model_choice == "sd15":
        return "sd15", SD15_MODEL_ID
    if model_choice != "auto":
        raise SmokeTestError(f"Unsupported model choice: {model_choice}")
    if total_memory_bytes is not None and total_memory_bytes >= AUTO_SDXL_THRESHOLD_BYTES:
        return "sdxl", SDXL_MODEL_ID
    return "sd15", SD15_MODEL_ID


def resolve_exact_revision(model_id: str, requested_revision: str, hub_module: Any) -> str:
    info = hub_module.HfApi().model_info(model_id, revision=requested_revision, token=False)
    revision = str(getattr(info, "sha", "") or "")
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision.lower()):
        raise SmokeTestError(f"Could not resolve an exact 40-character revision SHA for {model_id}.")
    return revision


def build_settings(args: argparse.Namespace, runtime: RuntimeInfo, hub_module: Any) -> GenerationSettings:
    model_key, model_id = select_model(args.model, runtime.total_gpu_memory_bytes)
    defaults = (
        {"width": 768, "height": 768, "steps": 15, "strength": 0.35, "guidance_scale": 6.5}
        if model_key == "sdxl"
        else {"width": 512, "height": 512, "steps": 20, "strength": 0.35, "guidance_scale": 7.0}
    )
    return GenerationSettings(
        model_key=model_key,
        model_id=model_id,
        resolved_revision=resolve_exact_revision(model_id, args.revision, hub_module),
        width=args.width or defaults["width"],
        height=args.height or defaults["height"],
        steps=args.steps or defaults["steps"],
        strength=args.strength if args.strength is not None else defaults["strength"],
        guidance_scale=(
            args.guidance_scale if args.guidance_scale is not None else defaults["guidance_scale"]
        ),
        seed=args.seed,
    )


def validate_settings(settings: GenerationSettings) -> None:
    if settings.width < 64 or settings.height < 64 or settings.width % 8 or settings.height % 8:
        raise SmokeTestError("Width and height must be at least 64 and divisible by 8.")
    if settings.steps < 1 or settings.steps > 100:
        raise SmokeTestError("Steps must be between 1 and 100.")
    if not 0.0 < settings.strength <= 1.0:
        raise SmokeTestError("Strength must be greater than 0 and at most 1.")
    if settings.guidance_scale < 0:
        raise SmokeTestError("Guidance scale cannot be negative.")


def prepare_input(image_module: Any, image_ops_module: Any, path: Path, width: int, height: int) -> Any:
    with image_module.open(path) as source:
        source = source.convert("RGB")
        fitted = image_ops_module.contain(source, (width, height))
        canvas = image_module.new("RGB", (width, height), (24, 24, 28))
        canvas.paste(fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2))
    return canvas


def load_pipeline(
    diffusers_module: Any,
    torch_module: Any,
    settings: GenerationSettings,
    cache_dir: Path,
    reduced_memory: bool,
    total_memory_bytes: int | None,
) -> tuple[Any, float, bool, bool]:
    load_started = time.perf_counter()
    pipeline = diffusers_module.AutoPipelineForImage2Image.from_pretrained(
        settings.model_id,
        revision=settings.resolved_revision,
        cache_dir=str(cache_dir),
        torch_dtype=torch_module.float16,
        use_safetensors=True,
    )
    attention_slicing = reduced_memory or (
        settings.model_key == "sdxl"
        and total_memory_bytes is not None
        and total_memory_bytes < DIRECT_SDXL_COMFORT_BYTES
    )
    cpu_offload = reduced_memory
    if attention_slicing:
        pipeline.enable_attention_slicing()
    if cpu_offload:
        pipeline.enable_model_cpu_offload()
    else:
        pipeline = pipeline.to("cuda")
    torch_module.cuda.synchronize()
    return pipeline, time.perf_counter() - load_started, cpu_offload, attention_slicing


def generate_once(
    pipeline: Any,
    torch_module: Any,
    input_image: Any,
    settings: GenerationSettings,
    output_path: Path,
) -> tuple[float, int | None, int | None]:
    torch_module.cuda.reset_peak_memory_stats()
    generator = torch_module.Generator(device="cuda").manual_seed(settings.seed)
    started = time.perf_counter()
    generated = pipeline(
        prompt=PROMPT,
        negative_prompt=NEGATIVE_PROMPT,
        image=input_image,
        width=settings.width,
        height=settings.height,
        num_inference_steps=settings.steps,
        strength=settings.strength,
        guidance_scale=settings.guidance_scale,
        generator=generator,
        num_images_per_prompt=1,
    ).images[0]
    torch_module.cuda.synchronize()
    generation_seconds = time.perf_counter() - started
    generated.save(output_path)
    try:
        peak_allocated = int(torch_module.cuda.max_memory_allocated(0))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        peak_allocated = None
    try:
        peak_reserved = int(torch_module.cuda.max_memory_reserved(0))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        peak_reserved = None
    return generation_seconds, peak_allocated, peak_reserved


def cleanup_gpu(torch_module: Any, pipeline: Any | None) -> None:
    if pipeline is not None:
        del pipeline
    try:
        torch_module.cuda.empty_cache()
    except (AttributeError, RuntimeError):
        pass


T = TypeVar("T")


def run_with_one_oom_retry(
    attempt: Callable[[bool], T],
    is_oom: Callable[[Exception], bool],
    cleanup: Callable[[], None],
    logger: logging.Logger,
) -> T:
    try:
        return attempt(False)
    except Exception as exc:
        if not is_oom(exc):
            raise
        logger.error("Genuine GPU out-of-memory error on direct attempt: %s", exc)
        cleanup()
    logger.info("Starting the single permitted reduced-memory retry of the same model.")
    return attempt(True)


def write_metadata(path: Path, metadata: dict[str, Any]) -> None:
    path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def base_metadata(
    args: argparse.Namespace,
    runtime: RuntimeInfo | None,
    input_path: Path,
    output_path: Path,
    started_at: str,
) -> dict[str, Any]:
    return {
        "status": "started",
        "model_id": None,
        "resolved_model_revision": None,
        "pipeline_class": None,
        "input_filename": input_path.name,
        "output_filename": output_path.name,
        "input_sha256": sha256_file(input_path) if input_path.is_file() else None,
        "output_sha256": None,
        "prompt": PROMPT,
        "negative_prompt": NEGATIVE_PROMPT,
        "width": args.width,
        "height": args.height,
        "steps": args.steps,
        "strength": args.strength,
        "guidance_scale": args.guidance_scale,
        "seed": args.seed,
        "model_load_seconds": None,
        "generation_seconds": None,
        "total_seconds": None,
        "gpu_device": runtime.device_name if runtime else None,
        "gpu_count": runtime.gpu_count if runtime else None,
        "total_gpu_memory_bytes": runtime.total_gpu_memory_bytes if runtime else None,
        "peak_allocated_gpu_memory_bytes": None,
        "peak_reserved_gpu_memory_bytes": None,
        "pytorch_version": runtime.pytorch_version if runtime else None,
        "hip_rocm_version": runtime.hip_version if runtime else None,
        "diffusers_version": None,
        "transformers_version": None,
        "python_version": platform.python_version(),
        "timestamp_utc": started_at,
        "cpu_offload_used": False,
        "attention_slicing_used": False,
        "output_produced_successfully": False,
        "error": None,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one real AMD Radeon ROCm image-to-image smoke test."
    )
    parser.add_argument("--input", type=Path, required=True, help="Rights-safe input image.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for output, metadata, and log.",
    )
    parser.add_argument("--model", choices=("auto", "sdxl", "sd15"), default="auto")
    parser.add_argument("--revision", default="main", help="Model branch, tag, or revision to resolve to a SHA.")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--steps", type=int)
    parser.add_argument("--strength", type=float)
    parser.add_argument("--guidance-scale", type=float)
    parser.add_argument("--seed", type=int, default=FIXED_SEED)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = args.output_dir.resolve()
    logger, _ = configure_logging(output_dir)
    metadata_path = output_dir / "generation-metadata.json"
    output_path = output_dir / "generated-output.png"
    started = time.perf_counter()
    started_at = utc_now()
    runtime: RuntimeInfo | None = None
    metadata = base_metadata(args, runtime, args.input, output_path, started_at)
    pipeline: Any | None = None

    try:
        if not args.input.is_file():
            raise SmokeTestError(f"Input image does not exist: {args.input}")
        try:
            import torch
        except (ImportError, OSError) as exc:
            raise SmokeTestError("PyTorch is required; refusing to run without ROCm PyTorch.") from exc
        runtime = require_rocm(torch)
        metadata.update(
            {
                "gpu_device": runtime.device_name,
                "gpu_count": runtime.gpu_count,
                "total_gpu_memory_bytes": runtime.total_gpu_memory_bytes,
                "pytorch_version": runtime.pytorch_version,
                "hip_rocm_version": runtime.hip_version,
            }
        )
        try:
            import diffusers
            import huggingface_hub
            import transformers
            from PIL import Image, ImageOps
        except (ImportError, OSError) as exc:
            raise SmokeTestError(
                "Diffusers, Transformers, huggingface_hub, safetensors, and Pillow are required."
            ) from exc

        settings = build_settings(args, runtime, huggingface_hub)
        validate_settings(settings)
        metadata.update(
            {
                "model_id": settings.model_id,
                "resolved_model_revision": settings.resolved_revision,
                "width": settings.width,
                "height": settings.height,
                "steps": settings.steps,
                "strength": settings.strength,
                "guidance_scale": settings.guidance_scale,
                "seed": settings.seed,
                "diffusers_version": str(diffusers.__version__),
                "transformers_version": str(transformers.__version__),
            }
        )
        cache_dir = Path(os.getenv("HF_HOME", output_dir / "model-cache")).resolve()
        cache_dir.mkdir(parents=True, exist_ok=True)
        input_image = prepare_input(Image, ImageOps, args.input, settings.width, settings.height)
        logger.info(
            "ROCm device=%s hip=%s memory_bytes=%s model=%s revision=%s",
            runtime.device_name,
            runtime.hip_version,
            runtime.total_gpu_memory_bytes,
            settings.model_id,
            settings.resolved_revision,
        )

        def attempt(reduced_memory: bool) -> AttemptResult:
            nonlocal pipeline
            pipeline, load_seconds, cpu_offload, attention_slicing = load_pipeline(
                diffusers,
                torch,
                settings,
                cache_dir,
                reduced_memory,
                runtime.total_gpu_memory_bytes,
            )
            generation_seconds, peak_allocated, peak_reserved = generate_once(
                pipeline, torch, input_image, settings, output_path
            )
            return AttemptResult(
                pipeline_class=type(pipeline).__name__,
                model_load_seconds=load_seconds,
                generation_seconds=generation_seconds,
                peak_allocated_bytes=peak_allocated,
                peak_reserved_bytes=peak_reserved,
                cpu_offload_used=cpu_offload,
                attention_slicing_used=attention_slicing,
            )

        oom_type = getattr(getattr(torch, "cuda", None), "OutOfMemoryError", ())

        def cleanup_current_pipeline() -> None:
            nonlocal pipeline
            cleanup_gpu(torch, pipeline)
            pipeline = None

        result = run_with_one_oom_retry(
            attempt=attempt,
            is_oom=lambda exc: bool(oom_type) and isinstance(exc, oom_type),
            cleanup=cleanup_current_pipeline,
            logger=logger,
        )
        if not output_path.is_file():
            raise SmokeTestError("Pipeline returned without creating the required output image.")
        metadata.update(
            {
                "status": "success",
                "pipeline_class": result.pipeline_class,
                "output_sha256": sha256_file(output_path),
                "model_load_seconds": result.model_load_seconds,
                "generation_seconds": result.generation_seconds,
                "peak_allocated_gpu_memory_bytes": result.peak_allocated_bytes,
                "peak_reserved_gpu_memory_bytes": result.peak_reserved_bytes,
                "cpu_offload_used": result.cpu_offload_used,
                "attention_slicing_used": result.attention_slicing_used,
                "output_produced_successfully": True,
            }
        )
        logger.info("Real image-to-image generation completed: %s", output_path)
        return_code = 0
    except Exception as exc:
        metadata.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        logger.exception("Smoke test failed without CPU or mock fallback: %s", exc)
        return_code = 2
    finally:
        metadata["total_seconds"] = time.perf_counter() - started
        write_metadata(metadata_path, metadata)
        if "torch" in locals():
            cleanup_gpu(torch, pipeline)
        logger.info("Metadata saved: %s", metadata_path)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
