import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray

from buildguard.config import PermissionConfig, VisionConfig, VisionModelConfig
from buildguard.exceptions import ModelUnavailableError
from buildguard.vision.preprocessing import DecodedImage, decode_image
from buildguard.vision.registry import VisionModelRegistry
from buildguard.vision.rtdetr_v2 import (
    RawRTDETRDetection,
    RTDETRConfig,
    RTDETRRunner,
    RTDETRv2Adapter,
)


def _files(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    config_path = tmp_path / "model.json"
    config_path.write_text("{}", encoding="utf-8")
    weights = tmp_path / "model.bin"
    weights.write_bytes(b"fixture weights")
    digest = hashlib.sha256(weights.read_bytes()).hexdigest()
    manifest = tmp_path / "model-manifest.json"
    manifest.write_text(
        json.dumps({"revision": "fixture-v1", "model_sha256": digest}),
        encoding="utf-8",
    )
    return config_path, weights, manifest, digest


def _image(tmp_path: Path, name: str) -> DecodedImage:
    path = tmp_path / name
    cv2.imwrite(str(path), np.zeros((50, 100, 3), dtype=np.uint8))
    return decode_image(path)


def _adapter(
    tmp_path: Path,
    runner: RTDETRRunner,
) -> RTDETRv2Adapter:
    config_path, weights, manifest, digest = _files(tmp_path)
    detector = VisionModelConfig(
        model_name="rtdetr-v2-ppe",
        backend="local",
        model_path=weights,
        applicable_roi_types=["*"],
        defect_classes=["person", "head", "helmet", "safety_vest"],
        input_size=(100, 100),
        confidence_threshold=0.5,
        nms_iou=0.5,
        device="cpu",
    )
    runtime = RTDETRConfig(
        config_path=config_path,
        weights_path=weights,
        manifest_path=manifest,
        device="cpu",
        batch_size=4,
        revision="fixture-v1",
        model_sha256=digest,
        class_mapping={0: "person", 1: "helmet"},
    )
    return RTDETRv2Adapter(detector, runtime, runner=runner)


def test_rtdetr_maps_classes_coordinates_and_filters(tmp_path: Path) -> None:
    def runner(
        _: list[NDArray[np.uint8]],
    ) -> list[list[RawRTDETRDetection]]:
        return [
            [
                RawRTDETRDetection(
                    class_id=0, confidence=0.9, box=(10, 30, 50, 50)
                ),
                RawRTDETRDetection(
                    class_id=1, confidence=0.2, box=(0, 25, 20, 40)
                ),
            ]
        ]

    result = _adapter(tmp_path, runner).predict(_image(tmp_path, "one.png"))

    assert len(result) == 1
    assert result[0].label == "person"
    assert result[0].bounding_box.model_dump() == {
        "x1": 10.0,
        "y1": 5.0,
        "x2": 50.0,
        "y2": 25.0,
    }


def test_rtdetr_reduces_batch_after_oom(tmp_path: Path) -> None:
    calls: list[int] = []

    def runner(
        images: list[NDArray[np.uint8]],
    ) -> list[list[RawRTDETRDetection]]:
        calls.append(len(images))
        if len(images) > 1:
            raise RuntimeError("out of memory")
        return [[] for _ in images]

    adapter = _adapter(tmp_path, runner)
    results = adapter.predict_batch(
        [_image(tmp_path, "a.png"), _image(tmp_path, "b.png")]
    )

    assert results == [[], []]
    assert calls == [2, 1, 1]
    assert len(adapter.performance_records) == 2


def test_rtdetr_does_not_silently_return_empty_on_inference_error(
    tmp_path: Path,
) -> None:
    calls = 0

    def runner(
        images: list[NDArray[np.uint8]],
    ) -> list[list[RawRTDETRDetection]]:
        nonlocal calls
        calls += 1
        if calls in {1, 2}:
            raise RuntimeError("fixture decode failure")
        return [[] for _ in images]

    adapter = _adapter(tmp_path, runner)
    with pytest.raises(RuntimeError, match="image index 0"):
        adapter.predict_batch(
            [_image(tmp_path, "bad.png"), _image(tmp_path, "good.png")]
        )


def test_rtdetr_rejects_manifest_or_weight_mismatch(tmp_path: Path) -> None:
    config_path, weights, manifest, digest = _files(tmp_path)
    detector = VisionModelConfig(
        model_name="rtdetr-v2-ppe",
        backend="local",
        model_path=weights,
        defect_classes=["person"],
    )
    runtime = RTDETRConfig(
        config_path=config_path,
        weights_path=weights,
        manifest_path=manifest,
        revision="wrong",
        model_sha256=digest,
        class_mapping={0: "person"},
    )

    with pytest.raises(ModelUnavailableError, match="revision mismatch"):
        RTDETRv2Adapter(detector, runtime, runner=lambda _: [])


def test_registry_constructs_configured_rtdetr_adapter(tmp_path: Path) -> None:
    config_path, weights, manifest, digest = _files(tmp_path)
    model = VisionModelConfig(
        model_name="rtdetr-v2-ppe",
        backend="local",
        local_adapter="rtdetr_v2",
        model_path=weights,
        model_config_path=config_path,
        model_manifest_path=manifest,
        model_revision="fixture-v1",
        model_sha256=digest,
        class_mapping={0: "person"},
        defect_classes=["person"],
    )

    registry = VisionModelRegistry.from_config(
        VisionConfig(models=[model]),
        PermissionConfig(),
        seed=42,
        rtdetr_runners={"rtdetr-v2-ppe": lambda images: [[] for _ in images]},
    )

    assert isinstance(registry.get("rtdetr-v2-ppe"), RTDETRv2Adapter)


def test_rtdetr_accepts_declared_non_ppe_classes(tmp_path: Path) -> None:
    config_path, weights, manifest, digest = _files(tmp_path)
    detector = VisionModelConfig(
        model_name="rtdetr-v2-construction",
        backend="local",
        model_path=weights,
        defect_classes=["crane", "excavator"],
    )
    runtime = RTDETRConfig(
        config_path=config_path,
        weights_path=weights,
        manifest_path=manifest,
        revision="fixture-v1",
        model_sha256=digest,
        class_mapping={0: "crane", 1: "excavator"},
    )

    adapter = RTDETRv2Adapter(detector, runtime, runner=lambda _: [[]])

    assert adapter.runtime.class_mapping == {0: "crane", 1: "excavator"}


def test_rtdetr_rejects_mapping_not_declared_by_model(tmp_path: Path) -> None:
    config_path, weights, manifest, digest = _files(tmp_path)
    detector = VisionModelConfig(
        model_name="rtdetr-v2-construction",
        backend="local",
        model_path=weights,
        defect_classes=["crane"],
    )
    runtime = RTDETRConfig(
        config_path=config_path,
        weights_path=weights,
        manifest_path=manifest,
        revision="fixture-v1",
        model_sha256=digest,
        class_mapping={0: "excavator"},
    )

    with pytest.raises(ModelUnavailableError, match="absent from defect_classes"):
        RTDETRv2Adapter(detector, runtime, runner=lambda _: [[]])
