"""Bundle 编译器。

把原始 Recording + TaskPlan 语义标注 编译为确定性 Bundle。

编译逻辑：
1. 对 TaskPlan 的每一步，从 Recording 中提取动作事件
2. 为每步生成 Resolution Ladder 定位证据
   - structural: 录制时记录的定位 hint (转为 selector 或保留语义)
   - template:   动作前截图 (crop 目标区域，MVP 保留整图引用)
   - ocr:        录制时 hint 的期望文字
   - geometry:   若提供 expected_location，记录为相对位置描述
3. 绑定语义标注 (description / risk / reversible)
4. 生成后置验证条件 (来自 TaskPlan postcondition)
5. 生成全局 effect_oracle
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from autoflow.models import (
    ActionType,
    Bundle,
    BundleStep,
    EvidenceType,
    PlanStep,
    Recording,
    StepEvidence,
    TaskPlan,
)


class BundleCompiler:
    """将 Recording + TaskPlan 编译为 Bundle。"""

    def compile(
        self,
        recording: Recording,
        plan: TaskPlan,
        version: int = 1,
    ) -> Bundle:
        steps: list[BundleStep] = []
        actions = {
            e.data.get("step_index"): e.data
            for e in recording.events
            if e.kind == "action"
        }

        for ps in plan.steps:
            action_event = actions.get(ps.step_index, {})
            steps.append(self._compile_step(ps, action_event, plan.parameters))

        return Bundle(
            task_id=plan.task_id,
            goal=plan.goal,
            version=version,
            metadata={
                "app_name": recording.app_name,
                "backend": recording.backend,
                "environment_fingerprint": {
                    "resolution": recording.metadata.get("viewport", "1440x900"),
                    "url": recording.metadata.get("url", ""),
                    "created_at": recording.started_at,
                },
            },
            parameters=plan.parameters,
            steps=steps,
            effect_oracle=plan.global_verification,
        )

    def _compile_step(
        self,
        ps: PlanStep,
        action_event: dict[str, Any],
        plan_parameters: dict[str, Any],
    ) -> BundleStep:
        # --- 定位证据 ---
        evidence = StepEvidence()

        # structural: 由 hint 推导 selector 或保留语义 hint
        structural = self._derive_structural(ps, action_event)
        if structural:
            evidence.structural = structural

        # template: 动作前截图引用
        before_screen = action_event.get("before_screen")
        if before_screen:
            evidence.template = {
                "screen_path": before_screen,
                "confidence_threshold": 0.85,
            }

        # ocr: 期望文字
        expected_text = ps.target_evidence.expected_text
        if expected_text:
            evidence.ocr = {"expected_text": expected_text}

        # geometry: 期望位置描述
        if ps.target_evidence.expected_location:
            evidence.geometry = {
                "description": ps.target_evidence.expected_location,
            }

        # --- Resolution Ladder 顺序 ---
        ladder: list[EvidenceType] = []
        for t in (EvidenceType.STRUCTURAL, EvidenceType.TEMPLATE, EvidenceType.OCR, EvidenceType.GEOMETRY):
            if getattr(evidence, t.value) is not None:
                ladder.append(t)
        # 至少保留 structural/ocr 之一作为保底
        if not ladder:
            ladder = [EvidenceType.OCR]

        # --- 动作 ---
        action = {"type": ps.action.value}
        if ps.action in (ActionType.CLICK,):
            action["button"] = "left"
        if ps.parameters:
            action["params"] = ps.parameters

        # --- 后置验证 ---
        postcondition = None
        if ps.postcondition:
            postcondition = {
                "type": "ocr_verify",
                "description": ps.postcondition,
                "timeout_ms": 5000,
            }

        # --- 参数槽位 ---
        # 识别 action 参数中 {slot} 占位，并从 plan.parameters 取默认值
        slots = {}
        for key, value in ps.parameters.items():
            if isinstance(value, str) and value.startswith("{"):
                slot = value.strip("{}")
                default = ""
                if slot in plan_parameters and isinstance(plan_parameters[slot], dict):
                    default = plan_parameters[slot].get("default", "")
                elif slot in plan_parameters:
                    default = plan_parameters[slot]
                slots[slot] = default

        return BundleStep(
            index=ps.step_index,
            action=action,
            description=ps.description,
            evidence=evidence,
            resolution_ladder=ladder,
            postcondition=postcondition,
            risk={
                "level": ps.risk_level.value,
                "reversible": ps.reversible,
                "irreversible": not ps.reversible,
            },
            slots=slots,
        )

    @staticmethod
    def _derive_structural(ps: PlanStep, action_event: dict[str, Any]) -> dict[str, Any] | None:
        """从 hint 推导结构化定位。MVP 阶段保存语义 hint 供 replay 反查。"""
        hint = ps.target_evidence
        out: dict[str, Any] = {
            "semantic_hint": hint.semantic_hint,
        }
        if hint.expected_text:
            out["expected_text"] = hint.expected_text
        if ps.action in (ActionType.CLICK, ActionType.TYPE):
            out["type"] = "playwright_semantic"
        return out if out else None


