import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from buildguard.vision.ppe_dataset import (
    CANONICAL_CLASSES,
    leakage_issues,
    prepare_dataset,
)


def _source(tmp_path: Path, *, invalid_box: bool = False) -> Path:
    images = tmp_path / "source" / "images"
    images.mkdir(parents=True)
    for name, color in (("a.png", "red"), ("b.png", "blue")):
        Image.new("RGB", (20, 10), color=color).save(images / name)
    coco = {
        "images": [
            {
                "id": 1,
                "file_name": "a.png",
                "width": 20,
                "height": 10,
                "site_id": "site-a",
                "camera_id": "camera-a",
                "capture_date": "2026-07-01",
                "video_clip_id": "clip-a",
            },
            {
                "id": 2,
                "file_name": "b.png",
                "width": 20,
                "height": 10,
                "site_id": "site-b",
                "camera_id": "camera-b",
                "capture_date": "2026-07-02",
                "video_clip_id": "clip-b",
            },
        ],
        "annotations": [
            {
                "id": 1,
                "image_id": 1,
                "category_id": 9,
                "bbox": [0, 0, 30 if invalid_box else 5, 5],
            },
            {
                "id": 2,
                "image_id": 2,
                "category_id": 10,
                "bbox": [2, 1, 5, 6],
            },
        ],
        "categories": [
            {"id": 9, "name": "worker"},
            {"id": 10, "name": "hardhat"},
        ],
    }
    annotations = tmp_path / "source" / "annotations.json"
    annotations.write_text(json.dumps(coco), encoding="utf-8")
    source_manifest = {
        "sources": [
            {
                "name": "licensed-fixture",
                "annotations": str(annotations),
                "image_root": str(images),
                "license": "CC-BY-4.0",
                "license_url": "https://example.invalid/license",
                "category_mapping": {
                    "worker": "person",
                    "hardhat": "helmet",
                },
            }
        ]
    }
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(source_manifest), encoding="utf-8")
    return path


def test_prepare_ppe_dataset_maps_classes_and_writes_manifests(
    tmp_path: Path,
) -> None:
    output = tmp_path / "prepared"
    result = prepare_dataset(_source(tmp_path), output)

    assert result["image_count"] == 2
    assert result["annotation_count"] == 2
    assert result["canonical_classes"] == list(CANONICAL_CLASSES)
    assert (output / "dataset_manifest.json").is_file()
    assert (output / "license_manifest.json").is_file()
    assert leakage_issues(output / "dataset_manifest.json") == []
    for split in ("train", "val", "test"):
        payload = json.loads(
            (output / "annotations" / f"{split}.json").read_text(encoding="utf-8")
        )
        assert [item["name"] for item in payload["categories"]] == list(
            CANONICAL_CLASSES
        )


def test_prepare_rejects_out_of_bounds_annotation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="out-of-bounds"):
        prepare_dataset(_source(tmp_path, invalid_box=True), tmp_path / "prepared")


def test_leakage_checker_returns_nonzero(tmp_path: Path) -> None:
    manifest = tmp_path / "dataset_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "images": [
                    {"group_key": "same", "sha256": "a" * 64, "split": "train"},
                    {"group_key": "same", "sha256": "b" * 64, "split": "test"},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert leakage_issues(manifest)
    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_ppe_split_leakage.py",
            "--manifest",
            str(manifest),
        ],
        check=False,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert result.returncode == 2
