"""Task Planner 实现。

职责：将自然语言任务描述转换为结构化 TaskPlan (JSON)。
- LLM 模式:    使用 Function Calling / JSON 输出生成计划
- Mock 模式:   无 API key 时用本地规则生成一个示例计划，用于演示链路
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from autoflow.config import get_settings
from autoflow.llm import LLMClient
from autoflow.models import (
    ActionType,
    PlanStep,
    RiskLevel,
    TargetEvidence,
    TaskPlan,
)

PLANNER_SYSTEM_PROMPT = """你是 UI 自动化任务规划器。把用户的自然语言任务转换为结构化的 JSON 任务计划。

要求：
1. 将任务分解为最小可执行的 UI 操作步骤
2. 每步必须给出语义定位提示 (semantic_hint / expected_text / expected_location)
3. 标记风险等级：不可逆操作 (如提交/删除) 标记为 high
4. 识别动态参数 (如用户名、金额、日期)，放入 parameters
5. 输出严格的 JSON，不要包含多余文字

输出格式 (JSON Schema):
{
  "task_id": "task_xxx",
  "goal": "任务一句话描述",
  "parameters": {"参数名": {"type": "string", "default": "默认值", "description": "说明"}},
  "steps": [
    {
      "step_index": 0,
      "action": "click | type | press | wait | hotkey",
      "description": "步骤描述",
      "target_evidence": {
        "semantic_hint": "目标控件语义",
        "expected_text": "期望文字",
        "expected_location": "期望位置"
      },
      "parameters": {"text": "输入内容或{参数槽}"},
      "postcondition": "操作后的期望状态",
      "risk_level": "low | medium | high",
      "reversible": true
    }
  ],
  "global_verification": {"type": "api_oracle", "description": "全局验证方式"}
}"""


class TaskPlanner:
    """基于 LLM 的任务规划器。"""

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient()
        self.settings = get_settings()

    def plan(self, user_input: str, context: dict[str, Any] | None = None) -> TaskPlan:
        if not self.client.available:
            raise RuntimeError(
                "未配置 LLM API key，无法使用 LLM 规划器。"
                "请设置 AUTOFLOW_LLM_API_KEY，或使用 mock 模式。"
            )

        user_prompt = json.dumps(
            {"user_input": user_input, "context": context or {}},
            ensure_ascii=False,
        )
        raw = self.client.chat_json(
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_format={"type": "json_object"},
        )
        return self._validate(raw, user_input)

    def _validate(self, raw: dict[str, Any], user_input: str) -> TaskPlan:
        steps = []
        for s in raw.get("steps", []):
            evidence = s.get("target_evidence", {})
            steps.append(
                PlanStep(
                    step_index=s.get("step_index", len(steps)),
                    action=ActionType(s.get("action", "click")),
                    description=s.get("description", ""),
                    target_evidence=TargetEvidence(
                        semantic_hint=evidence.get("semantic_hint", ""),
                        expected_text=evidence.get("expected_text"),
                        expected_location=evidence.get("expected_location"),
                    ),
                    parameters=s.get("parameters", {}),
                    postcondition=s.get("postcondition", ""),
                    risk_level=RiskLevel(s.get("risk_level", "low")),
                    reversible=s.get("reversible", True),
                )
            )
        return TaskPlan(
            task_id=raw.get("task_id") or f"task_{uuid.uuid4().hex[:6]}",
            goal=raw.get("goal") or user_input,
            steps=steps,
            parameters=raw.get("parameters", {}),
            global_verification=raw.get("global_verification"),
            context=raw.get("context", {}),
        )


class MockPlanner:
    """无 API key 时的本地规划器，用于演示链路。

    根据任务关键词生成一个示例计划 (演示: 在 Web 表单中填写并提交)。
    真实场景下应替换为 LLM 模式。
    """

    def __init__(self) -> None:
        pass

    def plan(self, user_input: str, context: dict[str, Any] | None = None) -> TaskPlan:
        context = context or {"app_name": "Demo App", "backend": "web"}
        task_id = f"task_{uuid.uuid4().hex[:6]}"

        steps = [
            PlanStep(
                step_index=0,
                action=ActionType.CLICK,
                description="点击输入框聚焦",
                target_evidence=TargetEvidence(
                    semantic_hint="表单输入框",
                    expected_location="页面表单第一项",
                ),
                postcondition="输入框获得焦点",
                risk_level=RiskLevel.LOW,
                reversible=True,
            ),
            PlanStep(
                step_index=1,
                action=ActionType.TYPE,
                description="输入表单内容",
                target_evidence=TargetEvidence(
                    semantic_hint="表单输入框",
                ),
                parameters={"text": "{note_content}"},
                postcondition="输入框显示内容",
                risk_level=RiskLevel.LOW,
                reversible=True,
            ),
            PlanStep(
                step_index=2,
                action=ActionType.CLICK,
                description="点击提交按钮",
                target_evidence=TargetEvidence(
                    semantic_hint="提交按钮",
                    expected_text="Submit",
                ),
                postcondition="页面显示提交成功提示",
                risk_level=RiskLevel.HIGH,
                reversible=False,
            ),
        ]

        return TaskPlan(
            task_id=task_id,
            goal=user_input,
            steps=steps,
            parameters={
                "note_content": {
                    "type": "string",
                    "default": "示例内容",
                    "description": "表单备注内容",
                }
            },
            global_verification={
                "type": "ocr_check",
                "description": "检测页面出现 'Submitted' 提示",
            },
            context=context,
        )


def create_planner(mock: bool = False) -> TaskPlanner | MockPlanner:
    """根据配置创建 planner。"""
    if mock:
        return MockPlanner()
    client = LLMClient()
    if not client.available:
        return MockPlanner()
    return TaskPlanner(client=client)
