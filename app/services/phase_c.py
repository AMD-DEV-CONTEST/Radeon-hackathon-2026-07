"""Project-scoped adapters for the Phase C task and report implementation.

Phase F integration: ``load_tasks()`` now prioritizes the SQLite task DB.
When the DB contains confirmed (non-pending) tasks, those are used for
report generation.  CSV / XLSX files remain the fallback.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from app.config import Settings
from app.llm.client import LLMClient
from app.reports.generator import (
    TaskEvaluation as InternalTaskEvaluation,
    TaskStatus as InternalTaskStatus,
    evaluate_with_llm,
    evaluate_with_rules,
    generate_next_week_plan,
    generate_risk_csv,
)
from app.schemas import Evidence, ReportDraft, Task, TaskEvaluation, TaskStatus
from app.security.paths import ensure_project_path, validate_project_id
from app.tools.task_checker import _parse_date
from app.tools.task_reader import TaskRecord, read_tasks

logger = logging.getLogger(__name__)

_DEFAULT_TASK_FILES = ("tasks.xlsx", "tasks.csv", "任务表.xlsx", "任务表.csv")


@dataclass(frozen=True)
class ReportBundle:
    markdown: str
    risk_csv: str
    next_week_plan: str


def load_tasks(
    project_id: str,
    *,
    settings: Settings | None = None,
    task_relative_path: str | None = None,
) -> list[Task]:
    """Load tasks for report generation.

    Phase F priority:
    1. SQLite task DB — confirmed tasks (not pending_confirmation, not cancelled)
    2. Fallback to CSV / XLSX files in the project source directory
    """
    runtime_settings = settings or Settings()
    project_id = validate_project_id(project_id)

    # ── 1. try SQLite task DB (Phase F) ─────────────────────────────────
    try:
        from app.services.task_lifecycle import TaskLifecycleService

        sqlite_path = Path(runtime_settings.sqlite_path)
        if not sqlite_path.is_dir():
            sqlite_path = sqlite_path.parent
        db_path = sqlite_path / "projects" / project_id / "tasks.db"
        if db_path.exists():
            svc = TaskLifecycleService(db_path)
            confirmed_tasks = svc.list_tasks(project_id)
            # Only use confirmed tasks for reports (exclude pending/cancelled)
            report_ready = [
                t for t in confirmed_tasks
                if t.status not in ("pending_confirmation", "cancelled")
            ]
            if report_ready:
                logger.info(
                    "Phase F: loaded %d tasks from SQLite task DB for project %s",
                    len(report_ready),
                    project_id,
                )
                result: list[Task] = []
                for t in report_ready:
                    parsed: date | None = None
                    if t.due_date:
                        try:
                            parsed = date.fromisoformat(t.due_date)
                        except ValueError:
                            pass
                    result.append(
                        Task(
                            task_id=t.id,
                            title=t.title,
                            owner=t.owner,
                            due_date=parsed,
                            priority=t.priority,
                            acceptance_criteria=t.acceptance_criteria,
                            source_reference=t.source_ref,
                        )
                    )
                return result
    except Exception:
        logger.debug("Phase F task DB not available, falling back to file-based tasks", exc_info=True)

    # ── 2. fallback: CSV / XLSX files ───────────────────────────────────
    source_root = ensure_project_path(runtime_settings.project_root, project_id, "source")
    path = _resolve_task_path(source_root, runtime_settings.project_root, project_id, task_relative_path)
    records = read_tasks(path)
    return [_to_task(record, index) for index, record in enumerate(records, start=1)]


def evaluate_tasks(
    tasks: list[Task], evidence_by_task: dict[str, list[Evidence]] | None = None
) -> list[TaskEvaluation]:
    """Apply Phase C rules and return the repository's public evaluation contract."""
    evidence_by_task = evidence_by_task or {}
    evaluations: list[TaskEvaluation] = []
    for task in tasks:
        evidence = evidence_by_task.get(task.task_id, [])
        internal = evaluate_with_rules(_to_record(task), [item.excerpt for item in evidence])
        evaluations.append(_to_evaluation(task, evidence, internal))
    return evaluations


async def evaluate_tasks_with_llm(
    tasks: list[Task], evidence_by_task: dict[str, list[Evidence]], settings: Settings, *, project_id: str
) -> list[TaskEvaluation]:
    """Keep status rule-owned while using the configured chat model for explanations."""
    client = LLMClient(settings)
    evaluations: list[TaskEvaluation] = []
    for task in tasks:
        evidence = evidence_by_task.get(task.task_id, [])
        internal = await evaluate_with_llm(
            _to_record(task), [item.excerpt for item in evidence], client, project_id=project_id
        )
        evaluations.append(_to_evaluation(task, evidence, internal))
    return evaluations


