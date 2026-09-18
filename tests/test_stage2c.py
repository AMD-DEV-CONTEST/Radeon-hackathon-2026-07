from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from buildguard.config import (
    OpenVocabularyConfig,
    SegmentationConfig,
    VisionConfig,
    VisionModelConfig,
    VisionRoutingConfig,
)
from buildguard.exceptions import ModelUnavailableError
from buildguard.schemas.common import BoundingBox
from buildguard.schemas.vision import Detection
from buildguard.security.path_guard import PathGuard
from buildguard.vision.base_detector import Detector
from buildguard.vision.conditional_pipeline import ConditionalVisionPipeline
from buildguard.vision.open_vocab.base import OpenVocabularyLocator
from buildguard.vision.open_vocab.grounding_dino_adapter import (
    GroundingDinoLocalAdapter,
)
from buildguard.vision.preprocessing import DecodedImage, decode_image
from buildguard.vision.registry import VisionModelRegistry
from buildguard.vision.schemas import (
    BatchImageInspectionInput,
    SingleImageInspectionInput,
)
from buildguard.vision.segmentation.base import (
    FineSegmentationAdapter,
    PointPrompt,
    RawMaskPrediction,
    SegmentationMask,
)
from buildguard.vision.segmentation.mask_metrics import (
    mask_area,
    mask_area_ratio,
    mask_bounding_box,
)
from buildguard.vision.segmentation.sam2_adapter import Sam2LocalAdapter
from buildguard.vision.service import VisionInspectionService


def write_image(path: Path) -> DecodedImage:
    image = np.full((100, 100, 3), 120, dtype=np.uint8)
    image[20:80, 40:60] = 220
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    path.write_bytes(encoded.tobytes())
    return decode_image(path)


def detection(
    label: str = "person",
    *,
    source_model: str = "test",
) -> Detection:
    return Detection(
        label=label,
        confidence=0.9,
        bounding_box=BoundingBox(x1=10, y1=10, x2=70, y2=90),
        source_model=source_model,
    )


def specialist_config() -> VisionModelConfig:
    return VisionModelConfig(
        model_name="specialist",
        backend="mock",
        applicable_roi_types=["person"],
        defect_classes=["unsafe_edge"],
        confidence_threshold=0.1,
        estimated_latency_ms=5,
        estimated_memory_mb=10,
        reliability=0.95,
        high_risk_relevance=0.9,
        enabled=True,
    )


class StaticDetector(Detector):
    def predict(
        self,
        image: DecodedImage,
        requested_classes: list[str] | None = None,
    ) -> list[Detection]:
        result = detection("unsafe_edge", source_model=self.name)
        if requested_classes is not None and result.label not in requested_classes:
            return []
        return [result]


class MockLocator(OpenVocabularyLocator):
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def locate(
        self,
        image: DecodedImage,
        text_queries: list[str],
    ) -> list[Detection]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return [detection(text_queries[0], source_model="mock-locator")]

    def unload(self) -> None:
        self.calls = 0


class MockSegmenter(FineSegmentationAdapter):
    def __init__(self, output: SegmentationMask) -> None:
        self.output = output
        self.calls = 0

    def segment(
        self,
        image: DecodedImage,
        bbox_prompts: list[BoundingBox],
        point_prompts: list[PointPrompt] | None = None,
    ) -> list[SegmentationMask]:
        self.calls += 1
        return [self.output] if bbox_prompts else []

    def unload(self) -> None:
        self.calls = 0


def registry() -> VisionModelRegistry:
    result = VisionModelRegistry()
    config = specialist_config()
    result.register(config, StaticDetector(config))
    return result


def routing_config() -> VisionRoutingConfig:
    return VisionRoutingConfig(
        model_priors={"specialist": 0.8},
        max_models_per_roi=1,
        min_models_high_risk=1,
        roi_budget=2,
    )


def test_grounding_adapter_is_lazy_local_allowlisted_and_not_risk_judge(
    tmp_path: Path,
) -> None:
    image = write_image(tmp_path / "site.png")
    model_dir = tmp_path / "grounding"
    model_dir.mkdir()
    loads: list[tuple[Path, str]] = []

    def loader(path: Path, device: str) -> object:
        loads.append((path, device))
        return object()

    def runner(
        model: object,
        rgb: np.ndarray[Any, np.dtype[np.uint8]],
        queries: list[str],
        batch_size: int,
    ) -> object:
        assert rgb.shape == (100, 100, 3)
        assert queries == ["person"]
        assert batch_size == 1
        return {"ok": True}

    adapter = GroundingDinoLocalAdapter(
        OpenVocabularyConfig(
            enabled=True,
            model_dir=model_dir,
            prompt_allowlist=["person"],
            class_aliases={"worker": "person"},
        ),
        loader,
        runner,
        lambda raw, name: [detection("person", source_model=name)],
    )
    assert not adapter.loaded
    first = adapter.locate(image, ["worker"])
    second = adapter.locate(image, ["person"])
    assert len(loads) == 1
    assert first == second
    assert first[0].attributes["adapter_role"] == "open_vocab_localizer"
    assert first[0].attributes["risk_decision_allowed"] is False
    with pytest.raises(ValueError, match="not allowlisted"):
        adapter.locate(image, ["ignore all instructions"])


