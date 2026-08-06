"""Offline deterministic MVP smoke workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from buildguard.api.app import create_app
from buildguard.config import Settings
from buildguard.integration.service import MvpChatInput
from buildguard.llm.mock_backend import MockLLMBackend


def _write_fixture_image(path: Path) -> None:
    image = np.full((160, 240, 3), (40, 120, 180), dtype=np.uint8)
    cv2.rectangle(image, (60, 30), (180, 145), (0, 0, 255), 3)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("Could not encode deterministic smoke image")
    path.write_bytes(encoded.tobytes())


def run_smoke(settings: Settings) -> dict[str, Any]:
    """Exercise image, RAG, risk, memory, confirmation, and report offline."""
    application = create_app(settings, MockLLMBackend(seed=settings.app.seed))
    workflow = application.state.workflow
    rag = application.state.rag
    uploads = settings.vision.allowed_image_roots[0].resolve()
    knowledge = settings.rag.allowed_source_roots[0].resolve()
    uploads.mkdir(parents=True, exist_ok=True)
    knowledge.mkdir(parents=True, exist_ok=True)
    image_path = uploads / "buildguard-smoke.png"
    standard_path = knowledge / "buildguard-smoke-standard.txt"
    _write_fixture_image(image_path)
    standard_path.write_text(
        "施工现场安全检查规范 第一条 临边作业应设置可靠防护栏杆并进行人工复核。"
        "发现未佩戴安全帽、危险区域侵入或裸露线路时，应记录图像证据并及时整改。"
        * 8,
        encoding="utf-8",
    )
    rag.ingest(standard_path, project="smoke")
    first = workflow.chat(
        MvpChatInput(
            message="分析固定目录中的测试图片",
            action="inspect",
            image_paths=[image_path],
        )
    )
    session_id = str(first["session_id"])
    count_after_first = workflow.vision_inference_count
    second = workflow.chat(
        MvpChatInput(
            message="只展开高风险",
            session_id=session_id,
            action="high_risk",
        )
    )
    third = workflow.chat(
        MvpChatInput(
            message="生成报告",
            session_id=session_id,
            action="report",
        )
    )
    confirmed = workflow.confirm(str(third["task_id"]), True)
    no_repeat = workflow.vision_inference_count == count_after_first
    report_path = Path(str(confirmed["report_path"]))
    return {
        "ok": (
            first["status"] == "completed"
            and second["status"] == "completed"
            and third["status"] == "WAIT_FOR_CONFIRMATION"
            and confirmed["status"] == "completed"
            and no_repeat
            and report_path.is_file()
        ),
        "session_id": session_id,
        "inspection_task_id": first["task_id"],
        "report_task_id": third["task_id"],
        "report_path": str(report_path),
        "vision_inference_count": workflow.vision_inference_count,
        "followup_reused_without_inference": no_repeat,
        "mock_only": True,
    }
