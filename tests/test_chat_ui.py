from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from buildguard.api.app import create_app
from buildguard.api import routes_agent
from buildguard.config import load_settings
from buildguard.llm.mock_backend import MockLLMBackend
from buildguard.storage.models import ReportModel
from buildguard.ui.api_client import LocalApiClient
from buildguard.ui.chat import split_chat_attachments
from buildguard.ui.chat_state import (
    append_message,
    initialize_chat_state,
    record_result,
    reset_chat,
    select_session,
)
from buildguard.ui.view_models import normalize_agent_result, risk_summary
from buildguard.ui.workbench import WORKBENCH_PAGES


def _decode_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in text.strip().split("\n\n"):
        event = "message"
        data: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line.partition(":")[2].strip()
            elif line.startswith("data:"):
                data.append(line.partition(":")[2].strip())
        if data:
            events.append((event, json.loads("\n".join(data))))
    return events


def test_agent_chat_stream_preserves_task_identity(config_tree: Path) -> None:
    settings = load_settings(config_tree)
    client = TestClient(create_app(settings, MockLLMBackend()))

    response = client.post(
        "/agent/chat/stream",
        json={"message": "查看历史", "session_id": "stream-ui", "action": "history"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _decode_sse(response.text)
    assert [event for event, _ in events] == ["accepted", "phase", "complete"]
    accepted = events[0][1]
    completed = events[-1][1]
    assert completed["session_id"] == accepted["session_id"]
    assert completed["task_id"] == accepted["task_id"]
    assert completed["status"] == "completed"
    stored = client.get(f"/agent/tasks/{accepted['task_id']}")
    assert stored.status_code == 200


def test_graph_agent_chat_stream_uses_the_accepted_task_id(config_tree: Path) -> None:
    settings = load_settings(config_tree)
    settings.app.agent.confirmation_tools = []
    client = TestClient(create_app(settings, MockLLMBackend()))

    response = client.post(
        "/agent/chat/stream",
        json={"message": "simple local query", "session_id": "graph-stream-ui"},
    )

    events = _decode_sse(response.text)
    accepted = events[0][1]
    completed = events[-1][1]
    assert events[-1][0] == "complete"
    assert completed["task_id"] == accepted["task_id"]
    assert completed["status"] == "completed"


def test_chat_stream_sends_silent_keepalives_during_slow_local_work(
    config_tree: Path,
    monkeypatch: Any,
) -> None:
    settings = load_settings(config_tree)
    settings.app.agent.confirmation_tools = []
    application = create_app(settings, MockLLMBackend())
    original_chat = application.state.agent.chat

    def slow_chat(
        user_query: str,
        session_id: str | None = None,
        *,
        task_id: str | None = None,
    ) -> Any:
        time.sleep(0.04)
        return original_chat(user_query, session_id, task_id=task_id)

    monkeypatch.setattr(routes_agent, "CHAT_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(application.state.agent, "chat", slow_chat)
    client = TestClient(application)

    response = client.post(
        "/agent/chat/stream",
        json={"message": "slow local query", "session_id": "slow-stream-ui"},
    )

    events = _decode_sse(response.text)
    phases = [data for event, data in events if event == "phase"]
    assert len(phases) == 1
    assert phases[0]["message"] == "正在执行自动规划任务…"
    assert response.text.count(": keep-alive\n\n") >= 1
    assert events[-1][0] == "complete"


def test_agent_chat_stream_emits_safe_error(config_tree: Path) -> None:
    settings = load_settings(config_tree)
    client = TestClient(create_app(settings, MockLLMBackend()))

    response = client.post(
        "/agent/chat/stream",
        json={"message": "检查图片", "action": "inspect", "image_paths": []},
    )

    events = _decode_sse(response.text)
    assert [event for event, _ in events] == ["accepted", "phase", "error"]
    assert "requires at least one image_path" in events[-1][1]["message"]
    assert events[-1][1]["retryable"] is False


def test_confirmed_report_artifacts_can_be_downloaded(
    config_tree: Path,
    tmp_path: Path,
) -> None:
    settings = load_settings(config_tree)
    settings.app.data_dir = tmp_path / "data"
    settings.reporting.output_dir = tmp_path / "reports"
    application = create_app(settings, MockLLMBackend())
    memory = application.state.memory
    memory.ensure_session("download-session")
    report_path = application.state.workflow.reports.output_dir / "inspection.md"
    report_path.write_text("# Local report", encoding="utf-8")
    with application.state.database.session() as session:
        report = ReportModel(
            session_id="download-session",
            title="Inspection",
            report_type="inspection",
            output_path=str(report_path),
            summary="Local summary",
        )
        session.add(report)
        session.flush()
        report_id = report.id
    client = TestClient(application)

    response = client.get(f"/reports/{report_id}/download", params={"format": "md"})

    assert response.status_code == 200
    assert response.text == "# Local report"
    unavailable = client.get(
        f"/reports/{report_id}/download",
        params={"format": "pdf"},
    )
    assert unavailable.status_code == 404


def test_local_api_client_parses_server_sent_events() -> None:
    body = (
        'event: accepted\ndata: {"session_id":"s1","task_id":"t1"}\n\n'
        'event: phase\ndata: {"phase":"executing"}\n\n'
        'event: complete\ndata: {"status":"completed"}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/agent/chat/stream"
        assert request.extensions["timeout"]["read"] == 60
        return httpx.Response(
            200,
            text=body,
            headers={"content-type": "text/event-stream"},
        )

    api = LocalApiClient("http://127.0.0.1:8000")
    api.client.close()
    api.client = httpx.Client(
        base_url=api.base_url,
        transport=httpx.MockTransport(handler),
    )
    try:
        events = list(api.stream_chat({"message": "hello"}))
    finally:
        api.client.close()

    assert [item["event"] for item in events] == ["accepted", "phase", "complete"]
    assert events[0]["data"]["task_id"] == "t1"


def test_chat_state_transitions_keep_one_timeline() -> None:
    state: dict[str, Any] = {}
    initialize_chat_state(state)
    append_message(state, "user", "检查现场图片")
    record_result(
        state,
        {
            "session_id": "session-1",
            "task_id": "task-1",
            "status": "WAIT_FOR_CONFIRMATION",
            "final_response": "需要确认",
        },
    )

    assert [item["role"] for item in state["chat_messages"]] == ["user", "assistant"]
    assert state["active_session_id"] == "session-1"
    assert state["pending_confirmation"]["task_id"] == "task-1"

    select_session(state, "session-2")
    assert state["chat_messages"] == []
    assert state["loaded_session_id"] is None
    reset_chat(state)
    assert state["active_session_id"] is None
    assert state["attachment_generation"] == 1


def test_result_view_normalizes_evidence_risks_and_reports() -> None:
    view = normalize_agent_result(
        {
            "session_id": "s1",
            "task_id": "t1",
            "status": "completed",
            "final_response": "已完成",
            "risks": [{"severity": "high"}, {"severity": "high"}],
            "retrieved_chunks": [
                {"chunk_id": "c1", "source_path": "rules.md", "content": "依据"}
            ],
            "visual_evidence": [{"label": "helmet", "confidence": 0.9}],
            "report_path": "/reports/result.md",
            "html_path": "/reports/result.html",
        }
    )

    assert view.content == "已完成"
    assert view.citations[0]["chunk_id"] == "c1"
    assert view.report_paths == [
        ("Markdown", "/reports/result.md"),
        ("HTML", "/reports/result.html"),
    ]
    assert risk_summary(view.risks) == {"high": 2}


def test_chat_attachments_accept_images_or_one_video_but_not_mixed() -> None:
    class Upload:
        def __init__(self, name: str) -> None:
            self.name = name

    images, videos = split_chat_attachments([Upload("one.jpg"), Upload("two.png")])
    assert len(images) == 2
    assert videos == []
    images, videos = split_chat_attachments([Upload("inspection.mp4")])
    assert images == []
    assert len(videos) == 1
    with pytest.raises(ValueError, match="不能混合"):
        split_chat_attachments([Upload("one.jpg"), Upload("inspection.mp4")])
    with pytest.raises(ValueError, match="只支持一个视频"):
        split_chat_attachments([Upload("one.mp4"), Upload("two.mov")])


def test_sessions_use_first_message_titles_and_legacy_fallback(config_tree: Path) -> None:
    application = create_app(load_settings(config_tree), MockLLMBackend())
    client = TestClient(application)
    response = client.post(
        "/agent/chat",
        json={"message": "检查塔吊区域的施工安全风险"},
    )
    assert response.status_code == 200
    session_id = response.json()["session_id"]
    application.state.memory.ensure_session("legacy-session", "BuildGuard session")
    application.state.memory.add_message(
        "legacy-session",
        "user",
        "查询脚手架历史隐患",
    )

    sessions = {item["id"]: item for item in client.get("/sessions").json()}

    assert sessions[session_id]["title"] == (
        f"检查塔吊区域的施工安全风险 · {session_id[:6]}"
    )
    assert sessions["legacy-session"]["title"] == "查询脚手架历史隐患 · legacy"


def test_resolved_event_acknowledgement_returns_conflict_not_500(
    config_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = create_app(load_settings(config_tree), MockLLMBackend())

    def reject_resolved(_: str) -> None:
        raise ValueError("Event cannot be acknowledged from resolved")

    monkeypatch.setattr(
        application.state.camera_manager,
        "acknowledge_event",
        reject_resolved,
    )
    response = TestClient(application).post(
        "/events/resolved-event/acknowledge",
        params={"confirmed": True},
    )

    assert response.status_code == 409
    assert "resolved" in response.json()["detail"]


def test_sidebar_has_no_redundant_image_inspection_page() -> None:
    assert all("图片巡检" not in label for label in WORKBENCH_PAGES)