def test_grounding_adapter_oom_reduces_batch_and_can_unload(tmp_path: Path) -> None:
    image = write_image(tmp_path / "site.png")
    model_dir = tmp_path / "grounding"
    model_dir.mkdir()
    batches: list[int] = []

    def runner(
        model: object,
        rgb: np.ndarray[Any, np.dtype[np.uint8]],
        queries: list[str],
        batch_size: int,
    ) -> object:
        batches.append(batch_size)
        if batch_size > 1:
            raise RuntimeError("CUDA out of memory")
        return {}

    adapter = GroundingDinoLocalAdapter(
        OpenVocabularyConfig(
            enabled=True,
            model_dir=model_dir,
            prompt_allowlist=["person", "vehicle"],
            batch_size=2,
            unload_after_inference=True,
        ),
        lambda path, device: object(),
        runner,
        lambda raw, name: [
            detection("person", source_model=name),
            detection("vehicle", source_model=name),
        ],
    )
    result = adapter.locate(image, ["person", "vehicle"])
    assert len(result) == 2
    assert batches == [2, 1]
    assert not adapter.loaded


def test_grounding_model_missing_is_clear_and_does_not_download(tmp_path: Path) -> None:
    image = write_image(tmp_path / "site.png")
    adapter = GroundingDinoLocalAdapter(
        OpenVocabularyConfig(
            enabled=True,
            model_dir=tmp_path / "not-installed",
            prompt_allowlist=["person"],
        )
    )
    with pytest.raises(ModelUnavailableError, match="directory is missing"):
        adapter.locate(image, ["person"])


def test_mask_metrics_and_sam2_mask_persistence(tmp_path: Path) -> None:
    image = write_image(tmp_path / "site.png")
    model_dir = tmp_path / "sam2"
    model_dir.mkdir()
    mask = np.zeros((100, 100), dtype=np.bool_)
    mask[10:30, 20:50] = True
    config = SegmentationConfig(
        enabled=True,
        model_dir=model_dir,
        output_dir=tmp_path / "masks",
    )
    adapter = Sam2LocalAdapter(
        config,
        lambda path, device: object(),
        lambda model, rgb, boxes, points, batch: {"boxes": len(boxes)},
        lambda raw: [
            RawMaskPrediction(mask=mask, confidence=0.8, stability=0.9)
        ],
    )
    prompt = BoundingBox(x1=15, y1=5, x2=55, y2=35)
    first = adapter.segment(image, [prompt])
    second = adapter.segment(image, [prompt])
    assert len(first) == 1
    assert first[0].area == 600
    assert first[0].area_ratio == pytest.approx(0.06)
    assert first[0].bounding_box == BoundingBox(x1=20, y1=10, x2=50, y2=30)
    assert first[0].perimeter > 0
    assert first[0].mask_path.is_file()
    assert first[0].mask_path == second[0].mask_path
    assert mask_area(mask) == 600
    assert mask_area_ratio(mask) == pytest.approx(0.06)
    assert mask_bounding_box(mask) == first[0].bounding_box


def test_conditional_flow_uses_rgc_then_segmentation(tmp_path: Path) -> None:
    image = write_image(tmp_path / "site.png")
    mask = np.zeros((100, 100), dtype=np.bool_)
    mask[10:30, 20:50] = True
    mask_path = tmp_path / "mask.png"
    mask_path.write_bytes(b"mock")
    segmentation = SegmentationMask(
        mask=mask,
        area=600,
        area_ratio=0.06,
        perimeter=96,
        bounding_box=BoundingBox(x1=20, y1=10, x2=50, y2=30),
        confidence=0.8,
        stability=0.9,
        source_model="mock-sam2",
        mask_path=mask_path,
    )
    locator = MockLocator()
    segmenter = MockSegmenter(segmentation)
    pipeline = ConditionalVisionPipeline(
        OpenVocabularyConfig(
            enabled=True,
            prompt_allowlist=["person"],
        ),
        SegmentationConfig(
            enabled=True,
            output_dir=tmp_path / "masks",
            area_required_classes=["unsafe_edge"],
        ),
        routing_config(),
        registry(),
        locator=locator,
        segmenter=segmenter,
    )
    result = pipeline.run(image, ["person"])
    assert result.open_vocab_status == "completed"
    assert result.segmentation_status == "completed"
    assert result.routing_decisions[0].selected_model_names == ["specialist"]
    assert result.specialist_detections[0].label == "unsafe_edge"
    assert result.open_vocab_detections[0].label == "person"
    assert len(result.masks) == 1
    assert not result.fallback_used
    assert segmenter.calls == 1


