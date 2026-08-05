"""Perceptual and cryptographic hashing for visual comparison."""

from __future__ import annotations

import hashlib
import logging

log = logging.getLogger(__name__)

try:
    from PIL import Image

    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


def sha256_file(path: str) -> str:
    """Cryptographic hash of raw file bytes."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception as exc:
        log.error("[image_hash] sha256_file failed: %s", exc)
        return ""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def average_hash(img: Image.Image, size: int = 8) -> str:
    """Simple average hash (aHash) — fast perceptual similarity."""
    if not _PIL_AVAILABLE:
        return ""
    small = img.convert("L").resize((size, size), Image.LANCZOS)  # type: ignore[attr-defined]
    pixels = list(small.getdata())
    avg = sum(pixels) / len(pixels)
    bits = "".join("1" if p > avg else "0" for p in pixels)
    return format(int(bits, 2), "016x")


def difference_hash(img: Image.Image, size: int = 8) -> str:
    """dHash — horizontal gradient hash, more robust than aHash."""
    if not _PIL_AVAILABLE:
        return ""
    small = img.convert("L").resize((size + 1, size), Image.LANCZOS)  # type: ignore[attr-defined]
    pixels = list(small.getdata())
    bits = ""
    for row in range(size):
        for col in range(size):
            bits += (
                "1" if pixels[row * (size + 1) + col] > pixels[row * (size + 1) + col + 1] else "0"
            )
    return format(int(bits, 2), "016x")


def hamming_distance(h1: str, h2: str) -> int:
    """Bit-level hamming distance between two hex hashes."""
    try:
        v1 = int(h1, 16)
        v2 = int(h2, 16)
        xor = v1 ^ v2
        return bin(xor).count("1")
    except ValueError:
        return 64  # max distance on error


def are_similar(h1: str, h2: str, threshold: int = 10) -> bool:
    """True if hamming distance is within threshold (default ≤10 bits out of 64)."""
    return hamming_distance(h1, h2) <= threshold
