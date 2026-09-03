"""AI Repair Agent。

当 Replay Halt 时，AI 分析失败原因并生成修复方案：
- 策略 A: 更新定位证据 (新截图/新OCR/新Selector)
- 策略 B: 插入新步骤 (如先关闭弹窗)
- 策略 C: 删除失效步骤
- 策略 D: 重新录制整个流程

MVP 阶段：
- 支持 LLM 模式 (配置 API key 时生成结构化修复方案)
- 支持 mock 模式 (返回固定修复策略，演示链路)
修复结果通过 apply 生成 vN+1 Bundle。
"""

from __future__ import annotations

import copy
from typing import Any

from autoflow.llm import LLMClient
from autoflow.models import Bundle, StepEvidence

REPAIR_SYSTEM_PROMPT = """你是 UI 自动化修复专家。根据失败报告生成修复方案，输出严格 JSON。

输出格式:
{
  "root_cause": "失败根因分析",
  "strategy": "A | B | C | D",
  "repair_details": "修复方案详细说明",
  "new_steps": [
    {
      "index": 0,
      "description": "步骤描述",
      "evidence": {"structural": {"semantic_hint": "...", "expected_text": "..."}},
      "resolution_ladder": ["structural", "ocr"]
    }
  ]
}"""


class RepairAgent:
    """碰壁修复 Agent。"""

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient()

    def diagnose(self, halt_report: dict[str, Any], bundle: Bundle) -> dict[str, Any]:
        """诊断失败并生成修复方案。"""
        if self.client.available:
            user_prompt = self._build_diagnose_prompt(halt_report, bundle)
            try:
                return self.client.chat_json(
                    system_prompt=REPAIR_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                )
            except RuntimeError:
                return self._mock_diagnosis(halt_report)
        return self._mock_diagnosis(halt_report)

    def apply(self, bundle: Bundle, repair_plan: dict[str, Any]) -> Bundle:
        """根据修复方案生成 vN+1 Bundle。"""
        strategy = repair_plan.get("strategy", "A")
        new_bundle = copy.deepcopy(bundle)
        new_bundle.version += 1

        if strategy == "A":
            # 更新定位证据
            new_steps = repair_plan.get("new_steps")
            if new_steps:
                self._apply_new_steps(new_bundle, new_steps)
        elif strategy == "B":
            # 插入新步骤 (MVP 简化: 在开头插入)
            new_steps = repair_plan.get("new_steps", [])
            self._prepend_steps(new_bundle, new_steps)
        elif strategy == "C":
            # 删除失败步骤之后的步骤 (MVP 简化)
            failed_idx = repair_plan.get("failed_step")
            if failed_idx is not None:
                new_bundle.steps = [s for s in new_bundle.steps if s.index <= failed_idx]
        elif strategy == "D":
            # 重新录制: 标记需要重新录制
            new_bundle.metadata["needs_re-record"] = True

        new_bundle.metadata["last_repair"] = {
            "strategy": strategy,
            "root_cause": repair_plan.get("root_cause", ""),
        }
        return new_bundle

    # ------------------------------------------------------------------ #

    def _build_diagnose_prompt(
        self, halt_report: dict[str, Any], bundle: Bundle
    ) -> str:
        return (
            f"【任务目标】{bundle.goal}\n"
            f"【失败步骤】第 {halt_report.get('failed_step')} 步\n"
            f"【失败原因】{halt_report.get('reason')}\n"
            f"【当前截图】{halt_report.get('current_screen')}\n"
            f"【已尝试证据】{halt_report.get('evidence_used')}\n"
        )

    def _mock_diagnosis(self, halt_report: dict[str, Any]) -> dict[str, Any]:
        """无 LLM 时的默认诊断：更新证据 + 重试。"""
        failed_step = halt_report.get("failed_step", 0)
        return {
            "root_cause": "元素定位失败 (mock 诊断)，可能是 UI 漂移或元素文字变更",
            "strategy": "A",
            "repair_details": f"建议更新第 {failed_step} 步的定位证据",
            "new_steps": [],
            "failed_step": failed_step,
        }

    @staticmethod
    def _apply_new_steps(bundle: Bundle, new_steps: list[dict[str, Any]]) -> None:
        """用新证据更新已有步骤。"""
        by_index = {s["index"]: s for s in new_steps}
        for step in bundle.steps:
            if step.index in by_index:
                spec = by_index[step.index]
                if spec.get("evidence"):
                    ev = spec["evidence"]
                    step.evidence = StepEvidence(
                        structural=ev.get("structural"),
                        ocr=ev.get("ocr"),
                        template=ev.get("template"),
                        geometry=ev.get("geometry"),
                    )
                if spec.get("description"):
                    step.description = spec["description"]

    @staticmethod
    def _prepend_steps(bundle: Bundle, new_steps: list[dict[str, Any]]) -> None:
        """在流程开头插入新步骤。"""
        if not new_steps:
            return
        from autoflow.models import BundleStep

        inserts = []
        max_idx = max(s.index for s in bundle.steps) if bundle.steps else -1
        for i, spec in enumerate(new_steps):
            ev = spec.get("evidence", {})
            inserts.append(
                BundleStep(
                    index=max_idx + 1 + i,
                    action={"type": "click", "button": "left"},
                    description=spec.get("description", "插入步骤"),
                    evidence=StepEvidence(
                        structural=ev.get("structural"),
                        ocr=ev.get("ocr"),
                    ),
                    resolution_ladder=["structural", "ocr"],
                )
            )
        bundle.steps = inserts + bundle.steps
        # 重新排序 index
        for i, s in enumerate(bundle.steps):
            s.index = i
