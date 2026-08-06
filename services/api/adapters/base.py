from abc import ABC, abstractmethod
from pathlib import Path


class MeshAsset:
    def __init__(self, mesh_path: Path, texture_path: Path | None = None):
        self.mesh_path = mesh_path
        self.texture_path = texture_path


class ThreeDProvider(ABC):
    name: str = "base"

    @abstractmethod
    def generate_3d_from_images(
        self, images: list[Path], prompt: str, style: str, output_path: Path | None = None
    ) -> MeshAsset:
        raise NotImplementedError

    @abstractmethod
    def generate_3d_from_text(self, prompt: str, style: str, output_path: Path | None = None) -> MeshAsset:
        raise NotImplementedError


class ImageProvider(ABC):
    name: str = "base"

    @abstractmethod
    def generate_image_from_text(self, prompt: str) -> Path:
        raise NotImplementedError

    @abstractmethod
    def generate_image_from_image(self, image: Path, prompt: str) -> Path:
        raise NotImplementedError

    @abstractmethod
    def generate_multiview_from_image(self, image: Path, prompt: str, num_views: int = 4) -> list[Path]:
        raise NotImplementedError


class DepthProvider(ABC):
    name: str = "base"

    @abstractmethod
    def generate_depth_map(self, image: Path, invert: bool = False) -> Path:
        """Estimate a depth / height map from a single image."""
        raise NotImplementedError
