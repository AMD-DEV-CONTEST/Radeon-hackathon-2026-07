import hashlib
import json
from pathlib import Path

import pytest

from buildguard.evaluation.vision_dataset import audit_coco_dataset
from buildguard.vision.model_artifact import finalize_vision_model


def _write_split(root: Path, split: str, *, name: str, image_id: int) -> None:
    image_dir = root / "images" / split
    annotation_dir = root / "annotations"
    image_dir.mkdir(parents=True, exist_ok=True)
    annotation_dir.mkdir(parents=True, exist_ok=True)
    (image_dir / name).write_bytes(f"image-{split}".encode())
    (annotation_dir / f"instances_{split}.json").write_text(
        json.dumps(
            {
                "images": [
                    {"id": image_id, "file_name": name, "width": 100, "height": 80}
                ],
                "annotations": [
                    {
                        "id": image_id,
                        "image_id": image_id,
                        "category_id": 7,
                        "bbox": [10, 10, 20, 20],
                    }
                ],
                "categories": [{"id": 7, "name": "crack"}],
            }
        ),
        encoding="utf-8",
    )


def test_coco_audit_passes_valid_splits_and_rejects_leakage(tmp_path: Path) -> None:
    for index, split in enumerate(("train", "validation", "test"), 1):
        _write_split(tmp_path, split, name=f"image-{split}.jpg", image_id=index)

    report = audit_coco_dataset(tmp_path, content_hash=False)
    assert report.status == "PASS"
    assert report.categories == {7: "crack"}
    assert [split.annotation_count for split in report.splits] == [1, 1, 1]

    leaked = tmp_path / "images" / "test" / "image-train.jpg"
    leaked.write_bytes(b"duplicate-name")
    report = audit_coco_dataset(tmp_path, content_hash=False)
    assert report.status == "FAIL"
    assert "train:test:filename" in report.leakage


def test_finalize_vision_model_preserves_source_and_refuses_overwrite(
    tmp_path: Path,
) -> None:
    source = tmp_path / "best-model"
    target = tmp_path / "deployment" / "crack-model"
    source.mkdir()
    weight = b"immutable-trained-weights"
    (source / "model.safetensors").write_bytes(weight)
    (source / "config.json").write_text(
        json.dumps({"id2label": {"0": "crack"}}), encoding="utf-8"
    )
    (source / "preprocessor_config.json").write_text("{}", encoding="utf-8")

    manifest = finalize_vision_model(
        source,
        target,
        model_id="rtdetr-v2-concrete-crack",
        revision="training-run-20260731",
        source_uri="authorized://construction-crack-v1",
        license_name="dataset-and-model-license-recorded",
        validated_on_amd=True,
    )

    expected = hashlib.sha256(weight).hexdigest()
    assert (source / "model.safetensors").read_bytes() == weight
    assert (target / "model.safetensors").read_bytes() == weight
    assert manifest["model_sha256"] == expected
    saved = json.loads((target / "model-manifest.json").read_text(encoding="utf-8"))
    assert saved["classes"] == {"0": "crack"}
    with pytest.raises(FileExistsError):
        finalize_vision_model(
            source,
            target,
            model_id="rtdetr-v2-concrete-crack",
            revision="training-run-20260731",
            source_uri="authorized://construction-crack-v1",
            license_name="dataset-and-model-license-recorded",
            validated_on_amd=True,
        )
