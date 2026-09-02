"""Scheduled Risk Scanner (Stage G).

Provides a scheduled scan that evaluates project tasks and materials against
configured risk rules. By default, the scanner ONLY creates risk suggestions
(risk records) and does NOT send external notifications.

Integration points:
- Can be invoked by a scheduler (cron, APScheduler, or manual trigger).
- Persists scan results to risk_record / risk_scan_run tables.
- Produces a summary report suitable for internal dashboard display.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Any

from app.services.risk_engine import (
    RiskLifecycle,
    RiskRecord,
    RiskRule,
    RiskScanContext,
    RiskSeverity,
    ScanRunResult,
    ScanType,
    TaskSnapshot,
    aggregate_summary,
    deduplicate_risks,
    evaluate_risks,
    seed_default_rules,
)
from app.services.doc_version import (
    DocChangeLog,
    DocVersion,
    FileChangeDiff,
    detect_file_changes,
    get_change_logs,
    get_affected_entities,
    initialise_project_versions,
)
from app.services.change_impact import (
    ChangeImpactAnalyzer,
    ImpactReport,
)


@dataclass
class ScannerConfig:
    """Configuration for a risk scan run.

    notify_external : bool
        If True, send notifications to external channels. **Default False** —
        the scanner only creates internal risk records by default.
    scan_type : str
        One of ``full``, ``incremental``, ``task_only``, ``material_only``.
    scan_materials : bool
        Whether to scan material documents for conflict detection.
    """

    notify_external: bool = False
    scan_type: str = "full"
    scan_materials: bool = True
    check_impact: bool = True


@dataclass
class ScannerResult:
    """Aggregated result from a risk scanner run."""

    scan_id: str = ""
    project_id: str = ""
    status: str = "completed"
    new_risks: int = 0
    total_active: int = 0
    impact_summary: str = ""
    risk_summary: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class RiskScanner:
    """Scheduled scanner for project tasks and materials.

    Usage::

        scanner = RiskScanner(conn, project_id)
        result = scanner.run(ScannerConfig())
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        project_root: Path | None = None,
    ):
        self.conn = conn
        self.project_id = project_id
        self.project_root = project_root or Path(".")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create Stage G tables if they do not exist."""
        from app.schemas.risk_sql import RISK_DDL
        from app.schemas.doc_version_sql import DOC_VERSION_DDL, QUALITY_METRIC_DDL
        self.conn.executescript(RISK_DDL + "\n" + DOC_VERSION_DDL + "\n" + QUALITY_METRIC_DDL)
        self.conn.commit()

    def _seed_default_rules(self) -> None:
        """Insert default risk rules if the table is empty."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM risk_rule")
        count = cursor.fetchone()[0]
        if count == 0:
            from app.schemas.risk_sql import RISK_DEFAULT_RULES
            for d in RISK_DEFAULT_RULES:
                self.conn.execute(
                    """INSERT OR IGNORE INTO risk_rule
                       (rule_id, rule_name, rule_type, description, severity, config_json, enabled)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (d["rule_id"], d["rule_name"], d["rule_type"],
                     d["description"], d["severity"], d["config_json"], d.get("enabled", 1)),
                )
            self.conn.commit()

    def _load_tasks(self) -> list[TaskSnapshot]:
        """Load tasks from the Phase F ``task`` table (or legacy ``tasks``)."""
        tasks: list[TaskSnapshot] = []
        task_table = self._task_table()
        if task_table is None:
            return tasks
        try:
            cursor = self.conn.execute(
                "SELECT id, title, owner, due_date, priority, acceptance_criteria, status, dependencies, source_ref "
                f"FROM {task_table} WHERE project_id = ?",
                (self.project_id,),
            )
            cols = ["task_id", "title", "owner", "due_date", "priority",
                    "acceptance_criteria", "status", "dependencies", "source_ref"]
            for row in cursor.fetchall():
                d = dict(zip(cols, row))
                deps_raw = d.get("dependencies", "[]") or "[]"
                import json
                try:
                    deps = json.loads(deps_raw) if isinstance(deps_raw, str) else deps_raw
                except (json.JSONDecodeError, TypeError):
                    deps = []
                dd = d.get("due_date")
                due = None
                if dd:
                    try:
                        due = date.fromisoformat(str(dd))
                    except (ValueError, TypeError):
                        pass
                # Count evidence
                ev_count = 0
                try:
                    ev_cur = self.conn.execute(
                        "SELECT COUNT(*) FROM task_evidence WHERE task_id = ? AND project_id = ?",
                        (d["task_id"], self.project_id),
                    )
                    ev_count = ev_cur.fetchone()[0] if ev_cur else 0
                except sqlite3.OperationalError:
                    pass

                tasks.append(TaskSnapshot(
                    task_id=d["task_id"],
                    title=d.get("title") or "",
                    owner=d.get("owner"),
                    due_date=due,
                    priority=d.get("priority"),
                    acceptance_criteria=d.get("acceptance_criteria"),
                    status=d.get("status") or "unknown",
                    dependencies=deps if isinstance(deps, list) else [],
                    evidence_count=ev_count,
                    source_references=[d.get("source_ref", "")] if d.get("source_ref") else [],
                ))
        except sqlite3.OperationalError:
            pass
        return tasks

    def _task_table(self) -> str | None:
        """Prefer the Phase F table name while retaining legacy compatibility."""
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('task', 'tasks')"
        ).fetchall()
        names = {row[0] for row in rows}
        if "task" in names:
            return "task"
        if "tasks" in names:
            return "tasks"
        return None

    def _load_rules(self) -> list[RiskRule]:
        """Load enabled risk rules from DB."""
        cursor = self.conn.execute("SELECT * FROM risk_rule WHERE enabled = 1")
        cols = ["rule_id", "rule_name", "rule_type", "description", "severity", "config_json", "enabled", "created_at", "updated_at"]
        rules: list[RiskRule] = []
        for row in cursor.fetchall():
            d = dict(zip(cols, row))
            rules.append(RiskRule(
                rule_id=d["rule_id"],
                rule_name=d.get("rule_name", ""),
                rule_type=d.get("rule_type", "custom"),
                description=d.get("description", ""),
                severity=RiskSeverity(d.get("severity", "medium")),
                config_json=d.get("config_json", "{}"),
                enabled=bool(d.get("enabled", 1)),
            ))
        return rules

    def _load_existing_hashes(self) -> set[str]:
        """Load dedup hashes from active risk records."""
        cursor = self.conn.execute(
            "SELECT DISTINCT dedup_hash FROM risk_record WHERE project_id = ? AND lifecycle = 'active'",
            (self.project_id,),
        )
        return {row[0] for row in cursor.fetchall() if row[0]}

    def _persist_risks(self, risks: list[RiskRecord], scan_id: str) -> int:
        """Persist risk records; return count of new records."""
        count = 0
        now = datetime.now().isoformat(timespec="seconds")
        for r in risks:
            r.scan_run_id = scan_id
            r.created_at = now
            r.updated_at = now
            try:
                cursor = self.conn.execute(
                    "INSERT OR IGNORE INTO risk_record"
                    " (record_id, project_id, rule_id, risk_type, entity_type, entity_id,"
                    " severity, title, description, source_material, lifecycle, dedup_hash,"
                    " scan_run_id, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        r.record_id, r.project_id, r.rule_id, r.risk_type, r.entity_type, r.entity_id,
                        r.severity.value if isinstance(r.severity, RiskSeverity) else str(r.severity),
                        r.title, r.description, r.source_material, r.lifecycle.value if isinstance(r.lifecycle, RiskLifecycle) else str(r.lifecycle),
                        r.dedup_hash, r.scan_run_id, r.created_at, r.updated_at,
                    ),
                )
                if cursor.rowcount > 0:
                    count += 1
            except sqlite3.IntegrityError:
                pass
        self.conn.commit()
        return count

    def _persist_scan_run(self, result: ScanRunResult) -> None:
        """Persist scan run metadata."""
        self.conn.execute(
            """INSERT INTO risk_scan_run
               (scan_id, project_id, scan_type, started_at, finished_at,
                total_rules, total_risks, new_risks, active_risks, resolved_risks, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result.scan_id, result.project_id, result.scan_type,
                result.started_at, result.finished_at,
                result.total_rules, result.total_risks, result.new_risks,
                result.active_risks, result.resolved_risks, result.status,
            ),
        )
        self.conn.commit()

    def run(self, config: ScannerConfig | None = None) -> ScannerResult:
        """Execute a risk scan.

        Args:
            config: Scanner configuration; defaults to a non-notifying full scan.

        Returns:
            :class:`ScannerResult` with counts and summaries.
        """
        if config is None:
            config = ScannerConfig()

        scan_id = f"scan-{uuid.uuid4().hex[:12]}"
        self._seed_default_rules()

        errors: list[str] = []

        # 1. Load tasks
        tasks = self._load_tasks()
        all_tasks = {t.task_id: t for t in tasks}

        # 2. Load rules
        rules = self._load_rules()

        # 3. Load existing dedup hashes
        existing_hashes = self._load_existing_hashes()

        # 4. Detect material conflicts (stub – extend with real analysis)
        material_conflicts: dict[str, list[str]] = {}

        # 5. Build context and evaluate
        ctx = RiskScanContext(
            project_id=self.project_id,
            scan_id=scan_id,
            tasks=tasks,
            all_tasks_dict=all_tasks,
            material_conflicts=material_conflicts,
            existing_hashes=existing_hashes,
            rules=rules,
        )

        risks, scan_result = evaluate_risks(ctx)
        new_risks = self._persist_risks(risks, scan_id)
        scan_result.new_risks = new_risks
        scan_result.active_risks = len(risks)
        self._persist_scan_run(scan_result)

        # 6. Change impact analysis
        impact_summary = ""
        if config.check_impact:
            try:
                logs = get_change_logs(self.conn, self.project_id, limit=10)
                changed_files = list({log.relative_path for log in logs if log.change_type == "modified"})
                if changed_files:
                    impact_analyzer = ChangeImpactAnalyzer(self.conn, self.project_id)
                    impact_report = impact_analyzer.analyse(changed_files)
                    from app.services.change_impact import persist_impact_report
                    persist_impact_report(self.conn, impact_report)
                    impact_summary = f"{impact_report.total_affected} entities affected across {len(changed_files)} changed files"
            except Exception as e:
                errors.append(f"impact_analysis: {e}")

        # 7. Summarise
        risk_summary = aggregate_summary(risks)

        return ScannerResult(
            scan_id=scan_id,
            project_id=self.project_id,
            status="completed",
            new_risks=new_risks,
            total_active=len(risks),
            impact_summary=impact_summary,
            risk_summary=risk_summary,
            errors=errors,
        )

    def ack_risk(self, record_id: str, acknowledged_by: str) -> bool:
        """Acknowledge a risk record."""
        now = datetime.now().isoformat(timespec="seconds")
        cursor = self.conn.execute(
            "UPDATE risk_record SET lifecycle = 'acknowledged',"
            " acknowledged_by = ?, acknowledged_at = ?, updated_at = ?"
            " WHERE record_id = ?",
            (acknowledged_by, now, now, record_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def resolve_risk(self, record_id: str, resolved_by: str, note: str = "") -> bool:
        """Mark a risk as resolved."""
        now = datetime.now().isoformat(timespec="seconds")
        cursor = self.conn.execute(
            "UPDATE risk_record SET lifecycle = 'resolved',"
            " resolved_by = ?, resolved_at = ?, resolution_note = ?, updated_at = ?"
            " WHERE record_id = ?",
            (resolved_by, now, note, now, record_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0


def ensure_all(conn: sqlite3.Connection) -> None:
    """Ensure all Stage G tables exist and default rules are seeded.

    Convenience function usable without creating a RiskScanner instance.
    """
    from app.schemas.risk_sql import RISK_DDL, RISK_DEFAULT_RULES
    from app.schemas.doc_version_sql import DOC_VERSION_DDL, QUALITY_METRIC_DDL

    conn.executescript(RISK_DDL + "\n" + DOC_VERSION_DDL + "\n" + QUALITY_METRIC_DDL)

    # Seed default risk rules if table is empty
    cursor = conn.execute("SELECT COUNT(*) FROM risk_rule")
    if cursor.fetchone()[0] == 0:
        for d in RISK_DEFAULT_RULES:
            conn.execute(
                "INSERT OR IGNORE INTO risk_rule"
                " (rule_id, rule_name, rule_type, description, severity, config_json, enabled)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (d["rule_id"], d["rule_name"], d["rule_type"],
                 d["description"], d["severity"], d["config_json"], d.get("enabled", 1)),
            )
    conn.commit()
