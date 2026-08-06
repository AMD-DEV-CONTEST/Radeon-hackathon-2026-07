from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from buildguard.config import (
    PermissionConfig,
    RiskPolicyConfig,
    VisionConfig,
    VisionModelConfig,
)
from buildguard.exceptions import EndpointSecurityError, ModelUnavailableError
from buildguard.logging_system.jsonl_writer import JsonlWriter
from buildguard.risk.policies import risk_level
from buildguard.risk.scorer import RiskComponents, RiskScorer
from buildguard.risk.service import RiskAssessmentService, register_risk_tool
from buildguard.schemas.common import BoundingBox, Severity
from buildguard.schemas.rag import RetrievedEvidence
from buildguard.schemas.vision import Detection, InspectionResult
from buildguard.security.audit import ToolAuditLogger
from buildguard.security.confirmation import ConfirmationManager
from buildguard.security.network_guard import NetworkGuard
from buildguard.security.path_guard import PathGuard
from buildguard.security.permission_engine import PermissionEngine
from buildguard.tools.executor import ToolExecutor
from buildguard.tools.registry import ToolRegistry
from buildguard.tools.schemas import ToolExecutionRequest
from buildguard.vision.base_detector import Detector
from buildguard.vision.http_detector import HttpLocalDetector
from buildguard.vision.local_detector import LocalDetectorAdapter
from buildguard.vision.mock_detector import MockDetector
from buildguard.vision.postprocessing import class_aware_nms, map_box_to_original
from buildguard.vision.preprocessing import decode_image, letterbox
from buildguard.vision.registry import VisionModelRegistry
from buildguard.vision.schemas import (
    BatchImageInspectionInput,
    SingleImageInspectionInput,
)
from buildguard.vision.service import VisionInspectionService, register_vision_tools


def write_image(path: Path, color: tuple[int, int, int] = (20, 100, 200)) -> None:
    image = np.full((120, 200, 3), color, dtype=np.uint8)
    ok, encoded = cv2.imencode(path.suffix, image)
    assert ok
    path.write_bytes(encoded.tobytes())


def model_config(**updates: Any) -> VisionModelConfig:
    values: dict[str, Any] = {
        "model_name": "mock-construction",
        "backend": "mock",
        "defect_classes": ["missing_helmet", "unsafe_edge", "exposed_wiring"],
        "input_size": (640, 640),
        "confidence_threshold": 0.35,
        "nms_iou": 0.5,
        "device": "cpu",
        "estimated_latency_ms": 10,
        "estimated_memory_mb": 32,
        "enabled": True,
    }
    values.update(updates)
    return VisionModelConfig.model_validate(values)


def vision_service(tmp_path: Path, seed: int = 42) -> VisionInspectionService:
    uploads = tmp_path / "uploads"
    visualizations = tmp_path / "workspace" / "events" / "images"
    uploads.mkdir(parents=True, exist_ok=True)
    config = VisionConfig(
        allowed_image_roots=[uploads],
        visualization_dir=visualizations,
        batch_max_items=10,
        requires_review_threshold=0.65,
        models=[model_config()],
    )
    registry = VisionModelRegistry.from_config(
        config,
        PermissionConfig(),
        seed=seed,
    )
    return VisionInspectionService(config, registry, PathGuard([uploads]))


def test_letterbox_coordinate_mapping() -> None:
    image = np.zeros((100, 200, 3), dtype=np.uint8)
    prepared, transform = letterbox(image, (640, 640))
    assert prepared.shape == (640, 640, 3)
    assert transform.scale == pytest.approx(3.2)
    assert transform.pad_y == 160
    mapped = map_box_to_original(
        BoundingBox(x1=32, y1=192, x2=320, y2=320),
        transform,
    )
    assert mapped == BoundingBox(x1=10, y1=10, x2=100, y2=50)
    assert map_box_to_original(
        BoundingBox(x1=10, y1=10, x2=20, y2=20),
        transform,
    ) is None


