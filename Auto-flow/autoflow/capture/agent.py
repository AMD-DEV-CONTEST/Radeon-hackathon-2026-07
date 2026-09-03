"""Computer Use Agent: 首次执行的核心编排器。

职责：
1. 按 TaskPlan 逐步定位目标并执行动作
2. 每步执行前后采集截图/状态写入 Recording
3. 执行后校验 postcondition (轻量级)
4. 返回带实际结果的 TaskPlan (供编译器使用)

MVP 阶段：Agent 按 Planner 提供的语义提示驱动 WebBackend。
真实 AI Computer Use 模式 (截图->VLM->点击) 通过 computer_use_enabled 开关预留，
后续可接入 Anthropic/OpenAI 的 Computer Use API。
"""

from __future__ import annotations

from typing import Any

from autoflow.capture.base import CaptureBackend
from autoflow.config import get_settings
from autoflow.models import PlanStep, Recording, TaskPlan


class ComputerUseAgent:
    """按 TaskPlan 执行并录制。"""

    def __init__(self, backend: CaptureBackend, recording: Recording) -> None:
        self.backend = backend
        self.recording = recording
        self.settings = get_settings()

    def execute(self, plan: TaskPlan, params: dict[str, Any] | None = None) -> TaskPlan:
        """执行整个 TaskPlan，返回带实际结果的 plan。

        Args:
            plan: 待执行的任务计划。
            params: 注入的动态参数 (如 {note_content: "xxx"})。

        Raises:
            RuntimeError: 任一步骤执行失败。
        """
        params = params or {}
        self.backend.start(self.recording)
        try:
            for step in plan.steps:
                self._execute_step(step, params)
        finally:
            # 执行结束采集最终状态
            self.recording.add_event("frame", self.backend.snapshot())
            self.backend.stop()
        return plan

    def _execute_step(self, step: PlanStep, params: dict[str, Any]) -> None:
        """执行单个步骤并录制。"""
        # 步骤前快照
        before = self.backend.snapshot()
        self.recording.add_event("frame", {"before_step": step.step_index, **before})

        hint = step.target_evidence.model_dump(exclude_none=True)

        # 1. 定位目标
        element = self.backend.locate(hint)

        # 2. 注入参数
        action_params = dict(step.parameters)
        for key, value in action_params.items():
            if isinstance(value, str):
                action_params[key] = self._inject(value, params)

        # 3. 执行动作
        try:
            self.backend.do(step.action.value, element=element, **action_params)
        except Exception as exc:
            raise RuntimeError(
                f"步骤 {step.step_index} ({step.description}) 执行失败: {exc}"
            ) from exc

        # 4. 动作后快照
        after = self.backend.snapshot()
        self.recording.add_event(
            "action",
            {
                "step_index": step.step_index,
                "action": step.action.value,
                "description": step.description,
                "hint": hint,
                "params": action_params,
                "before_screen": before.get("screen"),
                "after_screen": after.get("screen"),
            },
        )

        # 5. 记录实际结果 (供编译器生成后置验证)
        step.actual_result = {
            "after_screen": after.get("screen"),
            "page_title": after.get("title"),
            "url": after.get("url"),
        }

    @staticmethod
    def _inject(text: str, params: dict[str, Any]) -> str:
        """把 {slot} 形式的参数占位替换为实际值。"""
        if not params:
            return text
        for key, value in params.items():
            placeholder = "{" + key + "}"
            if placeholder in text:
                text = text.replace(placeholder, str(value))
        return text
