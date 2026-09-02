"""Report generator — weekly report, risk CSV, next week plan (Phase C).

Generates:

* Markdown weekly report (per-task evaluation with status, evidence, risk)
* CSV risk list (high-risk items with reasons and action items)
* Next week plan draft (Markdown, non-destructive — never overwrites original
  task list)

Architecture (per WORKPLAN Phase C, line 65):
  Rules determine the task status.
  The LLM is only asked to produce structured explanation and risk reasons.
  If the LLM is unavailable, rule-based fallback is used transparently.
"""

from __future__ import annotations

import csv
import io
import json as _json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from app.tools.task_reader import TaskRecord
from app.tools.task_checker import CheckResult, check_task

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums & data models
# ---------------------------------------------------------------------------


class TaskStatus(str, Enum):
    """Final evaluated task status."""

    COMPLETED = "completed"
    MOSTLY_COMPLETED = "mostly_completed"
    IN_PROGRESS = "in_progress"
    NOT_STARTED = "not_started"
    DELAYED = "delayed"
    NEEDS_CONFIRMATION = "needs_confirmation"
    CANCELLED = "cancelled"


# Status display mapping
_STATUS_DISPLAY: Dict[TaskStatus, str] = {
    TaskStatus.COMPLETED: "已完成",
    TaskStatus.MOSTLY_COMPLETED: "基本完成",
    TaskStatus.IN_PROGRESS: "进行中",
    TaskStatus.NOT_STARTED: "未开始",
    TaskStatus.DELAYED: "已延期",
    TaskStatus.NEEDS_CONFIRMATION: "待确认",
    TaskStatus.CANCELLED: "已取消",
}

_STATUS_EMOJI: Dict[TaskStatus, str] = {
    TaskStatus.COMPLETED: "✅",
    TaskStatus.MOSTLY_COMPLETED: "🟡",
    TaskStatus.IN_PROGRESS: "🔵",
    TaskStatus.NOT_STARTED: "⚪",
    TaskStatus.DELAYED: "🔴",
    TaskStatus.NEEDS_CONFIRMATION: "🟠",
    TaskStatus.CANCELLED: "❌",
}


@dataclass
class TaskEvaluation:
    """Full evaluation for a single task."""

    task: TaskRecord
    status: TaskStatus
    evidence_summary: str = ""
    risk_level: str = "low"  # high / medium / low
    risk_reason: str = ""
    recommendation: str = ""
    evidence_items: List[str] = field(default_factory=list)
    check_result: Optional[CheckResult] = None

    @property
    def display_status(self) -> str:
        return _STATUS_DISPLAY.get(self.status, self.status.value)

    @property
    def status_emoji(self) -> str:
        return _STATUS_EMOJI.get(self.status, "❓")

    @property
    def is_risky(self) -> bool:
        return self.risk_level in ("high", "medium")


# ---------------------------------------------------------------------------
# LLM structured output model (Phase C – explanation + risk only)
# ---------------------------------------------------------------------------


class LLMExplanation(BaseModel):
    """Structured output the LLM must return for a single task.

    Per WORKPLAN Phase C line 65:
    "将任务、证据、规则结果交给模型，仅让模型输出结构化解释和风险原因"
    """

    explanation: str = Field(
        description="Natural-language explanation of why the rule-based "
        "status was assigned, referencing the evidence and criteria "
        "matched or missing"
    )
    risk_reason: str = Field(
        description="Why the risk level is high/medium/low, with concrete "
        "evidence gaps, deadline pressure, or blocker references"
    )
    recommendation: str = Field(
        description="Specific, actionable suggestion (e.g. schedule review, "
        "escalate, gather missing evidence)"
    )


# ---------------------------------------------------------------------------
# LLM prompt (status fixed by rules, LLM only explains)
# ---------------------------------------------------------------------------

_EXPLAIN_PROMPT_TEMPLATE = """你是一个项目进度核验助手。
任务状态已由规则引擎判定完毕，你不需要修改状态。
你只需要输出：结构化解释 + 风险原因 + 行动建议。

=== 任务信息 ===
{task_info}

=== 规则判定结果（已确定，不可更改） ===
状态: {rule_status}
时间状态: {time_status}

=== 证据材料 ===
{evidence_text}

=== 验收标准匹配情况 ===
{ac_detail}

=== 缺失项 ===
{missing_detail}

请严格按照以下JSON格式输出（不要包含任何其他文字）:
{{
  "explanation": "不超过120个中文字符，解释'已{rule_status}'的规则依据",
  "risk_reason": "不超过80个中文字符，说明风险原因",
  "recommendation": "不超过80个中文字符，给出1-2条可执行建议"
}}
"""


