"""SQLite DDL for document version tracking (Stage G).

Tracks SHA-256 hashes, parse versions, index versions, and replacement
relationships per material file within a project.
"""

from __future__ import annotations

DOC_VERSION_DDL: str = r"""
CREATE TABLE IF NOT EXISTS document_version (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        TEXT NOT NULL,
    relative_path     TEXT NOT NULL,
    sha256            TEXT NOT NULL DEFAULT '',
    size_bytes        INTEGER NOT NULL DEFAULT 0,
    parse_version     INTEGER NOT NULL DEFAULT 1,
    index_version     INTEGER NOT NULL DEFAULT 1,
    replaced_by       TEXT DEFAULT NULL,
    replaced_reason   TEXT DEFAULT '',
    file_modified_at  TEXT NOT NULL DEFAULT '',
    first_seen_at     TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at      TEXT NOT NULL DEFAULT (datetime('now')),
    is_current        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS document_change_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        TEXT NOT NULL,
    relative_path     TEXT NOT NULL,
    change_type       TEXT NOT NULL DEFAULT 'modified',
    old_sha256        TEXT NOT NULL DEFAULT '',
    new_sha256        TEXT NOT NULL DEFAULT '',
    old_parse_version INTEGER NOT NULL DEFAULT 0,
    new_parse_version INTEGER NOT NULL DEFAULT 0,
    old_index_version  INTEGER NOT NULL DEFAULT 0,
    new_index_version  INTEGER NOT NULL DEFAULT 0,
    affected_chunks   TEXT NOT NULL DEFAULT '[]',
    changed_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS change_impact (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        TEXT NOT NULL,
    relative_path     TEXT NOT NULL,
    change_log_id     INTEGER NOT NULL DEFAULT 0,
    affected_entity_type TEXT NOT NULL DEFAULT 'task',
    affected_entity_id TEXT NOT NULL DEFAULT '',
    impact_reason     TEXT NOT NULL DEFAULT '',
    severity          TEXT NOT NULL DEFAULT 'medium',
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_docver_project ON document_version(project_id);
CREATE INDEX IF NOT EXISTS idx_docver_path ON document_version(relative_path);
CREATE INDEX IF NOT EXISTS idx_docver_sha256 ON document_version(sha256);
CREATE INDEX IF NOT EXISTS idx_docver_current ON document_version(is_current);
CREATE INDEX IF NOT EXISTS idx_docchangelog_project ON document_change_log(project_id);
CREATE INDEX IF NOT EXISTS idx_docchangelog_path ON document_change_log(relative_path);
CREATE INDEX IF NOT EXISTS idx_changeimpact_project ON change_impact(project_id);
CREATE INDEX IF NOT EXISTS idx_changeimpact_entity ON change_impact(affected_entity_id);
"""

QUALITY_METRIC_DDL: str = r"""
CREATE TABLE IF NOT EXISTS quality_metric (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    benchmark_name    TEXT NOT NULL DEFAULT 'default',
    test_case_id      TEXT NOT NULL DEFAULT '',
    category          TEXT NOT NULL DEFAULT 'factual',
    question          TEXT NOT NULL DEFAULT '',
    expected_answer   TEXT DEFAULT NULL,
    actual_answer     TEXT DEFAULT NULL,
    recall_count      INTEGER NOT NULL DEFAULT 0,
    total_relevant    INTEGER NOT NULL DEFAULT 0,
    recall_rate       REAL NOT NULL DEFAULT 0.0,
    citation_correct  INTEGER NOT NULL DEFAULT 0,
    citation_accuracy REAL NOT NULL DEFAULT 0.0,
    refused           INTEGER NOT NULL DEFAULT 0,
    should_refuse     INTEGER NOT NULL DEFAULT 0,
    refusal_rate      REAL NOT NULL DEFAULT 0.0,
    latency_ms        REAL NOT NULL DEFAULT 0.0,
    total_queries     INTEGER NOT NULL DEFAULT 1,
    failed_count      INTEGER NOT NULL DEFAULT 0,
    failure_rate      REAL NOT NULL DEFAULT 0.0,
    run_at            TEXT NOT NULL DEFAULT (datetime('now')),
    embed_model       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS quality_bench_dataset (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    test_case_id      TEXT NOT NULL UNIQUE,
    category          TEXT NOT NULL DEFAULT 'factual',
    question          TEXT NOT NULL DEFAULT '',
    expected_answer   TEXT DEFAULT NULL,
    expected_relevant  TEXT NOT NULL DEFAULT '[]',
    should_refuse     INTEGER NOT NULL DEFAULT 0,
    conflict_docs     TEXT NOT NULL DEFAULT '[]',
    tags              TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_quality_metric_name ON quality_metric(benchmark_name);
CREATE INDEX IF NOT EXISTS idx_quality_metric_category ON quality_metric(category);
CREATE INDEX IF NOT EXISTS idx_quality_bench_category ON quality_bench_dataset(category);
"""

COMBINED_STAGE_G_DDL: str = (
    DOC_VERSION_DDL
    + "\n"
    + QUALITY_METRIC_DDL
)
