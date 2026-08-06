import hashlib
from pathlib import Path

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray

from buildguard.config import PermissionConfig, VisionConfig, VisionModelConfig
from buildguard.exceptions import ModelUnavailableError
from buildguard.vision.preprocessing import DecodedImage, decode_image
from buildguard.vision.registry import VisionModelRegistry
from buildguard.vision.yolo11 import YOLO11Adapter, YOLO11Runner


def _pt_file(tmp_path: Path) -> tuple[Path, str]:
    pt = tmp_path / "yolo11m_safety.pt"
    pt.write_bytes(b"fake pt weights")
    digest = hashlib.sha256(pt.read_bytes()).hexdigest()
    return pt, digest


def _image(
    tmp_path: Path,
    name: str = "img.png",
    height: int = 200,
    width: int = 200,
) -> DecodedImage:
    path = tmp_path / name
    cv2.imwrite(str(path), np.zeros((height, width, 3), dtype=np.uint8))
    return decode_image(path)


def _adapter(tmp_path: Path, runner: YOLO11Runner) -> YOLO11Adapter:
    pt, digest = _pt_file(tmp_path)
    cfg = VisionModelConfig(
        model_name="yolo11-ppe",
        backend="local",
        local_adapter="yolo11",
        model_path=pt,
        model_sha256=digest,
        yolo_class_mapping={
            "nohat": "missing_helmet",
            "novest": "missing_vest",
            "person": "person",
        },
        defect_classes=["missing_helmet", "missing_vest", "person"],
        input_size=(200, 200),
        confidence_threshold=0.5,
        nms_iou=0.5,
        device="cpu",
    )
    return YOLO11Adapter(cfg, runner=runner)


def test_yolo11_maps_violation_classes_and_drops_compliant(tmp_path: Path) -> None:
    # Runner returns one detection per YOLO class
    def runner(images: list[NDArray[np.uint8]]) -> list[list[tuple[str, float, tuple[float, float, float, float]]]]:
        return [
            [
                ("nohat",  0.9, (10.0, 10.0, 50.0, 50.0)),
                ("novest", 0.8, (20.0, 20.0, 60.0, 60.0)),
                ("person", 0.7, (0.0,  0.0,  100.0, 100.0)),
                ("hat",    0.95, (5.0,  5.0,  40.0, 40.0)),   # compliant — must be dropped
                ("vest",   0.95, (5.0,  5.0,  40.0, 40.0)),   # compliant — must be dropped
            ]
        ]

    result = _adapter(tmp_path, runner).predict(_image(tmp_path))

    labels = {d.label for d in result}
    assert "missing_helmet" in labels
    assert "missing_vest" in labels
    assert "person" in labels
    assert "hat" not in labels
    assert "vest" not in labels


def test_yolo11_filters_below_confidence_threshold(tmp_path: Path) -> None:
    def runner(images: list[NDArray[np.uint8]]) -> list[list[tuple[str, float, tuple[float, float, float, float]]]]:
        return [
            [
                ("nohat", 0.9, (10.0, 10.0, 50.0, 50.0)),   # above threshold 0.5
                ("nohat", 0.3, (60.0, 60.0, 90.0, 90.0)),   # below threshold — must be dropped
            ]
        ]

    result = _adapter(tmp_path, runner).predict(_image(tmp_path))
    assert len(result) == 1
    assert result[0].label == "missing_helmet"


def test_yolo11_boxes_are_in_original_image_coords(tmp_path: Path) -> None:
    # Image is 200×100, input_size is (200,200) → letterbox adds top/bottom padding
    # scale = min(200/200, 200/100) = 1.0, pad_y = (200-100)/2 = 50
    # A box at letterbox coords (10, 60, 50, 110) → original (10, 10, 50, 60)
    def runner(images: list[NDArray[np.uint8]]) -> list[list[tuple[str, float, tuple[float, float, float, float]]]]:
        return [[("nohat", 0.9, (10.0, 60.0, 50.0, 110.0))]]

    result = _adapter(tmp_path, runner).predict(_image(tmp_path, height=100, width=200))
    assert len(result) == 1
    bb = result[0].bounding_box
    assert abs(bb.x1 - 10.0) < 1.0
    assert abs(bb.y1 - 10.0) < 1.0
    assert abs(bb.x2 - 50.0) < 1.0
    assert abs(bb.y2 - 60.0) < 1.0


def test_yolo11_raises_on_missing_model_path(tmp_path: Path) -> None:
    cfg = VisionModelConfig(
        model_name="yolo11-ppe",
        backend="local",
        local_adapter="yolo11",
        model_path=tmp_path / "nonexistent.pt",
        model_sha256="a" * 64,
        yolo_class_mapping={"nohat": "missing_helmet"},
        defect_classes=["missing_helmet"],
    )
    with pytest.raises(ModelUnavailableError, match="missing"):
        YOLO11Adapter(cfg, runner=lambda _: [])


def test_yolo11_raises_on_sha256_mismatch(tmp_path: Path) -> None:
    pt, _ = _pt_file(tmp_path)
    cfg = VisionModelConfig(
        model_name="yolo11-ppe",
        backend="local",
        local_adapter="yolo11",
        model_path=pt,
        model_sha256="b" * 64,   # wrong digest
        yolo_class_mapping={"nohat": "missing_helmet"},
        defect_classes=["missing_helmet"],
    )
    with pytest.raises(ModelUnavailableError, match="SHA-256"):
        YOLO11Adapter(cfg, runner=lambda _: [])


def test_yolo11_batch_returns_aligned_results(tmp_path: Path) -> None:
    call_count = 0

    def runner(images: list[NDArray[np.uint8]]) -> list[list[tuple[str, float, tuple[float, float, float, float]]]]:
        nonlocal call_count
        call_count += 1
        return [
            [("nohat", 0.9, (10.0, 10.0, 50.0, 50.0))],
            [],
        ]

    adapter = _adapter(tmp_path, runner)
    results = adapter.predict_batch(
        [_image(tmp_path, "a.png"), _image(tmp_path, "b.png")]
    )
    assert len(results) == 2
    assert len(results[0]) == 1
    assert results[1] == []


def test_registry_constructs_yolo11_adapter(tmp_path: Path) -> None:
    pt, digest = _pt_file(tmp_path)
    model = VisionModelConfig(
        model_name="yolo11-ppe",
        backend="local",
        local_adapter="yolo11",
        model_path=pt,
        model_sha256=digest,
        yolo_class_mapping={"nohat": "missing_helmet"},
        defect_classes=["missing_helmet"],
    )
    registry = VisionModelRegistry.from_config(
        VisionConfig(models=[model]),
        PermissionConfig(),
        seed=42,
        yolo11_runners={"yolo11-ppe": lambda _: [[]]},
    )
    assert isinstance(registry.get("yolo11-ppe"), YOLO11Adapter)
