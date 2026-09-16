"""Deterministic pixel-level gate for generated preview corruption."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps


def _metrics(path: str | Path) -> dict[str, float]:
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB").resize((256, 256))
    pixels = np.asarray(image, dtype=np.float32)
    edge_energy = (
        np.abs(np.diff(pixels, axis=0)).mean()
        + np.abs(np.diff(pixels, axis=1)).mean()
    ) / 2
    chroma = pixels.max(axis=2) - pixels.min(axis=2)
    return {
        "edge_energy": round(float(edge_energy), 4),
        "color_std": round(float(pixels.std()), 4),
        "clipped_fraction": round(
            float(np.mean((pixels < 2) | (pixels > 253))), 6
        ),
        "extreme_chroma_fraction": round(float(np.mean(chroma > 180)), 6),
    }


def assess_image_health(
    reference_path: str | Path, preview_path: str | Path
) -> dict[str, Any]:
    """Reject noise, contrast collapse, and saturated block artifacts."""
    reference = _metrics(reference_path)
    preview = _metrics(preview_path)
    issues: list[str] = []

    if preview["edge_energy"] > max(35.0, reference["edge_energy"] * 4.0):
        issues.append("High-frequency noise pattern detected.")
    if (
        preview["color_std"] < 4.0
        or (
            reference["color_std"] > 20.0
            and preview["color_std"] < reference["color_std"] * 0.38
        )
    ):
        issues.append("Generated image contrast collapsed.")
    if preview["clipped_fraction"] > max(
        0.18, reference["clipped_fraction"] * 8.0 + 0.02
    ):
        issues.append("Excessive clipped pixels detected.")
    if preview["extreme_chroma_fraction"] > max(
        0.0025, reference["extreme_chroma_fraction"] * 8.0 + 0.0025
    ):
        issues.append("Saturated color-block artifacts detected.")

    return {
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "reference_metrics": reference,
        "preview_metrics": preview,
    }
