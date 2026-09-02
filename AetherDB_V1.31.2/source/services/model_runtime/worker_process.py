"""Isolated native model worker process.

Only AetherDB-owned adapters are registered here. Package manifests cannot name
an import path or execute model-provided Python code.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import io
import json
import math
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from services.model_runtime.worker_protocol import (
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    WorkerError,
    WorkerRequest,
    WorkerResponse,
    WorkerState,
)


class AdapterError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.safe_message = message


class BgeM3WorkerAdapter:
    run_operations_on_main_thread = True

    def __init__(self, model_root: Path):
        self.model_root = model_root
        self.runtime = None
        self.backend = None
        self._external_data_lock = threading.RLock()

    def capabilities(self) -> dict:
        return {
            "operations": ["probe", "embedding"],
            "modalities": ["text"],
            "max_batch_items": 100,
            "vector_dimension": 1024,
        }

    def load(self, payload: dict) -> dict:
        backend = str(payload.get("backend") or "")
        accelerator = {
            "rocm_migraphx": "rocm",
            "cuda": "cuda",
            "cpu": "cpu",
        }.get(backend)
        if accelerator is None:
            raise AdapterError("INVALID_BACKEND", "Unsupported embedding backend")
        visible_index = payload.get("visible_index")
        if visible_index is not None:
            value = str(int(visible_index))
            if backend == "rocm_migraphx":
                os.environ["HIP_VISIBLE_DEVICES"] = value
                os.environ["ROCR_VISIBLE_DEVICES"] = value
            elif backend == "cuda":
                os.environ["CUDA_VISIBLE_DEVICES"] = value

        from services.embedding_runtime import BgeM3OnnxRuntime

        self.runtime = BgeM3OnnxRuntime(
            self.model_root,
            accelerator=accelerator,
        )
        status = self.runtime.status()
        effective = {
            "MIGraphXExecutionProvider": "rocm_migraphx",
            "CUDAExecutionProvider": "cuda",
            "CPUExecutionProvider": "cpu",
        }.get(status.execution_provider)
        if effective != backend:
            self.unload()
            raise AdapterError(
                "BACKEND_MISMATCH",
                "Embedding runtime did not activate the admitted backend",
            )
        self.backend = backend
        return {
            "effective_backend": effective,
            "execution_provider": status.execution_provider,
            "model_id": status.model_id,
            "revision": status.revision,
            "dimensions": status.dimensions,
            "detail": status.detail,
        }

    def unload(self) -> dict:
        self.runtime = None
        self.backend = None
        gc.collect()
        return {"unloaded": True}

    def _embed_batch(self, texts):
        if self.backend != "rocm_migraphx":
            return self.runtime.embed_batch(texts)

        # MIGraphX resolves ONNX external data against the process cwd. This
        # adapter owns an isolated Worker process, so scope and restore the cwd
        # around inference instead of changing the API process directory.
        model_directory = (self.model_root / "onnx").resolve()
        with self._external_data_lock:
            try:
                previous_directory = Path.cwd()
                os.chdir(model_directory)
            except OSError as exc:
                raise AdapterError(
                    "MODEL_DIRECTORY_UNAVAILABLE",
                    "Verified embedding model directory is unavailable",
                ) from exc
            try:
                return self.runtime.embed_batch(texts)
            finally:
                try:
                    os.chdir(previous_directory)
                except OSError as exc:
                    raise AdapterError(
                        "WORKER_DIRECTORY_RESTORE_FAILED",
                        "Embedding Worker could not restore its working directory",
                    ) from exc

    def probe(self, _payload: dict, cancelled: threading.Event) -> dict:
        if self.runtime is None:
            raise AdapterError("NOT_LOADED", "Embedding runtime is not loaded")
        if cancelled.is_set():
            raise AdapterError("CANCELLED", "Runtime probe was cancelled")
        texts = ("AetherDB multilingual runtime probe", "本地多语言向量运行探针")
        result = self._embed_batch(texts)
        if len(result.vectors) != 2 or result.dimensions != 1024:
            raise AdapterError("PROBE_INVALID", "Embedding probe returned an invalid shape")
        norms = [math.sqrt(sum(value * value for value in vector)) for vector in result.vectors]
        if any(not 0.999 <= norm <= 1.001 for norm in norms):
            raise AdapterError("PROBE_INVALID", "Embedding probe normalization failed")
        digest = hashlib.sha256(
            json.dumps(result.vectors, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            "verified": True,
            "effective_backend": {
                "MIGraphXExecutionProvider": "rocm_migraphx",
                "CUDAExecutionProvider": "cuda",
                "CPUExecutionProvider": "cpu",
            }.get(result.execution_provider),
            "execution_provider": result.execution_provider,
            "dimensions": result.dimensions,
            "batch_items": len(result.vectors),
            "normalized": result.normalized,
            "elapsed_ms": result.elapsed_ms,
            "output_digest": digest,
        }

    def infer(self, payload: dict, cancelled: threading.Event) -> dict:
        if self.runtime is None:
            raise AdapterError("NOT_LOADED", "Embedding runtime is not loaded")
        texts = payload.get("texts")
        if (
            not isinstance(texts, list)
            or not 1 <= len(texts) <= 100
            or any(not isinstance(item, str) or not item.strip() or len(item) > 50_000 for item in texts)
            or sum(len(item) for item in texts) > 500_000
        ):
            raise AdapterError("INVALID_INPUT", "Embedding input batch is invalid")
        if cancelled.is_set():
            raise AdapterError("CANCELLED", "Embedding operation was cancelled")
        result = self._embed_batch(texts)
        if cancelled.is_set():
            raise AdapterError("CANCELLED", "Embedding operation was cancelled")
        return {
            "vectors": result.vectors,
            "model_id": result.model_id,
            "revision": result.revision,
            "dimensions": result.dimensions,
            "execution_provider": result.execution_provider,
            "effective_backend": {
                "MIGraphXExecutionProvider": "rocm_migraphx",
                "CUDAExecutionProvider": "cuda",
                "CPUExecutionProvider": "cpu",
            }.get(result.execution_provider),
            "normalized": result.normalized,
            "elapsed_ms": result.elapsed_ms,
        }

    def metrics(self) -> dict:
        status = self.runtime.status() if self.runtime is not None else None
        return {
            "loaded": self.runtime is not None,
            "execution_provider": status.execution_provider if status else None,
            "actual_vram_mb": None,
            "actual_peak_vram_mb": None,
        }


class BgeVLClipWorkerAdapter:
    """Pinned BGE-VL CLIP runtime without model-supplied executable code."""

    VECTOR_DIMENSION = 512
    MAX_IMAGE_ITEMS = 16
    MAX_TEXT_ITEMS = 64
    MAX_IMAGE_PIXELS = 50_000_000

    def __init__(self, model_root: Path):
        self.model_root = model_root
        self.model = None
        self.processor = None
        self.torch = None
        self.device = None
        self.backend = None
        self.execution_provider = None

    def capabilities(self) -> dict:
        return {
            "operations": ["probe", "vision"],
            "modalities": ["text", "image"],
            "max_image_items": self.MAX_IMAGE_ITEMS,
            "max_text_items": self.MAX_TEXT_ITEMS,
            "image_size": 224,
            "vector_dimension": self.VECTOR_DIMENSION,
            "normalization": "l2",
            "remote_code": False,
        }

    @staticmethod
    def _provider_for_backend(torch, backend: str) -> tuple[str, str]:
        if backend == "rocm_pytorch":
            if not torch.cuda.is_available() or not getattr(torch.version, "hip", None):
                raise AdapterError(
                    "BACKEND_UNAVAILABLE",
                    "PyTorch ROCm is unavailable in this Worker runtime",
                )
            return "cuda", "PyTorchROCm"
        if backend == "cuda":
            if (
                not torch.cuda.is_available()
                or not getattr(torch.version, "cuda", None)
                or getattr(torch.version, "hip", None)
            ):
                raise AdapterError(
                    "BACKEND_UNAVAILABLE",
                    "PyTorch CUDA is unavailable in this Worker runtime",
                )
            return "cuda", "PyTorchCUDA"
        if backend == "cpu":
            return "cpu", "PyTorchCPU"
        raise AdapterError("INVALID_BACKEND", "Unsupported BGE-VL backend")

    def load(self, payload: dict) -> dict:
        backend = str(payload.get("backend") or "")
        visible_index = payload.get("visible_index")
        if visible_index is not None:
            value = str(int(visible_index))
            if backend == "rocm_pytorch":
                os.environ["HIP_VISIBLE_DEVICES"] = value
                os.environ["ROCR_VISIBLE_DEVICES"] = value
            elif backend == "cuda":
                os.environ["CUDA_VISIBLE_DEVICES"] = value
        try:
            import torch
            from transformers import CLIPModel, CLIPProcessor
        except ImportError as exc:
            raise AdapterError(
                "WORKER_DEPENDENCY_MISSING",
                "The isolated BGE-VL Worker requires PyTorch, Transformers, and Pillow",
            ) from exc

        device, provider = self._provider_for_backend(torch, backend)
        dtype = torch.float32 if device == "cpu" else torch.float16
        try:
            processor = CLIPProcessor.from_pretrained(
                str(self.model_root),
                local_files_only=True,
            )
            model = CLIPModel.from_pretrained(
                str(self.model_root),
                local_files_only=True,
                torch_dtype=dtype,
            )
            model.train(False)
            model.to(device)
        except Exception as exc:
            raise AdapterError(
                "MODEL_LOAD_FAILED",
                f"BGE-VL model loading failed: {type(exc).__name__}",
            ) from exc

        self.torch = torch
        self.processor = processor
        self.model = model
        self.device = device
        self.backend = backend
        self.execution_provider = provider
        return {
            "effective_backend": backend,
            "execution_provider": provider,
            "model_id": "BAAI/BGE-VL-base",
            "revision": "cc4c733ed997dbee4ac70ccffb911e70c9c24b93",
            "dimensions": self.VECTOR_DIMENSION,
            "image_size": 224,
            "remote_code": False,
        }

    def unload(self) -> dict:
        torch = self.torch
        self.model = None
        self.processor = None
        self.device = None
        self.backend = None
        self.execution_provider = None
        self.torch = None
        gc.collect()
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
        return {"unloaded": True}

    def _normalize(self, tensor) -> list[list[float]]:
        normalized = self.torch.nn.functional.normalize(tensor.float(), dim=-1)
        vectors = normalized.detach().cpu().tolist()
        if any(
            len(vector) != self.VECTOR_DIMENSION
            or any(not math.isfinite(value) for value in vector)
            for vector in vectors
        ):
            raise AdapterError("INFERENCE_INVALID", "BGE-VL returned invalid vectors")
        return vectors

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        inputs = self.processor(
            text=texts,
            return_tensors="pt",
            padding=True,
            truncation=True,
        )
        inputs = {
            key: value.to(self.device)
            for key, value in inputs.items()
            if key in {"input_ids", "attention_mask"}
        }
        with self.torch.inference_mode():
            return self._normalize(self.model.get_text_features(**inputs))

    def _embed_images(self, images: list) -> list[list[float]]:
        inputs = self.processor(images=images, return_tensors="pt")
        pixel_values = inputs["pixel_values"].to(self.device)
        with self.torch.inference_mode():
            return self._normalize(
                self.model.get_image_features(pixel_values=pixel_values)
            )

    @staticmethod
    def _sha256_path(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def _load_image_inputs(self, items: list[dict]) -> list:
        try:
            from PIL import Image
        except ImportError as exc:
            raise AdapterError(
                "WORKER_DEPENDENCY_MISSING",
                "The isolated BGE-VL Worker requires Pillow",
            ) from exc
        Image.MAX_IMAGE_PIXELS = self.MAX_IMAGE_PIXELS
        images = []
        for item in items:
            if not isinstance(item, dict):
                raise AdapterError("INVALID_INPUT", "Image input is invalid")
            raw_path = item.get("path")
            expected_hash = str(item.get("sha256") or "")
            if (
                not isinstance(raw_path, str)
                or not raw_path
                or len(raw_path) > 4096
                or len(expected_hash) != 64
            ):
                raise AdapterError("INVALID_INPUT", "Image input is invalid")
            try:
                path = Path(raw_path).resolve(strict=True)
            except OSError as exc:
                raise AdapterError("IMAGE_UNAVAILABLE", "Image input is unavailable") from exc
            if not path.is_file() or path.is_symlink():
                raise AdapterError("IMAGE_UNAVAILABLE", "Image input is unavailable")
            if self._sha256_path(path) != expected_hash:
                raise AdapterError(
                    "IMAGE_INTEGRITY_MISMATCH",
                    "Image input no longer matches its media asset hash",
                )
            try:
                with Image.open(path) as image:
                    images.append(image.convert("RGB").copy())
            except Exception as exc:
                raise AdapterError(
                    "IMAGE_DECODE_FAILED",
                    f"Image decoding failed: {type(exc).__name__}",
                ) from exc
        return images

    def probe(self, _payload: dict, cancelled: threading.Event) -> dict:
        if self.model is None:
            raise AdapterError("NOT_LOADED", "BGE-VL runtime is not loaded")
        if cancelled.is_set():
            raise AdapterError("CANCELLED", "Runtime probe was cancelled")
        try:
            from PIL import Image
        except ImportError as exc:
            raise AdapterError(
                "WORKER_DEPENDENCY_MISSING",
                "The isolated BGE-VL Worker requires Pillow",
            ) from exc
        started = time.perf_counter()
        text_vectors = self._embed_texts(["A red square on a white background"])
        image_vectors = self._embed_images(
            [Image.new("RGB", (224, 224), (220, 40, 40))]
        )
        vectors = text_vectors + image_vectors
        norms = [math.sqrt(sum(value * value for value in vector)) for vector in vectors]
        if any(not 0.999 <= norm <= 1.001 for norm in norms):
            raise AdapterError("PROBE_INVALID", "BGE-VL normalization probe failed")
        digest = hashlib.sha256(
            json.dumps(vectors, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            "verified": True,
            "effective_backend": self.backend,
            "execution_provider": self.execution_provider,
            "dimensions": self.VECTOR_DIMENSION,
            "batch_items": 2,
            "normalized": True,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "output_digest": digest,
            "remote_code": False,
        }

    def infer(self, payload: dict, cancelled: threading.Event) -> dict:
        if self.model is None:
            raise AdapterError("NOT_LOADED", "BGE-VL runtime is not loaded")
        mode = payload.get("mode")
        started = time.perf_counter()
        if mode == "text":
            texts = payload.get("texts")
            if (
                not isinstance(texts, list)
                or not 1 <= len(texts) <= self.MAX_TEXT_ITEMS
                or any(
                    not isinstance(item, str)
                    or not item.strip()
                    or len(item) > 4000
                    for item in texts
                )
            ):
                raise AdapterError("INVALID_INPUT", "BGE-VL text input is invalid")
            vectors = self._embed_texts(texts)
        elif mode == "image":
            items = payload.get("images")
            if not isinstance(items, list) or not 1 <= len(items) <= self.MAX_IMAGE_ITEMS:
                raise AdapterError("INVALID_INPUT", "BGE-VL image input is invalid")
            vectors = self._embed_images(self._load_image_inputs(items))
        else:
            raise AdapterError("INVALID_INPUT", "BGE-VL inference mode is invalid")
        if cancelled.is_set():
            raise AdapterError("CANCELLED", "BGE-VL operation was cancelled")
        return {
            "vectors": vectors,
            "model_id": "BAAI/BGE-VL-base",
            "revision": "cc4c733ed997dbee4ac70ccffb911e70c9c24b93",
            "dimensions": self.VECTOR_DIMENSION,
            "execution_provider": self.execution_provider,
            "effective_backend": self.backend,
            "normalized": True,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "input_kind": mode,
            "remote_code": False,
        }

    def metrics(self) -> dict:
        actual = None
        peak = None
        if (
            self.torch is not None
            and self.device == "cuda"
            and self.torch.cuda.is_available()
        ):
            actual = self.torch.cuda.memory_allocated() // (1024 * 1024)
            peak = self.torch.cuda.max_memory_allocated() // (1024 * 1024)
        return {
            "loaded": self.model is not None,
            "execution_provider": self.execution_provider,
            "actual_vram_mb": actual,
            "actual_peak_vram_mb": peak,
        }


class Kandinsky22WorkerAdapter:
    """Pinned Diffusers runtime for the trusted Kandinsky 2.2 package."""

    MAX_IMAGE_PIXELS = 50_000_000
    MAX_OUTPUT_BYTES = 32 * 1024 * 1024

    def __init__(self, model_root: Path):
        self.model_root = model_root
        self.prior = None
        self.decoder = None
        self.img2img = None
        self.torch = None
        self.device = None
        self.backend = None
        self.execution_provider = None

    def capabilities(self) -> dict:
        return {
            "operations": [
                "probe",
                "image.generate",
                "image.img2img",
                "image.enhance",
            ],
            "modalities": ["text", "image"],
            "output_mime_types": ["image/png"],
            "minimum_dimension": 256,
            "maximum_dimension": 1024,
            "dimension_multiple": 64,
            "remote_code": False,
        }

    @staticmethod
    def _provider_for_backend(torch, backend: str) -> tuple[str, str]:
        if backend == "rocm_pytorch":
            if not torch.cuda.is_available() or not getattr(torch.version, "hip", None):
                raise AdapterError(
                    "BACKEND_UNAVAILABLE",
                    "PyTorch ROCm is unavailable in this Worker runtime",
                )
            return "cuda", "PyTorchROCmDiffusers"
        if backend == "cuda":
            if (
                not torch.cuda.is_available()
                or not getattr(torch.version, "cuda", None)
                or getattr(torch.version, "hip", None)
            ):
                raise AdapterError(
                    "BACKEND_UNAVAILABLE",
                    "PyTorch CUDA is unavailable in this Worker runtime",
                )
            return "cuda", "PyTorchCUDADiffusers"
        raise AdapterError(
            "INVALID_BACKEND",
            "Kandinsky 2.2 requires a declared ROCm or CUDA backend",
        )

    def load(self, payload: dict) -> dict:
        backend = str(payload.get("backend") or "")
        visible_index = payload.get("visible_index")
        if visible_index is not None:
            value = str(int(visible_index))
            if backend == "rocm_pytorch":
                os.environ["HIP_VISIBLE_DEVICES"] = value
                os.environ["ROCR_VISIBLE_DEVICES"] = value
            elif backend == "cuda":
                os.environ["CUDA_VISIBLE_DEVICES"] = value
        try:
            import torch
            from diffusers import (
                KandinskyV22Img2ImgPipeline,
                KandinskyV22Pipeline,
                KandinskyV22PriorPipeline,
            )
        except ImportError as exc:
            raise AdapterError(
                "WORKER_DEPENDENCY_MISSING",
                "The isolated image Worker requires PyTorch, Diffusers, Transformers, and Pillow",
            ) from exc

        device, provider = self._provider_for_backend(torch, backend)
        dtype = torch.float16
        prior_root = self.model_root / "prior"
        decoder_root = self.model_root / "decoder"
        try:
            prior = KandinskyV22PriorPipeline.from_pretrained(
                str(prior_root),
                local_files_only=True,
                torch_dtype=dtype,
                use_safetensors=True,
            )
            decoder = KandinskyV22Pipeline.from_pretrained(
                str(decoder_root),
                local_files_only=True,
                torch_dtype=dtype,
                use_safetensors=True,
            )
            img2img = KandinskyV22Img2ImgPipeline(
                unet=decoder.unet,
                scheduler=decoder.scheduler,
                movq=decoder.movq,
            )
            prior.to(device)
            decoder.to(device)
            img2img.to(device)
        except Exception as exc:
            raise AdapterError(
                "MODEL_LOAD_FAILED",
                f"Kandinsky 2.2 model loading failed: {type(exc).__name__}",
            ) from exc

        self.torch = torch
        self.prior = prior
        self.decoder = decoder
        self.img2img = img2img
        self.device = device
        self.backend = backend
        self.execution_provider = provider
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        return {
            "effective_backend": backend,
            "execution_provider": provider,
            "model_id": "kandinsky-community/kandinsky-2-2",
            "revision": (
                "prior:9fc51ad5732afc5d031724219d22e6c42179c5a8;"
                "decoder:9ae140d347fed8ce6e8bb3005dcc1f48543bb8e3"
            ),
            "remote_code": False,
        }

    def unload(self) -> dict:
        torch = self.torch
        self.prior = None
        self.decoder = None
        self.img2img = None
        self.device = None
        self.backend = None
        self.execution_provider = None
        self.torch = None
        gc.collect()
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
        return {"unloaded": True}

    @staticmethod
    def _sha256_path(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def _source_image(self, source: dict | None):
        if not isinstance(source, dict):
            raise AdapterError("SOURCE_IMAGE_REQUIRED", "A source image is required")
        raw_path = source.get("path")
        expected_hash = str(source.get("sha256") or "")
        if (
            not isinstance(raw_path, str)
            or not raw_path
            or len(raw_path) > 4096
            or len(expected_hash) != 64
        ):
            raise AdapterError("INVALID_INPUT", "Source image reference is invalid")
        try:
            path = Path(raw_path).resolve(strict=True)
        except OSError as exc:
            raise AdapterError("IMAGE_UNAVAILABLE", "Source image is unavailable") from exc
        if not path.is_file() or path.is_symlink():
            raise AdapterError("IMAGE_UNAVAILABLE", "Source image is unavailable")
        if self._sha256_path(path) != expected_hash:
            raise AdapterError(
                "IMAGE_INTEGRITY_MISMATCH",
                "Source image no longer matches its media asset hash",
            )
        try:
            from PIL import Image

            Image.MAX_IMAGE_PIXELS = self.MAX_IMAGE_PIXELS
            with Image.open(path) as image:
                return image.convert("RGB").copy()
        except Exception as exc:
            raise AdapterError(
                "IMAGE_DECODE_FAILED",
                f"Source image decoding failed: {type(exc).__name__}",
            ) from exc

    @staticmethod
    def _validate_request(payload: dict) -> tuple[str, str, dict, int]:
        mode = str(payload.get("mode") or "")
        if mode not in {"image.generate", "image.img2img", "image.enhance"}:
            raise AdapterError("INVALID_INPUT", "Image generation mode is invalid")
        prompt = payload.get("prompt")
        negative_prompt = payload.get("negative_prompt") or ""
        if (
            not isinstance(prompt, str)
            or not prompt.strip()
            or len(prompt) > 6000
            or not isinstance(negative_prompt, str)
            or len(negative_prompt) > 3000
        ):
            raise AdapterError("INVALID_INPUT", "Image generation prompt is invalid")
        parameters = payload.get("parameters")
        if not isinstance(parameters, dict):
            raise AdapterError("INVALID_INPUT", "Image generation parameters are invalid")
        width = parameters.get("width")
        height = parameters.get("height")
        steps = parameters.get("steps")
        guidance = parameters.get("guidance_scale")
        strength = parameters.get("strength")
        if (
            not isinstance(width, int)
            or not isinstance(height, int)
            or width < 256
            or width > 1024
            or height < 256
            or height > 1024
            or width % 64
            or height % 64
            or not isinstance(steps, int)
            or not 1 <= steps <= 100
            or not isinstance(guidance, (int, float))
            or not 1 <= float(guidance) <= 20
            or not isinstance(strength, (int, float))
            or not 0.05 <= float(strength) <= 1
        ):
            raise AdapterError("INVALID_INPUT", "Image generation parameters are invalid")
        seed = payload.get("seed")
        if not isinstance(seed, int) or not 0 <= seed <= 9_223_372_036_854_775_807:
            raise AdapterError("INVALID_INPUT", "Image generation seed is invalid")
        return mode, prompt.strip(), {**parameters, "guidance_scale": float(guidance)}, seed

    def _generate(self, payload: dict, cancelled: threading.Event):
        if self.prior is None or self.decoder is None or self.img2img is None:
            raise AdapterError("NOT_LOADED", "Kandinsky 2.2 runtime is not loaded")
        mode, prompt, parameters, seed = self._validate_request(payload)
        negative_prompt = str(payload.get("negative_prompt") or "")
        if cancelled.is_set():
            raise AdapterError("CANCELLED", "Image generation was cancelled")

        generator = self.torch.Generator(device=self.device).manual_seed(seed)
        prior_steps = max(2, min(25, int(parameters["steps"]) // 2))
        with self.torch.inference_mode():
            prior_output = self.prior(
                prompt=prompt,
                negative_prompt=negative_prompt or None,
                num_inference_steps=prior_steps,
                generator=generator,
            )
        if cancelled.is_set():
            raise AdapterError("CANCELLED", "Image generation was cancelled")

        def on_step_end(_pipeline, _step, _timestep, callback_kwargs):
            if cancelled.is_set():
                raise AdapterError("CANCELLED", "Image generation was cancelled")
            return callback_kwargs

        common = {
            "image_embeds": prior_output.image_embeds,
            "negative_image_embeds": prior_output.negative_image_embeds,
            "height": int(parameters["height"]),
            "width": int(parameters["width"]),
            "num_inference_steps": int(parameters["steps"]),
            "guidance_scale": float(parameters["guidance_scale"]),
            "generator": generator,
            "callback_on_step_end": on_step_end,
        }
        with self.torch.inference_mode():
            if mode == "image.generate":
                image = self.decoder(**common).images[0]
            else:
                image = self.img2img(
                    **common,
                    image=self._source_image(payload.get("source")),
                    strength=float(parameters["strength"]),
                ).images[0]
        if cancelled.is_set():
            raise AdapterError("CANCELLED", "Image generation was cancelled")
        return image, mode, seed

    def _encode_png(self, image) -> bytes:
        output = io.BytesIO()
        image.save(output, format="PNG")
        data = output.getvalue()
        if not data or len(data) > self.MAX_OUTPUT_BYTES:
            raise AdapterError("OUTPUT_TOO_LARGE", "Generated image exceeds the output limit")
        return data

    @staticmethod
    def _write_output(path_value: str, data: bytes) -> None:
        if not isinstance(path_value, str) or not path_value or len(path_value) > 4096:
            raise AdapterError("INVALID_OUTPUT_PATH", "Generated image output path is invalid")
        path = Path(path_value)
        if not path.is_absolute() or path.exists() or path.is_symlink():
            raise AdapterError("INVALID_OUTPUT_PATH", "Generated image output path is invalid")
        try:
            parent = path.parent.resolve(strict=True)
        except OSError as exc:
            raise AdapterError(
                "INVALID_OUTPUT_PATH",
                "Generated image output directory is unavailable",
            ) from exc
        if not parent.is_dir() or parent.is_symlink():
            raise AdapterError("INVALID_OUTPUT_PATH", "Generated image output path is invalid")
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise AdapterError(
                "OUTPUT_WRITE_FAILED",
                "Generated image could not be written to staging",
            ) from exc

    def probe(self, _payload: dict, cancelled: threading.Event) -> dict:
        started = time.perf_counter()
        image, _mode, seed = self._generate(
            {
                "mode": "image.generate",
                "prompt": "A small red square on a clean white background",
                "negative_prompt": "",
                "parameters": {
                    "width": 256,
                    "height": 256,
                    "steps": 2,
                    "guidance_scale": 4.0,
                    "strength": 0.3,
                },
                "seed": 1729,
            },
            cancelled,
        )
        data = self._encode_png(image)
        return {
            "verified": True,
            "effective_backend": self.backend,
            "execution_provider": self.execution_provider,
            "width": image.width,
            "height": image.height,
            "seed": seed,
            "output_size_bytes": len(data),
            "output_digest": hashlib.sha256(data).hexdigest(),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "remote_code": False,
        }

    def infer(self, payload: dict, cancelled: threading.Event) -> dict:
        started = time.perf_counter()
        image, mode, seed = self._generate(payload, cancelled)
        data = self._encode_png(image)
        self._write_output(payload.get("output_path"), data)
        return {
            "model_id": "kandinsky-community/kandinsky-2-2",
            "effective_backend": self.backend,
            "execution_provider": self.execution_provider,
            "operation": mode,
            "width": image.width,
            "height": image.height,
            "seed": seed,
            "output_mime_type": "image/png",
            "output_size_bytes": len(data),
            "output_digest": hashlib.sha256(data).hexdigest(),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "remote_code": False,
        }

    def metrics(self) -> dict:
        actual = None
        peak = None
        if (
            self.torch is not None
            and self.device == "cuda"
            and self.torch.cuda.is_available()
        ):
            actual = self.torch.cuda.memory_allocated() // (1024 * 1024)
            peak = self.torch.cuda.max_memory_allocated() // (1024 * 1024)
        return {
            "loaded": self.prior is not None and self.decoder is not None,
            "execution_provider": self.execution_provider,
            "actual_vram_mb": actual,
            "actual_peak_vram_mb": peak,
        }


class KokoroTTSWorkerAdapter:
    SAMPLE_RATE = 24_000
    MAX_TEXT_CHARS = 4_000
    MAX_PCM_BYTES = 12 * 1024 * 1024
    LANG_CODES = {
        "en": "a",
        "en-us": "a",
        "en-gb": "b",
        "zh": "z",
        "zh-cn": "z",
    }

    def __init__(self, model_root: Path):
        self.model_root = model_root
        self.model = None
        self.torch = None
        self.pipeline_class = None
        self.pipelines = {}
        self.backend = None
        self.execution_provider = None

    def capabilities(self) -> dict:
        return {
            "operations": ["probe", "tts"],
            "modalities": ["text", "audio"],
            "sample_rate": self.SAMPLE_RATE,
            "languages": sorted(self.LANG_CODES),
            "max_text_chars": self.MAX_TEXT_CHARS,
            "remote_code": False,
        }

    def load(self, payload: dict) -> dict:
        backend = str(payload.get("backend") or "")
        if backend not in {"rocm_pytorch", "cuda", "cpu"}:
            raise AdapterError("INVALID_BACKEND", "Unsupported TTS backend")
        visible_index = payload.get("visible_index")
        if visible_index is not None:
            value = str(int(visible_index))
            if backend == "rocm_pytorch":
                os.environ["HIP_VISIBLE_DEVICES"] = value
                os.environ["ROCR_VISIBLE_DEVICES"] = value
            elif backend == "cuda":
                os.environ["CUDA_VISIBLE_DEVICES"] = value
        try:
            import torch
            from kokoro import KModel, KPipeline
        except ImportError as exc:
            raise AdapterError(
                "TTS_RUNTIME_DEPENDENCY_MISSING",
                "The isolated Kokoro TTS Worker dependencies are not installed",
            ) from exc
        if backend == "rocm_pytorch":
            if not torch.cuda.is_available() or not getattr(torch.version, "hip", None):
                raise AdapterError(
                    "ROCM_RUNTIME_UNAVAILABLE",
                    "PyTorch ROCm is not available in this TTS Worker",
                )
            device = "cuda"
            provider = "PyTorchROCm"
        elif backend == "cuda":
            if (
                not torch.cuda.is_available()
                or not getattr(torch.version, "cuda", None)
                or getattr(torch.version, "hip", None)
            ):
                raise AdapterError(
                    "CUDA_RUNTIME_UNAVAILABLE",
                    "PyTorch CUDA is not available in this TTS Worker",
                )
            device = "cuda"
            provider = "PyTorchCUDA"
        else:
            device = "cpu"
            provider = "PyTorchCPU"
        config_path = (self.model_root / "config.json").resolve()
        weights_path = (self.model_root / "kokoro-v1_0.pth").resolve()
        if not config_path.is_file() or not weights_path.is_file():
            raise AdapterError(
                "MODEL_FILES_MISSING",
                "Verified Kokoro model files are unavailable",
            )
        try:
            model = KModel(
                repo_id="hexgrad/Kokoro-82M",
                config=str(config_path),
                model=str(weights_path),
            ).to(device).eval()
        except Exception as exc:
            raise AdapterError(
                "TTS_MODEL_LOAD_FAILED",
                f"Kokoro model failed to load: {type(exc).__name__}",
            ) from exc
        self.torch = torch
        self.pipeline_class = KPipeline
        self.model = model
        self.pipelines = {}
        self.backend = backend
        self.execution_provider = provider
        return {
            "effective_backend": backend,
            "execution_provider": provider,
            "model_id": "hexgrad/Kokoro-82M",
            "sample_rate": self.SAMPLE_RATE,
            "remote_code": False,
        }

    def unload(self) -> dict:
        self.pipelines = {}
        self.model = None
        if self.torch is not None and self.torch.cuda.is_available():
            self.torch.cuda.empty_cache()
        self.backend = None
        self.execution_provider = None
        gc.collect()
        return {"unloaded": True}

    def _pipeline(self, locale: str):
        normalized = str(locale or "und").strip().lower().replace("_", "-")
        lang_code = self.LANG_CODES.get(normalized)
        if lang_code is None:
            primary = normalized.split("-", 1)[0]
            lang_code = self.LANG_CODES.get(primary)
        if lang_code is None:
            raise AdapterError(
                "TTS_LANGUAGE_UNSUPPORTED",
                "The selected Kokoro voice locale is not supported",
            )
        pipeline = self.pipelines.get(lang_code)
        if pipeline is None:
            try:
                pipeline = self.pipeline_class(
                    lang_code=lang_code,
                    repo_id="hexgrad/Kokoro-82M",
                    model=self.model,
                )
            except Exception as exc:
                raise AdapterError(
                    "TTS_LANGUAGE_RUNTIME_MISSING",
                    f"Kokoro language runtime failed to initialize: {type(exc).__name__}",
                ) from exc
            self.pipelines[lang_code] = pipeline
        return pipeline

    def _voice_path(self, voice_name: str) -> Path:
        if (
            not voice_name
            or len(voice_name) > 128
            or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in voice_name)
        ):
            raise AdapterError("INVALID_TTS_VOICE", "Invalid Kokoro voice name")
        voice_root = (self.model_root / "voices").resolve()
        voice_path = (voice_root / f"{voice_name}.pt").resolve()
        if voice_root not in voice_path.parents or not voice_path.is_file():
            raise AdapterError(
                "TTS_VOICE_MISSING",
                "The selected verified Kokoro voice file is unavailable",
            )
        return voice_path

    def _synthesize(self, payload: dict, cancelled: threading.Event) -> bytes:
        if self.model is None:
            raise AdapterError("NOT_LOADED", "Kokoro TTS runtime is not loaded")
        if payload.get("action") != "tts":
            raise AdapterError("INVALID_TTS_OPERATION", "Unsupported TTS Worker action")
        text = str(payload.get("text") or "").strip()
        if not text or len(text) > self.MAX_TEXT_CHARS or "\x00" in text:
            raise AdapterError("INVALID_TTS_TEXT", "TTS text is empty or too large")
        speed = float(payload.get("speed", 1.0))
        if not 0.5 <= speed <= 2.0:
            raise AdapterError("INVALID_TTS_SPEED", "TTS speed is outside the allowed range")
        pipeline = self._pipeline(str(payload.get("locale") or "und"))
        voice_path = self._voice_path(str(payload.get("voice_name") or ""))
        chunks = []
        try:
            generator = pipeline(
                text,
                voice=str(voice_path),
                speed=speed,
                split_pattern=None,
            )
            for result in generator:
                if cancelled.is_set():
                    raise AdapterError("CANCELLED", "TTS inference was cancelled")
                audio = result.audio
                if audio is None or audio.numel() == 0:
                    continue
                chunks.append(audio.detach().float().cpu())
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(
                "TTS_INFERENCE_FAILED",
                f"Kokoro inference failed: {type(exc).__name__}",
            ) from exc
        if not chunks:
            raise AdapterError("TTS_OUTPUT_EMPTY", "Kokoro returned no audio samples")
        audio = self.torch.cat(chunks).clamp(-1.0, 1.0)
        pcm = (
            (audio * 32767.0)
            .round()
            .to(dtype=self.torch.int16)
            .contiguous()
            .numpy()
            .tobytes()
        )
        if not pcm or len(pcm) > self.MAX_PCM_BYTES:
            raise AdapterError(
                "TTS_OUTPUT_TOO_LARGE",
                "Generated TTS segment exceeds the Worker output limit",
            )
        return pcm

    @staticmethod
    def _write_wav(output_path: str, pcm: bytes, sample_rate: int) -> None:
        candidate = Path(str(output_path or ""))
        if (
            not candidate.is_absolute()
            or candidate.suffix.lower() != ".wav"
            or not candidate.parent.is_dir()
            or candidate.parent.is_symlink()
        ):
            raise AdapterError(
                "INVALID_OUTPUT_PATH",
                "TTS output path must be a prepared absolute WAV staging path",
            )
        try:
            import wave

            with wave.open(str(candidate), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(sample_rate)
                handle.writeframes(pcm)
        except OSError as exc:
            raise AdapterError(
                "OUTPUT_WRITE_FAILED",
                "Generated TTS audio could not be written to staging",
            ) from exc

    def probe(self, _payload: dict, cancelled: threading.Event) -> dict:
        started = time.perf_counter()
        pcm = self._synthesize(
            {
                "action": "tts",
                "text": "AetherDB multilingual audio runtime probe.",
                "locale": "en-US",
                "voice_name": "af_heart",
                "speed": 1.0,
            },
            cancelled,
        )
        return {
            "verified": True,
            "effective_backend": self.backend,
            "execution_provider": self.execution_provider,
            "model_id": "hexgrad/Kokoro-82M",
            "sample_rate": self.SAMPLE_RATE,
            "duration_ms": round(len(pcm) / 2 / self.SAMPLE_RATE * 1000),
            "output_size_bytes": len(pcm),
            "output_digest": hashlib.sha256(pcm).hexdigest(),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "remote_code": False,
        }

    def infer(self, payload: dict, cancelled: threading.Event) -> dict:
        started = time.perf_counter()
        pcm = self._synthesize(payload, cancelled)
        self._write_wav(payload.get("output_path"), pcm, self.SAMPLE_RATE)
        return {
            "model_id": "hexgrad/Kokoro-82M",
            "effective_backend": self.backend,
            "execution_provider": self.execution_provider,
            "operation": "tts",
            "sample_rate": self.SAMPLE_RATE,
            "channels": 1,
            "sample_width_bytes": 2,
            "duration_ms": round(len(pcm) / 2 / self.SAMPLE_RATE * 1000),
            "output_mime_type": "audio/wav",
            "output_size_bytes": len(pcm) + 44,
            "output_digest": hashlib.sha256(pcm).hexdigest(),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "remote_code": False,
        }

    def metrics(self) -> dict:
        actual = None
        peak = None
        if (
            self.torch is not None
            and self.model is not None
            and self.torch.cuda.is_available()
        ):
            actual = self.torch.cuda.memory_allocated() // (1024 * 1024)
            peak = self.torch.cuda.max_memory_allocated() // (1024 * 1024)
        return {
            "loaded": self.model is not None,
            "execution_provider": self.execution_provider,
            "actual_vram_mb": actual,
            "actual_peak_vram_mb": peak,
        }


class TestEchoWorkerAdapter:
    """Deterministic process-boundary fixture; never selected by bundled packages."""

    def __init__(self, _model_root: Path):
        self.backend = None

    def capabilities(self) -> dict:
        return {"operations": ["probe", "echo"], "modalities": ["text"]}

    def load(self, payload: dict) -> dict:
        self.backend = payload.get("backend")
        return {"effective_backend": self.backend, "execution_provider": "TestProvider"}

    def unload(self) -> dict:
        self.backend = None
        return {"unloaded": True}

    def probe(self, _payload: dict, cancelled: threading.Event) -> dict:
        if cancelled.is_set():
            raise AdapterError("CANCELLED", "Probe cancelled")
        return {
            "verified": True,
            "effective_backend": self.backend,
            "execution_provider": "TestProvider",
            "elapsed_ms": 1.0,
        }

    def infer(self, payload: dict, cancelled: threading.Event) -> dict:
        if payload.get("crash"):
            os._exit(70)
        delay = min(float(payload.get("delay_seconds") or 0), 5.0)
        deadline = time.monotonic() + delay
        while time.monotonic() < deadline:
            if cancelled.wait(0.02):
                raise AdapterError("CANCELLED", "Inference cancelled")
        return {
            "echo": payload.get("value"),
            "effective_backend": self.backend,
            "elapsed_ms": delay * 1000,
        }

    def metrics(self) -> dict:
        return {
            "loaded": self.backend is not None,
            "actual_vram_mb": 64 if self.backend != "cpu" else 0,
            "actual_peak_vram_mb": 96 if self.backend != "cpu" else 0,
        }


ADAPTERS = {
    "aetherdb_onnx_embedding": BgeM3WorkerAdapter,
    "aetherdb_torch_bge_vl": BgeVLClipWorkerAdapter,
    "aetherdb_diffusers_kandinsky": Kandinsky22WorkerAdapter,
    "aetherdb_torch_kokoro": KokoroTTSWorkerAdapter,
    "test_worker": TestEchoWorkerAdapter,
}


class WorkerServer:
    def __init__(self, args):
        self.worker_id = args.worker_id
        adapter_class = ADAPTERS.get(args.runtime_adapter)
        if adapter_class is None:
            raise AdapterError(
                "UNSUPPORTED_ADAPTER",
                "Package runtime adapter is not registered by AetherDB",
            )
        self.adapter = adapter_class(Path(args.model_root).resolve())
        self.state = WorkerState.COLD
        self._write_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._stop = threading.Event()
        self._active_operation_id: str | None = None
        self._active_cancel: threading.Event | None = None

    def write(
        self,
        *,
        request_id: str | None,
        event: str,
        ok: bool,
        data: dict | None = None,
        error: WorkerError | None = None,
    ) -> None:
        response = WorkerResponse(
            request_id=request_id,
            event=event,
            ok=ok,
            worker_id=self.worker_id,
            state=self.state,
            data=data or {},
            error=error,
        )
        encoded = response.model_dump_json()
        with self._write_lock:
            sys.stdout.write(encoded + "\n")
            sys.stdout.flush()

    def heartbeat_loop(self):
        while not self._stop.wait(2):
            try:
                self.write(
                    request_id=None,
                    event="heartbeat",
                    ok=True,
                    data={"metrics": self.adapter.metrics()},
                )
            except Exception:
                return

    def _finish_operation(self, request: WorkerRequest, command: str, cancelled: threading.Event):
        try:
            if command == "load":
                data = self.adapter.load(request.payload)
                self.state = WorkerState.READY
            elif command == "unload":
                data = self.adapter.unload()
                self.state = WorkerState.COLD
            elif command == "probe":
                data = self.adapter.probe(request.payload, cancelled)
                self.state = WorkerState.READY
            else:
                data = self.adapter.infer(request.payload, cancelled)
                self.state = WorkerState.READY
            if cancelled.is_set() and command in {"probe", "infer"}:
                raise AdapterError("CANCELLED", "Worker operation was cancelled")
            self.write(request_id=request.request_id, event="result", ok=True, data=data)
        except AdapterError as exc:
            self.state = WorkerState.READY if command in {"probe", "infer"} else WorkerState.FAILED
            self.write(
                request_id=request.request_id,
                event="error",
                ok=False,
                error=WorkerError(code=exc.code, message=exc.safe_message),
            )
        except Exception as exc:
            self.state = WorkerState.FAILED
            self.write(
                request_id=request.request_id,
                event="error",
                ok=False,
                error=WorkerError(
                    code="WORKER_OPERATION_FAILED",
                    message=f"Worker operation failed: {type(exc).__name__}",
                ),
            )
        finally:
            with self._state_lock:
                self._active_operation_id = None
                self._active_cancel = None

    def dispatch(self, request: WorkerRequest):
        if request.command == "health":
            self.write(
                request_id=request.request_id,
                event="result",
                ok=True,
                data={"protocol_version": PROTOCOL_VERSION, "alive": True},
            )
            return
        if request.command == "capabilities":
            self.write(
                request_id=request.request_id,
                event="result",
                ok=True,
                data=self.adapter.capabilities(),
            )
            return
        if request.command == "metrics":
            self.write(
                request_id=request.request_id,
                event="result",
                ok=True,
                data=self.adapter.metrics(),
            )
            return
        if request.command == "cancel":
            target = str(request.payload.get("operation_id") or "")
            with self._state_lock:
                accepted = target == self._active_operation_id and self._active_cancel is not None
                if accepted:
                    self._active_cancel.set()
            self.write(
                request_id=request.request_id,
                event="result",
                ok=True,
                data={"cancel_requested": accepted, "operation_id": target},
            )
            return
        if request.command == "shutdown":
            self.state = WorkerState.DRAINING
            with self._state_lock:
                if self._active_cancel is not None:
                    self._active_cancel.set()
            try:
                self.adapter.unload()
            except Exception:
                pass
            self.state = WorkerState.STOPPED
            self.write(
                request_id=request.request_id,
                event="result",
                ok=True,
                data={"stopped": True},
            )
            self._stop.set()
            return

        with self._state_lock:
            if self._active_operation_id is not None:
                self.write(
                    request_id=request.request_id,
                    event="error",
                    ok=False,
                    error=WorkerError(
                        code="WORKER_BUSY",
                        message="Worker already has an active operation",
                    ),
                )
                return
            if request.command in {"probe", "infer"} and self.state != WorkerState.READY:
                self.write(
                    request_id=request.request_id,
                    event="error",
                    ok=False,
                    error=WorkerError(code="NOT_READY", message="Worker model is not ready"),
                )
                return
            if request.command == "load" and self.state not in {
                WorkerState.COLD,
                WorkerState.FAILED,
            }:
                self.write(
                    request_id=request.request_id,
                    event="error",
                    ok=False,
                    error=WorkerError(code="INVALID_STATE", message="Worker cannot load now"),
                )
                return
            if request.command == "unload" and self.state != WorkerState.READY:
                self.write(
                    request_id=request.request_id,
                    event="error",
                    ok=False,
                    error=WorkerError(code="INVALID_STATE", message="Worker cannot unload now"),
                )
                return
            operation_id = str(request.payload.get("operation_id") or request.request_id)
            cancelled = threading.Event()
            self._active_operation_id = operation_id
            self._active_cancel = cancelled
            self.state = (
                WorkerState.STARTING
                if request.command in {"load", "unload"}
                else WorkerState.BUSY
            )
        if getattr(self.adapter, "run_operations_on_main_thread", False):
            self._finish_operation(request, request.command, cancelled)
            return
        threading.Thread(
            target=self._finish_operation,
            args=(request, request.command, cancelled),
            daemon=True,
            name=f"worker-{request.command}",
        ).start()

    def run(self):
        threading.Thread(target=self.heartbeat_loop, daemon=True, name="worker-heartbeat").start()
        for line in sys.stdin:
            if self._stop.is_set():
                break
            if len(line.encode("utf-8")) > MAX_MESSAGE_BYTES:
                continue
            try:
                request = WorkerRequest.model_validate_json(line)
            except Exception:
                continue
            self.dispatch(request)
            if self._stop.is_set():
                break
        self._stop.set()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--package-version", required=True)
    parser.add_argument("--manifest-digest", required=True)
    parser.add_argument("--runtime-adapter", required=True)
    parser.add_argument("--model-root", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        WorkerServer(args).run()
    except AdapterError as exc:
        sys.stderr.write(f"{exc.code}:{exc.safe_message}\n")
        raise SystemExit(64)


if __name__ == "__main__":
    main()
