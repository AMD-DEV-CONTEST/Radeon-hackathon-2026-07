"""
Iron Law — 巡检逻辑
对任务包做内容层面的合规性检查，发现问题后尝试自动修复。
"""
from __future__ import annotations

import re
from typing import Any


# ── 校验规则库 ────────────────────────────────────────────────────────

# agent_type → 合法的 acceptance_check command 关键词
AGENT_ACCEPTABLE_COMMANDS: dict[str, list[str]] = {
    "claude_code": ["pytest", "curl", "python", "grep", "test", "cat", "ls", "bash"],
    "codex":       ["pnpm", "npm", "npx", "jest", "vitest", "tsc", "node", "pytest", "curl"],
    "reasonix":    ["pytest", "curl", "python", "bash", "ls", "cat", "grep"],
    "generic":     [],  # 不限制
}

# 明确错误的命令模式
FORBIDDEN_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"pnpm\s+build"), "pnpm build 不适合验收后端/Python 服务", "pytest -q"),
    (re.compile(r"npm\s+run\s+build"), "npm run build 不适合验收后端服务", "pytest -q"),
    (re.compile(r"rm\s+-rf"), "acceptance_check 不应包含删除操作", None),
    (re.compile(r"DROP\s+TABLE", re.I), "acceptance_check 不应包含 DDL 操作", None),
]

REQUIRED_TASK_FIELDS = ["title", "acceptance_check"]


def check_single_task(task: dict[str, Any]) -> list[dict[str, Any]]:
    """检查单个任务，返回问题列表。"""
    issues: list[dict[str, Any]] = []
    title = task.get("title", "(untitled)")
    agent_type = (task.get("required_capabilities") or {}).get("agent", "") or \
                 (task.get("required_capabilities") or {}).get("agent_type", "")

    # 1. 必填字段
    for field in REQUIRED_TASK_FIELDS:
        if not task.get(field):
            issues.append({
                "field": field,
                "reason": f"任务 '{title}' 缺少必填字段 {field}",
                "can_auto_fix": False,
                "fix": None,
            })

    # 2. context 检查
    payload = task.get("payload") or {}
    ctx = payload.get("context") or task.get("context")
    if not ctx or not ctx.get("goal"):
        issues.append({
            "field": "payload.context.goal",
            "reason": f"任务 '{title}' 缺少 context.goal，Agent 接单后没有目标方向",
            "can_auto_fix": False,
            "fix": None,
        })

    # 3. acceptance_check 内容检查
    ac = task.get("acceptance_check") or {}
    if ac.get("type") == "command":
        cmd = ac.get("command", [])
        cmd_str = " ".join(str(c) for c in cmd)

        # 检查禁止模式
        for pattern, reason, suggestion in FORBIDDEN_PATTERNS:
            if pattern.search(cmd_str):
                fix = None
                if suggestion and agent_type:
                    fix = {"type": "command", "command": [suggestion], "expected_exit_code": 0}
                issues.append({
                    "field": "acceptance_check.command",
                    "reason": f"[{title}] {reason}。当前: {cmd_str!r}",
                    "can_auto_fix": fix is not None,
                    "fix": {"acceptance_check": fix} if fix else None,
                })

        # 检查 agent_type 适配性
        if agent_type in AGENT_ACCEPTABLE_COMMANDS:
            allowed = AGENT_ACCEPTABLE_COMMANDS[agent_type]
            if allowed:  # generic 不限制
                first_cmd = cmd[0] if cmd else ""
                if first_cmd and not any(a in first_cmd for a in allowed):
                    issues.append({
                        "field": "acceptance_check.command",
                        "reason": (
                            f"命令 '{first_cmd}' 与 agent_type='{agent_type}' 不匹配。"
                            f"该类型 Agent 推荐使用: {', '.join(allowed[:4])}"
                        ),
                        "can_auto_fix": False,
                        "fix": None,
                    })

    # 4. 粒度检查
    estimated_hours = payload.get("estimated_hours")
    if estimated_hours is not None and float(estimated_hours) > 1.0:
        issues.append({
            "field": "payload.estimated_hours",
            "reason": f"任务 '{title}' 估时 {estimated_hours}h 超过 1 小时铁律上限，建议拆分",
            "can_auto_fix": True,
            "fix": None,  # 拆分需要 LLM 参与，标记但不自动修
        })

    # 5. max_turns 检查
    max_turns = task.get("max_turns") or payload.get("max_turns")
    if max_turns is not None and int(max_turns) < 30:
        issues.append({
            "field": "max_turns",
            "reason": f"max_turns={max_turns} 过低，建议至少 60",
            "can_auto_fix": True,
            "fix": {"max_turns": 60},
        })

    return issues


def check_dag(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """检查整个任务 DAG：单任务 + 依赖关系 + 全局合规。"""
    all_issues: list[dict[str, Any]] = []
    fixed_tasks: list[dict[str, Any]] = []
    any_not_fixable = False

    task_ids = {t.get("id") or t.get("title") for t in tasks}

    for task in tasks:
        issues = check_single_task(task)
        all_issues.extend(issues)

        # 应用可自动修复的问题
        fixed = dict(task)
        for issue in issues:
            if issue["can_auto_fix"] and issue["fix"]:
                fixed.update(issue["fix"])
            elif not issue["can_auto_fix"]:
                any_not_fixable = True
        fixed_tasks.append(fixed)

        # 依赖关系检查
        for dep in task.get("dependencies", []):
            if dep not in task_ids:
                all_issues.append({
                    "field": "dependencies",
                    "reason": f"任务 '{task.get('title')}' 依赖 '{dep}' 不在本次 DAG 中",
                    "can_auto_fix": False,
                    "fix": None,
                })
                any_not_fixable = True

    can_auto_fix = not any_not_fixable and all(i["can_auto_fix"] for i in all_issues if not i["can_auto_fix"] is None)

    return {
        "compliant": len(all_issues) == 0,
        "issues": all_issues,
        "can_auto_fix": can_auto_fix and len(all_issues) > 0,
        "fixed_data": {"tasks": fixed_tasks} if all_issues else None,
        "summary": f"{len(all_issues)} 个问题，{'可自动修复' if can_auto_fix else '需人工介入'}",
    }


def check_structuring(data: dict[str, Any]) -> dict[str, Any]:
    """检查结构化输出：必要字段是否完整。"""
    issues = []
    required = ["objective", "tasks"]
    for field in required:
        if not data.get(field):
            issues.append({
                "field": field,
                "reason": f"结构化输出缺少 {field} 字段",
                "can_auto_fix": False,
                "fix": None,
            })
    return {
        "compliant": len(issues) == 0,
        "issues": issues,
        "can_auto_fix": False,
        "fixed_data": None,
    }


def check_final(data: dict[str, Any]) -> dict[str, Any]:
    """检查最终交付：是否有完整 summary 和 acceptance_result。"""
    issues = []
    summary = data.get("summary", "")
    if not summary or len(summary) < 20:
        issues.append({
            "field": "summary",
            "reason": "完成报告 summary 太短或为空，Agent 必须写清楚做了什么",
            "can_auto_fix": False,
            "fix": None,
        })
    if data.get("acceptance_result") != "pass":
        issues.append({
            "field": "acceptance_result",
            "reason": f"验收结果不是 pass（当前: {data.get('acceptance_result')}），不能标记 done",
            "can_auto_fix": False,
            "fix": None,
        })
    return {
        "compliant": len(issues) == 0,
        "issues": issues,
        "can_auto_fix": False,
        "fixed_data": None,
    }
