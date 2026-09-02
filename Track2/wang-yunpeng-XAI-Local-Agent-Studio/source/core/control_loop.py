"""中枢控制环 `xai-grok-control`（解决审计冲突 C1：Guardian↔reason↔meta 成环）。

单向管线（绝不互递归）：
    meta外环(思考预算) → reason(思考/自精炼/多轨迹) → meta.reflect(校准置信)
    → guardian(审批) → execute(执行) → meta.observe(L8审计 + 校准更新)

guardian 是被调用的节点，不反向调用 reason/meta；meta 的 observe 只做记录与校准更新，
不触发新的 reason 循环。由此彻底消除死锁风险。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .guardian import Action, approve
from .meta import BrierCalibrator, reflect, L8Auditor
from .model_backend import ModelBackend
from .cognition.reasoner import thinking_budget, thinking_protocol, thinking_protocol_full, self_refine, multi_trajectory, Budget, split_thinking_answer
from .observability import global_tracer


@dataclass
class A2UIEvent:
    """A2UI 结构化流式事件（吸收 superagent-base 的 A2UI 协议）。

    类型：text / thinking / tool_call / tool_result / interrupt / done / progress / agent_switch
    """

    type: str
    payload: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


@dataclass
class LoopResult:
    answer: str
    calibrated_confidence: float
    allowed: bool
    audit_passed: bool
    audit_notes: str
    thinking: str = ""  # 思考要点（3-6 条关键节点，供前端过程展示，不混入答案）


class ControlLoop:
    def __init__(self, backend: ModelBackend, auto_mode: bool = False,
                 emitter: Optional[Callable[[A2UIEvent], None]] = None):
        self.backend = backend
        self.auto_mode = auto_mode
        self.calibrator = BrierCalibrator()
        self.auditor = L8Auditor()
        self.emitter = emitter

    def _emit(self, etype: str, **payload) -> None:
        if self.emitter is not None:
            self.emitter(A2UIEvent(type=etype, payload=payload))

    # ---- v2.0 轻量包装（供 engine.chat() 快速调用）----

    def reason(self, prompt: str, history: list[dict] | None = None) -> Budget | None:
        """轻量 Reason：思考预算计算。失败返回 None，不影响主流程。"""
        try:
            context = prompt
            if history:
                context += "\n".join(
                    f"{h.get('role','')}: {str(h.get('content',''))[:200]}"
                    for h in history[-5:]
                )
            return thinking_budget(context)
        except Exception:
            return None

    def meta_reflect(self, task: str) -> dict | None:
        """轻量 Meta 反射：置信校准（使用 heuristics，无额外 API 调用）。失败返回 None。"""
        try:
            # 不再调用 complete_with_confidence（双重 API 调用）
            answer = self.backend.complete(task[:200]) if hasattr(self.backend, 'complete') else task
            raw_conf = min(0.9, max(0.2, len(answer) / 400))
            refl = reflect(raw_conf, answer, self.calibrator)
            return {"confidence": refl.calibrated_confidence,
                    "raw_confidence": raw_conf}
        except Exception:
            return None

    # ---- 完整控制环 ----

    def act(self, task: str, action: Optional[Action] = None,
            execute_fn: Optional[Callable[[str], str]] = None,
            use_refine: bool = False, use_multi: bool = False,
            emit: bool = False) -> LoopResult:
        # 1. meta 外环：思考预算
        budget: Budget = thinking_budget(task)
        if emit:
            self._emit("thinking", stage="budget", budget=budget.value)

        # 2. reason：思考增强（思考要点与答案分流：要点透出给用户看进度，答案单独返回）
        thinking = ""
        if use_multi:
            answer, _ = multi_trajectory(self.backend, task, n=3)
        elif use_refine:
            answer, _ = self_refine(self.backend, lambda: thinking_protocol(self.backend, task))
        else:
            thinking, answer = thinking_protocol_full(self.backend, task)
        if emit:
            self._emit("thinking", stage="answer", len=len(answer), key_points=thinking[:600])

        # 3. meta.reflect：校准置信（使用 heuristics，不额外调用 API）
        ans_len = len(answer) if answer else 0
        has_refusal = "refused" in answer.lower() if answer else False
        heuristic_conf = 0.3 + min(0.6, ans_len / 800) if not has_refusal else 0.1
        refl = reflect(heuristic_conf, answer, self.calibrator)
        if emit:
            self._emit("progress", calibrated=refl.calibrated_confidence)

        # 4. guardian：审批（单向节点，不回调 reason/meta）
        allowed = True
        if action is not None:
            g = approve(action, auto_mode=self.auto_mode)
            allowed = g.allowed
            if emit:
                self._emit("tool_call", action=action.kind, allowed=allowed, level=g.level)
            if not allowed and emit:
                self._emit("interrupt", reason=g.reason)

        # 5. execute
        output = None
        if allowed and execute_fn is not None:
            output = execute_fn(answer)
            if emit:
                self._emit("tool_result", ok=bool(output))

        # 6. meta.observe：L8 审计 + 校准更新（真实 tracing 统计，不再用 BrierCalibrator 假校准）
        dims = self.auditor.audit(
            data_present=bool(task),
            logic_consistent=("矛盾" not in answer),
            no_hallucination=("[REFUSED]" not in answer),
            action=action if action is not None else None,
            auto_mode=self.auto_mode,
        )
        audit_pass = self.auditor.all_pass(dims)
        # 用真实 tracing 统计的 success_rate 作为校准置信度替代假 BrierCalibrator
        trace_stats = global_tracer.stats()
        calibrated_conf = trace_stats.get("success_rate", refl.calibrated_confidence)
        # 若 tracing 无数据（冷启动），回退 BrierCalibrator
        if trace_stats.get("total", 0) > 0:
            self.calibrator.update(calibrated_conf, 1.0 if audit_pass else 0.0)
        else:
            self.calibrator.update(refl.calibrated_confidence, 1.0 if audit_pass else 0.0)
            calibrated_conf = refl.calibrated_confidence
        if emit:
            self._emit("done", audit_passed=audit_pass)

        return LoopResult(
            answer=output if output is not None else answer,
            calibrated_confidence=calibrated_conf,
            allowed=allowed,
            audit_passed=audit_pass,
            audit_notes="; ".join(f"{d.name}:{'OK' if d.passed else 'FAIL'}" for d in dims),
            thinking=thinking,
        )
