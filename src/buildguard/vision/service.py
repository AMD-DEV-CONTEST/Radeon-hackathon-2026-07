"""Single-image and resilient batch inspection service."""

from __future__ import annotations

import hashlib
import logging
import time
from collections import Counter
from pathlib import Path

import cv2

from buildguard.config import Settings, VisionConfig
from buildguard.exceptions import ConfigurationError
from buildguard.scheduling.runtime_gate import GpuInferenceGate
from buildguard.scheduling.schemas import GpuTask, GpuTaskType, SchedulingDecision
from buildguard.schemas.vision import Detection, InspectionResult
from buildguard.security.path_guard import PathGuard
from buildguard.tools.base import ToolDefinition
from buildguard.tools.registry import ToolRegistry
from buildguard.vision.base_detector import Detector
from buildguard.vision.conditional_pipeline import (
    ConditionalInspectionInput,
    ConditionalVisionPipeline,
    ConditionalVisionPublicResult,
    ConditionalVisionResult,
)
from buildguard.vision.fusion import fuse_detections
from buildguard.vision.open_vocab.grounding_dino_adapter import (
    GroundingDinoLocalAdapter,
)
from buildguard.vision.preprocessing import DecodedImage, decode_image
from buildguard.vision.registry import VisionModelRegistry
from buildguard.vision.routing.schemas import RoutingDecision
from buildguard.vision.schemas import (
    BatchImageInspectionInput,
    BatchInspectionResult,
    BatchInspectionToolOutput,
    EvidenceRecord,
    ImageFailure,
    InspectionSummary,
    SingleImageInspectionInput,
    SingleImageInspectionOutput,
)
from buildguard.vision.segmentation.sam2_adapter import Sam2LocalAdapter
from buildguard.vision.semantic.mobileclip2_adapter import MobileClip2S0Adapter

LOGGER = logging.getLogger(__name__)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def _evidence_id(image: DecodedImage, detection: Detection) -> str:
    box = detection.bounding_box
    material = "|".join(
        [
            image.checksum,
            detection.source_model,
            detection.label,
            f"{box.x1:.6f}",
            f"{box.y1:.6f}",
            f"{box.x2:.6f}",
            f"{box.y2:.6f}",
            f"{detection.confidence:.8f}",
        ]
    )
    return hashlib.sha256(material.encode()).hexdigest()


