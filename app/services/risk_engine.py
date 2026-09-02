"""Risk Rule Engine (Stage G).

Provides configurable risk detection, deduplication, aggregation,
severity calculation, and lifecycle management.

Integration points:
- Scans project tasks against risk rules via :func:`evaluate_risks`.
- Persists risk records with lifecycle states to SQLite.
- Targets risk types:
    near_deadline, overdue, no_evidence, acceptance_gap,
    dependency_block, material_conflict.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any, Callable

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class RiskSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskLifecycle(StrEnum):
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


class RiskRuleType(StrEnum):
    NEAR_DEADLINE = "near_deadline"
    OVERDUE = "overdue"
    NO_EVIDENCE = "no_evidence"
    ACCEPTANCE_GAP = "acceptance_gap"
    DEPENDENCY_BLOCK = "dependency_block"
    MATERIAL_CONFLICT = "material_conflict"
    CUSTOM = "custom"


class ScanType(StrEnum):
    FULL = "full"
    INCREMENTAL = "incremental"
    TASK_ONLY = "task_only"
    MATERIAL_ONLY = "material_only"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class RiskRule(BaseModel):
    """A single risk detection rule (matches risk_rule table)."""
    rule_id: str
    rule_name: str = ""
    rule_type: str = RiskRuleType.CUSTOM
    description: str = ""
    severity: RiskSeverity = RiskSeverity.MEDIUM
    config_json: str = "{}"
    enabled: bool = True

    def config(self) -> dict[str, Any]:
        try:
            return json.loads(self.config_json)
        except (json.JSONDecodeError, TypeError):
            return {}


class RiskRecord(BaseModel):
    """A single risk detection result (matches risk_record table)."""
    record_id: str
    project_id: str = ""
    rule_id: str = ""
    risk_type: str = ""
    entity_type: str = "task"
    entity_id: str = ""
    severity: RiskSeverity = RiskSeverity.MEDIUM
    title: str = ""
    description: str = ""
    source_material: str = ""
    lifecycle: RiskLifecycle = RiskLifecycle.ACTIVE
    dedup_hash: str = ""
    scan_run_id: str = ""
    acknowledged_by: str | None = None
    acknowledged_at: str | None = None
    resolved_by: str | None = None
    resolved_at: str | None = None
    resolution_note: str = ""
    created_at: str = ""
    updated_at: str = ""


class ScanRunResult(BaseModel):
    """Metadata for a risk scan run (matches risk_scan_run table)."""
    scan_id: str
    project_id: str = ""
    scan_type: str = "full"
    started_at: str = ""
    finished_at: str | None = None
    total_rules: int = 0
    total_risks: int = 0
    new_risks: int = 0
    active_risks: int = 0
    resolved_risks: int = 0
    status: str = "running"


class TaskSnapshot(BaseModel):
    """Lightweight task snapshot for risk evaluation."""
    task_id: str
    title: str = ""
    owner: str | None = None
    due_date: date | None = None
    priority: str | None = None
    acceptance_criteria: str | None = None
    status: str = "unknown"
    dependencies: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    source_references: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _make_dedup_hash(project_id: str, rule_id: str, entity_id: str, key_fields: str) -> str:
    """Create a stable deduplication hash for a risk."""
    raw = f"{project_id}|{rule_id}|{entity_id}|{key_fields}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def deduplicate_risks(
    risks: list[RiskRecord],
    existing_hashes: set[str] | None = None,
) -> tuple[list[RiskRecord], int]:
    """Deduplicate risk records by dedup_hash.

    Returns (unique_risks, duplicate_count).
    """
    existing: set[str] = existing_hashes or set()
    seen: set[str] = set()
    unique: list[RiskRecord] = []
    dupes = 0
    for r in risks:
        if r.dedup_hash in existing or r.dedup_hash in seen:
            dupes += 1
            continue
        seen.add(r.dedup_hash)
        unique.append(r)
    return unique, dupes


# ---------------------------------------------------------------------------
# Severity mapping
# ---------------------------------------------------------------------------

SEVERITY_ORDER: dict[RiskSeverity, int] = {
    RiskSeverity.LOW: 0,
    RiskSeverity.MEDIUM: 1,
    RiskSeverity.HIGH: 2,
    RiskSeverity.CRITICAL: 3,
}


def highest_severity(severities: list[RiskSeverity]) -> RiskSeverity:
    """Return the highest severity from a list."""
    if not severities:
        return RiskSeverity.LOW
    return max(severities, key=lambda s: SEVERITY_ORDER.get(s, 0))


def aggregate_summary(risks: list[RiskRecord]) -> dict[str, Any]:
    """Produce a summary aggregation of risk records."""
    by_severity: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_lifecycle: dict[str, int] = {}
    for r in risks:
        by_severity[r.severity] = by_severity.get(r.severity, 0) + 1
        by_type[r.risk_type] = by_type.get(r.risk_type, 0) + 1
        by_lifecycle[r.lifecycle] = by_lifecycle.get(r.lifecycle, 0) + 1
    return {
        "total": len(risks),
        "by_severity": by_severity,
        "by_type": by_type,
        "by_lifecycle": by_lifecycle,
    }


# ---------------------------------------------------------------------------
# Individual rule checkers
# ---------------------------------------------------------------------------

def _check_near_deadline(task: TaskSnapshot, config: dict) -> RiskRecord | None:
    days_before = config.get("days_before", 3)
    if task.due_date is None:
        return None
    if task.status in ("completed", "cancelled"):
        return None
    diff = (task.due_date - date.today()).days
    if diff < 0:
        return None  # Handled by overdue rule
    if diff > days_before:
        return None
    title = f"[临近截止] {task.title}"
    desc = f"任务「{task.title}」距离截止日期还有 {diff} 天，当前状态为 {task.status}。"
    return _build_risk(task, "near_deadline", RiskSeverity.MEDIUM if diff > 1 else RiskSeverity.HIGH, title, desc, config)


def _check_overdue(task: TaskSnapshot, config: dict) -> RiskRecord | None:
    grace_days = config.get("grace_days", 0)
    if task.due_date is None:
        return None
    if task.status in ("completed", "cancelled"):
        return None
    diff = (date.today() - task.due_date).days
    if diff <= grace_days:
        return None
    title = f"[逾期] {task.title}"
    desc = f"任务「{task.title}」已逾期 {diff} 天，当前状态为 {task.status}。"
    severity = RiskSeverity.HIGH if diff <= 7 else RiskSeverity.CRITICAL
    return _build_risk(task, "overdue", severity, title, desc, config)


def _check_no_evidence(task: TaskSnapshot, config: dict) -> RiskRecord | None:
    check_statuses = config.get("check_status", ["completed", "mostly_completed"])
    min_evidence = config.get("min_evidence", 1)
    if task.status not in check_statuses:
        return None
    if task.evidence_count >= min_evidence:
        return None
    title = f"[无证据] {task.title}"
    desc = f"任务「{task.title}」状态为 {task.status}，但缺少证据材料（需要 ≥{min_evidence} 条，当前 {task.evidence_count} 条）。"
    return _build_risk(task, "no_evidence", RiskSeverity.HIGH, title, desc, config)


def _check_acceptance_gap(task: TaskSnapshot, config: dict) -> RiskRecord | None:
    check_statuses = config.get("check_status", ["completed", "mostly_completed"])
    if task.status not in check_statuses:
        return None
    if not task.acceptance_criteria:
        return None  # No acceptance criteria defined, can't check
    title = f"[验收缺失] {task.title}"
    desc = f"任务「{task.title}」的验收标准可能未在证据材料中得到充分验证。"
    return _build_risk(task, "acceptance_gap", RiskSeverity.MEDIUM, title, desc, config)


def _check_dependency_block(task: TaskSnapshot, config: dict) -> RiskRecord | None:
    """Check if any dependency is blocking this task.

    This requires access to all tasks in the project. For the basic engine
    we accept an `all_tasks` dict passed via config at engine invocation level.
    """
    all_tasks: dict[str, TaskSnapshot] = config.get("_all_tasks", {})
    if not all_tasks:
        return None
    blocking_statuses = set(config.get("blocking_statuses", ["not_started", "delayed", "in_progress"]))
    blocks: list[str] = []
    for dep_id in task.dependencies:
        dep = all_tasks.get(dep_id)
        if dep is None:
            continue
        if dep.status in blocking_statuses:
            blocks.append(f"{dep.title} ({dep.status})")
    if not blocks:
        return None
    title = f"[依赖阻塞] {task.title}"
    desc = f"任务「{task.title}」依赖的任务尚未完成：{'，'.join(blocks)}。"
    return _build_risk(task, "dependency_block", RiskSeverity.HIGH, title, desc, config)


def _check_material_conflict(task: TaskSnapshot, config: dict) -> RiskRecord | None:
    """Detect contradictory status claims from different materials.

    This requires pre-computed conflict data. For the basic engine
    we accept `_conflicts` dict passed via config.
    """
    conflicts: dict[str, list[str]] = config.get("_conflicts", {})
    if task.task_id not in conflicts:
        return None
    conflicting = conflicts[task.task_id]
    if len(conflicting) < 2:
        return None
    title = f"[资料冲突] {task.title}"
    desc = f"任务「{task.title}」在不同资料中存在矛盾信息：" + " | ".join(conflicting)
    return _build_risk(task, "material_conflict", RiskSeverity.HIGH, title, desc, config)


# ---------------------------------------------------------------------------
# Rule registry
# ---------------------------------------------------------------------------

RULE_CHECKER_MAP: dict[str, Callable] = {
    RiskRuleType.NEAR_DEADLINE: _check_near_deadline,
    RiskRuleType.OVERDUE: _check_overdue,
    RiskRuleType.NO_EVIDENCE: _check_no_evidence,
    RiskRuleType.ACCEPTANCE_GAP: _check_acceptance_gap,
    RiskRuleType.DEPENDENCY_BLOCK: _check_dependency_block,
    RiskRuleType.MATERIAL_CONFLICT: _check_material_conflict,
}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _build_risk(
    task: TaskSnapshot,
    rule_type: str,
    severity: RiskSeverity,
    title: str,
    description: str,
    config: dict,
) -> RiskRecord:
    dedup_hash = _make_dedup_hash(task.task_id, rule_type, task.task_id, task.status)
    return RiskRecord(
        record_id=f"risk-{uuid.uuid4().hex[:12]}",
        risk_type=rule_type,
        entity_type="task",
        entity_id=task.task_id,
        severity=severity,
        title=title,
        description=description,
        dedup_hash=dedup_hash,
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

@dataclass
class RiskScanContext:
    """Context object passed through a risk scan."""
    project_id: str
    scan_id: str = field(default_factory=lambda: f"scan-{uuid.uuid4().hex[:12]}")
    tasks: list[TaskSnapshot] = field(default_factory=list)
    all_tasks_dict: dict[str, TaskSnapshot] = field(default_factory=dict)
    material_conflicts: dict[str, list[str]] = field(default_factory=dict)
    existing_hashes: set[str] = field(default_factory=set)
    rules: list[RiskRule] = field(default_factory=list)


def evaluate_risks(ctx: RiskScanContext) -> tuple[list[RiskRecord], ScanRunResult]:
    """Run all enabled rules against the context and return risks.

    Returns (risk_records, scan_run_result).
    """
    records: list[RiskRecord] = []
    enabled_rules = [r for r in ctx.rules if r.enabled]

    for task in ctx.tasks:
        for rule in enabled_rules:
            raw_cfg = rule.config()
            cfg = dict(raw_cfg)
            cfg["_all_tasks"] = ctx.all_tasks_dict
            cfg["_conflicts"] = ctx.material_conflicts
            checker = RULE_CHECKER_MAP.get(rule.rule_type)
            if checker is None:
                continue
            result = checker(task, cfg)
            if result is not None:
                result.project_id = ctx.project_id
                result.rule_id = rule.rule_id
                result.scan_run_id = ctx.scan_id
                result.severity = RiskSeverity(rule.severity) if rule.severity else result.severity
                records.append(result)

    # Deduplicate
    unique, dupes = deduplicate_risks(records, ctx.existing_hashes)

    run_result = ScanRunResult(
        scan_id=ctx.scan_id,
        project_id=ctx.project_id,
        scan_type="full",
        started_at=datetime.now().isoformat(timespec="seconds"),
        finished_at=datetime.now().isoformat(timespec="seconds"),
        total_rules=len(enabled_rules),
        total_risks=len(records),
        new_risks=len(unique),
        active_risks=len(unique),
        resolved_risks=0,
        status="completed",
    )

    return unique, run_result


def seed_default_rules() -> list[RiskRule]:
    """Return the built-in default risk rules."""
    from app.schemas.risk_sql import RISK_DEFAULT_RULES

    rules: list[RiskRule] = []
    for d in RISK_DEFAULT_RULES:
        rules.append(RiskRule(
            rule_id=d["rule_id"],
            rule_name=d["rule_name"],
            rule_type=d["rule_type"],
            description=d["description"],
            severity=RiskSeverity(d["severity"]),
            config_json=d["config_json"],
            enabled=bool(d.get("enabled", 1)),
        ))
    return rules
