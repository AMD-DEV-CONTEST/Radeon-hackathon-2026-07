"""内存 Mock 录制后端。

用于测试和演示核心链路 (不依赖 Playwright / 浏览器)。
模拟一个简单的"表单提交" Web 页面状态机：
- 元素池: {text, semantic} -> element
- 点击/输入会改变内部状态，供后置验证使用。
"""

from __future__ import annotations

from typing import Any

from autoflow.capture.base import CaptureBackend
from autoflow.models import Recording


class MockBackend(CaptureBackend):
    """内存态 Mock 后端，模拟可交互元素。

    元素池包含两个目标：
    - "表单输入框": 可输入
    - "提交按钮" (text=Submit): 点击后置 submitted=True
    """

    def __init__(self) -> None:
        self.submitted = False
        self.input_text = ""
        self.started = False

    def start(self, recording: Recording) -> None:
        self.started = True
        self.submitted = False
        self.input_text = ""

    def locate(self, hint: dict[str, Any]) -> Any:
        text = hint.get("expected_text", "")
        semantic = hint.get("semantic_hint", "")

        if "Submit" in text or "提交" in semantic:
            return {"id": "submit", "text": "Submit"}
        if "输入" in semantic or "文本框" in semantic or semantic in ("表单输入框", ""):
            return {"id": "input", "text": ""}
        return None

    def do(self, action: str, element: Any = None, **kwargs: Any) -> Any:
        if action == "click":
            if element and element["id"] == "submit":
                self.submitted = True
            return None
        if action == "type":
            if element and element["id"] == "input":
                self.input_text = kwargs.get("text", "")
            return None
        if action in ("wait", "press", "hotkey"):
            return None
        raise ValueError(f"不支持的 action: {action}")

    def snapshot(self) -> dict[str, Any]:
        return {
            "screen": None,
            "title": "Demo",
            "url": "mock://form",
            "state": {"submitted": self.submitted, "input": self.input_text},
        }

    def stop(self) -> None:
        self.started = False
