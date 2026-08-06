import random
from pathlib import Path

from adapters.base import ImageProvider


class StubImageProvider(ImageProvider):
    """Returns the input image duplicated for quick integration testing."""

    name = "stub_image"

    def generate_image_from_text(self, prompt: str) -> Path:
        raise NotImplementedError("Stub does not support text-to-image.")

    def generate_image_from_image(self, image: Path, prompt: str) -> Path:
        return image

    def generate_multiview_from_image(self, image: Path, prompt: str, num_views: int = 4) -> list[Path]:
        # In a real implementation this would call Zero123 / MVDream / etc.
        return [image for _ in range(num_views)]
