"""Explicit local Grounding DINO-family adapter with no assumed package format."""

from __future__ import annotations

import gc
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from buildguard.config import OpenVocabularyConfig
from buildguard.exceptions import ModelUnavailableError
from buildguard.schemas.common import BoundingBox
from buildguard.schemas.vision import Detection
from buildguard.vision.open_vocab.base import OpenVocabularyLocator
from buildguard.vision.open_vocab.class_mapping import PromptClassMapper
from buildguard.vision.preprocessing import DecodedImage, bgr_to_rgb

GroundingModelLoader = Callable[[Path, str], object]
GroundingRunner = Callable[
    [object, NDArray[np.uint8], list[str], int],
    Any,
]
GroundingOutputAdapter = Callable[[Any, str], list[Detection]]


@dataclass
class _TransformersGroundingRuntime:
    processor: Any
    model: Any
    torch: Any
    device: Any


def _load_transformers_grounding(model_dir: Path, device_name: str) -> object:
    try:
        import torch
        from transformers import (
            GroundingDinoForObjectDetection,
            GroundingDinoProcessor,
        )
    except ImportError as exc:
        raise ModelUnavailableError(
            "Grounding DINO requires compatible local torch and transformers"
        ) from exc
    device = torch.device(device_name)
    processor = GroundingDinoProcessor.from_pretrained(
        model_dir,
        local_files_only=True,
    )
    model = GroundingDinoForObjectDetection.from_pretrained(
        model_dir,
        local_files_only=True,
    )
    model.to(device)  # type: ignore[arg-type]
    model.eval()  # type: ignore[no-untyped-call]
    return _TransformersGroundingRuntime(processor, model, torch, device)


def _run_transformers_grounding(
    runtime: object,
    rgb: NDArray[np.uint8],
    queries: list[str],
    batch_size: int,
) -> object:
    if not isinstance(runtime, _TransformersGroundingRuntime):
        raise TypeError("Unexpected Grounding DINO runtime")
    detections: list[Detection] = []
    for offset in range(0, len(queries), batch_size):
        current = queries[offset : offset + batch_size]
        prompt = ". ".join(current) + "."
        encoded = runtime.processor(
            images=rgb,
            text=prompt,
            return_tensors="pt",
        )
        encoded = {key: value.to(runtime.device) for key, value in encoded.items()}
        with runtime.torch.no_grad():
            output = runtime.model(**encoded)
        processed = runtime.processor.post_process_grounded_object_detection(
            output,
            input_ids=encoded.get("input_ids"),
            threshold=0.0,
            text_threshold=0.0,
            target_sizes=[rgb.shape[:2]],
        )[0]
        labels = processed.get("text_labels", processed.get("labels", []))
        for score, label, box in zip(
            processed["scores"],
            labels,
            processed["boxes"],
        ):
            if isinstance(label, str):
                canonical = label.strip().rstrip(".")
            else:
                index = int(label)
                canonical = current[index] if 0 <= index < len(current) else ""
            if not canonical:
                continue
            values = box.detach().cpu().tolist()
            detections.append(
                Detection(
                    label=canonical,
                    confidence=max(0.0, min(1.0, float(score))),
                    bounding_box=BoundingBox(
                        x1=float(values[0]),
                        y1=float(values[1]),
                        x2=float(values[2]),
                        y2=float(values[3]),
                    ),
                    source_model="grounding-dino-local",
                )
            )
    return detections


def _adapt_transformers_grounding(raw: Any, model_name: str) -> list[Detection]:
    if not isinstance(raw, list) or any(not isinstance(item, Detection) for item in raw):
        raise ValueError("Unexpected Grounding DINO output format")
    return [item.model_copy(update={"source_model": model_name}) for item in raw]


def _is_oom_error(exc: BaseException) -> bool:
    name = type(exc).__name__.casefold()
    message = str(exc).casefold()
    return "outofmemory" in name or "out of memory" in message or "oom" in message


def _release_device_cache() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except (ImportError, RuntimeError):
        return


class GroundingDinoLocalAdapter(OpenVocabularyLocator):
    """Lazy local Transformers adapter with injectable test/runtime functions."""

    def __init__(
        self,
        config: OpenVocabularyConfig,
        loader: GroundingModelLoader | None = None,
        runner: GroundingRunner | None = None,
        output_adapter: GroundingOutputAdapter | None = None,
    ) -> None:
        self.config = config
        supplied = (loader, runner, output_adapter)
        if any(item is not None for item in supplied) and not all(
            item is not None for item in supplied
        ):
            raise ValueError(
                "Grounding loader, runner, and output adapter must be supplied together"
            )
        self.loader = loader or _load_transformers_grounding
        self.runner = runner or _run_transformers_grounding
        self.output_adapter = output_adapter or _adapt_transformers_grounding
        self.mapper = PromptClassMapper(
            config.prompt_allowlist,
            config.class_aliases,
        )
        self._model: object | None = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _load(self) -> object:
        if not self.config.enabled:
            raise ModelUnavailableError("Open-vocabulary localization is disabled")
        if self.config.model_dir is None:
            raise ModelUnavailableError(
                "Open-vocabulary model_dir is not configured; localization skipped"
            )
        model_dir = self.config.model_dir.resolve()
        if not model_dir.is_dir():
            raise ModelUnavailableError(
                f"Open-vocabulary local model directory is missing: {model_dir}"
            )
        if self._model is None:
            try:
                self._model = self.loader(model_dir, self.config.device)
            except Exception as exc:
                raise ModelUnavailableError(
                    f"Could not load local open-vocabulary model: {exc}"
                ) from exc
        return self._model

    def locate(
        self,
        image: DecodedImage,
        text_queries: list[str],
    ) -> list[Detection]:
        queries = self.mapper.normalize(text_queries)
        model = self._load()
        batch_size = min(self.config.batch_size, len(queries))
        try:
            while True:
                try:
                    raw = self.runner(
                        model,
                        bgr_to_rgb(image.bgr),
                        queries,
                        batch_size,
                    )
                    break
                except Exception as exc:
                    if not _is_oom_error(exc):
                        raise
                    _release_device_cache()
                    if batch_size <= 1:
                        self.unload()
                        raise ModelUnavailableError(
                            "Open-vocabulary inference ran out of device memory"
                        ) from exc
                    batch_size = max(1, batch_size // 2)
            adapted = self.output_adapter(raw, self.config.model_name)
            detections: list[Detection] = []
            allowed = set(queries)
            for detection in adapted:
                if detection.label not in allowed:
                    continue
                if detection.confidence < self.config.confidence_threshold:
                    continue
                try:
                    box = detection.bounding_box.clip(
                        float(image.width),
                        float(image.height),
                    )
                except ValueError:
                    continue
                detections.append(
                    detection.model_copy(
                        update={
                            "bounding_box": box,
                            "source_model": self.config.model_name,
                            "attributes": {
                                **detection.attributes,
                                "adapter_role": "open_vocab_localizer",
                                "risk_decision_allowed": False,
                            },
                        }
                    )
                )
            return sorted(
                detections,
                key=lambda item: (
                    item.label,
                    -item.confidence,
                    item.bounding_box.x1,
                    item.bounding_box.y1,
                ),
            )
        finally:
            if self.config.unload_after_inference:
                self.unload()

    def unload(self) -> None:
        self._model = None
        gc.collect()
        _release_device_cache()
