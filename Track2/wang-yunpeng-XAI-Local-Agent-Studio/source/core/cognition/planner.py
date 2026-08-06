"""XAI V4 Task Planner — 将用户目标转换为可执行步骤。

V4 §4.1: 把用户目标转换为执行计划。
第一版最小可用：
  Goal → Steps → Agent Assignment → Execution Order

不加入：
  - 自动搜索树
  - 复杂反思
  - 多层规划
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PlanStep:
    """单个执行步骤"""
    step_id: int
    agent: str          # "hermes" | "grok" | "reviewer"
    task: str           # 自然语言描述的任务
    depends_on: List[int] = field(default_factory=list)  # 依赖的前置 step_id
    status: str = "pending"  # pending | running | done | failed


@dataclass
class Plan:
    """完整执行计划"""
    goal: str
    steps: List[PlanStep]
    rationale: str = ""   # 规划理由

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "steps": [{"step_id": s.step_id, "agent": s.agent,
                       "task": s.task, "depends_on": s.depends_on,
                       "status": s.status} for s in self.steps],
            "rationale": self.rationale,
        }

    def next_pending(self) -> Optional[PlanStep]:
        """返回下一个可执行的步骤（满足依赖 + 未完成）。"""
        done_ids = {s.step_id for s in self.steps if s.status == "done"}
        for s in self.steps:
            if s.status == "pending":
                if all(d in done_ids for d in s.depends_on):
                    return s
        return None


class Planner:
    """V4 任务规划器。

    第一版: 基于规则的分层分解，不需要 LLM 调用。
    复杂任务以后接 Hermes/DeepSeek 做语义规划。
    """

    def plan(self, goal: str, complexity: int = 50) -> Plan:
        """根据目标生成执行计划。

        Args:
            goal: 用户目标（自然语言）
            complexity: 任务复杂度评分 0-100
        """
        goal_lower = goal.lower()

        # —— 开发任务 ——
        if any(kw in goal_lower for kw in ["开发", "写代码", "编程", "build", "code", "app", "网站", "api"]):
            return Plan(
                goal=goal,
                steps=[
                    PlanStep(step_id=1, agent="hermes", task=f"分析需求: {goal}"),
                    PlanStep(step_id=2, agent="hermes", task="制定技术方案与架构设计", depends_on=[1]),
                    PlanStep(step_id=3, agent="grok", task="核心代码开发", depends_on=[2]),
                    PlanStep(step_id=4, agent="reviewer", task="代码审查与质量检查", depends_on=[3]),
                    PlanStep(step_id=5, agent="grok", task="根据审查意见修改代码", depends_on=[4]),
                    PlanStep(step_id=6, agent="reviewer", task="最终验证与交付", depends_on=[5]),
                ],
                rationale="开发任务标准流程: 分析→设计→编码→审查→修改→验证",
            )

        # —— 研究任务 ——
        if any(kw in goal_lower for kw in ["研究", "分析", "调研", "research", "行业", "报告"]):
            return Plan(
                goal=goal,
                steps=[
                    PlanStep(step_id=1, agent="hermes", task=f"明确研究范围: {goal}"),
                    PlanStep(step_id=2, agent="hermes", task="资料收集与信息检索", depends_on=[1]),
                    PlanStep(step_id=3, agent="hermes", task="深度分析与观点形成", depends_on=[2]),
                    PlanStep(step_id=4, agent="reviewer", task="报告质量审查", depends_on=[3]),
                    PlanStep(step_id=5, agent="hermes", task="生成最终报告", depends_on=[4]),
                ],
                rationale="研究任务标准流程: 范围→收集→分析→审查→报告",
            )

        # —— 修复/调试任务 ——
        if any(kw in goal_lower for kw in ["修复", "bug", "错误", "fix", "debug", "调试", "问题"]):
            return Plan(
                goal=goal,
                steps=[
                    PlanStep(step_id=1, agent="hermes", task=f"诊断问题根因: {goal}"),
                    PlanStep(step_id=2, agent="grok", task="修复代码", depends_on=[1]),
                    PlanStep(step_id=3, agent="grok", task="编写并运行测试", depends_on=[2]),
                    PlanStep(step_id=4, agent="reviewer", task="验证修复效果", depends_on=[3]),
                ],
                rationale="修复任务标准流程: 诊断→修复→测试→验证",
            )

        # —— 通用任务（低复杂度跳过完整规划） ——
        if complexity < 30:
            return Plan(
                goal=goal,
                steps=[PlanStep(step_id=1, agent="hermes", task=goal)],
                rationale="简单任务，直接回答",
            )

        # 中等复杂度通用任务
        return Plan(
            goal=goal,
            steps=[
                PlanStep(step_id=1, agent="hermes", task=f"理解任务: {goal}"),
                PlanStep(step_id=2, agent="hermes", task="执行核心推理与回答"),
                PlanStep(step_id=3, agent="reviewer", task="检查回答质量", depends_on=[2]),
            ],
            rationale="通用任务标准流程: 理解→推理→审查",
        )
