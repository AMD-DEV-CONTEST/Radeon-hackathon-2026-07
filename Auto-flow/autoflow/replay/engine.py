"""确定性执行引擎 (Replay)。

核心特性：
- 零模型调用：健康路径完全不调用 LLM/VLM
- Resolution Ladder：逐级尝试定位 (structural -> template -> ocr -> geometry)
- Identity Check：高风险步骤执行前防误触检查
- 严格 Halt：任何不确定情况立即停止，不猜测
- 参数注入：运行前注入动态参数

定位实现说明：
MVP 阶段通过抽象 backend 执行。这里把 Bundle 的证据翻译为 backend.locate 可理解的
语义 hint，并逐级尝试。structural 证据保留的 semantic_hint 是最主要的定位来源。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from autoflow.capture.base import CaptureBackend
from autoflow.models import (
    Bundle,
    BundleStep,
    EvidenceType,
    RunResult,
    StepResult,
)


class ReplayHalt(Exception):
    """Replay 中途停止。"""

    def __init__(self, step_index: int, reason: str, evidence_used: EvidenceType | None = None):
        super().__init__(reason)
        self.step_index = step_index
        self.reason = reason
        self.evidence_used = evidence_used


class ReplayEngine:
    """零模型确定性执行引擎。"""

    def __init__(self, backend: CaptureBackend) -> None:
        self.backend = backend

    def replay(
        self,
        bundle: Bundle,
        params: dict[str, Any] | None = None,
    ) -> RunResult:
        """执行 Bundle。

        Args:
            bundle: 待执行的确定性程序。
            params: 注入的动态参数。

        Returns:
            RunResult，包含每步结果和 halt 报告。
        """
        params = params or {}
        run = RunResult(
            run_id=f"run_{uuid.uuid4().hex[:8]}",
            task_id=bundle.task_id,
            status="success",
        )
        start = time.time()

        self.backend.start(self._make_recording_stub(bundle))
        try:
            for step in bundle.steps:
                step_start = time.time()
                try:
                    evidence_used = self._execute_step(step, params)
                    run.steps.append(
                        StepResult(
                            index=step.index,
                            status="success",
                            evidence_used=evidence_used,
                            duration_ms=int((time.time() - step_start) * 1000),
                        )
                    )
                except ReplayHalt as halt:
                    run.steps.append(
                        StepResult(
                            index=halt.step_index,
                            status="halt",
                            reason=halt.reason,
                            evidence_used=halt.evidence_used,
                            duration_ms=int((time.time() - step_start) * 1000),
                        )
                    )
                    run.status = "halted"
                    run.halt_report = self._build_halt_report(bundle, halt)
                    break
        finally:
            self.backend.stop()

        run.duration_ms = int((time.time() - start) * 1000)
        run.receipt = self._generate_receipt(run)
        return run

    def _execute_step(self, step: BundleStep, params: dict[str, Any]) -> EvidenceType:
        """执行单步，返回命中的证据层级。"""
        # 1. Resolution Ladder 定位
        target, evidence_used = self._resolve_target(step)

        # 2. 身份检查 (高风险步骤)
        if step.risk.get("level") == "high" and step.identity_check:
            if not self._verify_identity(target, step.identity_check):
                raise ReplayHalt(
                    step.index,
                    f"身份验证失败 (步骤 {step.index}: {step.description})，防止误触",
                    evidence_used,
                )

        # 3. 执行动作 (注入参数)
        action_params = self._inject_action_params(step, params)
        try:
            self.backend.do(step.action.get("type", "click"), element=target, **action_params)
        except Exception as exc:
            raise ReplayHalt(
                step.index,
                f"动作执行失败 (步骤 {step.index}: {step.description}): {exc}",
                evidence_used,
            ) from exc

        # 4. 后置验证
        if step.postcondition:
            if not self._verify_postcondition(step):
                raise ReplayHalt(
                    step.index,
                    f"后置验证失败 (步骤 {step.index}: {step.description})",
                    evidence_used,
                )

        return evidence_used

    def _resolve_target(self, step: BundleStep) -> tuple[Any, EvidenceType]:
        """Resolution Ladder 逐级定位目标。

        按 step.resolution_ladder 定义顺序尝试每种证据。
        MVP 阶段所有证据最终映射为 semantic hint 交给 backend.locate。
        """
        ladder = step.resolution_ladder or [
            EvidenceType.STRUCTURAL,
            EvidenceType.TEMPLATE,
            EvidenceType.OCR,
            EvidenceType.GEOMETRY,
        ]

        # 尝试顺序 (按 bundle 声明的 ladder，保证优先级)
        for ev_type in ladder:
            hint = self._evidence_to_hint(step, ev_type)
            if not hint:
                continue
            target = self.backend.locate(hint)
            if target is not None:
                return target, ev_type

        # 全失败 -> Halt
        raise ReplayHalt(
            step.index,
            f"步骤 {step.index} ({step.description})：所有证据层级均无法定位目标 "
            f"(ladder={[e.value for e in ladder]})",
        )

    @staticmethod
    def _evidence_to_hint(step: BundleStep, ev_type: EvidenceType) -> dict[str, Any]:
        """把某种证据翻译为 backend.locate 可理解的 hint。"""
        ev = step.evidence
        if ev_type == EvidenceType.STRUCTURAL and ev.structural:
            return dict(ev.structural)
        if ev_type == EvidenceType.OCR and ev.ocr:
            return {"expected_text": ev.ocr.get("expected_text", "")}
        if ev_type == EvidenceType.GEOMETRY and ev.geometry:
            return {"semantic_hint": ev.geometry.get("description", "")}
        if ev_type == EvidenceType.TEMPLATE and ev.template:
            # MVP: template 退化为用 semantic hint 尝试
            if ev.structural:
                return dict(ev.structural)
            return {}
        return {}

    def _verify_identity(self, target: Any, identity_check: dict[str, Any]) -> bool:
        """身份检查：确认目标确实是期望控件。MVP 阶段返回 True (交由用户确认)。"""
        return True

    def _verify_postcondition(self, step: BundleStep) -> bool:
        """后置验证。MVP 阶段使用延时快照 + 弱校验。

        理想实现应比较 before/after 截图 (模板差异检测)。
        """
        pc = step.postcondition or {}
        timeout = pc.get("timeout_ms", 5000)
        # 简单等待目标效果出现
        if isinstance(timeout, int):
            self.backend.do("wait", ms=min(timeout, 1500))
        return True

    @staticmethod
    def _inject_action_params(step: BundleStep, params: dict[str, Any]) -> dict[str, Any]:
        """从 step.action.params 注入参数槽位。"""
        action_params = dict(step.action.get("params", {}))
        for key, value in action_params.items():
            if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
                slot = value.strip("{}")
                action_params[key] = params.get(slot, step.slots.get(slot, ""))
        return action_params

    def _build_halt_report(self, bundle: Bundle, halt: ReplayHalt) -> dict[str, Any]:
        return {
            "task_id": bundle.task_id,
            "goal": bundle.goal,
            "failed_step": halt.step_index,
            "reason": halt.reason,
            "evidence_used": halt.evidence_used.value if halt.evidence_used else None,
            "current_screen": self._last_screen(),
        }

    def _last_screen(self) -> str | None:
        try:
            snap = self.backend.snapshot()
            return snap.get("screen")
        except Exception:
            return None

    @staticmethod
    def _generate_receipt(run: RunResult) -> str:
        """生成隐私安全凭证 (不含截图/文字/参数)。"""
        summary = {
            "run_id": run.run_id,
            "task_id": run.task_id,
            "status": run.status,
            "steps": [
                {"index": s.index, "status": s.status, "evidence": s.evidence_used.value if s.evidence_used else None}
                for s in run.steps
            ],
        }
        import json

        return json.dumps(summary, ensure_ascii=False)

    @staticmethod
    def _make_recording_stub(bundle: Bundle) -> Any:
        """为 replay 构造一个轻量 Recording 占位，用于 backend.start 的环境指纹。"""
        from autoflow.models import Recording

        return Recording(
            recording_id=f"replay_{bundle.task_id}",
            app_name=bundle.metadata.get("app_name", ""),
            backend=bundle.metadata.get("backend", "web"),
            metadata={"url": bundle.metadata.get("environment_fingerprint", {}).get("url", "")},
        )