class VisionInspectionService:
    def __init__(
        self,
        config: VisionConfig,
        models: VisionModelRegistry,
        path_guard: PathGuard,
        conditional_pipeline: ConditionalVisionPipeline | None = None,
        gpu_gate: GpuInferenceGate | None = None,
    ) -> None:
        self.config = config
        self.models = models
        self.path_guard = path_guard
        self.conditional_pipeline = conditional_pipeline
        self.gpu_gate = gpu_gate
        self.visualization_dir = config.visualization_dir.resolve()
        self.visualization_dir.mkdir(parents=True, exist_ok=True)

    def start(self) -> None:
        """Preload the configured resident semantic router without touching detectors."""
        pipeline = self.conditional_pipeline
        semantic = pipeline.semantic_router if pipeline is not None else None
        if semantic is None or not semantic.config.enabled or not semantic.config.resident:
            return
        try:
            semantic.load()
        except Exception:
            if semantic.config.required:
                raise
            LOGGER.exception(
                "MobileCLIP2 preload failed; guarded heuristic routing remains available"
            )

    def close(self) -> None:
        """Release only semantic pre-router resources owned by this service."""
        pipeline = self.conditional_pipeline
        semantic = pipeline.semantic_router if pipeline is not None else None
        if semantic is not None and semantic.loaded:
            semantic.unload()

    def semantic_router_status(self) -> dict[str, object]:
        """Expose model identity and actual residency without leaking local paths."""
        pipeline = self.conditional_pipeline
        semantic = pipeline.semantic_router if pipeline is not None else None
        if semantic is None:
            return {"enabled": False, "loaded": False}
        return {
            "enabled": semantic.config.enabled,
            "required": semantic.config.required,
            "resident": semantic.config.resident,
            "loaded": semantic.loaded,
            "model_name": semantic.config.model_name,
            "model_revision": semantic.config.model_revision,
            "checkpoint_sha256": semantic.config.model_sha256,
        }

    def inspect_conditionally(
        self,
        request: ConditionalInspectionInput,
    ) -> ConditionalVisionResult:
        """Run the optional 2C flow without weakening ordinary detector fallback."""
        if self.conditional_pipeline is None:
            raise RuntimeError("Conditional visual pipeline is not configured")
        source = self.path_guard.resolve_read(request.image_path)
        if source.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ValueError(f"Unsupported image extension: {source.suffix}")
        return self.conditional_pipeline.run(
            decode_image(source),
            request.text_queries,
            require_area=request.require_area,
            routing_strategy=request.routing_strategy,
            temporal_key=str(source),
        )

    def _route_detectors(
        self,
        image: DecodedImage,
        model_names: list[str] | None,
        *,
        temporal_key: str | None,
    ) -> tuple[list[Detector], list[RoutingDecision]]:
        fallback = self.models.enabled(model_names)
        if self.conditional_pipeline is None or not self.config.routing.enabled:
            return fallback, []
        try:
            selected_names, decision = self.conditional_pipeline.route_scene(
                image,
                model_names=model_names,
                temporal_key=temporal_key,
            )
            selected = self.models.enabled(selected_names)
            if selected:
                return selected, [decision]
        except Exception as exc:
            LOGGER.warning("Visual routing failed; using all requested detectors: %s", exc)
        return fallback, []

    def _run_detectors(
        self,
        image: DecodedImage,
        *,
        model_names: list[str] | None,
        requested_classes: list[str] | None,
        temporal_key: str | None,
        task_type: GpuTaskType = "risk_confirmation",
    ) -> tuple[
        list[Detector],
        list[list[Detection]],
        list[str],
        list[str],
        list[RoutingDecision],
    ]:
        detectors, routing = self._route_detectors(
            image,
            model_names,
            temporal_key=temporal_key,
        )
        if not detectors:
            raise ValueError("No enabled visual detectors are available")
        detector_results: list[list[Detection]] = []
        successful_models: list[str] = []
        errors: list[str] = []
        for detector in detectors:
            try:
                result = self._predict_scheduled(
                    detector,
                    image,
                    requested_classes,
                    task_type=task_type,
                )
                detector_results.append(self._with_image_dimensions(result, image))
                successful_models.append(detector.name)
            except Exception as exc:
                message = f"Detector {detector.name} failed: {exc}"
                errors.append(message)
                LOGGER.warning("%s", message)
        if not successful_models:
            raise RuntimeError("; ".join(errors) or "All visual detectors failed")
        return detectors, detector_results, successful_models, errors, routing

    @staticmethod
    def _uses_gpu(detector: Detector) -> bool:
        return detector.config.device.casefold() not in {"cpu", "mps"}

    def _task(
        self,
        detector: Detector,
        task_type: GpuTaskType,
        batch_size: int,
    ) -> GpuTask:
        return GpuTask(
            task_type=task_type,
            model_name=detector.name,
            estimated_latency_ms=detector.config.estimated_latency_ms,
            estimated_memory_mb=detector.config.estimated_memory_mb,
            batch_size=batch_size,
            can_cpu_fallback=False,
        )

    def _predict_scheduled(
        self,
        detector: Detector,
        image: DecodedImage,
        requested_classes: list[str] | None,
        *,
        task_type: GpuTaskType,
    ) -> list[Detection]:
        if self.gpu_gate is None or not self._uses_gpu(detector):
            return detector.predict(image, requested_classes)
        with self.gpu_gate.admit(self._task(detector, task_type, 1)):
            return detector.predict(image, requested_classes)

    def _predict_batch_scheduled(
        self,
        detector: Detector,
        images: list[DecodedImage],
        requested_classes: list[str] | None,
        *,
        task_type: GpuTaskType,
    ) -> list[list[Detection]]:
        if self.gpu_gate is None or not self._uses_gpu(detector):
            return detector.predict_batch(images, requested_classes)
        with self.gpu_gate.admit(
            self._task(detector, task_type, len(images))
        ) as decision:
            effective = (
                decision.effective_batch_size
                if isinstance(decision, SchedulingDecision)
                else len(images)
            )
            results: list[list[Detection]] = []
            for offset in range(0, len(images), effective):
                results.extend(
                    detector.predict_batch(
                        images[offset : offset + effective],
                        requested_classes,
                    )
                )
            return results

    def detect_decoded(
        self,
        image: DecodedImage,
        *,
        model_names: list[str] | None = None,
        requested_classes: list[str] | None = None,
        temporal_key: str | None = None,
        task_type: GpuTaskType = "normal_monitoring",
    ) -> list[Detection]:
        """Run routed detectors on an already decoded image without rendering evidence."""
        detectors, results, _, _, _ = self._run_detectors(
            image,
            model_names=model_names,
            requested_classes=requested_classes,
            temporal_key=temporal_key,
            task_type=task_type,
        )
        return fuse_detections(
            results,
            min(detector.config.nms_iou for detector in detectors),
        )

    def _visualize(
        self,
        image: DecodedImage,
        detections: list[Detection],
    ) -> Path:
        canvas = image.bgr.copy()
        for detection in detections:
            box = detection.bounding_box
            point1 = (round(box.x1), round(box.y1))
            point2 = (round(box.x2), round(box.y2))
            cv2.rectangle(canvas, point1, point2, (0, 0, 255), 2)
            cv2.putText(
                canvas,
                f"{detection.label} {detection.confidence:.2f}",
                (point1[0], max(12, point1[1] - 4)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 0, 255),
                1,
                cv2.LINE_AA,
            )
        signature = hashlib.sha256(
            (
                image.checksum + "|" + "|".join(_evidence_id(image, item) for item in detections)
            ).encode()
        ).hexdigest()[:20]
        target = self.visualization_dir / f"{image.path.stem}-{signature}.jpg"
        temporary = target.with_suffix(".tmp.jpg")
        ok, encoded = cv2.imencode(".jpg", canvas)
        if not ok:
            raise ValueError(f"Could not encode visualization for {image.path}")
        temporary.write_bytes(encoded.tobytes())
        temporary.replace(target)
        return target

    def inspect_single(
        self,
        request: SingleImageInspectionInput,
    ) -> SingleImageInspectionOutput:
        started = time.perf_counter()
        source = self.path_guard.resolve_read(request.image_path)
        if source.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ValueError(f"Unsupported image extension: {source.suffix}")
        image = decode_image(source)
        detectors, detector_results, successful_models, errors, routing = (
            self._run_detectors(
                image,
                model_names=request.model_names,
                requested_classes=request.requested_classes,
                temporal_key=image.checksum,
            )
        )
        return self._complete_inspection(
            source=source,
            image=image,
            detectors=detectors,
            detector_results=detector_results,
            successful_models=successful_models,
            errors=errors,
            routing_decisions=routing,
            started=started,
        )

    @staticmethod
    def _with_image_dimensions(
        detections: list[Detection],
        image: DecodedImage,
    ) -> list[Detection]:
        return [
            item.model_copy(
                update={
                    "attributes": {
                        **item.attributes,
                        "image_width": image.width,
                        "image_height": image.height,
                    }
                }
            )
            for item in detections
        ]

    def _complete_inspection(
        self,
        *,
        source: Path,
        image: DecodedImage,
        detectors: list[Detector],
        detector_results: list[list[Detection]],
        successful_models: list[str],
        errors: list[str],
        routing_decisions: list[RoutingDecision],
        started: float,
    ) -> SingleImageInspectionOutput:
        nms_iou = min(detector.config.nms_iou for detector in detectors)
        detections = fuse_detections(detector_results, nms_iou)
        visualization = self._visualize(image, detections)
        evidence = [
            EvidenceRecord(
                evidence_id=_evidence_id(image, detection),
                image_path=source,
                bbox=detection.bounding_box,
                confidence=detection.confidence,
                source_model=detection.source_model,
                visualization_path=visualization,
                requires_review=detection.confidence < self.config.requires_review_threshold,
                metadata={
                    "label": detection.label,
                    "image_checksum": image.checksum,
                },
            )
            for detection in detections
        ]
        counts = Counter(item.label for item in detections)
        risk_candidates = sorted(counts)
        inspection = InspectionResult(
            source_path=source,
            detections=detections,
            model_name=",".join(successful_models),
            processing_ms=(time.perf_counter() - started) * 1000,
            success=True,
            error="; ".join(errors) if errors else None,
        )
        summary = InspectionSummary(
            image_path=source,
            success=True,
            detection_count=len(detections),
            category_counts=dict(counts),
            max_confidence=max((item.confidence for item in detections), default=0),
            evidence_ids=[item.evidence_id for item in evidence],
            risk_candidates=risk_candidates,
            routing_decisions=routing_decisions,
            error=inspection.error,
        )
        return SingleImageInspectionOutput(
            inspection=inspection,
            evidence=evidence,
            summary=summary,
        )

    def _batch_paths(self, request: BatchImageInspectionInput) -> list[Path]:
        candidates = list(request.image_paths)
        if request.directory is not None:
            directory = self.path_guard.resolve_read(request.directory)
            if not directory.is_dir():
                raise ValueError(f"Batch image directory does not exist: {directory}")
            iterator = directory.rglob("*") if request.recursive else directory.iterdir()
            candidates.extend(
                item
                for item in iterator
                if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS
            )
        resolved: list[Path] = []
        for candidate in candidates:
            if candidate.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            safe = self.path_guard.resolve_read(candidate)
            if safe not in resolved:
                resolved.append(safe)
        limit = min(request.max_items or self.config.batch_max_items, self.config.batch_max_items)
        return sorted(resolved)[:limit]

    def inspect_batch(self, request: BatchImageInspectionInput) -> BatchInspectionResult:
        results: list[SingleImageInspectionOutput] = []
        failures: list[ImageFailure] = []
        counts: Counter[str] = Counter()
        evidence_ids: list[str] = []
        risk_candidates: set[str] = set()
        decoded: list[tuple[Path, DecodedImage, float]] = []
        for image_path in self._batch_paths(request):
            try:
                decoded.append((image_path, decode_image(image_path), time.perf_counter()))
            except Exception as exc:
                LOGGER.warning("Skipping failed batch image %s: %s", image_path, exc)
                failures.append(ImageFailure(image_path=image_path, error=str(exc)))

        if not decoded:
            return BatchInspectionResult(
                results=[],
                failures=failures,
                category_counts={},
                risk_candidates=[],
                evidence_ids=[],
            )

        all_detectors = self.models.enabled(request.model_names)
        if not all_detectors:
            error = "No enabled visual detectors are available"
            failures.extend(ImageFailure(image_path=path, error=error) for path, _, _ in decoded)
            return BatchInspectionResult(
                results=[],
                failures=failures,
                category_counts={},
                risk_candidates=[],
                evidence_ids=[],
            )

        per_image_detectors: list[list[Detector]] = []
        per_image_routing: list[list[RoutingDecision]] = []
        for _, image, _ in decoded:
            selected, routing = self._route_detectors(
                image,
                request.model_names,
                temporal_key=image.checksum,
            )
            per_image_detectors.append(selected)
            per_image_routing.append(routing)

        per_image_results: list[list[list[Detection]]] = [[] for _ in decoded]
        per_image_models: list[list[str]] = [[] for _ in decoded]
        per_image_errors: list[list[str]] = [[] for _ in decoded]
        images = [image for _, image, _ in decoded]
        detectors_by_name = {detector.name: detector for detector in all_detectors}
        selected_names = sorted(
            {
                detector.name
                for selected in per_image_detectors
                for detector in selected
            }
        )
        for detector_name in selected_names:
            detector = detectors_by_name[detector_name]
            selected_indices = [
                index
                for index, selected in enumerate(per_image_detectors)
                if any(item.name == detector_name for item in selected)
            ]
            selected_images = [images[index] for index in selected_indices]
            try:
                batch = self._predict_batch_scheduled(
                    detector,
                    selected_images,
                    request.requested_classes,
                    task_type="risk_confirmation",
                )
                if len(batch) != len(selected_images):
                    raise RuntimeError(
                        f"Detector returned {len(batch)} results for "
                        f"{len(selected_images)} images"
                    )
            except Exception as batch_exc:
                LOGGER.warning(
                    "Detector %s batch path failed; isolating images: %s",
                    detector.name,
                    batch_exc,
                )
                batch = []
                for index in selected_indices:
                    try:
                        batch.append(
                            detector.predict(images[index], request.requested_classes)
                        )
                    except Exception as exc:
                        batch.append([])
                        per_image_errors[index].append(f"Detector {detector.name} failed: {exc}")
            for index, detections in zip(selected_indices, batch, strict=True):
                if any(
                    message.startswith(f"Detector {detector.name} failed:")
                    for message in per_image_errors[index]
                ):
                    continue
                per_image_results[index].append(
                    self._with_image_dimensions(detections, images[index])
                )
                per_image_models[index].append(detector.name)

        for index, (source, image, started) in enumerate(decoded):
            if not per_image_models[index]:
                failures.append(
                    ImageFailure(
                        image_path=source,
                        error="; ".join(per_image_errors[index]) or "All visual detectors failed",
                    )
                )
                continue
            try:
                result = self._complete_inspection(
                    source=source,
                    image=image,
                    detectors=per_image_detectors[index],
                    detector_results=per_image_results[index],
                    successful_models=per_image_models[index],
                    errors=per_image_errors[index],
                    routing_decisions=per_image_routing[index],
                    started=started,
                )
            except Exception as exc:
                LOGGER.warning("Skipping failed batch image %s: %s", source, exc)
                failures.append(ImageFailure(image_path=source, error=str(exc)))
                continue
            results.append(result)
            counts.update(result.summary.category_counts)
            evidence_ids.extend(result.summary.evidence_ids)
            risk_candidates.update(result.summary.risk_candidates)
        return BatchInspectionResult(
            results=results,
            failures=failures,
            category_counts=dict(counts),
            risk_candidates=sorted(risk_candidates),
            evidence_ids=evidence_ids,
        )