def test_class_aware_nms() -> None:
    detections = [
        Detection(
            label="missing_helmet",
            confidence=0.9,
            bounding_box=BoundingBox(x1=0, y1=0, x2=100, y2=100),
        ),
        Detection(
            label="missing_helmet",
            confidence=0.8,
            bounding_box=BoundingBox(x1=5, y1=5, x2=95, y2=95),
        ),
        Detection(
            label="unsafe_edge",
            confidence=0.7,
            bounding_box=BoundingBox(x1=5, y1=5, x2=95, y2=95),
        ),
    ]
    kept = class_aware_nms(detections, 0.5)
    assert len(kept) == 2
    assert {item.label for item in kept} == {"missing_helmet", "unsafe_edge"}
    assert kept[0].confidence == 0.9


def test_mock_detector_is_checksum_and_seed_deterministic(tmp_path: Path) -> None:
    image_path = tmp_path / "image.jpg"
    write_image(image_path)
    image = decode_image(image_path)
    detector = MockDetector(model_config(), seed=42)
    first = detector.predict(image)
    second = detector.predict(image)
    assert first == second
    assert all(item.source_model == "mock-construction" for item in first)
    different = MockDetector(model_config(), seed=43).predict(image)
    assert different != first


def test_local_and_http_adapters_require_explicit_formats(tmp_path: Path) -> None:
    model = tmp_path / "detector.onnx"
    model.write_bytes(b"placeholder")
    local = LocalDetectorAdapter(
        model_config(backend="local", model_path=model),
    )
    image_path = tmp_path / "image.png"
    write_image(image_path)
    with pytest.raises(ModelUnavailableError, match="explicit runner"):
        local.predict(decode_image(image_path))

    http_config = model_config(
        backend="http",
        endpoint="http://127.0.0.1:9000/predict",
    )
    http = HttpLocalDetector(
        http_config,
        NetworkGuard(["http://127.0.0.1:9000/predict"]),
        None,
        timeout_seconds=1,
        retry_attempts=1,
        retry_wait_seconds=0,
    )
    with pytest.raises(ModelUnavailableError, match="response adapter"):
        http.predict(decode_image(image_path))
    http.close()

    remote_config = model_config(
        backend="http",
        endpoint="https://api.example.com/predict",
    )
    with pytest.raises(EndpointSecurityError):
        HttpLocalDetector(
            remote_config,
            NetworkGuard(["https://api.example.com/predict"]),
            None,
            timeout_seconds=1,
            retry_attempts=1,
            retry_wait_seconds=0,
        )


def test_batch_continues_after_damaged_image(tmp_path: Path) -> None:
    service = vision_service(tmp_path)
    uploads = tmp_path / "uploads"
    valid = uploads / "valid.jpg"
    damaged = uploads / "damaged.jpg"
    write_image(valid)
    damaged.write_bytes(b"not an image")
    result = service.inspect_batch(
        BatchImageInspectionInput(
            image_paths=[valid, damaged],
            max_items=10,
        )
    )
    assert len(result.results) == 1
    assert result.results[0].summary.success
    assert len(result.failures) == 1
    assert result.failures[0].image_path == damaged.resolve()
    assert "damaged" in result.failures[0].error


def test_batch_service_uses_detector_batch_contract(tmp_path: Path) -> None:
    class BatchDetector(Detector):
        def __init__(self, config: VisionModelConfig) -> None:
            super().__init__(config)
            self.batch_calls = 0

        def predict(
            self,
            image: Any,
            requested_classes: list[str] | None = None,
        ) -> list[Detection]:
            return []

        def predict_batch(
            self,
            images: list[Any],
            requested_classes: list[str] | None = None,
        ) -> list[list[Detection]]:
            self.batch_calls += 1
            return [[] for _ in images]

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    first = uploads / "first.jpg"
    second = uploads / "second.jpg"
    write_image(first)
    write_image(second)
    config = VisionConfig(
        allowed_image_roots=[uploads],
        visualization_dir=tmp_path / "visualizations",
        models=[model_config(model_name="batch-detector")],
    )
    detector = BatchDetector(config.models[0])
    registry = VisionModelRegistry()
    registry.register(config.models[0], detector)
    service = VisionInspectionService(config, registry, PathGuard([uploads]))
    result = service.inspect_batch(
        BatchImageInspectionInput(image_paths=[first, second])
    )
    assert detector.batch_calls == 1
    assert len(result.results) == 2


