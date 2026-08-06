"""Explicit local model adapter without assumed output formats."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
from numpy.typing import NDArray

from buildguard.config import VisionModelConfig
from buildguard.exceptions import ModelUnavailableError
from buildguard.schemas.vision import Detection
from buildguard.vision.base_detector import Detector
from buildguard.vision.postprocessing import class_aware_nms, map_box_to_original
from buildguard.vision.preprocessing import DecodedImage, letterbox

LocalRunner = Callable[[NDArray[np.uint8]], Any]
LocalOutputAdapter = Callable[[Any, str], list[Detection]]


class LocalDetectorAdapter(Detector):
    """Wrap an externally supplied ONNX/PyTorch runner and output adapter."""

    def __init__(
        self,
        config: VisionModelConfig,
        runner: LocalRunner | None = None,
        output_adapter: LocalOutputAdapter | None = None,
    ) -> None:
        super().__init__(config)
        if config.model_path is None or not config.model_path.resolve().exists():
            raise ModelUnavailableError(
                f"Local detector model path is missing: {config.model_path}"
            )
        self.runner = runner
        self.output_adapter = output_adapter

    def predict(
        self,
        image: DecodedImage,
        requested_classes: list[str] | None = None,
    ) -> list[Detection]:
        if self.runner is None or self.output_adapter is None:
            raise ModelUnavailableError(
                f"Detector {self.name} requires an explicit runner and output adapter"
            )
        prepared, transform = letterbox(image.bgr, self.config.input_size)
        raw = self.runner(prepared)
        adapted = self.output_adapter(raw, self.name)
        mapped: list[Detection] = []
        for detection in adapted:
            if requested_classes is not None and detection.label not in requested_classes:
                continue
            if detection.confidence < self.config.confidence_threshold:
                continue
            box = map_box_to_original(detection.bounding_box, transform)
            if box is not None:
                mapped.append(detection.model_copy(update={"bounding_box": box}))
        return class_aware_nms(mapped, self.config.nms_iou)

