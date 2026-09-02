"""Change Impact Analysis (Stage G).

After a material file is updated (SHA-256 change detected), this module:
1. Identifies tasks that reference the changed file (via source_ref or evidence).
2. Identifies reports generated from the changed file.
3. Produces a ranked impact report with severity levels.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ImpactEntry(BaseModel):
    """A single impact entry describing one affected entity."""
    entity_type: str = "task"
    entity_id: str = ""
    entity_title: str = ""
    impact_type: str = "reference_changed"
    reason: str = ""
    severity: str = "medium"
    source_file: str = ""


class ImpactReport(BaseModel):
    """Full change impact analysis report."""
    project_id: str
    changed_files: list[str] = []
    total_affected: int = 0
    affected_tasks: list[ImpactEntry] = []
    affected_reports: list[ImpactEntry] = []
    generated_at: str = ""


@dataclass
class ChangeImpactAnalyzer:
    """Analyses the impact of document changes on tasks and reports."""

    conn: sqlite3.Connection
    project_id: str

    def analyse(
        self,
        changed_files: list[str],
    ) -> ImpactReport:
        """Produce an impact report for a set of changed files.

        Args:
            changed_files: List of relative paths that have changed.

        Returns:
            :class:`ImpactReport` with affected tasks and reports.
        """
        affected_tasks: list[ImpactEntry] = []
        affected_reports: list[ImpactEntry] = []

        for fp in changed_files:
            # Check tasks that have source_ref pointing to this file
            task_entries = self._find_tasks_by_source_file(fp)
            affected_tasks.extend(task_entries)

            # Check tasks that have evidence from this file
            evidence_entries = self._find_tasks_by_evidence_file(fp)
            affected_tasks.extend(evidence_entries)

            # Check reports that reference this file
            report_entries = self._find_reports_by_source_file(fp)
            affected_reports.extend(report_entries)

        # Deduplicate by entity_id
        seen_tasks: set[str] = set()
        unique_tasks: list[ImpactEntry] = []
        for entry in affected_tasks:
            if entry.entity_id not in seen_tasks:
                seen_tasks.add(entry.entity_id)
                unique_tasks.append(entry)

        seen_reports: set[str] = set()
        unique_reports: list[ImpactEntry] = []
        for entry in affected_reports:
            if entry.entity_id not in seen_reports:
                seen_reports.add(entry.entity_id)
                unique_reports.append(entry)

        return ImpactReport(
            project_id=self.project_id,
            changed_files=list(changed_files),
            total_affected=len(unique_tasks) + len(unique_reports),
            affected_tasks=unique_tasks,
            affected_reports=unique_reports,
            generated_at=datetime.now().isoformat(timespec="seconds"),
        )

    def _find_tasks_by_source_file(self, relative_path: str) -> list[ImpactEntry]:
        """Find tasks whose source_ref contains the given path."""
        entries: list[ImpactEntry] = []
        task_table = self._task_table()
        if task_table is None:
            return entries
        try:
            cursor = self.conn.execute(
                f"SELECT id, title, status, source_ref FROM {task_table} WHERE project_id = ? AND source_ref LIKE ?",
                (self.project_id, f"%{relative_path}%"),
            )
            for row in cursor.fetchall():
                entries.append(ImpactEntry(
                    entity_type="task",
                    entity_id=row[0],
                    entity_title=row[1] or "",
                    impact_type="source_reference_changed",
                    reason=f"任务「{row[1]}」的源引用指向已变更文件 {relative_path}",
                    severity="medium" if row[2] in ("completed",) else "high",
                    source_file=relative_path,
                ))
        except sqlite3.OperationalError:
            pass  # Table may not exist yet
        return entries

    def _find_tasks_by_evidence_file(self, relative_path: str) -> list[ImpactEntry]:
        """Find tasks whose evidence references point to the given path."""
        entries: list[ImpactEntry] = []
        task_table = self._task_table()
        if task_table is None:
            return entries
        try:
            cursor = self.conn.execute(
                f"""SELECT te.task_id, t.title, t.status
                   FROM task_evidence te
                   JOIN {task_table} t ON te.task_id = t.id AND te.project_id = t.project_id
                   WHERE te.project_id = ? AND te.evidence_path LIKE ?""",
                (self.project_id, f"%{relative_path}%"),
            )
            for row in cursor.fetchall():
                entries.append(ImpactEntry(
                    entity_type="task",
                    entity_id=row[0],
                    entity_title=row[1] or "",
                    impact_type="evidence_changed",
                    reason=f"任务「{row[1]}」的证据材料指向已变更文件 {relative_path}",
                    severity="high",
                    source_file=relative_path,
                ))
        except sqlite3.OperationalError:
            pass
        return entries

    def _task_table(self) -> str | None:
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('task', 'tasks')"
        ).fetchall()
        names = {row[0] for row in rows}
        if "task" in names:
            return "task"
        if "tasks" in names:
            return "tasks"
        return None

    def _find_reports_by_source_file(self, relative_path: str) -> list[ImpactEntry]:
        """Find reports (runs) that reference the given source file."""
        entries: list[ImpactEntry] = []
        try:
            cursor = self.conn.execute(
                "SELECT run_id, status FROM runs WHERE project_id = ? AND error LIKE ?",
                (self.project_id, f"%{relative_path}%"),
            )
            for row in cursor.fetchall():
                entries.append(ImpactEntry(
                    entity_type="report",
                    entity_id=row[0],
                    entity_title=f"Report {row[0]}",
                    impact_type="report_source_changed",
                    reason=f"报告 {row[0]} 的源资料 {relative_path} 已变更，可能需要重新生成",
                    severity="medium",
                    source_file=relative_path,
                ))
        except sqlite3.OperationalError:
            pass
        return entries


def persist_impact_report(
    conn: sqlite3.Connection,
    report: ImpactReport,
) -> None:
    """Persist all impact entries from a report to the change_impact table."""
    from app.services.doc_version import record_change_impact

    for entry in report.affected_tasks:
        record_change_impact(
            conn,
            report.project_id,
            entry.source_file,
            0,
            entry.entity_type,
            entry.entity_id,
            entry.reason,
            entry.severity,
        )
    for entry in report.affected_reports:
        record_change_impact(
            conn,
            report.project_id,
            entry.source_file,
            0,
            entry.entity_type,
            entry.entity_id,
            entry.reason,
            entry.severity,
        )
