"""Headless tests for the GUI application service."""

from __future__ import annotations

import pytest

import autoflow.config as config
from autoflow.gui import AutoFlowService


@pytest.fixture()
def gui_service(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOFLOW_HOME", str(tmp_path / "autoflow-home"))
    config._settings = None
    yield AutoFlowService()
    config._settings = None


def test_gui_service_full_lifecycle(gui_service):
    messages: list[str] = []
    bundle = gui_service.create_task(
        "在表单中填写内容并提交",
        task_name="GUI smoke test",
        use_mock=True,
        params={"note_content": "来自 GUI 的内容"},
        progress=messages.append,
    )

    assert bundle.metadata["backend"] == "mock"
    assert len(bundle.steps) == 3
    assert gui_service.get_task(bundle.task_id).goal == bundle.goal
    assert any(entry["task_id"] == bundle.task_id for entry in gui_service.list_tasks())
    assert any("已注册" in message for message in messages)

    result = gui_service.run_task(
        bundle.task_id,
        params={"note_content": "复查"},
    )
    assert result.status == "success"
    assert len(result.steps) == 3

    repaired = gui_service.repair_task(bundle.task_id)
    assert repaired.version == 2
    assert gui_service.get_task(bundle.task_id).version == 2


def test_gui_service_rejects_empty_task(gui_service):
    with pytest.raises(ValueError, match="请输入任务描述"):
        gui_service.create_task("   ")