def create_vision_service(
    settings: Settings,
    *,
    gpu_gate: GpuInferenceGate | None = None,
) -> VisionInspectionService:
    workspace = settings.app.workspace_dir.resolve()
    visualization = settings.vision.visualization_dir.resolve()
    mask_output = settings.vision.segmentation.output_dir.resolve()
    try:
        visualization.relative_to(workspace)
        mask_output.relative_to(workspace)
    except ValueError as exc:
        raise ConfigurationError(
            "vision visualization and mask output directories must remain inside workspace"
        ) from exc
    roots = [path.resolve() for path in settings.vision.allowed_image_roots]
    config = settings.vision.model_copy(
        update={
            "visualization_dir": visualization,
            "allowed_image_roots": roots,
            "segmentation": settings.vision.segmentation.model_copy(
                update={"output_dir": mask_output}
            ),
        }
    )
    registry = VisionModelRegistry.from_config(
        config,
        settings.permissions,
        seed=settings.app.seed,
    )
    conditional = ConditionalVisionPipeline(
        config.open_vocab,
        config.segmentation,
        config.routing,
        registry,
        locator=GroundingDinoLocalAdapter(config.open_vocab),
        segmenter=Sam2LocalAdapter(config.segmentation),
        semantic_router=MobileClip2S0Adapter(config.semantic_router),
    )
    return VisionInspectionService(
        config,
        registry,
        PathGuard(roots),
        conditional,
        gpu_gate,
    )