def build_explanation_prompt(check_result: CheckResult) -> str:
    """Build an LLM prompt where status is fixed and LLM only explains.

    Per WORKPLAN Phase C: rules own the status, LLM owns the explanation.
    """
    task = check_result.task
    evidence_text = "\n".join(
        # Status is rule-owned. A concise source-labelled excerpt is enough
        # for the model explanation and prevents long repeated RAG prompts.
        f"- [{ei.source or 'unknown'}] {ei.content[:180]}"
        for ei in check_result.evidence_items
    ) or "（无证据）"

    ac_detail = "\n".join(
        f"  - {k}: {v}" for k, v in check_result.acceptance_criteria_matched.items()
    ) or "（无验收标准）"

    missing_detail = "\n".join(f"  - {m}" for m in check_result.missing_items) or "（无缺失项）"

    return _EXPLAIN_PROMPT_TEMPLATE.format(
        task_info=(
            f"标题: {task.title}\n"
            f"负责人: {task.assignee}\n"
            f"截止日期: {task.deadline or '未设置'}\n"
            f"优先级: {task.priority}\n"
            f"验收标准: {task.acceptance_criteria or '无'}"
        ),
        rule_status=check_result.rule_based_status,
        time_status=check_result.time_status,
        evidence_text=evidence_text,
        ac_detail=ac_detail,
        missing_detail=missing_detail,
    )


# ---------------------------------------------------------------------------
# Legacy prompt / parse (kept for backward compatibility)
# ---------------------------------------------------------------------------

_EVALUATION_PROMPT_TEMPLATE = """你是一个项目进度评估助手。请根据以下规则检查结果，判断任务的完成状态与风险。

规则检查结果:
{check_context}

可选的评估状态:
- completed（已完成）: 验收标准全部满足，有交付物证明
- mostly_completed（基本完成）: 主要标准满足，仅有少量次要项缺失
- in_progress（进行中）: 有进展证据但未完成主要验收标准
- not_started（未开始）: 无任何证据/交付物
- delayed（已延期）: 已超截止日期，完成度低
- needs_confirmation（待确认）: 证据不充分，存在矛盾或不确定
- cancelled（已取消）: 任务明确被取消

请按以下JSON格式输出:
{{
  "status": "<状态值>",
  "risk_level": "high|medium|low",
  "risk_reason": "<风险原因，中文>",
  "recommendation": "<建议行动，中文>",
  "evidence_summary": "<证据摘要，中文>"
}}
"""


def build_evaluation_prompt(check_result: CheckResult) -> str:
    """Build legacy LLM evaluation prompt from check result context."""
    return _EVALUATION_PROMPT_TEMPLATE.format(
        check_context=check_result.to_prompt_context()
    )


def parse_llm_response(response: str) -> dict:
    """Parse the LLM JSON response. Falls back to empty dict if parsing fails."""
    try:
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            return _json.loads(response[start:end])
    except (_json.JSONDecodeError, ValueError):
        pass
    return {}


