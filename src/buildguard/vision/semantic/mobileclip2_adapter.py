"""Offline MobileCLIP2-S0 semantic scorer for expert-model routing."""

from __future__ import annotations

import gc
import hashlib
import hmac
import importlib
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from buildguard.config import MobileClip2SemanticRouterConfig
from buildguard.exceptions import ModelUnavailableError
from buildguard.schemas.common import BoundingBox
from buildguard.vision.preprocessing import DecodedImage, bgr_to_rgb
from buildguard.vision.routing.schemas import RoutingModel
from buildguard.vision.semantic.base import SemanticImageRouter
from buildguard.vision.semantic.schemas import (
    SemanticExpertScore,
    SemanticRoutingResult,
)

MobileClipLoader = Callable[[Path, str, str], object]
MobileClipRunner = Callable[
    [object, NDArray[np.uint8], list[str], str],
    list[float],
]


@dataclass
class _OpenClipRuntime:
    model: Any
    preprocess: Any
    tokenizer: Any
    torch: Any
    device: Any
    text_cache: dict[tuple[str, ...], Any] = field(default_factory=dict)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _reparameterize_for_inference(model: Any) -> Any:
    """Copy a re-parameterizable model and fuse every supported inference block."""
    inference_model = deepcopy(model)
    for module in inference_model.modules():
        reparameterize = getattr(module, "reparameterize", None)
        if callable(reparameterize):
            reparameterize()
    return inference_model


def _load_open_clip_runtime(model_path: Path, model_name: str, device_name: str) -> object:
    try:
        import torch

        open_clip = importlib.import_module("open_clip")
    except ImportError as exc:
        raise ModelUnavailableError(
            "MobileCLIP2-S0 requires the optional mobileclip dependencies"
        ) from exc

    try:
        model, _, preprocess = open_clip.create_model_and_transforms(
            model_name,
            pretrained=str(model_path),
            device="cpu",
            precision="fp32",
            image_mean=(0.0, 0.0, 0.0),
            image_std=(1.0, 1.0, 1.0),
        )
        tokenizer = open_clip.get_tokenizer(model_name)
        model.eval()
        model = _reparameterize_for_inference(model)
        device = torch.device(device_name)
        model.to(device)
        model.eval()
    except Exception as exc:
        raise ModelUnavailableError(f"Could not load MobileCLIP2-S0: {exc}") from exc
    return _OpenClipRuntime(model, preprocess, tokenizer, torch, device)


def _run_open_clip(
    raw_runtime: object,
    rgb: NDArray[np.uint8],
    prompts: list[str],
    precision: str,
) -> list[float]:
    if not isinstance(raw_runtime, _OpenClipRuntime):
        raise TypeError("Unexpected MobileCLIP2 runtime")
    if not prompts:
        return []
    try:
        from PIL import Image

        runtime = raw_runtime
        image = runtime.preprocess(Image.fromarray(rgb)).unsqueeze(0).to(runtime.device)
        prompt_key = tuple(prompts)
        text_features = runtime.text_cache.get(prompt_key)
        autocast_enabled = runtime.device.type == "cuda" and precision != "fp32"
        dtype = {
            "fp16": runtime.torch.float16,
            "bf16": runtime.torch.bfloat16,
        }.get(precision, runtime.torch.float32)
        with runtime.torch.inference_mode(), runtime.torch.autocast(
            device_type=runtime.device.type,
            dtype=dtype,
            enabled=autocast_enabled,
        ):
            if text_features is None:
                tokens = runtime.tokenizer(prompts).to(runtime.device)
                text_features = runtime.model.encode_text(tokens)
                text_features = text_features / text_features.norm(
                    dim=-1, keepdim=True
                ).clamp_min(1e-12)
                runtime.text_cache[prompt_key] = text_features
            image_features = runtime.model.encode_image(image)
            image_features = image_features / image_features.norm(
                dim=-1, keepdim=True
            ).clamp_min(1e-12)
            similarities = image_features @ text_features.T
        return [
            float(value)
            for value in similarities.detach().float().cpu().reshape(-1).tolist()
        ]
    except Exception as exc:
        raise ModelUnavailableError(f"MobileCLIP2-S0 inference failed: {exc}") from exc


def _release_device_cache() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except (ImportError, RuntimeError):
        return


