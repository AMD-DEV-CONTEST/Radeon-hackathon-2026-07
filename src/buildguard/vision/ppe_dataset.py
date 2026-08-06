"""Licensed COCO PPE dataset preparation and split-leakage validation."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from buildguard.schemas.common import StrictSchema
from buildguard.vision.preprocessing import decode_image

CANONICAL_CLASSES = ("person", "head", "helmet", "safety_vest")
Split = Literal["train", "val", "test"]


class DatasetSource(StrictSchema):
    name: str = Field(min_length=1)
    annotations: Path
    image_root: Path
    license: str = Field(min_length=1)
    license_url: str | None = None
    category_mapping: dict[str, str]
    group_defaults: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_mapping(self) -> DatasetSource:
        invalid = set(self.category_mapping.values()) - set(CANONICAL_CLASSES)
        if invalid:
            raise ValueError(f"Non-canonical mapped classes: {sorted(invalid)}")
        return self


class SourceManifest(StrictSchema):
    sources: list[DatasetSource] = Field(min_length=1)
    split_ratios: tuple[float, float, float] = (0.8, 0.1, 0.1)
    split_seed: str = "buildguard-ppe-v1"

    @model_validator(mode="after")
    def validate_ratios(self) -> SourceManifest:
        if any(value <= 0 for value in self.split_ratios):
            raise ValueError("All split ratios must be positive")
        if abs(sum(self.split_ratios) - 1.0) > 1e-9:
            raise ValueError("Split ratios must sum to 1")
        return self


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _split(group_key: str, seed: str, ratios: tuple[float, float, float]) -> Split:
    value = int.from_bytes(
        hashlib.sha256(f"{seed}:{group_key}".encode()).digest()[:8], "big"
    ) / (2**64)
    if value < ratios[0]:
        return "train"
    if value < ratios[0] + ratios[1]:
        return "val"
    return "test"


def _group(image: dict[str, Any], source: DatasetSource) -> tuple[str, dict[str, str]]:
    values: dict[str, str] = {}
    for field in ("site_id", "camera_id", "capture_date", "video_clip_id"):
        raw = image.get(field, source.group_defaults.get(field))
        if raw is None and field == "video_clip_id":
            raw = Path(str(image["file_name"])).stem
        if raw is None:
            raise ValueError(
                f"Image {image.get('id')} lacks grouping field {field}"
            )
        values[field] = str(raw)
    return "|".join(values[field] for field in values), values


def _load_coco(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"COCO root must be an object: {path}")
    for key in ("images", "annotations", "categories"):
        if not isinstance(payload.get(key), list):
            raise TypeError(f"COCO field {key} must be a list: {path}")
    return payload


def prepare_dataset(manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    manifest = SourceManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    output = output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    images_by_split: dict[Split, list[dict[str, Any]]] = defaultdict(list)
    annotations_by_split: dict[Split, list[dict[str, Any]]] = defaultdict(list)
    records: list[dict[str, Any]] = []
    seen_hashes: dict[str, str] = {}
    next_image_id = 1
    next_annotation_id = 1

    for source in manifest.sources:
        coco = _load_coco(source.annotations.resolve())
        category_names = {
            int(item["id"]): str(item["name"]) for item in coco["categories"]
        }
        mapped_categories = {
            identifier: source.category_mapping.get(name)
            for identifier, name in category_names.items()
        }
        image_annotations: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for annotation in coco["annotations"]:
            image_annotations[int(annotation["image_id"])].append(annotation)
        for image in coco["images"]:
            source_path = (source.image_root / str(image["file_name"])).resolve()
            try:
                source_path.relative_to(source.image_root.resolve())
            except ValueError as exc:
                raise ValueError(f"Image path escapes source root: {source_path}") from exc
            decoded = decode_image(source_path)
            width, height = decoded.width, decoded.height
            if int(image.get("width", width)) != width or int(
                image.get("height", height)
            ) != height:
                raise ValueError(f"COCO dimensions do not match image: {source_path}")
            digest = decoded.checksum
            if digest in seen_hashes:
                raise ValueError(
                    f"Duplicate image content: {source_path} and {seen_hashes[digest]}"
                )
            seen_hashes[digest] = str(source_path)
            group_key, group_values = _group(image, source)
            split = _split(group_key, manifest.split_seed, manifest.split_ratios)
            extension = source_path.suffix.casefold()
            target_name = f"{digest}{extension}"
            target = output / "images" / split / target_name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)
            output_image = {
                "id": next_image_id,
                "file_name": f"images/{split}/{target_name}",
                "width": width,
                "height": height,
                **group_values,
            }
            images_by_split[split].append(output_image)
            for annotation in image_annotations[int(image["id"])]:
                mapped = mapped_categories.get(int(annotation["category_id"]))
                if mapped is None:
                    continue
                bbox = annotation.get("bbox")
                if (
                    not isinstance(bbox, list)
                    or len(bbox) != 4
                    or any(not isinstance(value, (int, float)) for value in bbox)
                ):
                    raise ValueError(f"Invalid bbox for annotation {annotation.get('id')}")
                x, y, box_width, box_height = map(float, bbox)
                if (
                    box_width <= 0
                    or box_height <= 0
                    or x < 0
                    or y < 0
                    or x + box_width > width
                    or y + box_height > height
                ):
                    raise ValueError(
                        f"Empty or out-of-bounds bbox: {annotation.get('id')}"
                    )
                annotations_by_split[split].append(
                    {
                        "id": next_annotation_id,
                        "image_id": next_image_id,
                        "category_id": CANONICAL_CLASSES.index(mapped) + 1,
                        "bbox": [x, y, box_width, box_height],
                        "area": box_width * box_height,
                        "iscrowd": int(annotation.get("iscrowd", 0)),
                    }
                )
                next_annotation_id += 1
            records.append(
                {
                    "source": source.name,
                    "source_path": str(source_path),
                    "prepared_path": str(target),
                    "sha256": digest,
                    "split": split,
                    "group_key": group_key,
                    **group_values,
                }
            )
            next_image_id += 1

    categories = [
        {"id": index, "name": name}
        for index, name in enumerate(CANONICAL_CLASSES, start=1)
    ]
    for split in ("train", "val", "test"):
        annotation_path = output / "annotations" / f"{split}.json"
        annotation_path.parent.mkdir(parents=True, exist_ok=True)
        annotation_path.write_text(
            json.dumps(
                {
                    "images": images_by_split[split],
                    "annotations": annotations_by_split[split],
                    "categories": categories,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    dataset_manifest = {
        "canonical_classes": list(CANONICAL_CLASSES),
        "images": records,
        "image_count": len(records),
        "annotation_count": next_annotation_id - 1,
    }
    (output / "dataset_manifest.json").write_text(
        json.dumps(dataset_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "license_manifest.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "name": source.name,
                        "license": source.license,
                        "license_url": source.license_url,
                    }
                    for source in manifest.sources
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return dataset_manifest


def leakage_issues(dataset_manifest: Path) -> list[str]:
    payload = json.loads(dataset_manifest.read_text(encoding="utf-8"))
    groups: dict[str, set[str]] = defaultdict(set)
    hashes: dict[str, set[str]] = defaultdict(set)
    for image in payload.get("images", []):
        groups[str(image["group_key"])].add(str(image["split"]))
        hashes[str(image["sha256"])].add(str(image["split"]))
    issues = [
        f"group leakage: {key} -> {sorted(splits)}"
        for key, splits in groups.items()
        if len(splits) > 1
    ]
    issues.extend(
        f"image hash leakage: {key} -> {sorted(splits)}"
        for key, splits in hashes.items()
        if len(splits) > 1
    )
    return sorted(issues)