def evaluate_with_rules(task: TaskRecord, evidence_texts: List[str]) -> TaskEvaluation:
    """Evaluate task using only rule-based checking (no LLM)."""
    cr = check_task(task, evidence_texts)

    # Map rule-based status to task status
    rule_to_status: Dict[str, TaskStatus] = {
        "completed": TaskStatus.COMPLETED,
        "mostly_completed": TaskStatus.MOSTLY_COMPLETED,
        "in_progress": TaskStatus.IN_PROGRESS,
        "not_started": TaskStatus.NOT_STARTED,
        "delayed": TaskStatus.DELAYED,
        "needs_confirmation": TaskStatus.NEEDS_CONFIRMATION,
        "cancelled": TaskStatus.CANCELLED,
    }
    status = rule_to_status.get(cr.rule_based_status, TaskStatus.NEEDS_CONFIRMATION)

    # Determine risk level
    risk_level = "low"
    risk_reason = ""

    if status in (TaskStatus.DELAYED, TaskStatus.CANCELLED):
        risk_level = "high"
        risk_reason = f"任务状态为{_STATUS_DISPLAY[status]}"
    elif status == TaskStatus.COMPLETED:
        risk_level = "low"
        risk_reason = "验收标准全部满足，无风险"
    elif status == TaskStatus.MOSTLY_COMPLETED:
        risk_level = "low"
        if cr.missing_items:
            risk_reason = f"基本完成，但部分项存疑：{', '.join(cr.missing_items)}"
        else:
            risk_reason = "基本完成，建议人工确认"
    elif status == TaskStatus.NEEDS_CONFIRMATION:
        risk_level = "medium"
        risk_reason = f"证据不充分，需人工确认{', '.join(cr.missing_items) if cr.missing_items else '进度'}"
    elif status == TaskStatus.NOT_STARTED:
        if cr.time_status == "overdue":
            risk_level = "high"
            risk_reason = "已超截止日期且无进展证据"
        elif cr.time_status == "approaching":
            risk_level = "medium"
            risk_reason = "临近截止日期但未开始"
        else:
            risk_level = "medium"
            risk_reason = "尚未开始"
    elif status == TaskStatus.IN_PROGRESS:
        risk_level = "low"
        risk_reason = "正常推进中"
        if cr.time_status == "approaching":
            risk_level = "medium"
            risk_reason = "临近截止日期，仍在进行中"
    elif cr.missing_items:
        risk_level = "medium"
        risk_reason = f"缺失: {', '.join(cr.missing_items)}"
    else:
        risk_level = "low"
        risk_reason = ""

    # Build evidence summary
    evidence_summary = _build_evidence_summary(cr, status)

    # Build recommendation
    recommendation = _build_recommendation(status, risk_level, cr)

    return TaskEvaluation(
        task=task,
        status=status,
        evidence_summary=evidence_summary,
        risk_level=risk_level,
        risk_reason=risk_reason,
        recommendation=recommendation,
        evidence_items=[ei.content for ei in cr.evidence_items],
        check_result=cr,
    )


# ---------------------------------------------------------------------------
# LLM integration (Phase C – status from rules, explanation from LLM)
# ---------------------------------------------------------------------------


def _extract_llm_json(response: str) -> dict:
    """Extract JSON object from an LLM response string."""
    try:
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            return _json.loads(response[start:end])
    except (_json.JSONDecodeError, ValueError):
        pass
    return {}


async def evaluate_with_llm(
    task: TaskRecord,
    evidence_texts: List[str],
    llm_client: object,
    *,
    project_id: str | None = None,
) -> TaskEvaluation:
    """Evaluate a task: rules determine status, LLM adds explanation.

    Per WORKPLAN Phase C line 65:
    "将任务、证据、规则结果交给模型，仅让模型输出结构化解释和风险原因"

    The LLM is asked only for explanation + risk_reason + recommendation.
    The task status is always determined by rules (never by the LLM).

    Gracefully falls back to rule-only evaluation if the LLM call fails
    (timeout, connection error, invalid output, etc.).

    Parameters
    ----------
    task : TaskRecord
        The task to evaluate.
    evidence_texts : list[str]
        Evidence strings from project materials.
    llm_client : object
        Must expose an async ``generate_text(prompt, system_prompt, temperature)``
        method returning a ``str`` (the current ``app.llm.client.LLMClient``
        satisfies this contract).

    Returns
    -------
    TaskEvaluation
        Status from rules, explanation fields from LLM (or rules if fallback).
    """
    # 1. Rule-based evaluation
    ev = evaluate_with_rules(task, evidence_texts)
    cr = ev.check_result
    if cr is None:
        return ev

    # 2. Build the explanation-only prompt (status is fixed)
    prompt = build_explanation_prompt(cr)
    system_prompt = (
        "你是一个项目进度核验助手。任务状态已由规则引擎确定。"
        "你只需输出解释和风险分析，用中文回复，严格遵循JSON格式。"
    )

    try:
        kwargs = {"prompt": prompt, "system_prompt": system_prompt, "temperature": 0.3}
        if project_id is not None:
            kwargs["project_id"] = project_id
        raw_response = await llm_client.generate_text(**kwargs)
        parsed = _extract_llm_json(raw_response)

        if parsed:
            # Apply LLM outputs (explanation, risk_reason, recommendation)
            if parsed.get("explanation"):
                ev.evidence_summary = parsed["explanation"]
            if parsed.get("risk_reason"):
                ev.risk_reason = parsed["risk_reason"]
            if parsed.get("recommendation"):
                ev.recommendation = parsed["recommendation"]

            logger.info(
                "LLM explanation applied for task '%s' (status=%s)",
                task.title, ev.status.value,
            )
        else:
            logger.warning(
                "LLM returned unparseable JSON for task '%s', using rule fallback",
                task.title,
            )

    except Exception as exc:
        logger.warning(
            "LLM call failed for task '%s' (%s), using rule fallback",
            task.title, exc,
        )

    return ev