def test_evidence_ids_are_stable_unique_and_visualized(tmp_path: Path) -> None:
    service = vision_service(tmp_path)
    image_path = tmp_path / "uploads" / "site.png"
    write_image(image_path)
    request = SingleImageInspectionInput(image_path=image_path)
    first = service.inspect_single(request)
    second = service.inspect_single(request)
    first_ids = [item.evidence_id for item in first.evidence]
    second_ids = [item.evidence_id for item in second.evidence]
    assert first_ids == second_ids
    assert len(first_ids) == len(set(first_ids))
    assert all(item.visualization_path.is_file() for item in first.evidence)
    assert first.summary.evidence_ids == first_ids


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.0, Severity.LOW),
        (0.299999, Severity.LOW),
        (0.30, Severity.NORMAL),
        (0.549999, Severity.NORMAL),
        (0.55, Severity.HIGH),
        (0.749999, Severity.HIGH),
        (0.75, Severity.CRITICAL),
        (1.0, Severity.CRITICAL),
    ],
)
def test_risk_boundaries(score: float, expected: Severity) -> None:
    assert risk_level(score) == expected


def test_risk_formula_and_no_llm_dependency() -> None:
    components = RiskComponents(severity=0.8, confidence=0.6, location=0.4, evidence=0.2)
    assert RiskScorer.score(components) == pytest.approx(
        0.35 * 0.8 + 0.15 * 0.6 + 0.20 * 0.4 + 0.10 * 0.2
    )
    service = RiskAssessmentService(
        RiskPolicyConfig(base_severity={"missing_helmet": 0.8})
    )
    detection = Detection(
        label="missing_helmet",
        confidence=0.9,
        bounding_box=BoundingBox(x1=10, y1=5, x2=50, y2=25),
        source_model="mock",
        attributes={
            "image_height": 100,
            "duration_seconds": 30,
            "repeat_count": 5,
        },
    )
    inspection = InspectionResult(
        source_path=Path("image.jpg"),
        detections=[detection],
        model_name="mock",
        processing_ms=1,
    )
    evidence = [
        RetrievedEvidence(
            document_id="doc",
            chunk_id="chunk",
            content="施工现场必须正确佩戴安全帽",
            score=0.7,
            source="standard.md",
        )
    ]
    first = service.assess(inspection, evidence)
    second = service.assess(inspection, evidence)
    assert first == second
    assert first.assessment.score == pytest.approx(
        0.35 * 0.8
        + 0.15 * 0.9
        + 0.20 * 0.8
        + 0.10 * 0.7
        + 0.10 * 0.5
        + 0.10 * 1.0
    )
    assert first.component_scores["duration"] == pytest.approx(0.5)
    assert first.component_scores["frequency"] == pytest.approx(1.0)
    assert not hasattr(service, "llm")
    assert "不受 LLM 影响" in first.assessment.summary


