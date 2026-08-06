"""Visual detector contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from buildguard.config import VisionModelConfig
from buildguard.schemas.vision import Detection
from buildguard.vision.preprocessing import DecodedImage


class Detector(ABC):
    def __init__(self, config: VisionModelConfig) -> None:
        self.config = config

    @property
    def name(self) -> str:
        return self.config.model_name

    @abstractmethod
    def predict(
        self,
        image: DecodedImage,
        requested_classes: list[str] | None = None,
    ) -> list[Detection]:
        """Return detections in original-image coordinates."""

    def predict_batch(
        self,
        images: list[DecodedImage],
        requested_classes: list[str] | None = None,
    ) -> list[list[Detection]]:
        """Return aligned batch results; adapters may override for GPU batching."""
        return [self.predict(image, requested_classes) for image in images]
