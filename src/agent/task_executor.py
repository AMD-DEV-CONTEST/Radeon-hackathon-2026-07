"""Practical multi-step task executor (plan → tools → deliverable)."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.agent.planner import build_task_plan
from src.agent.tools import ToolRegistry
from src.agent.workflow import match_workflow, run_workflow


@dataclass
class TaskExecution:
    goal: str
    plan: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    deliverable: str = ""


def execute_practical_task(tools: ToolRegistry, goal: str) -> TaskExecution:
    """Run a concrete office task with tools; produce a usable deliverable."""
    plan = build_task_plan(goal)
    actions: list[str] = []
    parts: list[str] = [f"## 任务目标\n{goal}", "## 执行计划"]
    parts.extend(f"{i}. {s}" for i, s in enumerate(plan, 1))

    wf_id = match_workflow(goal)
    if wf_id:
        wf = run_workflow(tools, wf_id)
        actions.append(f"workflow:{wf_id}")
        parts.append("## 工作流结果")
        parts.append(wf.summary)
        return TaskExecution(goal=goal, plan=plan, actions=actions, deliverable="\n".join(parts))

    kb = tools.run("kb_search", {"query": goal}).output
    actions.append("kb_search")
    mem = tools.run("recall_memory", {}).output
    actions.append("recall_memory")
    files = tools.run("list_files", {}).output
    actions.append("list_files")
    tools.run("write_note", {"note": f"任务执行备忘: {goal[:120]}"})
    actions.append("write_note")

    parts.append("## 知识库证据\n" + kb[:2000])
    parts.append("## 本地记忆\n" + mem[:800])
    parts.append("## 本地文件\n" + files)
    parts.append(
        "## 可执行下一步\n"
        "- 根据证据完成申请/变更\n"
        "- 如需生成工程文件：使用开发技能脚手架\n"
        "- 如需正式制度：以知识库原文为准"
    )
    return TaskExecution(goal=goal, plan=plan, actions=actions, deliverable="\n".join(parts))