async def batch_evaluate_with_llm(
    tasks: Sequence[TaskRecord],
    evidence_map: Dict[str, List[str]],
    llm_client: object,
    concurrency: int = 5,
) -> List[TaskEvaluation]:
    """Evaluate multiple tasks with LLM explanation in batch.

    Tasks are processed sequentially to avoid overwhelming the LLM server
    (most local models handle one request at a time well).

    Parameters
    ----------
    tasks : Sequence[TaskRecord]
        Tasks to evaluate.
    evidence_map : dict[str, list[str]]
        Mapping from task title to evidence text list.
    llm_client : object
        Async LLM client.
    concurrency : int
        Reserved for future parallel evaluation support. Currently unused.

    Returns
    -------
    list[TaskEvaluation]
        One evaluation per task, same order as input.
    """
    evaluations: List[TaskEvaluation] = []
    for task in tasks:
        evidence = evidence_map.get(task.title, [])
        ev = await evaluate_with_llm(task, evidence, llm_client)
        evaluations.append(ev)
    return evaluations


def _build_evidence_summary(cr: CheckResult, status: TaskStatus) -> str:
    parts = []
    parts.append(f"时间状态: {cr.time_status}")
    if cr.evidence_items:
        parts.append(f"共{len(cr.evidence_items)}条证据")
        sources = list(set(ei.source for ei in cr.evidence_items if ei.source))
        if sources:
            parts.append(f"来源: {', '.join(sources[:3])}")
    else:
        parts.append("无证据记录")
    if cr.completion_keywords_found:
        parts.append(f"完成关键词: {', '.join(cr.completion_keywords_found)}")
    if cr.missing_items:
        parts.append(f"缺失: {', '.join(cr.missing_items)}")
    return "；".join(parts)


def _build_recommendation(
    status: TaskStatus, risk_level: str, cr: CheckResult
) -> str:
    if status == TaskStatus.COMPLETED:
        return "任务已完成，建议更新总结文档"
    if status == TaskStatus.DELAYED:
        return f"任务已逾期，建议立即跟进负责人{cr.task.assignee}，明确所需资源和新的完成时间"
    if status == TaskStatus.NOT_STARTED:
        if cr.time_status == "overdue":
            return f"任务严重逾期未启动，建议评估是否仍需执行或取消"
        return f"任务尚未启动，建议负责人{cr.task.assignee}尽快启动"
    if status == TaskStatus.NEEDS_CONFIRMATION:
        return f"证据存在矛盾或不足，需与负责人{cr.task.assignee}确认实际进度"
    if status == TaskStatus.IN_PROGRESS:
        return f"任务进行中，当前进展正常，持续跟踪"
    if status == TaskStatus.MOSTLY_COMPLETED:
        return f"主要工作已基本完成，建议收尾和完善{', '.join(cr.missing_items) if cr.missing_items else '细节'}"
    return "持续跟踪"


# ---------------------------------------------------------------------------
# Weekly report generation
# ---------------------------------------------------------------------------


