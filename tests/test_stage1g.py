from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from buildguard.api.app import create_app
from buildguard.config import (
    RagConfig,
    RealtimeConfig,
    ReportingConfig,
    ServiceConfig,
    TemporalRuleConfig,
    VisionConfig,
    VisionModelConfig,
    load_settings,
)
from buildguard.integration.service import MvpChatInput
from buildguard.llm.mock_backend import MockLLMBackend
from buildguard.rag.schemas import DocumentChunk
from buildguard.realtime.schemas import EventCandidate, VideoFrame
from buildguard.realtime.temporal_confirmation import MOfNConfirmation
from buildguard.realtime.tracker import SimpleIoUTracker
from buildguard.reporting.builder import ReportBuilder, ReportInput
from buildguard.reporting.citation_validator import CitationStatement, CitationValidator
from buildguard.schemas.common import BoundingBox, Severity
from buildguard.schemas.vision import Detection, RiskAssessment
from buildguard.storage.database import Database
from buildguard.storage.memory import LongTermMemory
from buildguard.utils.time import utc_now


def _write_image(path: Path, value: int = 100) -> None:
    image = np.full((120, 180, 3), value, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    path.write_bytes(encoded.tobytes())


def _settings(config_tree: Path, tmp_path: Path) -> tuple[object, Path, Path]:
    settings = load_settings(config_tree)
    workspace = tmp_path / "workspace"
    uploads = workspace / "uploads"
    knowledge = workspace / "knowledge"
    uploads.mkdir(parents=True)
    knowledge.mkdir(parents=True)
    settings.app.workspace_dir = workspace
    settings.app.database_path = workspace / "database" / "buildguard.db"
    settings.rag = RagConfig(
        embedding_mode="mock",
        reranker_mode="mock",
        index_dir=workspace / "indexes" / "rag",
        allowed_source_roots=[knowledge],
        chunk_min_chars=100,
        chunk_max_chars=300,
        chunk_overlap_chars=20,
        min_top_score=0,
        min_keyword_coverage=0,
    )
    settings.vision = VisionConfig(
        allowed_image_roots=[uploads],
        visualization_dir=workspace / "events" / "images",
        models=[
            VisionModelConfig(
                model_name="stage1g-mock",
                backend="mock",
                defect_classes=["missing_helmet", "unsafe_edge"],
                input_size=(320, 320),
                confidence_threshold=0.3,
                nms_iou=0.5,
                device="cpu",
            )
        ],
        risk=settings.vision.risk.model_copy(
            update={"base_severity": {"missing_helmet": 0.9, "unsafe_edge": 0.8}}
        ),
    )
    settings.realtime = RealtimeConfig(
        allowed_video_roots=[workspace / "cameras"],
        event_image_dir=workspace / "events" / "images",
        event_clip_dir=workspace / "events" / "clips",
    )
    settings.reporting = ReportingConfig(output_dir=workspace / "reports")
    return settings, uploads, knowledge


def _chunk(source: Path) -> DocumentChunk:
    return DocumentChunk(
        chunk_id="a" * 64,
        document_name="施工安全标准",
        source_path=source,
        document_checksum="b" * 64,
        page=3,
        article="第一条",
        title="临边防护",
        content="临边作业应设置可靠防护栏杆，并由现场负责人复核。",
    )


def test_citation_validation_and_confirmed_report_export(tmp_path: Path) -> None:
    source = tmp_path / "standard.pdf"
    source.write_bytes(b"fixture")
    chunk = _chunk(source)
    valid = CitationStatement(
        chunk_id=chunk.chunk_id,
        standard_name=chunk.document_name,
        source_path=source,
        page=3,
        article="第一条",
        quoted_content="临边作业应设置可靠防护栏杆",
    )
    invalid = valid.model_copy(update={"page": 4})
    validation = CitationValidator().validate([valid, invalid], [chunk])
    assert validation[0].valid
    assert not validation[1].valid
    builder = ReportBuilder(
        ReportingConfig(output_dir=tmp_path / "reports"),
        MockLLMBackend(),
    )
    draft = builder.build(
        ReportInput(
            task_id=str(uuid4()),
            session_id=str(uuid4()),
            title="测试报告",
            sources=["camera-1"],
            findings=["缺少安全帽"],
            risks=[
                RiskAssessment(
                    severity=Severity.HIGH,
                    score=0.7,
                    summary="确定性评分",
                )
            ],
            retrieved_chunks=[chunk],
            citation_statements=[valid, invalid],
        )
    )
    assert draft.verified_citation_count == 1
    with pytest.raises(PermissionError, match="confirmation"):
        builder.export(draft, confirmed=False)
    artifact = builder.export(draft, confirmed=True)
    assert artifact.markdown_path.is_file()
    assert artifact.html_path.is_file()
    assert not artifact.pdf.available
    assert "第 3 页" in artifact.markdown_path.read_text(encoding="utf-8")
    assert "第 4 页" not in artifact.markdown_path.read_text(encoding="utf-8")


def test_markdown_chunk_citation_does_not_require_fake_page(tmp_path: Path) -> None:
    source = tmp_path / "local-standard.md"
    source.write_text("# 临边防护\n必须设置可靠防护栏杆。", encoding="utf-8")
    chunk = DocumentChunk(
        chunk_id="c" * 64,
        document_name="本地施工标准",
        source_path=source,
        document_checksum="d" * 64,
        title="临边防护",
        content="必须设置可靠防护栏杆。",
    )
    statement = CitationStatement(
        chunk_id=chunk.chunk_id,
        standard_name=chunk.document_name,
        source_path=source,
        quoted_content="必须设置可靠防护栏杆",
    )
    validation = CitationValidator().validate([statement], [chunk])
    assert validation[0].valid


def test_sqlite_long_term_memory_and_risk_filter(tmp_path: Path) -> None:
    memory = LongTermMemory(Database(tmp_path / "memory.db"))
    session_id = str(uuid4())
    low = memory.create_task(
        session_id,
        "low",
        "low task",
        status="completed",
        result={"max_risk": "low", "inspections": [{"id": "fixture"}]},
    )
    high = memory.create_task(
        session_id,
        "high",
        "high task",
        status="completed",
        result={"max_risk": "high", "inspections": [{"id": "fixture"}]},
    )
    assert memory.get_task(low.id) is not None
    assert [item.id for item in memory.list_tasks(risk="high")] == [high.id]
    assert memory.previous_completed(session_id) is not None
    assert high.created_at.tzinfo is not None


def test_three_turn_workflow_reuses_visual_result(config_tree: Path, tmp_path: Path) -> None:
    settings, uploads, knowledge = _settings(config_tree, tmp_path)
    image = uploads / "inspection.png"
    _write_image(image)
    standard = knowledge / "standard.txt"
    standard.write_text("安全帽 临边 防护栏杆 现场复核。" * 30, encoding="utf-8")
    application = create_app(settings, MockLLMBackend())
    workflow = application.state.workflow
    application.state.rag.ingest(standard)
    first = workflow.chat(
        MvpChatInput(message="分析图片", action="inspect", image_paths=[image])
    )
    count = workflow.vision_inference_count
    second = workflow.chat(
        MvpChatInput(
            message="只展开高风险",
            action="high_risk",
            session_id=first["session_id"],
        )
    )
    third = workflow.chat(
        MvpChatInput(
            message="生成报告",
            action="report",
            session_id=first["session_id"],
        )
    )
    assert first["status"] == "completed"
    assert second["new_inference_count"] == 0
    assert third["status"] == "WAIT_FOR_CONFIRMATION"
    assert workflow.vision_inference_count == count == 1
    confirmed = workflow.confirm(str(third["task_id"]), True)
    assert confirmed["status"] == "completed"
    assert Path(str(confirmed["report_path"])).is_file()
    assert workflow.vision_inference_count == 1


def test_report_rejection_writes_no_file(config_tree: Path, tmp_path: Path) -> None:
    settings, uploads, _ = _settings(config_tree, tmp_path)
    image = uploads / "reject.png"
    _write_image(image)
    workflow = create_app(settings, MockLLMBackend()).state.workflow
    first = workflow.chat(
        MvpChatInput(message="inspect", action="inspect", image_paths=[image])
    )
    pending = workflow.chat(
        MvpChatInput(
            message="report",
            action="report",
            session_id=first["session_id"],
        )
    )
    rejected = workflow.confirm(str(pending["task_id"]), False)
    assert rejected["status"] == "safe_failure"
    assert not list(settings.reporting.output_dir.glob("*.md"))


def test_mvp_api_routes_and_metrics(config_tree: Path, tmp_path: Path) -> None:
    settings, uploads, _ = _settings(config_tree, tmp_path)
    image = uploads / "api.png"
    _write_image(image)
    client = TestClient(create_app(settings, MockLLMBackend()))
    first = client.post(
        "/agent/chat",
        json={
            "message": "分析图片",
            "action": "inspect",
            "image_paths": [str(image)],
        },
    )
    assert first.status_code == 200
    session_id = first.json()["session_id"]
    followup = client.post(
        "/agent/chat",
        json={
            "message": "只展开高风险",
            "session_id": session_id,
        },
    )
    assert followup.status_code == 200
    assert followup.json()["new_inference_count"] == 0
    assert client.get("/tasks").status_code == 200
    assert client.get(f"/tasks/{first.json()['task_id']}").status_code == 200
    assert client.get("/reports").status_code == 200
    assert client.get("/events").status_code == 200
    assert client.get("/cameras").status_code == 200
    assert client.get("/runtime/metrics").json()["process"]["rss_bytes"] > 0
    assert client.get("/audit").status_code == 200
    assert client.get("/health").json()["database"] is True


def test_image_api_runs_complete_agent_loop_and_persists_reportable_facts(
    config_tree: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, uploads, knowledge = _settings(config_tree, tmp_path)
    image = uploads / "agent-loop.png"
    _write_image(image)
    standard = knowledge / "helmet-standard.txt"
    standard.write_text("安全帽 施工安全规范 现场复核。" * 30, encoding="utf-8")
    application = create_app(settings, MockLLMBackend())
    application.state.rag.ingest(standard)

    def reject_mvp_bypass(_: object) -> dict[str, object]:
        raise AssertionError("image chat must not bypass the Agent graph")

    monkeypatch.setattr(application.state.workflow, "chat", reject_mvp_bypass)
    client = TestClient(application)

    response = client.post(
        "/agent/chat",
        json={
            "message": "检查图片，分析风险并给出规范依据",
            "image_paths": [str(image)],
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "completed"
    assert result["intent"]["category"] == "inspection"
    assert result["inspection_analysis"]["search_standards"] is True
    assert result["tool_chain"] == [
        "inspect_single_image",
        "search_construction_standards",
        "assess_risk",
    ]
    assert len(result["inspections"]) == 1
    assert len(result["risks"]) == 1
    assert result["grounding_result"] is not None
    stored = application.state.memory.get_task(result["task_id"])
    assert stored is not None
    assert stored.result["inspections"]
    assert stored.result["risks"]
    assert stored.result["agent_state"]["inspection_analysis"] is not None


def test_agent_generated_report_reuses_persisted_agent_inspection(
    config_tree: Path,
    tmp_path: Path,
) -> None:
    settings, uploads, _ = _settings(config_tree, tmp_path)
    image = uploads / "agent-report.png"
    _write_image(image)
    client = TestClient(create_app(settings, MockLLMBackend()))
    inspected = client.post(
        "/agent/chat",
        json={"message": "检查图片", "image_paths": [str(image)]},
    ).json()

    pending = client.post(
        "/agent/chat",
        json={
            "message": "生成巡检报告",
            "action": "report",
            "session_id": inspected["session_id"],
        },
    ).json()
    assert pending["status"] == "WAIT_FOR_CONFIRMATION"

    confirmed = client.post(
        "/agent/confirm",
        json={"task_id": pending["task_id"], "approved": True},
    )
    assert confirmed.status_code == 200
    result = confirmed.json()
    assert result["status"] == "completed"
    assert Path(result["report_path"]).is_file()
    assert Path(result["html_path"]).is_file()


def test_twenty_repeated_inspections_are_stable_and_reused(
    config_tree: Path,
    tmp_path: Path,
) -> None:
    settings, uploads, _ = _settings(config_tree, tmp_path)
    image = uploads / "stable.png"
    _write_image(image, 77)
    workflow = create_app(settings, MockLLMBackend()).state.workflow
    session_id = str(uuid4())
    results = [
        workflow.chat(
            MvpChatInput(
                message=f"inspection {index}",
                action="inspect",
                session_id=session_id,
                image_paths=[image],
            )
        )
        for index in range(20)
    ]
    assert all(item["status"] == "completed" for item in results)
    assert results[0]["new_inference_count"] == 1
    assert all(item["new_inference_count"] == 0 for item in results[1:])
    assert workflow.vision_inference_count == 1


def test_service_configuration_blocks_remote_bind() -> None:
    with pytest.raises(ValidationError, match="loopback"):
        ServiceConfig(api_host="0.0.0.0")
    assert ServiceConfig(api_host="127.0.0.1").api_port == 8000


def test_synthetic_video_event_to_confirmed_report(
    config_tree: Path,
    tmp_path: Path,
) -> None:
    settings, _, _ = _settings(config_tree, tmp_path)
    application = create_app(settings, MockLLMBackend())
    tracker = SimpleIoUTracker(iou_threshold=0.3, max_age=2, minimum_hits=1)
    detection = Detection(
        label="emergency",
        confidence=0.95,
        bounding_box=BoundingBox(x1=10, y1=10, x2=50, y2=70),
        source_model="synthetic-video-detector",
    )
    tracked = tracker.update([detection], frame_index=0)[0]
    confirmation = MOfNConfirmation(
        {"emergency": TemporalRuleConfig(m=1, n=2, alpha=0.6)}
    ).update("emergency", tracked.track_id, detected=True, confidence=0.95)
    frame = VideoFrame(
        camera_id="synthetic-camera",
        sequence=0,
        captured_at=utc_now(),
        source_time_seconds=0,
        image=np.full((90, 120, 3), 120, dtype=np.uint8),
        key_frame=True,
    )
    event = application.state.camera_manager.event_engine.process(
        EventCandidate(
            camera_id="synthetic-camera",
            event_type="emergency",
            track_id=tracked.track_id,
            bbox=tracked.bbox,
            confidence=confirmation.smoothed_confidence,
            confirmed=confirmation.confirmed,
            frame=frame,
            detections=[tracked],
        )
    )
    assert event.status.value == "active"
    client = TestClient(application)
    pending = client.post(
        "/agent/chat",
        json={
            "message": "生成实时事件报告",
            "action": "event_report",
            "session_id": str(uuid4()),
        },
    )
    assert pending.status_code == 200
    assert pending.json()["event_ids"] == [event.id]
    confirmed = client.post(
        "/agent/confirm",
        json={"task_id": pending.json()["task_id"], "approved": True},
    )
    assert confirmed.status_code == 200
    assert Path(confirmed.json()["report_path"]).is_file()
