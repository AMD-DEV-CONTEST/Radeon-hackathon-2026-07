"""Capture: 录制与执行层。

- base:    抽象录制后端接口 (Web / Desktop)
- web:     Playwright 实现的 Web 录制执行器
- agent:   Computer Use Agent (按 TaskPlan 驱动录制执行)
"""

from autoflow.capture.base import CaptureBackend
from autoflow.capture.agent import ComputerUseAgent

__all__ = ["CaptureBackend", "ComputerUseAgent"]
