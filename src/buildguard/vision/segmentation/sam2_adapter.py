"""Explicit local SAM 2 adapter with box-prompt mask measurement."""

from __future__ import annotations

import gc
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from buildguard.config import SegmentationConfig
from buildguard.exceptions import ModelUnavailableError
from buildguard.schemas.common import BoundingBox
from buildguard.vision.preprocessing import DecodedImage, bgr_to_rgb
from buildguard.vision.segmentation.base import (
    FineSegmentationAdapter,
    PointPrompt,
    RawMaskPrediction,
    SegmentationMask,
)
from buildguard.vision.segmentation.mask_metrics import (
    mask_area,
    mask_area_ratio,
    mask_bounding_box,
    mask_perimeter,
    normalize_mask,
)
from buildguard.vision.segmentation.visualization import save_mask

Sam2ModelLoader = Callable[[Path, str], object]
Sam2Runner = Callable[
    [
        object,
        NDArray[np.uint8],
        list[BoundingBox],
        list[PointPrompt] | None,
        int,
    ],
    Any,
]
Sam2OutputAdapter = Callable[[Any], list[RawMaskPrediction]]


@dataclass
class _TransformersSam2Runtime:
    processor: Any
    model: Any
    torch: Any
    device: Any


def _load_transformers_sam2(model_dir: Path, device_name: str) -> object:
    try:
        import torch
        from transformers import Sam2Model, Sam2Processor
    except ImportError as exc:
        raise ModelUnavailableError(
            "SAM 2 requires compatible local torch and transformers"
        ) from exc
    device = torch.device(device_name)
    processor = Sam2Processor.from_pretrained(model_dir, local_files_only=True)
    model = Sam2Model.from_pretrained(model_dir, local_files_only=True)
    model.to(device)  # type: ignore[arg-type]
    model.eval()  # type: ignore[no-untyped-call]
    return _TransformersSam2Runtime(processor, model, torch, device)


def _mask_stability(logits: Any) -> float:
    high = logits > 0.05
    low = logits > -0.05
    intersection = int((high & low).sum().item())
    union = int((high | low).sum().item())
    return intersection / union if union else 0.0


def _run_transformers_sam2(
    runtime: object,
    rgb: NDArray[np.uint8],
    boxes: list[BoundingBox],
    points: list[PointPrompt] | None,
    batch_size: int,
) -> object:
    if not isinstance(runtime, _TransformersSam2Runtime):
        raise TypeError("Unexpected SAM 2 runtime")
    predictions: list[RawMaskPrediction] = []
    for offset in range(0, len(boxes), batch_size):
        current = boxes[offset : offset + batch_size]
        input_boxes = [
            [[box.x1, box.y1, box.x2, box.y2] for box in current]
        ]
        point_values = None
        point_labels = None
        if points:
            point_values = [
                [[[point.x, point.y] for point in points] for _ in current]
            ]
            point_labels = [
                [[point.label for point in points] for _ in current]
            ]
        encoded = runtime.processor(
            images=rgb,
            input_boxes=input_boxes,
            input_points=point_values,
            input_labels=point_labels,
            return_tensors="pt",
        )
        encoded = {key: value.to(runtime.device) for key, value in encoded.items()}
        with runtime.torch.no_grad():
            output = runtime.model(**encoded, multimask_output=True)
        restored = runtime.processor.post_process_masks(
            output.pred_masks,
            encoded["original_sizes"],
            binarize=False,
        )[0]
        scores = output.iou_scores[0]
        for object_index in range(len(current)):
            object_scores = scores[object_index]
            best_index = int(runtime.torch.argmax(object_scores).item())
            logits = restored[object_index][best_index].detach().cpu()
            mask = (logits > 0).numpy().astype(np.bool_)
            predictions.append(
                RawMaskPrediction(
                    mask=mask,
                    confidence=max(
                        0.0,
                        min(1.0, float(object_scores[best_index].detach().cpu())),
                    ),
                    stability=_mask_stability(logits),
                )
            )
    return predictions


