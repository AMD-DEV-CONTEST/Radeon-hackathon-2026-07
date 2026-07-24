# -*- coding: utf-8 -*-
"""Textovid — SHA-256 uniqueness fingerprint engine"""

from __future__ import annotations

import hashlib
from PIL import Image
import io


def image_fingerprint(img: Image.Image) -> str:
    """Return a SHA-256 hash hex string for the image pixels.

    Converts to RGB, resizes to a small canonical size (64×64) to
    make the fingerprint robust against minor re-encodings, then hashes
    the raw pixel bytes.
    """
    canonical = img.convert("RGB").resize((64, 64), Image.LANCZOS)
    buf = io.BytesIO()
    canonical.save(buf, format="PNG")
    return hashlib.sha256(buf.getvalue()).hexdigest()[:32]


def text_fingerprint(text: str) -> str:
    """SHA-256 hash of a text string, truncated to 32 hex chars."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def panel_fingerprint(panel: dict, img: Image.Image) -> dict:
    """Combined fingerprint for a panel (text prompt + image pixels)."""
    fp_prompt = text_fingerprint(panel.get("image_prompt", ""))
    fp_image = image_fingerprint(img)
    combined = hashlib.sha256(
        (fp_prompt + fp_image).encode("utf-8")
    ).hexdigest()[:32]
    return {
        "prompt_hash": fp_prompt,
        "image_hash": fp_image,
        "combined_hash": combined,
    }
