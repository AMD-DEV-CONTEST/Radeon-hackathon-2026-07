"""Conditional open-vocabulary, RGC specialist, and segmentation flow."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from pydantic import Field

from buildguard.config import (
    OpenVocabularyConfig,
    SegmentationConfig,
    VisionRoutingConfig,
)
from buildguard.schemas.common import BoundingBox, StrictSchema
from buildguard.schemas.vision import Detection
from buildguard.vision.open_vocab.base import OpenVocabularyLocator
from buildguard.vision.preprocessing import DecodedImage
from buildguard.vision.registry import VisionModelRegistry
from buildguard.vision.routing.feature_extractor import RoiFeatureExtractor
from buildguard.vision.routing.router import VisualRouter
from buildguard.vision.routing.schemas import (
    RoiContext,
    RoutingDecision,
    RoutingModel,
    RoutingStrategy,
)
from buildguard.vision.segmentation.base import (
    FineSegmentationAdapter,
    SegmentationMask,
)
from buildguard.vision.semantic.base import SemanticImageRouter
from buildguard.vision.semantic.schemas import SemanticRoutingResult

LOGGER = logging.getLogger(__name__)
AdapterStatus = Literal["disabled", "skipped", "completed", "failed"]


class ConditionalInspectionInput(StrictSchema):
    image_path: Path
    text_queries: list[str] = Field(min_length=1, max_length=64)
    require_area: bool = False
    routing_strategy: RoutingStrategy = "cost-aware-guard"


class ConditionalVisionResult(StrictSchema):
    """Structured result that keeps locator boxes out of numeric risk inputs."""

    open_vocab_status: AdapterStatus
    segmentation_status: AdapterStatus
    open_vocab_detections: list[Detection] = Field(default_factory=list)
    specialist_detections: list[Detection] = Field(default_factory=list)
    routing_decisions: list[RoutingDecision] = Field(default_factory=list)
    masks: list[SegmentationMask] = Field(default_factory=list)
    fallback_used: bool = False
    messages: list[str] = Field(default_factory=list)

    def to_public_result(self) -> ConditionalVisionPublicResult:
        """Return an API/tool-safe result without embedding raw mask arrays."""
        return ConditionalVisionPublicResult(
            open_vocab_status=self.open_vocab_status,
            segmentation_status=self.segmentation_status,
            open_vocab_detections=self.open_vocab_detections,
            specialist_detections=self.specialist_detections,
            routing_decisions=self.routing_decisions,
            masks=[
                SegmentationMaskSummary(
                    area=item.area,
                    area_ratio=item.area_ratio,
                    perimeter=item.perimeter,
                    bounding_box=item.bounding_box,
                    confidence=item.confidence,
                    stability=item.stability,
                    source_model=item.source_model,
                    mask_path=item.mask_path,
                )
                for item in self.masks
            ],
            fallback_used=self.fallback_used,
            messages=self.messages,
        )


class SegmentationMaskSummary(StrictSchema):
    """Serializable mask metadata exposed at process boundaries."""

    area: int = Field(gt=0)
    area_ratio: float = Field(gt=0, le=1)
    perimeter: float = Field(gt=0)
    bounding_box: BoundingBox
    confidence: float = Field(ge=0, le=1)
    stability: float = Field(ge=0, le=1)
    source_model: str = Field(min_length=1, max_length=256)
    mask_path: Path


class ConditionalVisionPublicResult(StrictSchema):
    """JSON/OpenAPI-safe conditional inspection result."""

    open_vocab_status: AdapterStatus
    segmentation_status: AdapterStatus
    open_vocab_detections: list[Detection] = Field(default_factory=list)
    specialist_detections: list[Detection] = Field(default_factory=list)
    routing_decisions: list[RoutingDecision] = Field(default_factory=list)
    masks: list[SegmentationMaskSummary] = Field(default_factory=list)
    fallback_used: bool = False
    messages: list[str] = Field(default_factory=list)


class ConditionalVisionPipeline:
    """Run optional adapters while preserving the dedicated-detector fallback."""

    def __init__(
        self,
        open_vocab_config: OpenVocabularyConfig,
        segmentation_config: SegmentationConfig,
        routing_config: VisionRoutingConfig,
        models: VisionModelRegistry,
        *,
        locator: OpenVocabularyLocator | None = None,
        segmenter: FineSegmentationAdapter | None = None,
        semantic_router: SemanticImageRouter | None = None,
    ) -> None:
        self.open_vocab_config = open_vocab_config
        self.segmentation_config = segmentation_config
        self.models = models
        self.locator = locator
        self.segmenter = segmenter
        self.semantic_router = semantic_router
        self.router = VisualRouter(routing_config)
        self.extractor = RoiFeatureExtractor()

    def _semantic_scores(
        self,
        image: DecodedImage,
        candidates: list[RoutingModel],
        *,
        crop: BoundingBox | None = None,
    ) -> tuple[SemanticRoutingResult | None, dict[str, float], float]:
        adapter = self.semantic_router
        if adapter is None or not adapter.config.enabled:
            return None, {}, 0.0
        try:
            result = adapter.score(image, candidates, crop=crop)
            return result, result.probabilities(), adapter.config.semantic_weight
        except Exception as exc:
            LOGGER.warning("MobileCLIP2 semantic routing unavailable; using heuristic: %s", exc)
            return (
                SemanticRoutingResult(
                    status="fallback",
                    model_name=adapter.config.model_name,
                    model_revision=adapter.config.model_revision,
                    checkpoint_sha256=adapter.config.model_sha256,
                    error=str(exc),
                ),
                {},
                0.0,
            )

    def route_scene(
        self,
        image: DecodedImage,
        *,
        model_names: list[str] | None = None,
        temporal_key: str | None = None,
        routing_strategy: RoutingStrategy = "cost-aware-guard",
    ) -> tuple[list[str], RoutingDecision]:
        """Select detectors for a complete frame when no locator RoI is available."""
        requested = self.models.enabled(model_names)
        requested_names = {detector.name for detector in requested}
        configs = [
            config
            for config in self.models.model_configs()
            if config.model_name in requested_names
        ]
        height, width = image.bgr.shape[:2]
        features = self.extractor.extract(
            image.bgr,
            BoundingBox(x1=0, y1=0, x2=float(width), y2=float(height)),
            RoiContext(
                roi_label="*",
                roi_confidence=1.0,
                high_risk=False,
            ),
        )
        candidates = self.router.candidates(features, configs)
        semantic, probabilities, semantic_weight = self._semantic_scores(
            image,
            candidates,
        )
        decision = self.router.route(
            features,
            configs,
            strategy=routing_strategy,
            temporal_key=temporal_key,
            semantic_probabilities=probabilities,
            semantic_weight=semantic_weight,
            semantic_routing=semantic,
        )
        return decision.selected_model_names, decision

    def _fallback(
        self,
        image: DecodedImage,
        messages: list[str],
    ) -> ConditionalVisionResult:
        detections: list[Detection] = []
        detectors = self.models.enabled()
        routing: list[RoutingDecision] = []
        if self.semantic_router is not None and self.semantic_router.config.enabled:
            try:
                selected_names, decision = self.route_scene(image)
                selected = self.models.enabled(selected_names)
                if selected:
                    detectors = selected
                    routing.append(decision)
            except Exception as exc:
                message = f"Semantic fallback routing failed; using all detectors: {exc}"
                LOGGER.warning("%s", message)
                messages.append(message)
        for detector in detectors:
            try:
                detections.extend(detector.predict(image))
            except Exception as exc:
                message = f"Fallback detector {detector.name} failed: {exc}"
                LOGGER.warning("%s", message)
                messages.append(message)
        return ConditionalVisionResult(
            open_vocab_status=(
                "disabled" if not self.open_vocab_config.enabled else "skipped"
            ),
            segmentation_status=(
                "disabled" if not self.segmentation_config.enabled else "skipped"
            ),
            specialist_detections=detections,
            routing_decisions=routing,
            fallback_used=True,
            messages=messages,
        )

    def run(
        self,
        image: DecodedImage,
        text_queries: list[str],
        *,
        require_area: bool = False,
        routing_strategy: RoutingStrategy = "cost-aware-guard",
        temporal_key: str | None = None,
    ) -> ConditionalVisionResult:
        messages: list[str] = []
        if not self.open_vocab_config.enabled:
            messages.append("Open-vocabulary localization is disabled; using fallback")
            return self._fallback(image, messages)
        if self.locator is None:
            messages.append("Open-vocabulary adapter is not configured; using fallback")
            return self._fallback(image, messages)
        try:
            localized = self.locator.locate(image, text_queries)
        except Exception as exc:
            message = f"Open-vocabulary localization unavailable: {exc}"
            LOGGER.warning("%s", message)
            messages.append(message)
            return self._fallback(image, messages)

        routing: list[RoutingDecision] = []
        selected_names: set[str] = set()
        configs = self.models.model_configs()
        for detection in localized:
            features = self.extractor.extract(
                image.bgr,
                detection.bounding_box,
                RoiContext(
                    roi_label=detection.label,
                    roi_confidence=detection.confidence,
                    high_risk=False,
                ),
            )
            candidates = self.router.candidates(features, configs)
            semantic, probabilities, semantic_weight = self._semantic_scores(
                image,
                candidates,
                crop=detection.bounding_box,
            )
            decision = self.router.route(
                features,
                configs,
                strategy=routing_strategy,
                temporal_key=(
                    f"{temporal_key}:{detection.label}:{len(routing)}"
                    if temporal_key is not None
                    else None
                ),
                semantic_probabilities=probabilities,
                semantic_weight=semantic_weight,
                semantic_routing=semantic,
            )
            routing.append(decision)
            selected_names.update(decision.selected_model_names)

        specialist: list[Detection] = []
        for model_name in sorted(selected_names):
            try:
                specialist.extend(self.models.get(model_name).predict(image))
            except Exception as exc:
                message = f"Routed detector {model_name} failed: {exc}"
                LOGGER.warning("%s", message)
                messages.append(message)

        masks: list[SegmentationMask] = []
        segmentation_status: AdapterStatus = (
            "disabled" if not self.segmentation_config.enabled else "skipped"
        )
        should_segment = require_area or any(
            detection.label in self.segmentation_config.area_required_classes
            for detection in specialist
        )
        if should_segment and self.segmentation_config.enabled:
            if self.segmenter is None:
                messages.append("Segmentation adapter is not configured; segmentation skipped")
            else:
                segmentation_candidates = [
                    detection
                    for detection in specialist
                    if require_area
                    or detection.label
                    in self.segmentation_config.area_required_classes
                ]
                if not segmentation_candidates and require_area:
                    segmentation_candidates = localized
                try:
                    masks = self.segmenter.segment(
                        image,
                        [item.bounding_box for item in segmentation_candidates],
                    )
                    segmentation_status = "completed"
                except Exception as exc:
                    segmentation_status = "failed"
                    message = f"Segmentation unavailable: {exc}"
                    LOGGER.warning("%s", message)
                    messages.append(message)

        return ConditionalVisionResult(
            open_vocab_status="completed",
            segmentation_status=segmentation_status,
            open_vocab_detections=localized,
            specialist_detections=specialist,
            routing_decisions=routing,
            masks=masks,
            fallback_used=False,
            messages=messages,
        )
