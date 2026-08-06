from __future__ import annotations

import math
from typing import Iterable

from PIL import Image, ImageFilter


TARGET_REGION_PAIRS = 2_000
TARGET_REGION_ASSETS = 500


def region_proposals(width: int, height: int) -> tuple[tuple[int, int, int, int], ...]:
    if min(width, height) < 256:
        raise ValueError("region preference asset must be at least 256px per side")
    return (
        (0, 0, width, height),
        (0, 0, max(1, width * 2 // 3), height),
        (width // 3, 0, width, height),
        (0, 0, width, max(1, height * 2 // 3)),
        (0, height // 3, width, height),
    )


def region_score(image: Image.Image, box: tuple[int, int, int, int]) -> dict[str, float]:
    crop = image.convert("RGB").crop(box).resize((128, 128), Image.Resampling.BILINEAR)
    gray = crop.convert("L")
    histogram = gray.histogram()
    total = sum(histogram)
    entropy = -sum(
        (count / total) * math.log2(count / total)
        for count in histogram
        if count
    )
    edge = gray.filter(ImageFilter.FIND_EDGES)
    edge_energy = sum(edge.getdata()) / (128 * 128 * 255)
    clipped = sum(histogram[:6]) + sum(histogram[250:])
    clipping_ratio = clipped / total
    score = (entropy / 8) * 0.45 + edge_energy * 0.40 + (1 - clipping_ratio) * 0.15
    return {
        "entropy": round(entropy, 9),
        "edge_energy": round(edge_energy, 9),
        "clipping_ratio": round(clipping_ratio, 9),
        "score": round(score, 9),
    }


def ranked_regions(image: Image.Image) -> tuple[dict[str, object], ...]:
    rows = [
        {"box": list(box), "metrics": region_score(image, box)}
        for box in region_proposals(*image.size)
    ]
    rows.sort(key=lambda row: (-float(row["metrics"]["score"]), row["box"]))
    return tuple(rows)


def score_spread(rows: Iterable[dict[str, object]]) -> float:
    scores = [float(row["metrics"]["score"]) for row in rows]
    return max(scores) - min(scores)