def _adapt_transformers_sam2(raw: Any) -> list[RawMaskPrediction]:
    if not isinstance(raw, list) or any(
        not isinstance(item, RawMaskPrediction) for item in raw
    ):
        raise ValueError("Unexpected SAM 2 output format")
    return raw


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


class Sam2LocalAdapter(FineSegmentationAdapter):
    """Lazy local Transformers SAM 2 adapter with injectable runtime functions."""

    def __init__(
        self,
        config: SegmentationConfig,
        loader: Sam2ModelLoader | None = None,
        runner: Sam2Runner | None = None,
        output_adapter: Sam2OutputAdapter | None = None,
    ) -> None:
        self.config = config
        supplied = (loader, runner, output_adapter)
        if any(item is not None for item in supplied) and not all(
            item is not None for item in supplied
        ):
            raise ValueError(
                "SAM 2 loader, runner, and output adapter must be supplied together"
            )
        self.loader = loader or _load_transformers_sam2
        self.runner = runner or _run_transformers_sam2
        self.output_adapter = output_adapter or _adapt_transformers_sam2
        self._model: object | None = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _load(self) -> object:
        if not self.config.enabled:
            raise ModelUnavailableError("SAM 2 segmentation is disabled")
        if self.config.model_dir is None:
            raise ModelUnavailableError(
                "SAM 2 model_dir is not configured; segmentation skipped"
            )
        model_dir = self.config.model_dir.resolve()
        if not model_dir.is_dir():
            raise ModelUnavailableError(
                f"SAM 2 local model directory is missing: {model_dir}"
            )
        if self._model is None:
            try:
                self._model = self.loader(model_dir, self.config.device)
            except Exception as exc:
                raise ModelUnavailableError(
                    f"Could not load local SAM 2 model: {exc}"
                ) from exc
        return self._model

    def segment(
        self,
        image: DecodedImage,
        bbox_prompts: list[BoundingBox],
        point_prompts: list[PointPrompt] | None = None,
    ) -> list[SegmentationMask]:
        if not bbox_prompts:
            return []
        boxes = [
            box.clip(float(image.width), float(image.height))
            for box in bbox_prompts
        ]
        model = self._load()
        batch_size = min(self.config.batch_size, len(boxes))
        try:
            while True:
                try:
                    raw = self.runner(
                        model,
                        bgr_to_rgb(image.bgr),
                        boxes,
                        point_prompts,
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
                            "SAM 2 inference ran out of device memory"
                        ) from exc
                    batch_size = max(1, batch_size // 2)
            predictions = self.output_adapter(raw)
            if len(predictions) != len(boxes):
                raise ValueError(
                    "SAM 2 output adapter must return one prediction per box prompt"
                )
            results: list[SegmentationMask] = []
            for index, (prompt, prediction) in enumerate(
                zip(boxes, predictions, strict=True)
            ):
                if prediction.confidence < self.config.min_confidence:
                    continue
                if prediction.stability < self.config.min_stability:
                    continue
                mask = normalize_mask(
                    prediction.mask,
                    (image.height, image.width),
                )
                if not np.any(mask):
                    continue
                results.append(
                    SegmentationMask(
                        mask=mask,
                        area=mask_area(mask),
                        area_ratio=mask_area_ratio(mask),
                        perimeter=mask_perimeter(mask),
                        bounding_box=mask_bounding_box(mask),
                        confidence=prediction.confidence,
                        stability=prediction.stability,
                        source_model=self.config.model_name,
                        mask_path=save_mask(
                            mask,
                            self.config.output_dir,
                            image_checksum=image.checksum,
                            prompt_box=prompt,
                            index=index,
                        ),
                    )
                )
            return results
        finally:
            if self.config.unload_after_inference:
                self.unload()

    def unload(self) -> None:
        self._model = None
        gc.collect()
        _release_device_cache()
