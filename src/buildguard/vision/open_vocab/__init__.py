"""Optional local open-vocabulary localization adapters."""

from buildguard.vision.open_vocab.base import OpenVocabularyLocator
from buildguard.vision.open_vocab.grounding_dino_adapter import (
    GroundingDinoLocalAdapter,
)

__all__ = ["GroundingDinoLocalAdapter", "OpenVocabularyLocator"]
