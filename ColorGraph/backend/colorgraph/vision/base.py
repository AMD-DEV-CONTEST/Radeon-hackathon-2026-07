from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np
from PIL import Image


@dataclass(frozen=True, slots=True)
class MaskPrediction:
    target: str
    mask: np.ndarray
    confidence: float
    metadata: dict[str, object] = field(default_factory=dict)
    score_semantics: str = "provider_defined_confidence_not_accuracy"

    def __post_init__(self) -> None:
        if self.mask.ndim != 2:
            raise ValueError("mask must be a two-dimensional array")
        if not np.isfinite(self.mask).all():
            raise ValueError("mask cannot contain NaN or infinite values")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between zero and one")


class MaskProvider(ABC):
    @property
    @abstractmethod
    def provider_id(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def supported_targets(self) -> frozenset[str]:
        raise NotImplementedError

    @abstractmethod
    def predict_many(
        self,
        image: Image.Image,
        targets: list[str],
    ) -> dict[str, MaskPrediction]:
        raise NotImplementedError
