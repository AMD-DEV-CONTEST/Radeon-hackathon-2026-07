"""Validation of real COCO detection datasets before GPU training."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from pathlib import Path
from typing import Any, Literal

import orjson
from pydantic import Field

from buildguard.schemas.common import StrictSchema

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SPLIT_ALIASES = {
    "train": ("train",),
    "validation": ("validation", "val"),
    "test": ("test",),
}


class CocoSplitAudit(StrictSchema):
    split: str
    image_dir: Path | None = None
    annotation_file: Path | None = None
    image_count: int = Field(ge=0)
    annotated_image_count: int = Field(ge=0)
    annotation_count: int = Field(ge=0)
    category_counts: dict[str, int] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)


class CocoDatasetAudit(StrictSchema):
    status: Literal["PASS", "FAIL"]
    root: Path
    content_hash_checked: bool
    categories: dict[int, str]
    splits: list[CocoSplitAudit]
    leakage: dict[str, list[str]] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)


def _load_object(path: Path) -> dict[str, Any]:
    payload = orjson.loads(path.read_bytes())
    if not isinstance(payload, dict):
        raise TypeError(f"COCO root must be an object: {path}")
    return payload


def _find_split(root: Path, canonical: str) -> tuple[Path | None, Path | None]:
    for alias in SPLIT_ALIASES[canonical]:
        image_candidates = (root / "images" / alias, root / alias)
        annotation_candidates = (
            root / "annotations" / f"instances_{alias}.json",
            root / f"instances_{alias}.json",
        )
        image_dir = next((path for path in image_candidates if path.is_dir()), None)
        annotation_file = next(
            (path for path in annotation_candidates if path.is_file()), None
        )
        if image_dir is not None or annotation_file is not None:
            return image_dir, annotation_file
    return None, None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _audit_split(root: Path, split: str) -> tuple[CocoSplitAudit, dict[str, Path]]:
    image_dir, annotation_file = _find_split(root, split)
    issues: list[str] = []
    if image_dir is None:
        issues.append(f"{split}: image directory is missing")
    if annotation_file is None:
        issues.append(f"{split}: COCO annotation file is missing")
    if image_dir is None or annotation_file is None:
        return (
            CocoSplitAudit(
                split=split,
                image_dir=image_dir,
                annotation_file=annotation_file,
                image_count=0,
                annotated_image_count=0,
                annotation_count=0,
                issues=issues,
            ),
            {},
        )

    image_files = {
        path.name.casefold(): path
        for path in image_dir.rglob("*")
        if path.is_file() and path.suffix.casefold() in IMAGE_SUFFIXES
    }
    try:
        payload = _load_object(annotation_file)
    except (OSError, TypeError, ValueError, orjson.JSONDecodeError) as exc:
        issues.append(f"{split}: invalid annotation JSON: {exc}")
        return (
            CocoSplitAudit(
                split=split,
                image_dir=image_dir,
                annotation_file=annotation_file,
                image_count=len(image_files),
                annotated_image_count=0,
                annotation_count=0,
                issues=issues,
            ),
            image_files,
        )

    images = payload.get("images")
    annotations = payload.get("annotations")
    categories = payload.get("categories")
    if not isinstance(images, list):
        images = []
        issues.append(f"{split}: images must be a list")
    if not isinstance(annotations, list):
        annotations = []
        issues.append(f"{split}: annotations must be a list")
    if not isinstance(categories, list):
        categories = []
        issues.append(f"{split}: categories must be a list")

    category_map: dict[int, str] = {}
    for item in categories:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int):
            issues.append(f"{split}: category without an integer id")
            continue
        category_id = item["id"]
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            issues.append(f"{split}: category {category_id} has no name")
            continue
        if category_id in category_map:
            issues.append(f"{split}: duplicate category id {category_id}")
        category_map[category_id] = name.strip()
    if len(set(category_map.values())) != len(category_map):
        issues.append(f"{split}: duplicate category names")

    image_map: dict[int, dict[str, Any]] = {}
    referenced_files: set[str] = set()
    for item in images:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int):
            issues.append(f"{split}: image without an integer id")
            continue
        image_id = item["id"]
        file_name = item.get("file_name")
        width = item.get("width")
        height = item.get("height")
        if image_id in image_map:
            issues.append(f"{split}: duplicate image id {image_id}")
            continue
        if not isinstance(file_name, str) or not file_name.strip():
            issues.append(f"{split}: image {image_id} has no file_name")
            continue
        if not isinstance(width, int) or width <= 0 or not isinstance(height, int) or height <= 0:
            issues.append(f"{split}: image {image_id} has invalid dimensions")
            continue
        normalized = Path(file_name).name.casefold()
        referenced_files.add(normalized)
        if normalized not in image_files:
            issues.append(f"{split}: missing image file {file_name}")
        image_map[image_id] = item

    category_counts: Counter[str] = Counter()
    annotated_images: set[int] = set()
    for index, annotation in enumerate(annotations):
        if not isinstance(annotation, dict):
            issues.append(f"{split}: annotation {index} is not an object")
            continue
        image_id = annotation.get("image_id")
        category_id = annotation.get("category_id")
        bbox = annotation.get("bbox")
        if not isinstance(image_id, int) or image_id not in image_map:
            issues.append(f"{split}: annotation {index} references unknown image")
            continue
        image = image_map[image_id]
        if not isinstance(category_id, int) or category_id not in category_map:
            issues.append(f"{split}: annotation {index} references unknown category")
            continue
        if (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                for value in bbox
            )
        ):
            issues.append(f"{split}: annotation {index} has an invalid bbox")
            continue
        x, y, width, height = (float(value) for value in bbox)
        if (
            x < 0
            or y < 0
            or width <= 0
            or height <= 0
            or x + width > float(image["width"]) + 1.0
            or y + height > float(image["height"]) + 1.0
        ):
            issues.append(f"{split}: annotation {index} bbox is outside the image")
            continue
        annotated_images.add(image_id)
        category_counts[category_map[category_id]] += 1

    unreferenced = sorted(set(image_files) - referenced_files)
    if unreferenced:
        issues.append(f"{split}: {len(unreferenced)} image files are not in COCO JSON")
    return (
        CocoSplitAudit(
            split=split,
            image_dir=image_dir,
            annotation_file=annotation_file,
            image_count=len(image_files),
            annotated_image_count=len(annotated_images),
            annotation_count=len(annotations),
            category_counts=dict(sorted(category_counts.items())),
            issues=issues,
        ),
        image_files,
    )


def audit_coco_dataset(root: Path, *, content_hash: bool = False) -> CocoDatasetAudit:
    """Audit train/validation/test COCO splits without changing the dataset."""
    resolved = root.resolve()
    split_results: list[CocoSplitAudit] = []
    split_files: dict[str, dict[str, Path]] = {}
    for split in SPLIT_ALIASES:
        result, files = _audit_split(resolved, split)
        split_results.append(result)
        split_files[split] = files

    issues: list[str] = []
    categories: dict[int, str] = {}
    for result in split_results:
        if result.annotation_file is None:
            continue
        try:
            payload = _load_object(result.annotation_file)
        except (OSError, TypeError, ValueError, orjson.JSONDecodeError):
            continue
        observed = {
            item["id"]: item["name"].strip()
            for item in payload.get("categories", [])
            if isinstance(item, dict)
            and isinstance(item.get("id"), int)
            and isinstance(item.get("name"), str)
        }
        if not categories:
            categories = observed
        elif observed != categories:
            issues.append(f"{result.split}: category map differs from other splits")

    leakage: dict[str, list[str]] = {}
    split_names = list(SPLIT_ALIASES)
    for offset, left in enumerate(split_names):
        for right in split_names[offset + 1 :]:
            repeated_names = sorted(set(split_files[left]) & set(split_files[right]))
            if repeated_names:
                leakage[f"{left}:{right}:filename"] = repeated_names

    if content_hash:
        hashes: dict[str, dict[str, str]] = {}
        for split, files in split_files.items():
            hashes[split] = {_sha256(path): name for name, path in files.items()}
        for offset, left in enumerate(split_names):
            for right in split_names[offset + 1 :]:
                overlap = sorted(set(hashes[left]) & set(hashes[right]))
                if overlap:
                    leakage[f"{left}:{right}:sha256"] = overlap

    if leakage:
        issues.append("train/validation/test leakage was detected")
    issues.extend(
        issue for result in split_results for issue in result.issues
    )
    if not categories:
        issues.append("no valid COCO categories were found")
    return CocoDatasetAudit(
        status="FAIL" if issues else "PASS",
        root=resolved,
        content_hash_checked=content_hash,
        categories=dict(sorted(categories.items())),
        splits=split_results,
        leakage=leakage,
        issues=issues,
    )
