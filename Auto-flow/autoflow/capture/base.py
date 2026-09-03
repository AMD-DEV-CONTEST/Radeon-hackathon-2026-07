"""Capture 后端抽象接口。

MVP 阶段默认使用 Web (Playwright)。定义统一接口以便未来扩展 Desktop (UI Automation)。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from autoflow.models import Recording


class CaptureBackend(ABC):
    """录制后端抽象基类。"""

    @abstractmethod
    def start(self, recording: Recording) -> None:
        """开始录制会话。"""

    @abstractmethod
    def locate(self, hint: dict[str, Any]) -> Any:
        """根据语义提示定位目标元素。

        Args:
            hint: 来自 PlanStep.target_evidence 的字典。

        Returns:
            定位到的元素句柄；找不到返回 None。
        """

    @abstractmethod
    def do(self, action: str, element: Any | None = None, **kwargs: Any) -> Any:
        """执行一个 UI 动作 (click / type / press / wait / hotkey)。"""

    @abstractmethod
    def snapshot(self) -> dict[str, Any]:
        """采集当前状态 (截图路径 / UI树 / OCR文字)。

        Returns:
            dict，包含 screen 等字段，供录制事件使用。
        """

    @abstractmethod
    def stop(self) -> None:
        """停止录制会话，释放资源。"""
