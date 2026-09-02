"""P0.5 思考增强层 `xai-grok-reason`（GPT-5.6 推理预算 + Thinking Claude 协议 + s1/自一致性）。

所有方法都接收一个 `ModelBackend`，对真实模型透明；测试用 StubBackend。
本层只提供"思考脚手架"，不绑定任何模型 —— 弱模型套上即获得结构化思考 + 多重验证。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from ..model_backend import ModelBackend, ModelResponse


class Budget(str, Enum):
    INSTANT = "instant"
    LIGHT = "light"
    MEDIUM = "medium"
    HIGH = "high"
    EXTRA = "extra_high"


# 复杂度启发式：按关键词/长度粗判任务难度，决定思考预算（避免 overthinking）。
_HEAVY_KEYWORDS = ("设计", "架构", "重构", "debug", "根因", "权衡", "分析", "规划", "implement", "design", "debug", "why")


def thinking_budget(task: str) -> Budget:
    """按任务复杂度选思考预算（GPT-5.6 推理油门思路）。"""
    lowered = task.lower()
    score = 0
    score += sum(1 for k in _HEAVY_KEYWORDS if k.lower() in lowered)
    score += len(task) // 80  # 长任务加权
    if score >= 4:
        return Budget.EXTRA
    if score >= 3:
        return Budget.HIGH
    if score >= 2:
        return Budget.MEDIUM
    if score >= 1:
        return Budget.LIGHT
    return Budget.INSTANT


# Thinking Claude 协议的标准思考阶段（重述→拆解→多假设→验证→纠错→综合）。
THINK_STEPS = ["重述问题", "拆解子问题", "列出多假设", "验证假设", "纠错修正", "综合结论"]


def thinking_protocol_full(backend: ModelBackend, task: str) -> tuple[str, str]:
    """结构化思考（Thinking Claude 协议），返回 (思考要点, 最终答案) 两段。

    设计（2026-07-27 v2）：
    - 思考过程不能全黑盒——操作者需要看到关键思考节点，及时发现跑偏；
    - 但思考全文也不能混进答案（曾导致假体检报告泄漏）。
    - 折中：让模型输出【思考要点】（3-6 条精炼要点）+【最终答案】两段，
      调用方把要点作为进度/过程展示，答案单独作为最终输出。
    """
    plan = " → ".join(THINK_STEPS)
    prompt = (
        f"[思考协议 {plan}]\n任务：{task}\n"
        "请严格按以下两段格式输出：\n"
        "【思考要点】\n- 用 3-6 条要点概括你的关键思考节点（每条一行，覆盖：问题理解、"
        "关键假设/依据、验证方式、潜在风险或不确定点）\n"
        "【最终答案】\n面向用户的最终答案本身。禁止在此段出现'我们被要求''让我''首先'等自述性推演文字。"
    )
    raw = backend.complete(prompt)
    return split_thinking_answer(raw)


def split_thinking_answer(raw: str) -> tuple[str, str]:
    """把「【思考要点】…【最终答案】…」拆为两段；格式不符时兜底为 (空, 剥离后全文)。"""
    if not raw:
        return "", ""
    import re
    m = re.search(r"【思考要点】([\s\S]*?)【最终答案】([\s\S]*)", raw)
    if m:
        return m.group(1).strip(), m.group(2).strip() or raw.strip()
    # 兼容模型用其他标记（'思考要点:' / '最终答案:'）
    m = re.search(r"思考要点[:：]?([\s\S]*?)最终答案[:：]?([\s\S]*)", raw)
    if m and m.group(2).strip():
        return m.group(1).strip(), m.group(2).strip()
    return "", strip_thinking(raw)


def thinking_protocol(backend: ModelBackend, task: str) -> str:
    """兼容旧调用：只返回最终答案（内部走 full 版）。"""
    _, answer = thinking_protocol_full(backend, task)
    return answer


def strip_thinking(text: str) -> str:
    """剥离答案文本中的思考残留：<think> 块、思考协议阶段标题段。

    保守策略：只剥离明确的思考标记；若剥离后为空则回退原文（宁泄漏勿丢答案）。
    """
    if not text:
        return text
    import re
    out = re.sub(r"<think>[\s\S]*?</think>", "", text)
    # 若模型仍以"我们被要求/让我/首先，"式自述 + 阶段标题开头，截到最后一个阶段标题之后
    step_pat = "|".join(re.escape(s) for s in THINK_STEPS)
    m = list(re.finditer(rf"(?:^|\n)\s*(?:[#*\d\.\s]*)?(?:{step_pat})[:：]?", out))
    if m and (out[:20].startswith(("我们被要求", "让我", "首先")) or out.lstrip().startswith("[思考")):
        tail = out[m[-1].end():].strip()
        if tail:
            out = tail
    out = out.strip()
    return out if out else text.strip()


def budget_force(text: str, backend: ModelBackend, min_len: int = 30) -> str:
    """s1 的 'Wait' 机制：检测过早结束时强制续思。"""
    if len(text.strip()) >= min_len and "最终" not in text and "结论" not in text:
        # 疑似未完成：注入 Wait 续思
        continued = backend.complete(text + "\nWait, 让我再检查一遍是否遗漏：")
        return text + "\n" + continued
    return text


def self_refine(backend: ModelBackend, draft_fn: Callable[[], str], max_rounds: int = 2) -> tuple[str, list[str]]:
    """Self-Refinement：初稿 → 批评 → 修订 → 再批评。

    返回 (最终文本, 各轮批评日志)。
    """
    logs: list[str] = []
    current = draft_fn()
    for _ in range(max_rounds):
        critique = backend.complete(f"[批评] 请指出下面内容的问题：\n{current}")
        logs.append(critique)
        if "无问题" in critique or "正确" in critique:
            break
        current = backend.complete(f"[修订] 根据批评改进：\n{current}\n批评：{critique}")
    return current, logs


@dataclass
class Trajectory:
    answer: str
    confidence: float


def multi_trajectory(backend: ModelBackend, task: str, n: int = 3) -> tuple[str, list[Trajectory]]:
    """ToT / 自一致性：并行采样多条轨迹，按答案众数投票（弱模型多次采样可逼近强模型单次）。
    使用 backend.complete() 避免 complete_with_confidence 的额外 logprobs 开销。"""
    trajs: list[Trajectory] = []
    for _ in range(n):
        text = backend.complete(f"[轨迹] {task}")
        confidence = min(1.0, max(0.1, len(text) / 500))
        trajs.append(Trajectory(answer=text, confidence=confidence))
    from collections import Counter
    vote = Counter(t.answer for t in trajs)
    winner = vote.most_common(1)[0][0]
    return winner, trajs
