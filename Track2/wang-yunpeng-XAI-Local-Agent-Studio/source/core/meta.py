"""P10 元认知层 `xai-grok-meta`（来自 beidou L7/L8，但校准改为中立可优化）。

关键修正（审计伪逻辑2）：原 l7 的 ×0.7/×0.8/×0.85 是"金融多系统投票"硬编码系数，
通用 Agent 单模型下无对象可打、无中立性。改为 **Brier Score 在线校准**：
追踪"报 p 置信的任务实际成功率是否≈p"，自动反修校准映射。模型无关、数据驱动、可逐步优化。

L8 四维审计（冲突C3修正）：不再用原 l8 硬编码回测三维(pass:False 永远误报)，
改为 Agent 四维度：数据完整 / 逻辑自洽 / 幻觉检测 / 动作安全（动作安全接 Guardian）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .guardian import Action, approve


@dataclass
class CalibSample:
    predicted: float
    outcome: float  # 1.0 成功 / 0.0 失败


class BrierCalibrator:
    """分桶 EMA 在线校准器（中立、可逐步优化、模型无关）。

    将置信度 [0,1] 分成若干桶，每桶维护"预测均值"与"实际成功率"的指数滑动平均，
    校准映射 = 用实际成功率替换模型自报置信（更可信）。
    """

    def __init__(self, n_bins: int = 10, ema_alpha: float = 0.3):
        self.n_bins = n_bins
        self.alpha = ema_alpha
        self.pred_sum = [0.0] * n_bins
        self.true_sum = [0.0] * n_bins
        self.count = [0] * n_bins

    def _bin(self, p: float) -> int:
        p = max(0.0, min(0.999, p))
        return min(self.n_bins - 1, int(p * self.n_bins))

    def update(self, predicted: float, outcome: float) -> None:
        b = self._bin(predicted)
        self.pred_sum[b] += predicted
        self.true_sum[b] += outcome
        self.count[b] += 1

    def calibrate(self, p: float) -> float:
        """返回校准后的置信度（若该桶无数据，原样返回）。"""
        b = self._bin(p)
        if self.count[b] == 0:
            return p
        actual = self.true_sum[b] / self.count[b]
        return actual

    def brier_score(self) -> float:
        """整体 Brier 分数（越小越准）。"""
        total = sum(self.count)
        if total == 0:
            return 0.0
        s = 0.0
        for b in range(self.n_bins):
            if self.count[b] == 0:
                continue
            pred = self.pred_sum[b] / self.count[b]
            true = self.true_sum[b] / self.count[b]
            s += self.count[b] * (pred - true) ** 2
        return s / total


@dataclass
class ReflectResult:
    raw_confidence: float
    calibrated_confidence: float
    reasoning_trace: str


def reflect(raw_confidence: float, reasoning_trace: str, calibrator: BrierCalibrator) -> ReflectResult:
    """L7 reflect：用在线校准映射替换自报置信（中立、公正）。"""
    cal = calibrator.calibrate(raw_confidence)
    return ReflectResult(
        raw_confidence=raw_confidence,
        calibrated_confidence=cal,
        reasoning_trace=reasoning_trace,
    )


@dataclass
class AuditDim:
    name: str
    passed: bool
    score: float  # [0,1]
    notes: str


class L8Auditor:
    """L8 四维审计（替代原硬编码回测三维）。"""

    def audit(self, *, data_present: bool, logic_consistent: bool,
              no_hallucination: bool, action: Optional[Action] = None,
              auto_mode: bool = False) -> list[AuditDim]:
        dims = [
            AuditDim("数据完整性", data_present, 1.0 if data_present else 0.0,
                     "输入数据齐备" if data_present else "缺失关键输入"),
            AuditDim("逻辑自洽", logic_consistent, 1.0 if logic_consistent else 0.0,
                     "推理链自洽" if logic_consistent else "存在逻辑矛盾"),
            AuditDim("幻觉检测", no_hallucination, 1.0 if no_hallucination else 0.0,
                     "未检出编造" if no_hallucination else "疑似编造事实"),
        ]
        # 动作安全：若涉及动作，交给 Guardian 判（冲突C3：用 Guardian 而非硬编码回测）
        if action is not None:
            g = approve(action, auto_mode=auto_mode)
            dims.append(AuditDim("动作安全", g.allowed, 1.0 if g.allowed else 0.0, g.reason))
        else:
            dims.append(AuditDim("动作安全", True, 1.0, "无外部动作"))
        return dims

    def all_pass(self, dims: list[AuditDim]) -> bool:
        return all(d.passed for d in dims)