def test_batch_tool_summary_has_no_raw_boxes_and_audit(tmp_path: Path) -> None:
    service = vision_service(tmp_path)
    uploads = tmp_path / "uploads"
    valid = uploads / "valid.jpg"
    damaged = uploads / "damaged.jpg"
    write_image(valid)
    damaged.write_bytes(b"bad")
    registry = ToolRegistry()
    register_vision_tools(registry, service)
    register_risk_tool(
        registry,
        RiskAssessmentService(RiskPolicyConfig()),
    )
    confirmations = ConfirmationManager(ttl_seconds=60)
    audit_path = tmp_path / "audit.jsonl"
    writer = JsonlWriter(audit_path)
    executor = ToolExecutor(
        registry,
        PermissionEngine(confirmations),
        ToolAuditLogger(writer),
        retry_attempts=1,
    )
    request = ToolExecutionRequest(
        session_id="session",
        task_id="task",
        actor="tester",
        tool_name="inspect_image_batch",
        arguments={
            "image_paths": [str(valid), str(damaged)],
            "max_items": 10,
        },
    )
    pending = executor.execute(request)
    assert not pending.success
    confirmation_id = str(pending.output["confirmation_id"])  # type: ignore[index]
    confirmations.decide(confirmation_id, True)
    request.confirmation_id = confirmation_id
    completed = executor.execute(request)
    writer.close()
    assert completed.success
    serialized = json.dumps(completed.output)
    assert '"bbox"' not in serialized
    assert completed.output is not None
    assert len(completed.output["summaries"]) == 1
    assert len(completed.output["failed_images"]) == 1
    records = [
        json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()
    ]
    assert records[0]["execution_status"] == "pending_confirmation"
    assert records[1]["execution_status"] == "success"
    assert records[1]["confirmation_result"] == "approved"


def test_vision_config_validation() -> None:
    with pytest.raises(ValidationError, match="model_path"):
        model_config(backend="local", model_path=None)
    with pytest.raises(ValidationError, match="endpoint"):
        model_config(backend="http", endpoint=None)
    with pytest.raises(ValidationError, match="unique"):
        VisionConfig(models=[model_config(), model_config()])


def test_disabled_local_model_does_not_require_runtime_adapter(tmp_path: Path) -> None:
    disabled = model_config(
        model_name="disabled-local",
        backend="local",
        model_path=tmp_path / "not-installed.onnx",
        enabled=False,
    )
    config = VisionConfig(models=[disabled, model_config()])
    registry = VisionModelRegistry.from_config(config, PermissionConfig(), seed=42)
    assert [detector.name for detector in registry.enabled()] == ["mock-construction"]
    with pytest.raises(PermissionError, match="disabled"):
        registry.get("disabled-local")


def test_inspect_video_samples_frames_and_aggregates(tmp_path: Path) -> None:
    import cv2
    import numpy as np
    from uuid import uuid4
    from buildguard.agent.production_tools import (
        InspectVideoInput,
        VideoInspectionOutput,
        _register_compatibility_tools,
    )
    from buildguard.rag.service import RagService
    from buildguard.tools.registry import ToolRegistry

    # Build a tiny synthetic video: 30 frames, 10 fps, 640x480, solid green
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    video_path = uploads / "test.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(video_path), fourcc, 10.0, (640, 480))
    for _ in range(30):
        frame = np.full((480, 640, 3), (0, 200, 0), dtype=np.uint8)
        writer.write(frame)
    writer.release()

    # Build a VisionInspectionService backed by MockDetector (seed=42)
    svc = vision_service(tmp_path)

    # Build a minimal RagService stub — inspect_video does not use RAG
    rag = RagService.__new__(RagService)

    registry = ToolRegistry()
    _register_compatibility_tools(registry, svc, rag, advanced_rag=None, timeout_seconds=120)

    registered = registry.get("inspect_video")
    result = VideoInspectionOutput.model_validate(
        registered.handler(InspectVideoInput(video_path=video_path, sample_interval_seconds=1.0, max_frames=3))
    )

    assert result.total_frames_sampled == 3
    assert result.duration_seconds > 0
    assert len(result.frame_results) == 3
    assert isinstance(result.all_labels, list)
    assert isinstance(result.summary, str)
    assert "frames sampled" in result.summary
    # Temp frames must be cleaned up — no hidden files left in uploads
    assert not any(p.name.startswith(".video_frame_") for p in uploads.iterdir())
