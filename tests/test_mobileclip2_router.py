from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from buildguard.config import (
    MobileClip2SemanticRouterConfig,
    OpenVocabularyConfig,
    SegmentationConfig,
    SemanticPromptSetConfig,
    VisionModelConfig,
    VisionRoutingConfig,
)
from buildguard.exceptions import ModelUnavailableError
from buildguard.vision.base_detector import Detector
from buildguard.vision.conditional_pipeline import ConditionalVisionPipeline
from buildguard.vision.preprocessing import DecodedImage
from buildguard.vision.registry import VisionModelRegistry
from buildguard.vision.routing.router import VisualRouter
from buildguard.vision.routing.schemas import RoiFeatures, RoutingModel
from buildguard.vision.semantic.mobileclip2_adapter import MobileClip2S0Adapter


def _checkpoint(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "mobileclip2_s0.pt"
    path.write_bytes(b"mobileclip2-test-checkpoint")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _semantic_config(
    tmp_path: Path,
    *,
    cache_max_items: int = 8,
) -> MobileClip2SemanticRouterConfig:
    path, checksum = _checkpoint(tmp_path)
    return MobileClip2SemanticRouterConfig(
        enabled=True,
        required=True,
        model_path=path,
        model_revision="test-revision",
        model_sha256=checksum,
        semantic_weight=1.0,
        cache_max_items=cache_max_items,
        experts={
            "ppe": SemanticPromptSetConfig(
                positive=["construction worker"],
                negative=["empty construction site"],
                temperature=0.1,
            ),
            "crack": SemanticPromptSetConfig(
                positive=["cracked concrete wall"],
                negative=["smooth concrete wall"],
                temperature=0.1,
            ),
        },
    )


def _model(name: str) -> VisionModelConfig:
    return VisionModelConfig(
        model_name=name,
        backend="mock",
        applicable_roi_types=["*"],
        defect_classes=[f"{name}_defect"],
        estimated_latency_ms=10,
        estimated_memory_mb=32,
        reliability=0.9,
        fixed_call_cost=0.1,
        high_risk_relevance=0.5,
    )


def _features(**updates: Any) -> RoiFeatures:
    raw: dict[str, Any] = {
        "roi_label": "*",
        "roi_confidence": 1.0,
        "area_ratio": 1.0,
        "aspect_ratio": 1.0,
        "center": (0.5, 0.5),
        "brightness": 0.5,
        "contrast": 0.5,
        "blur": 0.1,
        "edge_density": 0.5,
        "texture_score": 0.5,
        "motion_score": 0.0,
        "track_age": 0,
        "previous_probability": 0.0,
        "previous_detection_confidence": 0.0,
        "device_load": 0.0,
        "high_risk": False,
    }
    raw.update(updates)
    return RoiFeatures.model_validate(raw)


def _image(tmp_path: Path) -> DecodedImage:
    bgr = np.full((48, 64, 3), 127, dtype=np.uint8)
    return DecodedImage(
        path=tmp_path / "image.png",
        checksum=hashlib.sha256(bgr.tobytes()).hexdigest(),
        bgr=bgr,
    )


class _EmptyDetector(Detector):
    def predict(
        self,
        image: DecodedImage,
        requested_classes: list[str] | None = None,
    ) -> list[Any]:
        return []


def _registry() -> VisionModelRegistry:
    registry = VisionModelRegistry()
    for name in ("ppe", "crack"):
        config = _model(name)
        registry.register(config, _EmptyDetector(config))
    return registry


def test_enabled_mobileclip_config_requires_local_artifact_metadata() -> None:
    with pytest.raises(ValidationError, match="missing"):
        MobileClip2SemanticRouterConfig(enabled=True)
    with pytest.raises(ValidationError, match="overlap"):
        SemanticPromptSetConfig(positive=["same"], negative=["same"])


def test_mobileclip_adapter_is_lazy_verified_calibrated_and_cached(
    tmp_path: Path,
) -> None:
    loads: list[tuple[Path, str, str]] = []
    calls: list[list[str]] = []

    def loader(path: Path, model_name: str, device: str) -> object:
        loads.append((path, model_name, device))
        return object()

    def runner(
        runtime: object,
        rgb: np.ndarray[Any, np.dtype[np.uint8]],
        prompts: list[str],
        precision: str,
    ) -> list[float]:
        assert runtime is not None
        assert rgb.shape == (48, 64, 3)
        assert precision == "fp32"
        calls.append(prompts)
        values = {
            "construction worker": 0.8,
            "empty construction site": 0.1,
            "cracked concrete wall": 0.2,
            "smooth concrete wall": 0.6,
        }
        return [values[item] for item in prompts]

    adapter = MobileClip2S0Adapter(
        _semantic_config(tmp_path),
        loader=loader,
        runner=runner,
    )
    models = [
        RoutingModel.from_config(_model("ppe")),
        RoutingModel.from_config(_model("crack")),
    ]
    assert not adapter.loaded

    first = adapter.score(_image(tmp_path), models)
    second = adapter.score(_image(tmp_path), models)

    assert adapter.loaded
    assert len(loads) == 1
    assert len(calls) == 1
    assert first.status == "completed"
    assert first.probabilities()["ppe"] > 0.99
    assert first.probabilities()["crack"] < 0.02
    assert second.cache_hit
    assert second.processing_ms == 0


def test_mobileclip_adapter_rejects_checkpoint_hash_mismatch(tmp_path: Path) -> None:
    config = _semantic_config(tmp_path).model_copy(update={"model_sha256": "0" * 64})
    adapter = MobileClip2S0Adapter(config, loader=lambda *_: object(), runner=lambda *_: [])
    with pytest.raises(ModelUnavailableError, match="checksum mismatch"):
        adapter.load()


def test_visual_router_blends_semantics_before_existing_recall_guard() -> None:
    router = VisualRouter(
        VisionRoutingConfig(
            model_priors={"ppe": 0.5, "crack": 0.5},
            max_models_per_roi=2,
            min_models_high_risk=1,
            roi_budget=2,
            top_probability_gap=0.08,
        )
    )
    models = [_model("ppe"), _model("crack")]
    semantic = router.route(
        _features(),
        models,
        strategy="cost-aware-guard",
        semantic_probabilities={"ppe": 0.9, "crack": 0.1},
        semantic_weight=1.0,
    )
    probabilities = {item.model.model_name: item.probability for item in semantic.model_scores}
    assert probabilities == pytest.approx({"crack": 0.1, "ppe": 0.9})
    assert semantic.probability_source == "mobileclip2_blend"

    ambiguous = router.route(
        _features(),
        models,
        strategy="cost-aware-guard",
        semantic_probabilities={"ppe": 0.51, "crack": 0.50},
        semantic_weight=1.0,
    )
    assert ambiguous.guard_triggered
    assert "top_probability_close" in ambiguous.guard_reasons
    assert ambiguous.selected_model_names == ["crack", "ppe"]


def test_pipeline_records_mobileclip_route_and_safe_heuristic_fallback(
    tmp_path: Path,
) -> None:
    config = _semantic_config(tmp_path)

    def scores(
        runtime: object,
        rgb: np.ndarray[Any, np.dtype[np.uint8]],
        prompts: list[str],
        precision: str,
    ) -> list[float]:
        return [0.9, 0.1, 0.2, 0.7]

    adapter = MobileClip2S0Adapter(
        config,
        loader=lambda *_: object(),
        runner=scores,
    )
    pipeline = ConditionalVisionPipeline(
        open_vocab_config=OpenVocabularyConfig(enabled=False),
        segmentation_config=SegmentationConfig(enabled=False),
        routing_config=VisionRoutingConfig(
            model_priors={"ppe": 0.5, "crack": 0.5},
            coverage_weight=0,
            cost_weight=1,
            call_count_weight=0.5,
            max_models_per_roi=2,
            min_models_high_risk=1,
            roi_budget=2,
        ),
        models=_registry(),
        semantic_router=adapter,
    )
    _, decision = pipeline.route_scene(_image(tmp_path))
    assert decision.probability_source == "mobileclip2_blend"
    assert decision.semantic_routing is not None
    assert decision.semantic_routing.status == "completed"

    failing = MobileClip2S0Adapter(
        config,
        loader=lambda *_: object(),
        runner=lambda *_: (_ for _ in ()).throw(RuntimeError("semantic unavailable")),
    )
    fallback_pipeline = ConditionalVisionPipeline(
        open_vocab_config=OpenVocabularyConfig(enabled=False),
        segmentation_config=SegmentationConfig(enabled=False),
        routing_config=VisionRoutingConfig(
            model_priors={"ppe": 0.5, "crack": 0.5},
            max_models_per_roi=2,
            min_models_high_risk=1,
            roi_budget=2,
        ),
        models=_registry(),
        semantic_router=failing,
    )
    _, fallback = fallback_pipeline.route_scene(_image(tmp_path))
    assert fallback.probability_source == "heuristic"
    assert fallback.semantic_routing is not None
    assert fallback.semantic_routing.status == "fallback"
    assert "semantic unavailable" in str(fallback.semantic_routing.error)
