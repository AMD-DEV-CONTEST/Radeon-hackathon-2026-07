"""OpenAI-compatible image generation service backed by Z-Image-Turbo."""

from __future__ import annotations

import asyncio
import base64
import gc
import io
import os
import re
import threading
import time
import uuid
from pathlib import Path

import torch
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image, ImageOps
from pydantic import BaseModel, Field


MODEL_PATH = os.getenv("IMAGE_MODEL_PATH", "/persistent/silent-core/models/Z-Image-Turbo")
UNLOAD_AFTER_REQUEST = os.getenv("IMAGE_UNLOAD_AFTER_REQUEST", "false").lower() in {"1", "true", "yes"}
COMPILE_TRANSFORMER = os.getenv("IMAGE_COMPILE_TRANSFORMER", "false").lower() in {"1", "true", "yes"}
CPU_OFFLOAD = os.getenv("IMAGE_CPU_OFFLOAD", "true").lower() in {"1", "true", "yes"}
MAX_INTERNAL_PIXELS = int(os.getenv("IMAGE_MAX_INTERNAL_PIXELS", str(512 * 512)))
GENERATED_IMAGE_DIR = Path(
    os.getenv("GENERATED_IMAGE_DIR", "/persistent/silent-core/generated/images")
)
_pipeline = None
_load_lock = threading.Lock()
_inference_lock = threading.Lock()

app = FastAPI(title="Silent Core Image API", version="1.0.0")


class ImageRequest(BaseModel):
    model: str = "silent-core/image"
    prompt: str = Field(min_length=1, max_length=4000)
    n: int = Field(default=1, ge=1, le=2)
    size: str = "1024x1024"
    response_format: str = "url"
    seed: int | None = None


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        with _load_lock:
            if _pipeline is None:
                from diffusers import ZImagePipeline

                candidate = ZImagePipeline.from_pretrained(
                    MODEL_PATH,
                    torch_dtype=torch.bfloat16,
                    local_files_only=True,
                )
                try:
                    if CPU_OFFLOAD:
                        candidate.enable_model_cpu_offload(device="cuda")
                    else:
                        candidate.to("cuda")
                    if COMPILE_TRANSFORMER:
                        candidate.transformer = torch.compile(
                            candidate.transformer,
                            mode="max-autotune-no-cudagraphs",
                            fullgraph=True,
                        )
                    _pipeline = candidate
                except Exception:
                    del candidate
                    gc.collect()
                    torch.cuda.empty_cache()
                    raise
    return _pipeline


def select_generation_size(target_width: int, target_height: int) -> tuple[int, int]:
    """Choose the largest safe 64-aligned shape closest to the target aspect ratio."""
    candidates = range(384, 1025, 64)
    target_ratio = target_width / target_height
    valid = [
        (width, height)
        for width in candidates
        for height in candidates
        if width * height <= MAX_INTERNAL_PIXELS
    ]
    return min(
        valid,
        key=lambda shape: (
            abs((shape[0] / shape[1]) - target_ratio),
            -(shape[0] * shape[1]),
        ),
    )


def resize_to_target(image: Image.Image, width: int, height: int) -> Image.Image:
    if image.size == (width, height):
        return image
    return ImageOps.fit(
        image,
        (width, height),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


def generate_images(request: ImageRequest, public_base_url: str) -> list[dict[str, str]]:
    global _pipeline
    try:
        width, height = (int(value) for value in request.size.lower().split("x", 1))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="size must use WIDTHxHEIGHT") from exc
    if not 512 <= width <= 1536 or not 512 <= height <= 1536:
        raise HTTPException(status_code=400, detail="width and height must be between 512 and 1536")
    if width % 64 or height % 64:
        raise HTTPException(status_code=400, detail="width and height must be multiples of 64")
    if width * height > 1024 * 1536:
        raise HTTPException(status_code=400, detail="requested image exceeds the 1024x1536 pixel budget")
    if request.response_format not in {"b64_json", "url"}:
        raise HTTPException(status_code=400, detail="response_format must be b64_json or url")

    images = []
    generation_width, generation_height = select_generation_size(width, height)
    with _inference_lock:
        pipeline = get_pipeline()
        try:
            for index in range(request.n):
                seed = (request.seed if request.seed is not None else torch.seed()) + index
                generator = torch.Generator(device="cuda").manual_seed(seed)
                with torch.inference_mode():
                    image = pipeline(
                        prompt=request.prompt,
                        width=generation_width,
                        height=generation_height,
                        num_inference_steps=9,
                        guidance_scale=0.0,
                        generator=generator,
                    ).images[0]
                image = resize_to_target(image, width, height)
                if request.response_format == "b64_json":
                    output = io.BytesIO()
                    image.save(output, format="PNG")
                    result = {"b64_json": base64.b64encode(output.getvalue()).decode("ascii")}
                else:
                    GENERATED_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
                    filename = f"{uuid.uuid4().hex}.png"
                    image.save(GENERATED_IMAGE_DIR / filename, format="PNG")
                    result = {"url": f"{public_base_url}/files/images/{filename}"}
                result["generation_size"] = f"{generation_width}x{generation_height}"
                images.append(result)
        finally:
            if UNLOAD_AFTER_REQUEST:
                _pipeline = None
                del pipeline
                gc.collect()
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
    return images


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model_loaded": _pipeline is not None,
        "unload_after_request": UNLOAD_AFTER_REQUEST,
        "compiled": COMPILE_TRANSFORMER,
        "cpu_offload": CPU_OFFLOAD,
        "max_internal_pixels": MAX_INTERNAL_PIXELS,
    }


@app.get("/files/images/{filename}")
async def image_file(filename: str):
    if not re.fullmatch(r"[0-9a-f]{32}\.png", filename):
        raise HTTPException(status_code=404, detail="image not found")
    path = GENERATED_IMAGE_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(path, media_type="image/png")


@app.post("/v1/images/generations")
async def image_generations(request: ImageRequest, http_request: Request):
    public_base_url = http_request.headers.get("x-public-base-url", "http://127.0.0.1:18000").rstrip("/")
    data = await asyncio.to_thread(generate_images, request, public_base_url)
    return {"created": int(time.time()), "data": data}
