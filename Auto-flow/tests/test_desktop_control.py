"""Tests for the real desktop automation product layer."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from autoflow.desktop_control import DesktopTaskStore, pyautogui_key, serialize_key
from autoflow.webapp import AutomationController


class FakeRecorder:
    def __init__(self) -> None:
        self.stopped = threading.Event()

    def start(self) -> None:
        return

    def stop(self):
        self.stopped.set()
        return {
            "duration": 1.2,
            "screen": {"width": 1920, "height": 1080},
            "events": [
                {"t": 0.1, "type": "mouse_down", "x": 100, "y": 80, "button": "left"},
                {"t": 0.2, "type": "mouse_up", "x": 100, "y": 80, "button": "left"},
            ],
        }

    def wait_stopped(self, timeout=None):
        return self.stopped.wait(timeout)


class FakeReplayer:
    def __init__(self) -> None:
        self.stop_called = False

    def run(self, task, *, speed=1.0, progress=None):
        assert task["events"]
        assert speed == 1.0
        if progress:
            progress("执行完成")

    def stop(self):
        self.stop_called = True


def wait_until_idle(controller: AutomationController) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if controller.state()["mode"] == "idle":
            return
        time.sleep(0.01)
    raise AssertionError("controller did not return to idle")


def test_desktop_task_store_lifecycle(tmp_path):
    store = DesktopTaskStore(tmp_path / "tasks")
    task = store.save(
        {
            "duration": 2.5,
            "screen": {"width": 1920, "height": 1080},
            "events": [{"t": 0.1, "type": "scroll", "x": 1, "y": 2, "dy": -1}],
        },
        "填写日报",
    )

    assert task["id"].startswith("desktop_")
    assert store.list()[0]["event_count"] == 1
    assert store.rename(task["id"], "提交日报")["name"] == "提交日报"
    store.mark_run(task["id"])
    assert store.get(task["id"])["run_count"] == 1
    store.delete(task["id"])
    assert store.list() == []


def test_controller_record_and_run(tmp_path):
    store = DesktopTaskStore(tmp_path / "tasks")
    controller = AutomationController(
        store=store,
        recorder_factory=FakeRecorder,
        replayer_factory=FakeReplayer,
    )

    assert controller.start_recording("整理文件")["mode"] == "recording"
    stopped = controller.stop_recording()
    assert stopped["mode"] == "idle"
    assert len(stopped["tasks"]) == 1

    task_id = stopped["tasks"][0]["id"]
    assert controller.run_task(task_id)["mode"] == "running"
    wait_until_idle(controller)
    assert store.get(task_id)["run_count"] == 1


def test_key_serialization_and_mapping():
    assert serialize_key(SimpleNamespace(char="a")) == {"kind": "char", "value": "a"}
    assert serialize_key(SimpleNamespace(char=None, name="enter")) == {
        "kind": "special",
        "value": "enter",
    }
    assert pyautogui_key({"kind": "special", "value": "ctrl_l"}) == "ctrl"
    assert pyautogui_key({"kind": "special", "value": "page_down"}) == "pgdn"


def test_store_rejects_path_traversal(tmp_path):
    store = DesktopTaskStore(tmp_path / "tasks")
    with pytest.raises(ValueError, match="无效"):
        store.get("../../secret")
