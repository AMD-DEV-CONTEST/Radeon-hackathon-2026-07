"""Base class for image generation providers."""

from abc import ABC, abstractmethod


class ImageProvider(ABC):
    """Abstract image generation provider.

    Implementations can use OpenRouter API, local GPU inference, or other backends.
    """

    @abstractmethod
    def generate_image(self, prompt: str, scene_index: int = 0) -> str | None:
        """Generate an image from a text prompt.

        Args:
            prompt: Text prompt for image generation.
            scene_index: Index of the scene (for logging/caching).

        Returns:
            Path to the downloaded/created image file, or None on failure.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this provider."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The model identifier used by this provider."""
        ...
