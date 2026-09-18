"""Lazy, local-only RT-DETRv2 adapter with an injectable test runner."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from pydantic import Field, field_validator

from buildguard.config import VisionModelConfig
from buildguard.exceptions import ModelUnavailableError
from buildguard.schemas.common import BoundingBox, StrictSchema
from buildguard.schemas.vision import Detection
from buildguard.vision.base_detector import Detector
from buildguard.vision.postprocessing import class_aware_nms, map_box_to_original
from buildguard.vision.preprocessing import DecodedImage, bgr_to_rgb, letterbox
from buildguard.vision.schemas import LetterboxTransform

PPE_CLASSES = ("person", "head", "helmet", "safety_vest")


class RTDETRConfig(StrictSchema):
    config_path: Path
    weights_path: Path
    manifest_path: Path
    device: str = "cpu"
    batch_size: int = Field(default=4, ge=1, le=256)
    revision: str = Field(min_length=1)
    model_sha256: str = Field(min_length=64, max_length=64)
    class_mapping: dict[int, str]

    @field_validator("class_mapping")
    @classmethod
    def canonical_mapping(cls, value: dict[int, str]) -> dict[int, str]:
        """Accept any declared detector class while keeping mappings unambiguous."""
        normalized = {class_id: label.strip() for class_id, label in value.items()}
        if any(class_id < 0 for class_id in normalized):
            raise ValueError("RT-DETRv2 class ids must be non-negative")
        if any(not label for label in normalized.values()):
            raise ValueError("RT-DETRv2 class labels must not be empty")
        if len(normalized.values()) != len(set(normalized.values())):
            raise ValueError("RT-DETRv2 class labels must be unique")
        return normalized


class RawRTDETRDetection(StrictSchema):
    class_id: int = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    box: tuple[float, float, float, float]


RTDETRRunner = Callable[
    [list[NDArray[np.uint8]]], list[list[RawRTDETRDetection]]
]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class _TransformersRunner:
    def __init__(self, config: RTDETRConfig) -> None:
        try:
            import torch
            from transformers import (
                RTDetrImageProcessor,
                RTDetrV2ForObjectDetection,
            )
        except ImportError as exc:
            raise ModelUnavailableError(
                "RT-DETRv2 requires compatible local torch and transformers"
            ) from exc
        self.torch = torch
        self.device = torch.device(config.device)
        local_root = (
            config.weights_path
            if config.weights_path.is_dir()
            else config.config_path.parent
        )
        try:
            self.processor: Any = RTDetrImageProcessor.from_pretrained(
                local_root,
                local_files_only=True,
                revision=config.revision,
            )
            self.model: Any = RTDetrV2ForObjectDetection.from_pretrained(
                local_root,
                local_files_only=True,
                revision=config.revision,
            )
            self.model.to(self.device)  # type: ignore[arg-type]
            self.model.eval()  # type: ignore[no-untyped-call]
        except (OSError, RuntimeError, ValueError) as exc:
            raise ModelUnavailableError(f"Cannot load local RT-DETRv2: {exc}") from exc

    def __call__(
        self, images: list[NDArray[np.uint8]]
    ) -> list[list[RawRTDETRDetection]]:
        encoded: dict[str, Any] = dict(
            self.processor(images=images, return_tensors="pt")
        )
        encoded = {key: value.to(self.device) for key, value in encoded.items()}
        with self.torch.no_grad():
            output = self.model(**encoded)
        sizes = [(image.shape[0], image.shape[1]) for image in images]
        processed = self.processor.post_process_object_detection(
            output, threshold=0.0, target_sizes=sizes
        )
        return [
            [
                RawRTDETRDetection(
                    class_id=int(label),
                    confidence=float(score),
                    box=(
                        float(box[0]),
                        float(box[1]),
                        float(box[2]),
                        float(box[3]),
                    ),
                )
                for score, label, box in zip(
                    result["scores"], result["labels"], result["boxes"]
                )
            ]
            for result in processed
        ]


class RTDETRv2Adapter(Detector):
    """Production RT-DETRv2 detector; imports model libraries only on demand."""

    def __init__(
        self,
        detector_config: VisionModelConfig,
        rtdetr_config: RTDETRConfig,
        runner: RTDETRRunner | None = None,
    ) -> None:
        super().__init__(detector_config)
        self.runtime = rtdetr_config
        self.performance_records: list[dict[str, float | int | str]] = []
        undeclared = set(rtdetr_config.class_mapping.values()) - set(
            detector_config.defect_classes
        )
        if undeclared:
            raise ModelUnavailableError(
                "RT-DETRv2 class mapping contains labels absent from defect_classes: "
                f"{sorted(undeclared)}"
            )
        for path in (
            rtdetr_config.config_path,
            rtdetr_config.weights_path,
            rtdetr_config.manifest_path,
        ):
            if not path.resolve().exists():
                raise ModelUnavailableError(f"RT-DETRv2 local path is missing: {path}")
        manifest = json.loads(
            rtdetr_config.manifest_path.read_text(encoding="utf-8")
        )
        if manifest.get("revision") != rtdetr_config.revision:
            raise ModelUnavailableError("RT-DETRv2 manifest revision mismatch")
        if manifest.get("model_sha256") != rtdetr_config.model_sha256:
            raise ModelUnavailableError("RT-DETRv2 manifest SHA-256 mismatch")
        if (
            rtdetr_config.weights_path.is_file()
            and _sha256_file(rtdetr_config.weights_path)
            != rtdetr_config.model_sha256
        ):
            raise ModelUnavailableError("RT-DETRv2 weights SHA-256 mismatch")
        self.runner = runner or _TransformersRunner(rtdetr_config)

    def _adapt(
        self,
        raw: list[RawRTDETRDetection],
        transform: LetterboxTransform,
        requested_classes: list[str] | None,
    ) -> list[Detection]:
        detections: list[Detection] = []
        for item in raw:
            label = self.runtime.class_mapping.get(item.class_id)
            if label is None or (
                requested_classes is not None and label not in requested_classes
            ):
                continue
            if item.confidence < self.config.confidence_threshold:
                continue
            mapped = map_box_to_original(
                BoundingBox(
                    x1=item.box[0],
                    y1=item.box[1],
                    x2=item.box[2],
                    y2=item.box[3],
                ),
                transform,
            )
            if mapped is not None:
                detections.append(
                    Detection(
                        label=label,
                        confidence=item.confidence,
                        bounding_box=mapped,
                        source_model=self.name,
                    )
                )
        return class_aware_nms(detections, self.config.nms_iou)

    def predict_batch(
        self,
        images: list[DecodedImage],
        requested_classes: list[str] | None = None,
    ) -> list[list[Detection]]:
        if not images:
            return []
        prepared: list[NDArray[np.uint8]] = []
        transforms: list[LetterboxTransform] = []
        for image in images:
            item, transform = letterbox(image.bgr, self.config.input_size)
            prepared.append(bgr_to_rgb(item))
            transforms.append(transform)
        output: list[list[Detection]] = []
        offset = 0
        batch_size = min(self.runtime.batch_size, len(images))
        while offset < len(images):
            current = prepared[offset : offset + batch_size]
            started = time.perf_counter()
            try:
                raw_batch = self.runner(current)
                if len(raw_batch) != len(current):
                    raise RuntimeError("RT-DETRv2 runner returned wrong batch length")
                for index, raw in enumerate(raw_batch):
                    output.append(
                        self._adapt(
                            raw,
                            transforms[offset + index],
                            requested_classes,
                        )
                    )
                self.performance_records.append(
                    {
                        "batch_size": len(current),
                        "duration_ms": (time.perf_counter() - started) * 1000,
                        "device": self.runtime.device,
                    }
                )
                offset += len(current)
            except RuntimeError as exc:
                is_oom = "out of memory" in str(exc).casefold()
                if batch_size > 1:
                    batch_size = max(1, batch_size // 2) if is_oom else 1
                    continue
                raise RuntimeError(
                    f"RT-DETRv2 inference failed for image index {offset}: {exc}"
                ) from exc
        return output

    def predict(
        self,
        image: DecodedImage,
        requested_classes: list[str] | None = None,
    ) -> list[Detection]:
        return self.predict_batch([image], requested_classes)[0]
