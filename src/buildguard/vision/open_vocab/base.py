"""Open-vocabulary localization contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from buildguard.schemas.vision import Detection
from buildguard.vision.preprocessing import DecodedImage


class OpenVocabularyLocator(ABC):
    """Locate allowlisted object concepts without assigning construction risk."""

    @abstractmethod
    def locate(
        self,
        image: DecodedImage,
        text_queries: list[str],
    ) -> list[Detection]:
        """Return object-localization boxes in original-image coordinates."""

    @abstractmethod
    def unload(self) -> None:
        """Release loaded local model resources when the adapter supports it."""