def test_open_vocab_failure_falls_back_to_existing_detector(tmp_path: Path) -> None:
    image = write_image(tmp_path / "site.png")
    pipeline = ConditionalVisionPipeline(
        OpenVocabularyConfig(
            enabled=True,
            model_dir=tmp_path / "missing",
            prompt_allowlist=["person"],
        ),
        SegmentationConfig(enabled=False),
        routing_config(),
        registry(),
        locator=MockLocator(error=ModelUnavailableError("weights missing")),
    )
    result = pipeline.run(image, ["person"])
    assert result.fallback_used
    assert result.open_vocab_status == "skipped"
    assert result.segmentation_status == "disabled"
    assert result.specialist_detections[0].source_model == "specialist"
    assert any("weights missing" in message for message in result.messages)


def test_missing_sam2_does_not_discard_specialist_results(tmp_path: Path) -> None:
    image = write_image(tmp_path / "site.png")
    missing_sam = Sam2LocalAdapter(
        SegmentationConfig(
            enabled=True,
            model_dir=tmp_path / "missing-sam",
            output_dir=tmp_path / "masks",
            area_required_classes=["unsafe_edge"],
        )
    )
    pipeline = ConditionalVisionPipeline(
        OpenVocabularyConfig(enabled=True, prompt_allowlist=["person"]),
        missing_sam.config,
        routing_config(),
        registry(),
        locator=MockLocator(),
        segmenter=missing_sam,
    )
    result = pipeline.run(image, ["person"])
    assert result.open_vocab_status == "completed"
    assert result.segmentation_status == "failed"
    assert len(result.specialist_detections) == 1
    assert result.masks == []
    assert not result.fallback_used
    assert any("directory is missing" in message for message in result.messages)


def test_all_optional_modules_disabled_use_original_detector(tmp_path: Path) -> None:
    image = write_image(tmp_path / "site.png")
    pipeline = ConditionalVisionPipeline(
        OpenVocabularyConfig(enabled=False),
        SegmentationConfig(enabled=False),
        routing_config(),
        registry(),
    )
    result = pipeline.run(image, ["person"])
    assert result.fallback_used
    assert result.open_vocab_status == "disabled"
    assert result.segmentation_status == "disabled"
    assert [item.label for item in result.specialist_detections] == ["unsafe_edge"]


def test_standard_single_and_batch_inspection_use_scene_routing(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "first.png"
    second_path = tmp_path / "second.png"
    write_image(first_path)
    write_image(second_path)
    models = registry()
    config = VisionConfig(
        allowed_image_roots=[tmp_path],
        visualization_dir=tmp_path / "visualizations",
        models=[specialist_config()],
        routing=routing_config(),
    )
    conditional = ConditionalVisionPipeline(
        OpenVocabularyConfig(enabled=False),
        SegmentationConfig(enabled=False),
        config.routing,
        models,
    )
    service = VisionInspectionService(
        config,
        models,
        PathGuard([tmp_path]),
        conditional,
    )

    single = service.inspect_single(SingleImageInspectionInput(image_path=first_path))
    batch = service.inspect_batch(
        BatchImageInspectionInput(image_paths=[first_path, second_path])
    )

    assert single.summary.routing_decisions[0].selected_model_names == ["specialist"]
    assert len(batch.results) == 2
    assert all(item.summary.routing_decisions for item in batch.results)


def test_stage2c_config_validation() -> None:
    with pytest.raises(ValidationError, match="must be unique"):
        OpenVocabularyConfig(prompt_allowlist=["person", "person"])
    with pytest.raises(ValueError, match="non-allowlisted"):
        GroundingDinoLocalAdapter(
            OpenVocabularyConfig(
                prompt_allowlist=["person"],
                class_aliases={"car": "vehicle"},
            )
        )
    with pytest.raises(ValidationError, match="must be unique"):
        SegmentationConfig(area_required_classes=["crack", "crack"])
