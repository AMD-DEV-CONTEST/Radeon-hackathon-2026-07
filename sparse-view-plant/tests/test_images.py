from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from sparse_view_plant.images import discover_images, load_rgb_np


def _make_images(root: Path, names: list[str]) -> list[Path]:
    paths = []
    for index, name in enumerate(names):
        path = root / name
        Image.new("RGB", (8, 6), color=(index * 40, 100, 200)).save(path)
        paths.append(path)
    return paths


def test_discover_images_sorts_by_name(tmp_path: Path) -> None:
    _make_images(tmp_path, ["c.png", "a.jpg", "b.jpeg"])
    images = discover_images(tmp_path)
    assert [image.view_id for image in images] == ["a", "b", "c"]
    assert [image.path.name for image in images] == ["a.jpg", "b.jpeg", "c.png"]


def test_discover_images_skips_hidden_and_non_images(tmp_path: Path) -> None:
    _make_images(tmp_path, ["a.png", "b.png"])
    (tmp_path / ".hidden.png").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    images = discover_images(tmp_path)
    assert [image.path.name for image in images] == ["a.png", "b.png"]


def test_discover_images_max_views(tmp_path: Path) -> None:
    _make_images(tmp_path, ["a.png", "b.png", "c.png"])
    assert len(discover_images(tmp_path, max_views=2)) == 2


def test_discover_images_requires_two(tmp_path: Path) -> None:
    _make_images(tmp_path, ["a.png"])
    with pytest.raises(ValueError, match="at least 2 images"):
        discover_images(tmp_path)


def test_discover_images_missing_folder(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        discover_images(tmp_path / "nope")


def test_load_rgb_np(tmp_path: Path) -> None:
    path = tmp_path / "a.png"
    Image.new("RGB", (8, 6), color=(10, 20, 30)).save(path)
    rgb = load_rgb_np(path)
    assert rgb.shape == (6, 8, 3)
    assert rgb.dtype == np.uint8
    assert rgb[0, 0].tolist() == [10, 20, 30]
