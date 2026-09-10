"""Deterministic structure-only L3 metric contract."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from specstyle.observability.hashing import hash_bytes


def _scene(
    *,
    foreground: tuple[int, int, int] = (240, 240, 240),
    position: tuple[int, int, int, int] = (16, 16, 48, 48),
    size: tuple[int, int] = (64, 64),
) -> bytes:
    image = Image.new("RGB", size, (10, 10, 10))
    ImageDraw.Draw(image).rectangle(position, fill=foreground)
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def test_structure_edge_similarity_is_color_invariant_for_same_geometry() -> None:
    from specstyle.verification.l3.structure_edges import structure_edge_similarity

    source = _scene(foreground=(240, 240, 240))
    output = _scene(foreground=(30, 180, 90))

    assert structure_edge_similarity(source, output) == pytest.approx(1.0)


def test_structure_edge_similarity_penalizes_geometry_change() -> None:
    from specstyle.verification.l3.structure_edges import structure_edge_similarity

    source = _scene(position=(8, 8, 28, 28))
    output = _scene(position=(36, 36, 56, 56))

    score = structure_edge_similarity(source, output)

    assert score is not None
    assert 0.0 <= score < 0.25


@pytest.mark.parametrize(
    ("source", "output"),
    (
        (b"not-a-png", _scene()),
        (_scene(), b"not-a-png"),
        (_scene(size=(64, 32), position=(8, 8, 24, 24)), _scene()),
        (_scene(foreground=(10, 10, 10)), _scene(foreground=(10, 10, 10))),
    ),
)
def test_structure_edge_similarity_returns_none_when_unverifiable(
    source: bytes, output: bytes
) -> None:
    from specstyle.verification.l3.structure_edges import structure_edge_similarity

    assert structure_edge_similarity(source, output) is None


def test_structure_verifier_pin_hashes_the_loaded_implementation() -> None:
    import specstyle.verification.l3.structure_edges as structure_edges

    pin = structure_edges.structure_edge_verifier_pin()

    assert pin.id == "structure-edge-verifier"
    assert pin.revision == "sobel-cosine-v1"
    assert pin.sha256 == hash_bytes(Path(structure_edges.__file__).read_bytes())
