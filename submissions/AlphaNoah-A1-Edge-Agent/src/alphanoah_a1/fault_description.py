"""Deterministic applicability guard for the bounded Web fault demo."""

from __future__ import annotations

import re


_ENGLISH_FAULT_SIGNALS = (
    r"\b(?:poor|weak|reduced|insufficient|no)\s+cool(?:ing)?\b",
    r"\bcool(?:ing)?\b.*\b(?:poor|poorly|weak|weaker|reduced|insufficient)\b",
    r"\b(?:not|isn['’]t|is not)\s+cool(?:ing)?\b",
    r"\b(?:temperature|outlet\s+temperature|too\s+warm|too\s+hot)\b",
    r"\b(?:unusual|abnormal|strange|loud)\s+(?:noise|sound|vibration)\b",
    r"\b(?:noise|noisy|rattl(?:e|ing)|buzz(?:ing)?|grind(?:ing)?|vibrat(?:e|ing|ion))\b",
    r"\b(?:leak(?:ing|age)?|drip(?:ping)?|water|condensation|overflow)\b",
    r"\b(?:air\s*flow|fan|vent)\b.*\b(?:weak|low|poor|blocked|abnormal|not|stopped)\b",
    r"\b(?:weak|low|poor|blocked|abnormal|no)\b.*\b(?:air\s*flow|fan|vent)\b",
    r"\b(?:odor|odour|smell|burning|smoke|smoky)\b",
    r"\b(?:won['’]t|will not|cannot|can['’]t|fails? to)\s+(?:start|stop|turn on|turn off)\b",
    r"\b(?:power|start|stop|shutdown|turn(?:ing)? on|turn(?:ing)? off)\b.*\b(?:fault|fail|problem|issue|abnormal|intermittent)\b",
    r"\b(?:air conditioner|air conditioning|a/c|ac unit|unit)\b.{0,60}\b(?:fault|failure|malfunction|broken|abnormal|problem|issue)\b",
    r"\b(?:fault|failure|malfunction|broken|abnormal|problem|issue)\b.{0,60}\b(?:air conditioner|air conditioning|a/c|ac unit|unit)\b",
    r"\b(?:fault|failure|malfunction|broken|abnormal)\b",
)

_CHINESE_FAULT_SIGNALS = (
    "制冷差",
    "制冷不良",
    "不制冷",
    "制冷不足",
    "无法制冷",
    "不能制冷",
    "温度异常",
    "温度偏高",
    "出风温度",
    "噪音",
    "异响",
    "振动",
    "漏水",
    "滴水",
    "渗水",
    "冷凝水",
    "气流异常",
    "风量异常",
    "风量不足",
    "风量变小",
    "风变小",
    "出风很小",
    "风很小",
    "出风异常",
    "风扇异常",
    "异味",
    "烧焦味",
    "冒烟",
    "烟雾",
    "无法启动",
    "开不了机",
    "不能开机",
    "无法关闭",
    "不能启动",
    "不能关闭",
    "启停异常",
    "供电异常",
    "运行异常",
    "空调故障",
    "空调异常",
    "空调有问题",
    "空调坏了",
    "设备故障",
)


def is_bounded_air_conditioner_fault(description: str) -> bool:
    """Return whether text reports an observed air-conditioner anomaly."""

    if not isinstance(description, str):
        return False
    normalized = " ".join(description.casefold().split())
    if not normalized:
        return False
    if any(signal in normalized for signal in _CHINESE_FAULT_SIGNALS):
        return True
    return any(
        re.search(pattern, normalized) is not None
        for pattern in _ENGLISH_FAULT_SIGNALS
    )
