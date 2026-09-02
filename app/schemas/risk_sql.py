"""SQLite DDL for risk rules and risk records (Stage G).

Tables
-------
risk_rule : Configured risk detection rules (near-deadline, overdue,
    no-evidence, acceptance-gap, dependency-block, material-conflict).
risk_record : Risk records detected by rules, with lifecycle states
    (active, acknowledged, resolved, dismissed, expired) and severity.
risk_scan_run : Metadata for each risk scan execution.
"""

from __future__ import annotations

RISK_DDL: str = r"""
CREATE TABLE IF NOT EXISTS risk_rule (
    rule_id        TEXT PRIMARY KEY,
    rule_name      TEXT NOT NULL,
    rule_type      TEXT NOT NULL DEFAULT 'custom',
    description    TEXT NOT NULL DEFAULT '',
    severity       TEXT NOT NULL DEFAULT 'medium',
    config_json    TEXT NOT NULL DEFAULT '{}',
    enabled        INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS risk_record (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id      TEXT NOT NULL UNIQUE,
    project_id     TEXT NOT NULL,
    rule_id        TEXT NOT NULL DEFAULT '',
    risk_type      TEXT NOT NULL DEFAULT '',
    entity_type    TEXT NOT NULL DEFAULT 'task',
    entity_id      TEXT NOT NULL DEFAULT '',
    severity       TEXT NOT NULL DEFAULT 'medium',
    title          TEXT NOT NULL DEFAULT '',
    description    TEXT NOT NULL DEFAULT '',
    source_material TEXT NOT NULL DEFAULT '',
    lifecycle      TEXT NOT NULL DEFAULT 'active',
    dedup_hash     TEXT NOT NULL DEFAULT '',
    scan_run_id    TEXT NOT NULL DEFAULT '',
    acknowledged_by TEXT DEFAULT NULL,
    acknowledged_at TEXT DEFAULT NULL,
    resolved_by    TEXT DEFAULT NULL,
    resolved_at    TEXT DEFAULT NULL,
    resolution_note TEXT DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS risk_scan_run (
    scan_id        TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL DEFAULT '',
    scan_type      TEXT NOT NULL DEFAULT 'full',
    started_at     TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at    TEXT DEFAULT NULL,
    total_rules    INTEGER NOT NULL DEFAULT 0,
    total_risks    INTEGER NOT NULL DEFAULT 0,
    new_risks      INTEGER NOT NULL DEFAULT 0,
    active_risks   INTEGER NOT NULL DEFAULT 0,
    resolved_risks INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'running'
);

CREATE INDEX IF NOT EXISTS idx_risk_record_project ON risk_record(project_id);
CREATE INDEX IF NOT EXISTS idx_risk_record_type ON risk_record(risk_type);
CREATE INDEX IF NOT EXISTS idx_risk_record_lifecycle ON risk_record(lifecycle);
CREATE INDEX IF NOT EXISTS idx_risk_record_dedup ON risk_record(dedup_hash);
CREATE INDEX IF NOT EXISTS idx_risk_scan_project ON risk_scan_run(project_id);
"""

RISK_DEFAULT_RULES: list[dict] = [
    {
        "rule_id": "risk-near-deadline",
        "rule_name": "临近截止",
        "rule_type": "near_deadline",
        "description": "任务截止日期在3天内但无完成证据",
        "severity": "medium",
        "config_json": '{"days_before": 3, "require_evidence": true}',
        "enabled": 1,
    },
    {
        "rule_id": "risk-overdue",
        "rule_name": "逾期",
        "rule_type": "overdue",
        "description": "任务已超过截止日期但未标记为完成",
        "severity": "high",
        "config_json": '{"grace_days": 0, "check_on_status": ["not_started","in_progress","delayed"]}',
        "enabled": 1,
    },
    {
        "rule_id": "risk-no-evidence",
        "rule_name": "无证据",
        "rule_type": "no_evidence",
        "description": "任务被标记为完成但没有相关证据",
        "severity": "high",
        "config_json": '{"check_status": ["completed","mostly_completed"], "min_evidence": 1}',
        "enabled": 1,
    },
    {
        "rule_id": "risk-acceptance-gap",
        "rule_name": "验收缺失",
        "rule_type": "acceptance_gap",
        "description": "验收标准未在证据材料中得到匹配",
        "severity": "medium",
        "config_json": '{"min_match_ratio": 0.5, "check_status": ["completed","mostly_completed"]}',
        "enabled": 1,
    },
    {
        "rule_id": "risk-dependency-block",
        "rule_name": "依赖阻塞",
        "rule_type": "dependency_block",
        "description": "依赖的任务未完成导致当前任务受阻",
        "severity": "high",
        "config_json": '{"blocking_statuses": ["not_started","delayed","in_progress"], "max_depth": 3}',
        "enabled": 1,
    },
    {
        "rule_id": "risk-material-conflict",
        "rule_name": "资料冲突",
        "rule_type": "material_conflict",
        "description": "同一任务的进度在不同资料中存在矛盾",
        "severity": "high",
        "config_json": '{"min_confidence": 0.6, "max_contradictory_chunks": 2}',
        "enabled": 1,
    },
]
"""Pre-seeded risk rules that ship with the product."""
