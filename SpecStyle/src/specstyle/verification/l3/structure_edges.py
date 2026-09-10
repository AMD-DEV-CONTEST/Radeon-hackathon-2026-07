"""Pinned structure-only verifier based on deterministic edge-map similarity."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image

from specstyle.errors import DomainError
from specstyle.observability.hashing import hash_bytes
from specstyle.spec.compiled_models import ResourcePin
from specstyle.verification.l1.decode import DecodedImage, decode_png_bytes

__all__ = ("structure_edge_similarity", "structure_edge_verifier_pin")

_GRID_SIZE = 64
_VERIFIER_ID = "structure-edge-verifier"
_VERIFIER_REVISION = "sobel-cosine-v1"


def _grayscale(pixel: tuple[int, int, int]) -> int:
    red, green, blue = pixel
    return (299 * red + 587 * green + 114 * blue + 500) // 1000


def _canonical_grayscale(decoded: DecodedImage) -> tuple[int, ...]:
    image = Image.new("L", decoded.size)
    resized: Image.Image | None = None
    try:
        image.putdata(tuple(_grayscale(pixel) for pixel in decoded.pixels_rgb))
        resized = image.resize(
            (_GRID_SIZE, _GRID_SIZE), resample=Image.Resampling.BILINEAR
        )
        raw = (
            resized.get_flattened_data()
            if hasattr(resized, "get_flattened_data")
            else resized.getdata()
        )
        return tuple(raw)  # type: ignore[arg-type]
    finally:
        if resized is not None:
            resized.close()
        image.close()


def _sobel_edges(pixels: tuple[int, ...]) -> tuple[float, ...]:
    if len(pixels) != _GRID_SIZE * _GRID_SIZE:
        raise ValueError("invalid canonical edge input")
    edges: list[float] = []
    for y in range(1, _GRID_SIZE - 1):
        row = y * _GRID_SIZE
        for x in range(1, _GRID_SIZE - 1):
            center = row + x
            upper, lower = center - _GRID_SIZE, center + _GRID_SIZE
            gx = (
                pixels[upper + 1]
                + 2 * pixels[center + 1]
                + pixels[lower + 1]
                - pixels[upper - 1]
                - 2 * pixels[center - 1]
                - pixels[lower - 1]
            )
            gy = (
                pixels[lower - 1]
                + 2 * pixels[lower]
                + pixels[lower + 1]
                - pixels[upper - 1]
                - 2 * pixels[upper]
                - pixels[upper + 1]
            )
            edges.append(float(abs(gx) + abs(gy)))
    return tuple(edges)


def _decode(value: object) -> DecodedImage | None:
    try:
        return decode_png_bytes(value)
    except DomainError:
        return None


def structure_edge_similarity(source: object, output: object, /) -> float | None:
    """Return cosine edge similarity, or ``None`` when evidence is unusable."""
    source_image, output_image = _decode(source), _decode(output)
    if source_image is None or output_image is None:
        return None
    source_width, source_height = source_image.size
    output_width, output_height = output_image.size
    if source_width * output_height != output_width * source_height:
        return None
    try:
        left = _sobel_edges(_canonical_grayscale(source_image))
        right = _sobel_edges(_canonical_grayscale(output_image))
        left_energy = math.sqrt(sum(value * value for value in left))
        right_energy = math.sqrt(sum(value * value for value in right))
        if left_energy <= 0.0 or right_energy <= 0.0:
            return None
        score = sum(a * b for a, b in zip(left, right, strict=True))
        score /= left_energy * right_energy
    except (MemoryError, OSError, ValueError):
        return None
    if not math.isfinite(score):
        return None
    return 0.0 if score <= 0.0 else min(1.0, score)


def structure_edge_verifier_pin() -> ResourcePin:
    """Bind the verifier capability to the exact implementation source bytes."""
    implementation = Path(__file__).read_bytes()
    return ResourcePin(_VERIFIER_ID, _VERIFIER_REVISION, hash_bytes(implementation))


def _structure_edge_similarity_for_pin(
    verifier_pin: object, source: object, output: object, /
) -> float | None:
    try:
        if verifier_pin != structure_edge_verifier_pin():
            return None
    except (OSError, ValueError):
        return None
    return structure_edge_similarity(source, output)