class MobileClip2S0Adapter(SemanticImageRouter):
    """Lazy, checksum-verified and cache-bounded MobileCLIP2-S0 adapter."""

    def __init__(
        self,
        config: MobileClip2SemanticRouterConfig,
        loader: MobileClipLoader | None = None,
        runner: MobileClipRunner | None = None,
    ) -> None:
        self.config = config
        self.loader = loader or _load_open_clip_runtime
        self.runner = runner or _run_open_clip
        self._runtime: object | None = None
        self._cache: OrderedDict[str, SemanticRoutingResult] = OrderedDict()
        self._lock = threading.RLock()

    @property
    def loaded(self) -> bool:
        return self._runtime is not None

    def _model_path(self) -> Path:
        if not self.config.enabled:
            raise ModelUnavailableError("MobileCLIP2 semantic routing is disabled")
        if self.config.model_path is None or self.config.model_sha256 is None:
            raise ModelUnavailableError("MobileCLIP2 model path or checksum is not configured")
        path = self.config.model_path.resolve()
        if not path.is_file():
            raise ModelUnavailableError(f"MobileCLIP2 checkpoint is missing: {path}")
        actual = _sha256_file(path)
        if not hmac.compare_digest(actual, self.config.model_sha256):
            raise ModelUnavailableError(
                "MobileCLIP2 checkpoint checksum mismatch: "
                f"expected {self.config.model_sha256}, got {actual}"
            )
        return path

    def load(self) -> None:
        with self._lock:
            if self._runtime is None:
                self._runtime = self.loader(
                    self._model_path(),
                    self.config.model_name,
                    self.config.device,
                )

    @staticmethod
    def _crop_rgb(
        image: DecodedImage,
        crop: BoundingBox | None,
    ) -> tuple[NDArray[np.uint8], str]:
        if crop is None:
            return bgr_to_rgb(image.bgr), "scene"
        clipped = crop.clip(float(image.width), float(image.height))
        x1, y1 = int(clipped.x1), int(clipped.y1)
        x2 = max(x1 + 1, math.ceil(clipped.x2))
        y2 = max(y1 + 1, math.ceil(clipped.y2))
        cropped = image.bgr[y1:y2, x1:x2]
        if cropped.size == 0:
            raise ValueError("MobileCLIP2 crop contains no pixels")
        key = f"{x1}:{y1}:{x2}:{y2}"
        return bgr_to_rgb(cropped), key

    def _cache_get(self, key: str) -> SemanticRoutingResult | None:
        result = self._cache.get(key)
        if result is None:
            return None
        self._cache.move_to_end(key)
        return result.model_copy(update={"processing_ms": 0.0, "cache_hit": True})

    def _cache_put(self, key: str, result: SemanticRoutingResult) -> None:
        if self.config.cache_max_items <= 0:
            return
        self._cache[key] = result
        self._cache.move_to_end(key)
        while len(self._cache) > self.config.cache_max_items:
            self._cache.popitem(last=False)

    def score(
        self,
        image: DecodedImage,
        models: list[RoutingModel],
        *,
        crop: BoundingBox | None = None,
    ) -> SemanticRoutingResult:
        with self._lock:
            rgb, crop_key = self._crop_rgb(image, crop)
            relevant = [
                model
                for model in sorted(models, key=lambda item: item.model_name)
                if model.enabled and model.model_name in self.config.experts
            ]
            cache_key = (
                f"{image.checksum}:{crop_key}:"
                + ",".join(model.model_name for model in relevant)
            )
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached

            started = time.perf_counter()
            self.load()
            prompts: list[str] = []
            spans: dict[str, tuple[int, int, int]] = {}
            for model in relevant:
                prompt_set = self.config.experts[model.model_name]
                positive_start = len(prompts)
                prompts.extend(prompt_set.positive)
                negative_start = len(prompts)
                prompts.extend(prompt_set.negative)
                spans[model.model_name] = (
                    positive_start,
                    negative_start,
                    len(prompts),
                )
            similarities = self.runner(
                self._runtime,
                rgb,
                prompts,
                self.config.precision,
            )
            if len(similarities) != len(prompts):
                raise ValueError(
                    "MobileCLIP2 similarity output count does not match prompt count"
                )
            if any(not math.isfinite(value) for value in similarities):
                raise ValueError("MobileCLIP2 similarities must be finite")
            scores: list[SemanticExpertScore] = []
            for model in relevant:
                positive_start, negative_start, end = spans[model.model_name]
                positive = max(similarities[positive_start:negative_start])
                negative = max(similarities[negative_start:end])
                prompt_set = self.config.experts[model.model_name]
                logit = (
                    positive - negative - prompt_set.bias
                ) / prompt_set.temperature
                probability = 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, logit))))
                scores.append(
                    SemanticExpertScore(
                        model_name=model.model_name,
                        positive_similarity=max(-1.0, min(1.0, positive)),
                        negative_similarity=max(-1.0, min(1.0, negative)),
                        probability=max(0.0, min(1.0, probability)),
                    )
                )
            result = SemanticRoutingResult(
                status="completed",
                model_name=self.config.model_name,
                model_revision=self.config.model_revision,
                checkpoint_sha256=self.config.model_sha256,
                expert_scores=scores,
                processing_ms=(time.perf_counter() - started) * 1000,
            )
            self._cache_put(cache_key, result)
            return result

    def unload(self) -> None:
        with self._lock:
            self._runtime = None
            self._cache.clear()
        gc.collect()
        _release_device_cache()
