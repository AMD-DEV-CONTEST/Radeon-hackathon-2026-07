"""Image-folder discovery and RGB loading for pipeline inputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp"})


@dataclass(frozen=True, slots=True)
class InputImage:
    view_id: str
    path: Path


def discover_images(
    folder: str | Path,
    *,
    max_views: int | None = None,
) -> list[InputImage]:
    """Return plant images sorted by filename, skipping hidden files."""
    root = Path(folder)
    if not root.is_dir():
        raise FileNotFoundError(f"image folder does not exist: {root}")
    images = [
        InputImage(view_id=path.stem, path=path)
        for path in sorted(root.iterdir())
        if path.is_file()
        and path.suffix.lower() in IMAGE_EXTENSIONS
        and not path.name.startswith(".")
    ]
    if max_views is not None:
        images = images[:max_views]
    if len(images) < 2:
        raise ValueError(
            f"need at least 2 images for sparse-view reconstruction, "
            f"found {len(images)} in {root}"
        )
    return images


def load_rgb_np(path: str | Path) -> np.ndarray:
    """Load an image as an (H, W, 3) uint8 RGB array."""
    try:
        with Image.open(path) as image:
            return np.asarray(image.convert("RGB"), dtype=np.uint8)
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError(f"could not read image {path}") from error
