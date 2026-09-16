"""Deterministically normalize uploaded photo orientation before local inference."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


def _mask_profile(result: dict[str, Any]) -> tuple[int, float]:
    ratios: list[float] = []
    for mask in result.get("masks") or []:
        bounds = mask.getbbox()
        if not bounds:
            continue
        width = max(1, bounds[2] - bounds[0])
        height = max(1, bounds[3] - bounds[1])
        ratios.append(min(3.0, height / width))
    return len(ratios), (sum(ratios) / len(ratios) if ratios else 0.0)


def _orientation_score(result: dict[str, Any]) -> tuple[float, int, float]:
    people, upright_ratio = _mask_profile(result)
    detections = int(result.get("detections") or 0)
    score = people * 4.0 + min(detections, 5) * 0.15 + upright_ratio
    return score, people, upright_ratio


def _person_geometry(
    result: dict[str, Any],
    image: Image.Image,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for mask in result.get("masks") or []:
        bounds = mask.getbbox()
        if not bounds:
            continue
        left, top, right, bottom = bounds
        width = max(1, right - left)
        height = max(1, bottom - top)
        candidates.append(
            {
                "box": [
                    round(left * 1000 / image.width),
                    round(top * 1000 / image.height),
                    round(right * 1000 / image.width),
                    round(bottom * 1000 / image.height),
                ],
                "area": width * height,
                "aspect": height / width,
                "height_ratio": height / image.height,
            }
        )
    largest_area = max((item["area"] for item in candidates), default=0)
    prominent = [
        item
        for item in candidates
        if largest_area and item["area"] >= largest_area * 0.28
    ]
    boxes = [item["box"] for item in prominent]
    aspects = [item["aspect"] for item in prominent]
    height_ratios = [item["height_ratio"] for item in prominent]
    largest_aspect = max(aspects, default=0.0)
    largest_height_ratio = max(height_ratios, default=0.0)
    return {
        "people_count": len(boxes),
        "visible_people_count": len(candidates),
        "person_boxes": boxes,
        "largest_aspect_ratio": round(largest_aspect, 3),
        "largest_height_ratio": round(largest_height_ratio, 3),
        "full_body_candidate": (
            largest_aspect >= 2.0 and largest_height_ratio >= 0.45
        ),
        "source": "local_mask_rcnn",
    }


def _save_normalized(image: Image.Image, path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        image.save(path, "JPEG", quality=95, subsampling=0)
    elif suffix == ".webp":
        image.save(path, "WEBP", quality=95)
    else:
        image.save(path, "PNG")


def normalize_image_orientation(
    image_path: str | Path,
    *,
    segmenter: Any | None = None,
) -> dict[str, Any]:
    """Apply EXIF orientation, then conservatively recover sideways people.

    Mask R-CNN is already part of the local deterministic toolchain. It is used
    only when the first pass does not contain a clearly upright person, and the
    chosen rotation must materially improve the upright-person score.
    """
    path = Path(image_path).expanduser().resolve()
    with Image.open(path) as opened:
        original_exif_orientation = int(opened.getexif().get(274, 1))
        source = ImageOps.exif_transpose(opened).convert("RGB")

    chosen = source
    chosen_degrees = 0
    method = "exif" if original_exif_orientation != 1 else "none"
    evaluated = [0]

    if segmenter is None:
        from src.tools.person_segmenter import get_shared_person_segmenter

        segmenter = get_shared_person_segmenter()

    baseline_result = segmenter.segment(source, [])
    chosen_result = baseline_result
    baseline_score, baseline_people, baseline_ratio = _orientation_score(
        baseline_result
    )

    if baseline_people == 0 or baseline_ratio < 1.05:
        best_score = baseline_score
        best_people = baseline_people
        best_ratio = baseline_ratio
        for degrees in (90, 270):
            candidate = source.rotate(degrees, expand=True)
            result = segmenter.segment(candidate, [])
            score, people, upright_ratio = _orientation_score(result)
            evaluated.append(degrees)
            if score > best_score:
                chosen = candidate
                chosen_result = result
                chosen_degrees = degrees
                best_score = score
                best_people = people
                best_ratio = upright_ratio

        material_gain = best_score >= baseline_score + 0.65
        visibly_upright = best_people > 0 and best_ratio >= 1.05
        if chosen_degrees and material_gain and visibly_upright:
            method = "exif_and_person_upright" if method == "exif" else "person_upright"
        else:
            chosen = source
            chosen_result = baseline_result
            chosen_degrees = 0

    _save_normalized(chosen, path)
    return {
        "status": "normalized",
        "rotation_degrees": chosen_degrees,
        "method": method,
        "evaluated_degrees": evaluated,
        "width": chosen.width,
        "height": chosen.height,
        "person_geometry": _person_geometry(chosen_result, chosen),
    }
