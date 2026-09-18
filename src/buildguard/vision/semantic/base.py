"""Contract for an image-aware semantic scorer used before VisualRouter."""

from __future__ import annotations

from abc import ABC, abstractmethod

from buildguard.config import MobileClip2SemanticRouterConfig
from buildguard.schemas.common import BoundingBox
from buildguard.vision.preprocessing import DecodedImage
from buildguard.vision.routing.schemas import RoutingModel
from buildguard.vision.semantic.schemas import SemanticRoutingResult


class SemanticImageRouter(ABC):
    """Score specialist relevance without producing detections or risk decisions."""

    config: MobileClip2SemanticRouterConfig

    @property
    @abstractmethod
    def loaded(self) -> bool:
        """Whether the local semantic model is currently resident."""

    @abstractmethod
    def load(self) -> None:
        """Load and prepare the local semantic model without downloading files."""

    @abstractmethod
    def score(
        self,
        image: DecodedImage,
        models: list[RoutingModel],
        *,
        crop: BoundingBox | None = None,
    ) -> SemanticRoutingResult:
        """Return bounded per-specialist relevance scores for an image or crop."""

    @abstractmethod
    def unload(self) -> None:
        """Release model resources."""