def register_vision_tools(
    registry: ToolRegistry,
    service: VisionInspectionService,
    *,
    timeout_seconds: float = 60,
) -> None:
    def single(raw: object) -> SingleImageInspectionOutput:
        return service.inspect_single(SingleImageInspectionInput.model_validate(raw))

    def batch(raw: object) -> BatchInspectionToolOutput:
        result = service.inspect_batch(BatchImageInspectionInput.model_validate(raw))
        return BatchInspectionToolOutput(
            summaries=[item.summary for item in result.results],
            failed_images=result.failures,
            category_counts=result.category_counts,
            risk_candidates=result.risk_candidates,
            evidence_ids=result.evidence_ids,
        )

    roots = service.config.allowed_image_roots
    registry.register(
        ToolDefinition(
            name="inspect_single_image",
            description="Inspect one allowlisted local construction image.",
            input_schema=SingleImageInspectionInput,
            output_schema=SingleImageInspectionOutput,
            permission="auto",
            read_only=False,
            timeout_seconds=timeout_seconds,
            category="inspection",
            allowed_roots=roots,
            allowed_extensions=sorted(IMAGE_EXTENSIONS),
            max_items=1,
        ),
        single,
    )
    registry.register(
        ToolDefinition(
            name="inspect_image_batch",
            description="Inspect a bounded local image batch and return an LLM-safe summary.",
            input_schema=BatchImageInspectionInput,
            output_schema=BatchInspectionToolOutput,
            permission="confirm",
            read_only=False,
            timeout_seconds=timeout_seconds,
            category="inspection",
            allowed_roots=roots,
            allowed_extensions=sorted(IMAGE_EXTENSIONS),
            max_items=service.config.batch_max_items,
        ),
        batch,
    )
    registry.register(
        ToolDefinition(
            name="inspect_image_batch_structured",
            description=(
                "Agent-internal bounded batch inspection with complete structured "
                "detections and visual evidence for downstream risk scoring."
            ),
            input_schema=BatchImageInspectionInput,
            output_schema=BatchInspectionResult,
            permission="confirm",
            read_only=False,
            timeout_seconds=timeout_seconds,
            category="inspection",
            allowed_roots=roots,
            allowed_extensions=sorted(IMAGE_EXTENSIONS),
            max_items=service.config.batch_max_items,
        ),
        lambda raw: service.inspect_batch(BatchImageInspectionInput.model_validate(raw)),
    )
    if service.conditional_pipeline is not None:
        registry.register(
            ToolDefinition(
                name="inspect_conditionally",
                description=(
                    "Run open-vocabulary localization, recall-guarded specialist routing, "
                    "and optional fine segmentation with deterministic fallback."
                ),
                input_schema=ConditionalInspectionInput,
                output_schema=ConditionalVisionPublicResult,
                permission="confirm",
                read_only=False,
                timeout_seconds=timeout_seconds,
                category="inspection",
                allowed_roots=roots,
                allowed_extensions=sorted(IMAGE_EXTENSIONS),
                max_items=1,
            ),
            lambda raw: service.inspect_conditionally(
                ConditionalInspectionInput.model_validate(raw)
            ).to_public_result(),
        )
