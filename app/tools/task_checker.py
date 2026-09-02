"""Rule-based task checker (Phase C).

Checks each task against its evidence using deterministic rules first,
then provides structured data for LLM-based evaluation.

Rules include:

* Time check — is the task already past its deadline?
* Deliverable check — do we have files/docs/records as evidence?
* Completion keyword check — do evidence texts contain "完成"/"done"/etc?
* Acceptance criteria check — do we have partial/complete match against
  acceptance criteria keywords?
* Missing items check — what key outputs are still absent?

Results are passed to the LLM for final structured explanation and risk
reasons.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from app.tools.task_reader import TaskRecord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """Result of rule-based checking for a single task."""

    task: TaskRecord
    evidence_items: List[EvidenceItem] = field(default_factory=list)
    time_status: str = "on_track"  # on_track / approaching / overdue
    has_deliverables: bool = False
    completion_keywords_found: List[str] = field(default_factory=list)
    acceptance_criteria_matched: Dict[str, str] = field(default_factory=dict)
    missing_items: List[str] = field(default_factory=list)
    rule_based_status: str = "not_started"

    def to_prompt_context(self) -> str:
        """Format check result as a prompt-friendly string for LLM evaluation."""
        lines = [
            f"任务: {self.task.title}",
            f"负责人: {self.task.assignee}",
            f"截止日期: {self.task.deadline or '未设置'}",
            f"优先级: {self.task.priority}",
            f"验收标准: {self.task.acceptance_criteria or '无'}",
            f"时间状态: {self.time_status}",
            f"有交付物: {'是' if self.has_deliverables else '否'}",
            f"完成关键词: {', '.join(self.completion_keywords_found) if self.completion_keywords_found else '无'}",
        ]
        if self.acceptance_criteria_matched:
            lines.append("验收标准匹配:")
            for k, v in self.acceptance_criteria_matched.items():
                lines.append(f"  - {k}: {v}")
        if self.missing_items:
            lines.append(f"缺失项: {', '.join(self.missing_items)}")
        if self.evidence_items:
            lines.append("证据片段:")
            for ei in self.evidence_items[:5]:  # 最多5条
                lines.append(f"  [{ei.source}] {ei.content[:200]}")
        return "\n".join(lines)


@dataclass
class EvidenceItem:
    """A single piece of evidence retrieved for a task."""

    content: str
    source: str = ""
    date: Optional[str] = None


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------

_COMPLETION_KEYWORDS_CN: List[str] = [
    "已完成",
    "完成",
    "已交付",
    "已上线",
    "已发布",
    "已验收",
    "通过测试",
    "done",
    "completed",
    "finished",
    "resolved",
    "closed",
    "已关闭",
    "已解决",
    "已修复",
]

_CANCEL_KEYWORDS: List[str] = [
    "已取消",
    "取消",
    "废弃",
    "不再维护",
    "已下线",
    "作废",
    "下架",
    "终止",
    "停用",
    "deprecated",
    "cancelled",
    "canceled",
    "obsolete",
    "abandoned",
    "removed",
]

_PARTIAL_PROGRESS_PATTERNS: List[str] = [
    r"预计完成\s*\d+%",
    r"完成约\s*\d+%",
    r"完成\s*\d+%",
    r"进度\s*\d+%",
    r"正在进行中",
    r"还在.*中",
    r"仍在.*中",
    r"尚未完成",
    r"未完成",
    r"进行中",
    r"开发中",
    r"编写中",
    r"整理中",
]

_ACCEPTANCE_KEYWORDS: Dict[str, List[str]] = {
    "测试": ["测试", "test", "testing", "压测", "自动化测试", "测试报告", "test report"],
    "文档": ["文档", "doc", "document", "readme", "说明", "手册", "wiki"],
    "报告": ["报告", "report", "总结", "summary", "周报", "日报"],
    "代码": ["代码", "code", "pr", "merge", "合入", "提交", "commit", "分支", "branch"],
    "部署": ["部署", "deploy", "上线", "release", "发版", "灰度", "rollout"],
    "评审": ["评审", "review", "code review", "评审通过", "approve", "lgtm"],
    "验收": ["验收", "acceptance", "uat", "签收", "确认"],
}

_MISSING_INDICATORS: Dict[str, List[str]] = {
    "报告": ["报告", "report", "总结", "summary"],
    "测试结果": ["测试结果", "test result", "test report", "测试报告"],
    "代码合入": ["代码合入", "merge", "pr", "pull request"],
    "文档": ["文档", "documentation", "readme"],
    "评审记录": ["评审", "review", "approve"],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_task(
    task: TaskRecord, evidence_texts: Optional[List[str]] = None
) -> CheckResult:
    """Run rule-based checks on a single task.

    Parameters
    ----------
    task : TaskRecord
        The task to check.
    evidence_texts : list[str], optional
        Evidence content strings retrieved from project materials
        (e.g. RAG search results, meeting notes, commit logs, etc.)

    Returns
    -------
    CheckResult
    """
    evidence_texts = evidence_texts or []

    # Build evidence items with date extraction
    evidence_items = _build_evidence_items(evidence_texts)
    combined_text = " ".join(evidence_texts).lower()

    # Time check
    time_status = _check_time(task.deadline)

    # Deliverable check
    has_deliverables = len(evidence_texts) > 0

    # Cancel keywords (check before completion to catch abandoned tasks)
    cancel_kw = _find_cancel_keywords(combined_text)

    # Completion keywords
    completion_kw = _find_completion_keywords(combined_text)

    # Detect partial-progress indicators that weaken completion signal
    partial_kw = _find_partial_progress(combined_text)

    # Acceptance criteria matching
    ac_matched = _match_acceptance_criteria(task.acceptance_criteria, combined_text)

    # Missing items
    missing = _find_missing_items(task, combined_text, evidence_items)

    # Rule-based preliminary status
    rule_status = _determine_rule_status(
        task, time_status, has_deliverables, completion_kw,
        cancel_kw, partial_kw, ac_matched, missing,
    )

    return CheckResult(
        task=task,
        evidence_items=evidence_items,
        time_status=time_status,
        has_deliverables=has_deliverables,
        completion_keywords_found=completion_kw,
        acceptance_criteria_matched=ac_matched,
        missing_items=missing,
        rule_based_status=rule_status,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _check_time(deadline_str: str) -> str:
    """Determine time status from deadline string."""
    if not deadline_str:
        return "no_deadline"

    today = date.today()
    deadline = _parse_date(deadline_str)
    if deadline is None:
        return "no_deadline"

    deadline_date = deadline.date() if isinstance(deadline, datetime) else deadline
    diff = (deadline_date - today).days

    if diff < 0:
        return "overdue"
    elif diff <= 3:
        return "approaching"
    return "on_track"


def _parse_date(s: str) -> Optional[date | datetime]:
    """Try multiple common date formats."""
    formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%Y年%m月%d日",
        "%Y%m%d",
    ]
    s = s.strip()
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # Try to extract a YYYY-MM-DD pattern
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


def _build_evidence_items(texts: List[str]) -> List[EvidenceItem]:
    items: List[EvidenceItem] = []
    for t in texts:
        source = ""
        date_val = None
        # Try to extract metadata prefix like "[source:xxx]" or "[date:xxx]"
        sm = re.match(r"\[source:(.+?)\](.*)", t)
        if sm:
            source = sm.group(1).strip()
            t = sm.group(2).strip()
        dm = re.match(r"\[date:(.+?)\](.*)", t)
        if dm:
            date_val = dm.group(1).strip()
            t = dm.group(2).strip()
        items.append(EvidenceItem(content=t.strip(), source=source, date=date_val))
    return items


def _find_completion_keywords(text: str) -> List[str]:
    found: List[str] = []
    text_lower = text.lower()
    for kw in _COMPLETION_KEYWORDS_CN:
        if kw.lower() in text_lower:
            found.append(kw)
    return found


def _find_cancel_keywords(text: str) -> List[str]:
    """Detect cancellation/abandonment keywords in evidence."""
    found: List[str] = []
    text_lower = text.lower()
    for kw in _CANCEL_KEYWORDS:
        if kw.lower() in text_lower:
            found.append(kw)
    return found


def _find_partial_progress(text: str) -> List[str]:
    """Detect patterns indicating work is in-progress, not completed.

    Examples: "预计完成40%", "正在开发中", "还在整理中"
    """
    found: List[str] = []
    for pattern in _PARTIAL_PROGRESS_PATTERNS:
        if re.search(pattern, text):
            found.append(pattern)
    return found


def _match_acceptance_criteria(criteria: str, evidence_text: str) -> Dict[str, str]:
    """Match acceptance criteria items against evidence.

    Matching strategy (three-tier, stop on first hit):

    1. Exact match — the criteria phrase appears as a contiguous substring.
    2. Semantic char match — Chinese-dominant phrases are split into
       individual characters; >= 75% of them must appear in the evidence.
       Common connector chars (和与及或的了等) are excluded from scoring.
       This handles cases like "测试通过" matching "测试全部100%通过" and
       "API文档和测试通过" matching "API文档完成 测试通过".
    3. Not matched.
    """
    # Connector characters excluded from semantic matching so that
    # "API文档和测试通过" can still match "API文档完成，测试通过"
    _CONNECTOR_CHARS = frozenset("和与及或的了等也加")

    if not criteria:
        return {}
    parts = re.split(r"[；;，,、\n]", criteria)
    parts = [p.strip() for p in parts if p.strip()]
    result: Dict[str, str] = {}
    for part in parts:
        # 1. Exact substring match
        if part.lower() in evidence_text:
            result[part] = "matched（精确匹配）"
            continue

        # 2. Semantic char match: extract Chinese chars + ASCII tokens,
        #    exclude connectors, require ALL remaining chars present.
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", part)
        word_tokens = re.findall(r"[a-zA-Z0-9_]+", part)

        meaningful_chars = [c for c in chinese_chars if c not in _CONNECTOR_CHARS]
        all_items: list[str] = meaningful_chars + word_tokens

        if len(all_items) >= 2 and all(
            item.lower() in evidence_text for item in all_items
        ):
            result[part] = "matched（语义匹配）"
            continue

        # 3. Not matched
        result[part] = "not_matched"
    return result


def _find_missing_items(
    task: TaskRecord, evidence_text: str, evidence_items: List[EvidenceItem]
) -> List[str]:
    """Identify expected but missing deliverables."""
    missing: List[str] = []
    if task.acceptance_criteria:
        # Check if acceptance criteria items are covered in evidence
        matched_any = any(
            v != "not_matched"
            for v in _match_acceptance_criteria(task.acceptance_criteria, evidence_text).values()
        )
        if not matched_any and task.acceptance_criteria:
            missing.append("验收标准未匹配到证据")

    # Check if no evidence at all
    if not evidence_items:
        missing.append("无任何证据/交付物记录")
        return missing

    # Check specific missing categories
    combined = evidence_text
    for category, indicators in _MISSING_INDICATORS.items():
        found_any = any(ind.lower() in combined for ind in indicators)
        # Only flag as missing if the task title/ac hints at this category
        task_text = f"{task.title} {task.acceptance_criteria}".lower()
        if any(ind.lower() in task_text for ind in indicators) and not found_any:
            missing.append(f"可能缺失: {category}")

    return missing


def _determine_rule_status(
    task: TaskRecord,
    time_status: str,
    has_deliverables: bool,
    completion_kw: List[str],
    cancel_kw: List[str],
    partial_kw: List[str],
    ac_matched: Dict[str, str],
    missing: List[str],
) -> str:
    """Determine preliminary status based on rule results.

    Priority order:
    1. cancelled — explicit cancel keywords in evidence (highest)
    2. not_started — no evidence at all
    3. delayed — overdue + insufficient completion
    4. in_progress — evidence but no completion keywords
    5. mostly_completed — completion keywords found, but AC partially
       matched OR partial-progress signals detected
    6. completed — all criteria matched, no missing items, no partial
    7. needs_confirmation — contradictory or insufficient signals
    """
    # Cancel keywords → cancelled (highest priority)
    if cancel_kw:
        return "cancelled"

    if not has_deliverables:
        return "not_started"

    # No completion keywords at all → in_progress or delayed
    if not completion_kw:
        if time_status == "overdue":
            return "delayed"
        return "in_progress"

    # Has completion keywords — now check AC and missing items
    if time_status == "overdue":
        return "delayed"

    # Check acceptance criteria matching
    not_matched: List[str] = [k for k, v in ac_matched.items() if v == "not_matched"]
    num_matched = len(ac_matched) - len(not_matched)
    total_criteria = len(ac_matched)
    no_criteria = total_criteria == 0
    all_matched = len(not_matched) == 0 and total_criteria > 0

    # No AC defined → judge by missing items
    if no_criteria:
        if missing:
            return "needs_confirmation"
        return "completed"

    # All criteria matched, no missing, no partial-progress → completed
    if all_matched and not missing and not partial_kw:
        return "completed"

    # All criteria matched, no missing, but partial-progress found → mostly_completed
    if all_matched and not missing and partial_kw:
        return "mostly_completed"

    # All criteria matched, some missing → mostly_completed
    # BUT if partial-progress signals exist AND there are multiple missing
    # items, downgrade to needs_confirmation (e.g. "系统测试" sceneario)
    if all_matched and missing:
        if partial_kw and len(missing) >= 2:
            return "needs_confirmation"
        return "mostly_completed"

    # Strict majority (> 50%) of criteria matched → mostly_completed
    # BUT if partial-progress signals are detected, the "matched" criteria
    # may be in-progress rather than truly done, requiring human confirmation
    if num_matched > total_criteria * 0.5:
        if partial_kw and missing:
            return "needs_confirmation"
        return "mostly_completed"
        return "mostly_completed"

    # Few criteria matched, completion keywords present → needs_confirmation
    return "needs_confirmation"
