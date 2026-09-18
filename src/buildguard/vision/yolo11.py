"""Lazy, local-only YOLOv11 adapter (ultralytics backend)."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from buildguard.config import VisionModelConfig
from buildguard.exceptions import ModelUnavailableError
from buildguard.schemas.common import BoundingBox
from buildguard.schemas.vision import Detection
from buildguard.vision.base_detector import Detector
from buildguard.vision.postprocessing import class_aware_nms, map_box_to_original
from buildguard.vision.preprocessing import DecodedImage, bgr_to_rgb, letterbox
from buildguard.vision.schemas import LetterboxTransform

# (yolo_class_name, confidence, (x1, y1, x2, y2)) — xyxy in letterbox space
_RawDetection = tuple[str, float, tuple[float, float, float, float]]
YOLO11Runner = Callable[[list[NDArray[np.uint8]]], list[list[_RawDetection]]]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class _UltralyticsRunner:
    def __init__(self, config: VisionModelConfig) -> None:
        try:
            from ultralytics import YOLO  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ModelUnavailableError(
                "YOLO11 requires ultralytics: pip install ultralytics"
            ) from exc
        try:
            self._model = YOLO(str(config.model_path))
        except Exception as exc:
            raise ModelUnavailableError(f"Cannot load YOLO11 model: {exc}") from exc
        self._device = config.device

    def __call__(
        self, images: list[NDArray[np.uint8]]
    ) -> list[list[_RawDetection]]:
        results = self._model.predict(
            source=images,
            conf=0.0,
            verbose=False,
            device=self._device,
        )
        output: list[list[_RawDetection]] = []
        for result in results:
            detections: list[_RawDetection] = []
            if result.boxes is not None:
                names = result.names  # dict[int, str]
                for box in result.boxes:
                    cls_id = int(box.cls[0].item())
                    conf = float(box.conf[0].item())
                    x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
                    detections.append((names[cls_id], conf, (x1, y1, x2, y2)))
            output.append(detections)
        return output


class YOLO11Adapter(Detector):
    """Production YOLOv11 detector; imports ultralytics only on demand."""

    def __init__(
        self,
        detector_config: VisionModelConfig,
        runner: YOLO11Runner | None = None,
    ) -> None:
        super().__init__(detector_config)

        model_path = detector_config.model_path
        if model_path is None or not Path(model_path).resolve().exists():
            raise ModelUnavailableError(
                f"YOLO11 model file is missing: {model_path}"
            )
        if detector_config.model_sha256:
            actual = _sha256_file(Path(model_path))
            if actual != detector_config.model_sha256:
                raise ModelUnavailableError(
                    f"YOLO11 weights SHA-256 mismatch: "
                    f"expected {detector_config.model_sha256}, got {actual}"
                )
        self._yolo_class_mapping: dict[str, str] = detector_config.yolo_class_mapping
        self.performance_records: list[dict[str, float | int | str]] = []
        self._runner: YOLO11Runner = runner or _UltralyticsRunner(detector_config)

    def _adapt(
        self,
        raw: list[_RawDetection],
        transform: LetterboxTransform,
        requested_classes: list[str] | None,
    ) -> list[Detection]:
        detections: list[Detection] = []
        for yolo_name, confidence, (x1, y1, x2, y2) in raw:
            label = self._yolo_class_mapping.get(yolo_name)
            if label is None:
                continue
            if requested_classes is not None and label not in requested_classes:
                continue
            if confidence < self.config.confidence_threshold:
                continue
            mapped = map_box_to_original(
                BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2), transform
            )
            if mapped is not None:
                detections.append(
                    Detection(
                        label=label,
                        confidence=confidence,
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
        batch_size = min(self.config.batch_size, len(images))
        while offset < len(images):
            current = prepared[offset : offset + batch_size]
            started = time.perf_counter()
            try:
                raw_batch = self._runner(current)
                if len(raw_batch) != len(current):
                    raise RuntimeError("YOLO11 runner returned wrong batch length")
                for index, raw in enumerate(raw_batch):
                    output.append(
                        self._adapt(raw, transforms[offset + index], requested_classes)
                    )
                self.performance_records.append(
                    {
                        "batch_size": len(current),
                        "duration_ms": (time.perf_counter() - started) * 1000,
                        "device": self.config.device,
                    }
                )
                offset += len(current)
            except RuntimeError as exc:
                is_oom = "out of memory" in str(exc).casefold()
                if batch_size > 1:
                    batch_size = max(1, batch_size // 2) if is_oom else 1
                    continue
                raise RuntimeError(
                    f"YOLO11 inference failed for image index {offset}: {exc}"
                ) from exc
        return output

    def predict(
        self,
        image: DecodedImage,
        requested_classes: list[str] | None = None,
    ) -> list[Detection]:
        return self.predict_batch([image], requested_classes)[0]
