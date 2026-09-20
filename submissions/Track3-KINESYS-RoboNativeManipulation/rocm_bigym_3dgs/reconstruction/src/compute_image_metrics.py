#!/usr/bin/env python3
"""Compute deterministic held-out RGB metrics for an OpenSplat render."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--render", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0


def main() -> None:
    args = parse_args()
    reference = load_rgb(args.reference)
    rendered = load_rgb(args.render)
    if reference.shape != rendered.shape:
        raise RuntimeError(
            f"held-out image shape mismatch: {reference.shape} != {rendered.shape}"
        )
    mse = float(np.mean((reference - rendered) ** 2))
    psnr = float("inf") if mse == 0 else -10.0 * math.log10(mse)
    ssim = float(
        structural_similarity(
            reference,
            rendered,
            channel_axis=2,
            data_range=1.0,
        )
    )
    report = {
        "schema_version": 1,
        "reference": str(args.reference),
        "render": str(args.render),
        "resolution": [int(reference.shape[1]), int(reference.shape[0])],
        "mse": mse,
        "psnr": psnr,
        "ssim": ssim,
        "lpips": None,
        "note": "LPIPS is intentionally reported as unmeasured when no pinned perceptual-model weights are present.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
