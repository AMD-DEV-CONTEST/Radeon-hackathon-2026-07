"""Deterministic checksum-based visual detector."""

from __future__ import annotations

import hashlib

import numpy as np

from buildguard.config import VisionModelConfig
from buildguard.schemas.common import BoundingBox
from buildguard.schemas.vision import Detection
from buildguard.vision.base_detector import Detector
from buildguard.vision.postprocessing import class_aware_nms
from buildguard.vision.preprocessing import DecodedImage


class MockDetector(Detector):
    def __init__(self, config: VisionModelConfig, seed: int) -> None:
        super().__init__(config)
        self.seed = seed

    def predict(
        self,
        image: DecodedImage,
        requested_classes: list[str] | None = None,
    ) -> list[Detection]:
        classes = [
            label
            for label in self.config.defect_classes
            if requested_classes is None or label in requested_classes
        ]
        if not classes:
            return []
        material = f"{self.seed}:{self.name}:{image.checksum}".encode()
        local_seed = int.from_bytes(hashlib.sha256(material).digest()[:8], "little")
        rng = np.random.default_rng(local_seed)
        count = int(rng.integers(1, min(3, len(classes)) + 1))
        detections: list[Detection] = []
        for index in range(count):
            width = float(rng.uniform(0.15, 0.45) * image.width)
            height = float(rng.uniform(0.15, 0.45) * image.height)
            x1 = float(rng.uniform(0, max(1.0, image.width - width)))
            y1 = float(rng.uniform(0, max(1.0, image.height - height)))
            confidence = float(
                rng.uniform(self.config.confidence_threshold, 0.99)
            )
            detections.append(
                Detection(
                    label=classes[index % len(classes)],
                    confidence=confidence,
                    bounding_box=BoundingBox(
                        x1=x1,
                        y1=y1,
                        x2=min(float(image.width), x1 + width),
                        y2=min(float(image.height), y1 + height),
                    ),
                    source_model=self.name,
                    attributes={"mock": True},
                )
            )
        return class_aware_nms(detections, self.config.nms_iou)

