"""
Iron Law — 五条铁律规则校验器
在任务创建和提交完成前调用，发现违规立即拦截。
"""
from __future__ import annotations

from typing import Any

# Task types where strict intake gates (Rule 1 context, Rule 5 acceptance_check)
# don't apply. These tasks ARE the analysis — context is their output, not input.
GATE_EXEMPT_TASK_TYPES: frozenset[str] = frozenset(
    {"review", "audit", "research", "analysis", "read_only", "planning", "discussion", "deployment"}
)


class RuleViolation(Exception):
    def __init__(self, rule: int, message: str, auto_fixable: bool = False):
        self.rule = rule
        self.message = message
        self.auto_fixable = auto_fixable
        super().__init__(f"[Rule {rule}] {message}")


def check_rule1_context_required(task_payload: dict[str, Any]) -> None:
    """规则1：任务 payload 必须包含 context 字段且不为空。"""
    ctx = task_payload.get("context") or task_payload.get("payload", {}).get("context")
    if not ctx or not ctx.get("goal"):
        raise RuleViolation(
            1,
            "任务缺少 context.goal 字段。必须先调用 /iron-law/context 组装上下文再发布任务。",
            auto_fixable=False,
        )


def check_rule3_task_granularity(
    title: str,
    estimated_hours: float | None,
    description: str = "",
) -> None:
    """规则3：单任务估时不超过 1 小时。"""
    if estimated_hours is not None and estimated_hours > 1.0:
        raise RuleViolation(
            3,
            f"任务 '{title}' 估时 {estimated_hours}h 超过 1 小时上限，必须拆分为更小的子任务。",
            auto_fixable=True,
        )
    # 启发式检测：描述里出现多个"然后""接着""再"等连接词，可能是大任务
    connectors = ["然后", "接着", "再然后", "之后再", "完成后再", "并且还要"]
    count = sum(description.count(c) for c in connectors)
    if count >= 3:
        raise RuleViolation(
            3,
            f"任务描述包含 {count} 个串行步骤连接词，疑似大任务，建议拆分。",
            auto_fixable=True,
        )


def check_rule5_acceptance_required(task: dict[str, Any]) -> None:
    """规则5：任务必须有 acceptance_check，且类型和 agent_type 匹配。"""
    ac = task.get("acceptance_check")
    if not ac:
        raise RuleViolation(
            5,
            f"任务 '{task.get('title')}' 缺少 acceptance_check，完成后无法验收。",
            auto_fixable=False,
        )
    ac_type = ac.get("type")
    agent_type = (task.get("required_capabilities") or {}).get("agent_type", "")

    # 安全校验：防止用前端 build 命令验收 Python 服务
    forbidden_combos = {
        ("command", "pnpm build"): "pnpm build 不适合验收 Python 服务",
        ("command", "npm build"): "npm build 不适合验收 Python/后端服务",
    }
    if ac_type == "command":
        cmd_str = " ".join(ac.get("command", []))
        for (_, pattern), reason in forbidden_combos.items():
            if pattern in cmd_str and "node" not in agent_type and "codex" not in agent_type:
                raise RuleViolation(5, f"acceptance_check 类型错误：{reason}", auto_fixable=True)


def validate_task_before_dispatch(task: dict[str, Any]) -> list[str]:
    """
    在任务进入 Orchestrator 队列前做全量校验。
    返回警告列表（不阻塞）；raise RuleViolation 则直接拒绝。
    """
    warnings: list[str] = []
    payload = task.get("payload") or {}
    task_type = (task.get("task_type") or "").lower()

    if task_type in GATE_EXEMPT_TASK_TYPES:
        # Audit/review/research tasks are exempt from Rule 1 (context.goal) and
        # Rule 5 (acceptance_check). Their output IS the context; requiring it
        # as input creates a chicken-and-egg block. Rule 3 still applies.
        try:
            check_rule3_task_granularity(
                task.get("title", ""),
                payload.get("estimated_hours"),
                task.get("description", ""),
            )
        except RuleViolation as e:
            if e.auto_fixable:
                warnings.append(str(e))
            else:
                raise
        return warnings

    # 规则1：上下文
    check_rule1_context_required(payload)

    # 规则3：粒度
    try:
        check_rule3_task_granularity(
            task.get("title", ""),
            payload.get("estimated_hours"),
            task.get("description", ""),
        )
    except RuleViolation as e:
        if e.auto_fixable:
            warnings.append(str(e))
        else:
            raise

    # 规则5：验收
    try:
        check_rule5_acceptance_required(task)
    except RuleViolation as e:
        if e.auto_fixable:
            warnings.append(str(e))
        else:
            raise

    return warnings