def generate_weekly_report(
    evaluations: List[TaskEvaluation],
    week_label: Optional[str] = None,
    project_name: str = "",
) -> str:
    """Generate a Markdown weekly progress report.

    Parameters
    ----------
    evaluations : list[TaskEvaluation]
        Evaluated tasks.
    week_label : str, optional
        e.g. "2026-W29". Defaults to current week.
    project_name : str
        Project display name.

    Returns
    -------
    str
        Markdown report content.
    """
    if week_label is None:
        today = date.today()
        iso = today.isocalendar()
        week_label = f"{iso[0]}-W{iso[1]:02d}"

    today_str = date.today().strftime("%Y-%m-%d")

    lines: List[str] = []

    # Header
    lines.append(f"# 项目周报 — {project_name or '未命名项目'}")
    lines.append(f"")
    lines.append(f"**报告周期**: {week_label}")
    lines.append(f"**生成日期**: {today_str}")
    lines.append(f"")

    # Summary stats
    total = len(evaluations)
    status_counts: Dict[str, int] = {}
    for ev in evaluations:
        status_counts[ev.status.value] = status_counts.get(ev.status.value, 0) + 1

    lines.append("## 总体概况")
    lines.append("")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 任务总数 | {total} |")
    for stat_label, status_val in [
        ("已完成", "completed"),
        ("基本完成", "mostly_completed"),
        ("进行中", "in_progress"),
        ("未开始", "not_started"),
        ("已延期", "delayed"),
        ("待确认", "needs_confirmation"),
        ("已取消", "cancelled"),
    ]:
        cnt = status_counts.get(status_val, 0)
        if cnt > 0:
            emoji = _STATUS_EMOJI.get(TaskStatus(status_val), "")
            lines.append(f"| {emoji} {stat_label} | {cnt} |")

    # Risk summary
    high_risk = [ev for ev in evaluations if ev.risk_level == "high"]
    medium_risk = [ev for ev in evaluations if ev.risk_level == "medium"]
    lines.append(f"| 🔴 高风险项 | {len(high_risk)} |")
    lines.append(f"| 🟡 中风险项 | {len(medium_risk)} |")
    lines.append("")

    # Task details
    lines.append("## 任务详情")
    lines.append("")

    for ev in evaluations:
        lines.append(f"### {ev.status_emoji} [{ev.status.value}] {ev.task.title}")
        lines.append("")
        lines.append(f"- **负责人**: {ev.task.assignee}")
        if ev.task.deadline:
            lines.append(f"- **截止日期**: {ev.task.deadline}")
        lines.append(f"- **优先级**: {ev.task.priority}")
        lines.append(f"- **证据摘要**: {ev.evidence_summary}")
        if ev.risk_reason:
            lines.append(f"- **风险等级**: {ev.risk_level.upper()} — {ev.risk_reason}")
        if ev.recommendation:
            lines.append(f"- **建议**: {ev.recommendation}")
        if ev.evidence_items:
            lines.append(f"- **证据数量**: {len(ev.evidence_items)} 条")
        if ev.task.acceptance_criteria:
            lines.append(f"- **验收标准**: {ev.task.acceptance_criteria}")
        lines.append("")

    # High risk focus
    if high_risk:
        lines.append("## ⚠️ 重点关注（高风险项）")
        lines.append("")
        for ev in high_risk:
            lines.append(f"- **{ev.task.title}** — {ev.risk_reason}")
            if ev.recommendation:
                lines.append(f"  - 建议: {ev.recommendation}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Risk CSV generation
# ---------------------------------------------------------------------------


def generate_risk_csv(evaluations: List[TaskEvaluation]) -> str:
    """Generate a CSV risk list of medium+ risk items.

    Columns:
    task_title, assignee, status, risk_level, risk_reason, recommendation,
    deadline, acceptance_criteria
    """
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(
        [
            "task_title",
            "assignee",
            "status",
            "risk_level",
            "risk_reason",
            "recommendation",
            "deadline",
            "acceptance_criteria",
        ]
    )

    risky = [ev for ev in evaluations if ev.risk_level in ("high", "medium")]
    # Sort: high risk first, then medium
    risky.sort(key=lambda x: (0 if x.risk_level == "high" else 1, x.task.title))

    for ev in risky:
        writer.writerow(
            [
                ev.task.title,
                ev.task.assignee,
                ev.display_status,
                ev.risk_level,
                ev.risk_reason,
                ev.recommendation,
                ev.task.deadline,
                ev.task.acceptance_criteria,
            ]
        )

    return output.getvalue()


# ---------------------------------------------------------------------------
# Next week plan generation
# ---------------------------------------------------------------------------


def generate_next_week_plan(
    evaluations: List[TaskEvaluation],
    project_name: str = "",
    week_label: Optional[str] = None,
) -> str:
    """Generate a next-week plan draft in Markdown.

    This is a **draft only** — it never modifies or overwrites the user's
    original task list.  It suggests continuation work for in-progress
    tasks, remediation for delayed tasks, and new starters for not-started
    tasks.

    Parameters
    ----------
    evaluations : list[TaskEvaluation]
        Evaluated tasks.
    project_name : str
        Project display name.
    week_label : str, optional
        Target week label.  Defaults to next week.

    Returns
    -------
    str
        Markdown plan draft.
    """
    today = date.today()
    next_monday = today + timedelta(days=(7 - today.weekday()))

    if week_label is None:
        iso = next_monday.isocalendar()
        week_label = f"{iso[0]}-W{iso[1]:02d}"

    lines: List[str] = []

    lines.append(f"# 下周计划（草案）— {project_name or '未命名项目'}")
    lines.append("")
    lines.append(
        f"> **注意**: 本文件为自动生成的计划草案，仅作为参考。"
        f"请勿直接覆盖原始任务列表。"
    )
    lines.append(f"> **目标周期**: {week_label}（{next_monday.strftime('%Y-%m-%d')} 起）")
    lines.append("")

    # Group tasks by status
    in_progress = [ev for ev in evaluations if ev.status == TaskStatus.IN_PROGRESS]
    not_started = [ev for ev in evaluations if ev.status == TaskStatus.NOT_STARTED]
    delayed = [ev for ev in evaluations if ev.status == TaskStatus.DELAYED]
    needs_confirm = [
        ev for ev in evaluations if ev.status == TaskStatus.NEEDS_CONFIRMATION
    ]
    mostly_done = [
        ev for ev in evaluations if ev.status == TaskStatus.MOSTLY_COMPLETED
    ]

    # --- Continue tasks ---
    if in_progress or mostly_done:
        lines.append("## 需要继续推进的任务")
        lines.append("")
        for ev in in_progress + mostly_done:
            lines.append(
                f"- **{ev.task.title}** ({ev.task.assignee})"
            )
            if ev.check_result and ev.check_result.missing_items:
                lines.append(
                    f"  - 待补充: {', '.join(ev.check_result.missing_items)}"
                )
            if ev.recommendation:
                lines.append(f"  - {ev.recommendation}")
        lines.append("")

    # --- Delayed tasks (urgent) ---
    if delayed:
        lines.append("## 🔴 逾期任务 — 需立即处理")
        lines.append("")
        for ev in delayed:
            lines.append(
                f"- **{ev.task.title}** ({ev.task.assignee})"
                f" — 截止: {ev.task.deadline or '未设'}"
            )
            lines.append(f"  - {ev.recommendation}")
        lines.append("")

    # --- Needs confirmation ---
    if needs_confirm:
        lines.append("## 🟠 待确认事项")
        lines.append("")
        for ev in needs_confirm:
            lines.append(
                f"- **{ev.task.title}** ({ev.task.assignee})"
            )
            lines.append(f"  - {ev.recommendation}")
        lines.append("")

    # --- New starters ---
    if not_started:
        lines.append("## 需要启动的任务")
        lines.append("")
        for ev in not_started:
            overdue = (
                " [已逾期]"
                if ev.check_result and ev.check_result.time_status == "overdue"
                else ""
            )
            lines.append(
                f"- **{ev.task.title}** ({ev.task.assignee})"
                f" — 截止: {ev.task.deadline or '未设'}"
                f"{overdue}"
            )
            lines.append(f"  - {ev.recommendation}")
        lines.append("")

    # --- Next week focus ---
    lines.append("## 下周重点")
    lines.append("")

    focus_items: List[str] = []
    if delayed:
        focus_items.append(f"{len(delayed)} 项逾期任务需要赶工")
    if in_progress:
        focus_items.append(f"{len(in_progress)} 项进行中任务持续推进")
    if not_started:
        overdue_starters = [
            ev
            for ev in not_started
            if ev.check_result and ev.check_result.time_status == "overdue"
        ]
        if overdue_starters:
            focus_items.append(
                f"{len(overdue_starters)} 项未启动任务已逾期，需决策继续或取消"
            )
        else:
            focus_items.append(f"{len(not_started)} 项任务待启动")
    if needs_confirm:
        focus_items.append(f"{len(needs_confirm)} 项待确认任务需尽快澄清")

    for item in focus_items:
        lines.append(f"- {item}")

    lines.append("")
    lines.append("---")
    lines.append(f"*草案生成时间: {date.today().strftime('%Y-%m-%d')}*")

    return "\n".join(lines)