def render_reports(project_id: str, evaluations: list[TaskEvaluation]) -> ReportDraft:
    """Create the safe, source-linked Markdown report consumed by the runner."""
    project_id = validate_project_id(project_id)
    lines = [f"# Project report: {project_id}", "", "## Task evaluations", ""]
    for evaluation in evaluations:
        lines.extend(
            [
                f"### {evaluation.task_id}",
                f"- Status: `{evaluation.status.value}`",
                f"- Explanation: {evaluation.explanation}",
            ]
        )
        if evaluation.evidence:
            lines.append("- Evidence:")
            lines.extend(
                f"  - `{item.relative_path}` ({item.locator}): {item.excerpt}" for item in evaluation.evidence
            )
        if evaluation.missing_evidence:
            lines.append(f"- Missing evidence: {', '.join(evaluation.missing_evidence)}")
        lines.append("")
    return ReportDraft(project_id=project_id, markdown="\n".join(lines).strip() + "\n", evaluations=evaluations)


def render_report_bundle(
    project_id: str, tasks: list[Task], evaluations: list[TaskEvaluation]
) -> ReportBundle:
    """Render all Phase C artifacts from the same task evaluation result."""
    project_id = validate_project_id(project_id)
    tasks_by_id = {task.task_id: task for task in tasks}
    internal = [
        _to_internal_evaluation(tasks_by_id[evaluation.task_id], evaluation)
        for evaluation in evaluations
    ]
    report = render_reports(project_id, evaluations)
    return ReportBundle(
        markdown=report.markdown,
        risk_csv=generate_risk_csv(internal),
        next_week_plan=generate_next_week_plan(internal, project_name=project_id),
    )


def _resolve_task_path(
    source_root: Path, project_root: Path, project_id: str, task_relative_path: str | None
) -> Path:
    if task_relative_path is None:
        candidates = [source_root / name for name in _DEFAULT_TASK_FILES if (source_root / name).is_file()]
        if len(candidates) != 1:
            raise FileNotFoundError(
                "expected exactly one default task file in source/: " + ", ".join(_DEFAULT_TASK_FILES)
            )
        return candidates[0].resolve()

    candidate = ensure_project_path(project_root, project_id, "source", task_relative_path)
    try:
        candidate.relative_to(source_root.resolve())
    except ValueError as error:
        raise ValueError("task file must remain inside the project source directory") from error
    if not candidate.is_file():
        raise FileNotFoundError(f"Task file not found: {candidate}")
    return candidate


def _to_task(record: TaskRecord, index: int) -> Task:
    digest = hashlib.sha256(f"{index}:{record.title}:{record.assignee}".encode("utf-8")).hexdigest()[:16]
    parsed_deadline = _parse_date(record.deadline)
    due_date = parsed_deadline.date() if isinstance(parsed_deadline, datetime) else parsed_deadline
    return Task(
        task_id=f"task-{digest}",
        title=record.title,
        owner=record.assignee or None,
        due_date=due_date,
        priority=record.priority or None,
        acceptance_criteria=record.acceptance_criteria or None,
        source_reference=record.original_source or None,
    )


def _to_record(task: Task) -> TaskRecord:
    return TaskRecord(
        title=task.title,
        assignee=task.owner or "unassigned",
        deadline=task.due_date.isoformat() if isinstance(task.due_date, date) else "",
        priority=task.priority or "normal",
        acceptance_criteria=task.acceptance_criteria or "",
        original_source=task.source_reference or "",
    )


def _to_evaluation(task: Task, evidence: list[Evidence], internal: object) -> TaskEvaluation:
    missing = internal.check_result.missing_items if internal.check_result else []
    explanation_parts = [internal.evidence_summary]
    if internal.risk_reason:
        explanation_parts.append(f"Risk: {internal.risk_reason}")
    if internal.recommendation:
        explanation_parts.append(f"Recommendation: {internal.recommendation}")
    return TaskEvaluation(
        task_id=task.task_id,
        status=TaskStatus(internal.status.value),
        explanation="\n".join(part for part in explanation_parts if part),
        evidence=evidence,
        missing_evidence=missing,
        risk_level=internal.risk_level,
        risk_reason=internal.risk_reason,
        recommendation=internal.recommendation,
    )


def _to_internal_evaluation(task: Task, evaluation: TaskEvaluation) -> InternalTaskEvaluation:
    return InternalTaskEvaluation(
        task=_to_record(task),
        status=InternalTaskStatus(evaluation.status.value),
        evidence_summary=evaluation.explanation,
        risk_level=evaluation.risk_level,
        risk_reason=evaluation.risk_reason,
        recommendation=evaluation.recommendation,
        evidence_items=[item.excerpt for item in evaluation.evidence],
    )
