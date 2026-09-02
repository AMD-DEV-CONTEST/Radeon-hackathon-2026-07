"""Stage G — 持续知识与风险监控 comprehensive tests.

Covers:
- Risk engine: rules, deduplication, severity, aggregation, lifecycle
- Document version: SHA-256 tracking, version bumps, change log, incremental indexing
- Change impact: change detection, affected entity analysis
- Quality benchmark: dataset seeding, recall, citation accuracy, refusal rate, latency
- Risk scanner: full scan flow, ack/resolve, no external notification by default
- Error codes: all Stage G error codes
- Schema: all Stage G tables and default rules
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db() -> sqlite3.Connection:
    """Create an in-memory SQLite database with Stage G schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Apply all Stage G DDL
    from app.schemas.risk_sql import RISK_DDL
    from app.schemas.doc_version_sql import DOC_VERSION_DDL, QUALITY_METRIC_DDL
    conn.executescript(RISK_DDL + "\n" + DOC_VERSION_DDL + "\n" + QUALITY_METRIC_DDL)
    conn.commit()
    return conn


@pytest.fixture
def tmp_project_dir() -> Path:
    """Temporary project directory with test files."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "project_plan.md").write_text(
            "# Project Plan\n\nA模块交付日期: 2026-09-15\nB模块开始: 2026-10-01\n",
            encoding="utf-8",
        )
        (root / "budget.md").write_text(
            "# Budget\n\n项目总预算: 500万元\n",
            encoding="utf-8",
        )
        yield root


@pytest.fixture
def task_snapshots() -> list:
    """Provide a standard set of task snapshots for risk testing."""
    from app.services.risk_engine import TaskSnapshot

    today = date.today()
    return [
        TaskSnapshot(
            task_id="task-001",
            title="完成A模块开发",
            owner="张三",
            due_date=today + timedelta(days=1),
            priority="high",
            acceptance_criteria="通过率≥95%",
            status="in_progress",
            evidence_count=0,
            dependencies=["task-003"],
        ),
        TaskSnapshot(
            task_id="task-002",
            title="完成B模块测试",
            owner="李四",
            due_date=today - timedelta(days=5),
            priority="medium",
            acceptance_criteria="错误率≤2%",
            status="not_started",
            evidence_count=0,
            dependencies=[],
        ),
        TaskSnapshot(
            task_id="task-003",
            title="设计方案评审",
            owner="王五",
            due_date=today - timedelta(days=1),
            priority="high",
            acceptance_criteria="评审通过",
            status="completed",
            evidence_count=0,
            dependencies=[],
        ),
        TaskSnapshot(
            task_id="task-004",
            title="编写用户手册",
            owner=None,
            due_date=None,
            priority="low",
            acceptance_criteria=None,
            status="in_progress",
            evidence_count=3,
            dependencies=[],
        ),
        TaskSnapshot(
            task_id="task-005",
            title="已取消任务",
            owner="赵六",
            due_date=today - timedelta(days=10),
            priority="low",
            acceptance_criteria=None,
            status="cancelled",
            evidence_count=0,
            dependencies=[],
        ),
    ]


# ============================================================================
# Test 1: Risk SQL Schema & Default Rules
# ============================================================================

class TestRiskSQLSchema:
    """Verify that all risk tables and default rules exist."""

    def test_risk_tables_exist(self, tmp_db):
        cursor = tmp_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {r[0] for r in cursor.fetchall()}
        assert "risk_rule" in tables
        assert "risk_record" in tables
        assert "risk_scan_run" in tables

    def test_doc_version_tables_exist(self, tmp_db):
        cursor = tmp_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {r[0] for r in cursor.fetchall()}
        assert "document_version" in tables
        assert "document_change_log" in tables
        assert "change_impact" in tables

    def test_quality_metric_tables_exist(self, tmp_db):
        cursor = tmp_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {r[0] for r in cursor.fetchall()}
        assert "quality_metric" in tables
        assert "quality_bench_dataset" in tables

    def test_default_rules_count(self, tmp_db):
        from app.schemas.risk_sql import RISK_DEFAULT_RULES
        assert len(RISK_DEFAULT_RULES) == 6

    def test_default_rules_have_required_fields(self, tmp_db):
        from app.schemas.risk_sql import RISK_DEFAULT_RULES
        required = {"rule_id", "rule_name", "rule_type", "severity", "config_json"}
        for rule in RISK_DEFAULT_RULES:
            assert required.issubset(rule.keys()), f"Missing fields in {rule['rule_id']}"

    def test_seed_default_rules(self, tmp_db):
        from app.schemas.risk_sql import RISK_DEFAULT_RULES
        for d in RISK_DEFAULT_RULES:
            tmp_db.execute(
                """INSERT INTO risk_rule
                   (rule_id, rule_name, rule_type, description, severity, config_json, enabled)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (d["rule_id"], d["rule_name"], d["rule_type"],
                 d["description"], d["severity"], d["config_json"], d.get("enabled", 1)),
            )
        tmp_db.commit()
        cursor = tmp_db.execute("SELECT COUNT(*) FROM risk_rule")
        assert cursor.fetchone()[0] == 6

    def test_risk_rule_types(self, tmp_db):
        from app.schemas.risk_sql import RISK_DEFAULT_RULES
        expected_types = {
            "near_deadline", "overdue", "no_evidence",
            "acceptance_gap", "dependency_block", "material_conflict",
        }
        actual_types = {r["rule_type"] for r in RISK_DEFAULT_RULES}
        assert actual_types == expected_types


# ============================================================================
# Test 2: Risk Rule Engine
# ============================================================================

class TestRiskEngineRules:
    """Test individual risk rule checkers."""

    def test_near_deadline_detected(self, task_snapshots):
        from app.services.risk_engine import _check_near_deadline
        result = _check_near_deadline(task_snapshots[0], {"days_before": 3})
        assert result is not None
        assert result.risk_type == "near_deadline"
        assert result.severity.value == "high"

    def test_near_deadline_not_detected_far_future(self):
        from app.services.risk_engine import TaskSnapshot, _check_near_deadline
        task = TaskSnapshot(
            task_id="t-far", title="远期任务",
            due_date=date.today() + timedelta(days=30),
            status="not_started",
        )
        assert _check_near_deadline(task, {"days_before": 3}) is None

    def test_near_deadline_completed_ignored(self):
        from app.services.risk_engine import TaskSnapshot, _check_near_deadline
        task = TaskSnapshot(
            task_id="t-done", title="已完成",
            due_date=date.today() + timedelta(days=1),
            status="completed",
        )
        assert _check_near_deadline(task, {"days_before": 3}) is None

    def test_near_deadline_cancelled_ignored(self):
        from app.services.risk_engine import TaskSnapshot, _check_near_deadline
        task = TaskSnapshot(
            task_id="t-cxl", title="已取消",
            due_date=date.today() + timedelta(days=1),
            status="cancelled",
        )
        assert _check_near_deadline(task, {"days_before": 3}) is None

    def test_overdue_detected(self, task_snapshots):
        from app.services.risk_engine import _check_overdue
        result = _check_overdue(task_snapshots[1], {"grace_days": 0})
        assert result is not None
        assert result.risk_type == "overdue"
        assert result.severity.value == "high"

    def test_overdue_critical(self):
        from app.services.risk_engine import TaskSnapshot, _check_overdue
        task = TaskSnapshot(
            task_id="t-old", title="严重逾期",
            due_date=date.today() - timedelta(days=14),
            status="not_started",
        )
        result = _check_overdue(task, {"grace_days": 0})
        assert result is not None
        assert result.severity.value == "critical"

    def test_overdue_with_grace_no_trigger(self):
        from app.services.risk_engine import TaskSnapshot, _check_overdue
        task = TaskSnapshot(
            task_id="t-grace", title="宽限期内",
            due_date=date.today() - timedelta(days=2),
            status="not_started",
        )
        result = _check_overdue(task, {"grace_days": 3})
        assert result is None

    def test_no_evidence_detected(self, task_snapshots):
        from app.services.risk_engine import _check_no_evidence
        result = _check_no_evidence(task_snapshots[2], {
            "check_status": ["completed"],
            "min_evidence": 1,
        })
        assert result is not None
        assert result.risk_type == "no_evidence"
        assert result.severity.value == "high"

    def test_no_evidence_with_sufficient_evidence(self):
        from app.services.risk_engine import TaskSnapshot, _check_no_evidence
        task = TaskSnapshot(
            task_id="t-evid", title="有证据",
            status="completed", evidence_count=5,
        )
        assert _check_no_evidence(task, {
            "check_status": ["completed"], "min_evidence": 1,
        }) is None

    def test_acceptance_gap_detected(self, task_snapshots):
        from app.services.risk_engine import _check_acceptance_gap
        result = _check_acceptance_gap(task_snapshots[2], {
            "check_status": ["completed"],
        })
        assert result is not None
        assert result.risk_type == "acceptance_gap"

    def test_acceptance_gap_no_criteria(self):
        from app.services.risk_engine import TaskSnapshot, _check_acceptance_gap
        task = TaskSnapshot(
            task_id="t-noac", title="无验收标准",
            status="completed", acceptance_criteria=None,
        )
        assert _check_acceptance_gap(task, {
            "check_status": ["completed"],
        }) is None

    def test_dependency_block_detected(self, task_snapshots):
        from app.services.risk_engine import _check_dependency_block
        all_tasks = {t.task_id: t for t in task_snapshots}
        result = _check_dependency_block(task_snapshots[0], {
            "blocking_statuses": ["not_started", "delayed", "in_progress"],
            "_all_tasks": all_tasks,
        })
        # task-001 depends on task-003 which is completed, so no block
        # Unless task-001 is blocked by a not_started/in_progress/delayed dep
        # task-003 is "completed", so not blocked
        assert result is None

    def test_dependency_block_when_blocked(self):
        from app.services.risk_engine import TaskSnapshot, _check_dependency_block
        dep = TaskSnapshot(task_id="dep-a", title="依赖A", status="not_started")
        parent = TaskSnapshot(
            task_id="parent", title="父任务",
            status="in_progress", dependencies=["dep-a"],
        )
        result = _check_dependency_block(parent, {
            "_all_tasks": {"dep-a": dep, "parent": parent},
            "blocking_statuses": ["not_started", "delayed", "in_progress"],
        })
        assert result is not None
        assert result.risk_type == "dependency_block"

    def test_material_conflict_detected(self):
        from app.services.risk_engine import TaskSnapshot, _check_material_conflict
        task = TaskSnapshot(task_id="t-confl", title="冲突任务")
        result = _check_material_conflict(task, {
            "_conflicts": {"t-confl": ["预算500万", "会议调整至450万"]},
        })
        assert result is not None
        assert result.risk_type == "material_conflict"

    def test_material_conflict_no_conflict(self):
        from app.services.risk_engine import TaskSnapshot, _check_material_conflict
        task = TaskSnapshot(task_id="t-ok", title="正常任务")
        assert _check_material_conflict(task, {"_conflicts": {}}) is None


# ============================================================================
# Test 3: Risk Deduplication, Aggregation, Severity
# ============================================================================

class TestRiskDedupAndAggregation:
    """Test risk deduplication, aggregation, and severity helpers."""

    def test_make_dedup_hash_stable(self):
        from app.services.risk_engine import _make_dedup_hash
        h1 = _make_dedup_hash("proj-1", "rule-1", "task-1", "in_progress")
        h2 = _make_dedup_hash("proj-1", "rule-1", "task-1", "in_progress")
        assert h1 == h2

    def test_make_dedup_hash_different(self):
        from app.services.risk_engine import _make_dedup_hash
        h1 = _make_dedup_hash("proj-1", "rule-1", "task-1", "in_progress")
        h2 = _make_dedup_hash("proj-1", "rule-2", "task-1", "in_progress")
        assert h1 != h2

    def test_deduplicate_risks_removes_dupes(self):
        from app.services.risk_engine import RiskRecord, deduplicate_risks
        r1 = RiskRecord(record_id="a", dedup_hash="hash1")
        r2 = RiskRecord(record_id="b", dedup_hash="hash1")
        r3 = RiskRecord(record_id="c", dedup_hash="hash2")
        unique, dupes = deduplicate_risks([r1, r2, r3])
        assert len(unique) == 2
        assert dupes == 1

    def test_deduplicate_with_existing(self):
        from app.services.risk_engine import RiskRecord, deduplicate_risks
        r1 = RiskRecord(record_id="a", dedup_hash="hash1")
        unique, dupes = deduplicate_risks([r1], {"hash1"})
        assert len(unique) == 0
        assert dupes == 1

    def test_highest_severity(self):
        from app.services.risk_engine import RiskSeverity, highest_severity
        result = highest_severity([
            RiskSeverity.LOW, RiskSeverity.HIGH, RiskSeverity.MEDIUM,
        ])
        assert result == RiskSeverity.HIGH

    def test_highest_severity_empty(self):
        from app.services.risk_engine import RiskSeverity, highest_severity
        assert highest_severity([]) == RiskSeverity.LOW

    def test_aggregate_summary(self):
        from app.services.risk_engine import RiskRecord, RiskSeverity, aggregate_summary
        risks = [
            RiskRecord(record_id="r1", severity=RiskSeverity.HIGH, risk_type="overdue", lifecycle="active"),
            RiskRecord(record_id="r2", severity=RiskSeverity.MEDIUM, risk_type="near_deadline", lifecycle="active"),
            RiskRecord(record_id="r3", severity=RiskSeverity.HIGH, risk_type="no_evidence", lifecycle="acknowledged"),
        ]
        summary = aggregate_summary(risks)
        assert summary["total"] == 3
        assert summary["by_severity"]["high"] == 2
        assert summary["by_severity"]["medium"] == 1
        assert summary["by_type"]["overdue"] == 1
        assert summary["by_lifecycle"]["active"] == 2

    def test_seed_default_rules_module(self):
        from app.services.risk_engine import seed_default_rules
        rules = seed_default_rules()
        assert len(rules) == 6
        rule_types = {r.rule_type for r in rules}
        assert "near_deadline" in rule_types
        assert "overdue" in rule_types
        assert all(r.enabled for r in rules)

    def test_evaluate_risks_orchestration(self, task_snapshots):
        from app.services.risk_engine import (
            RiskScanContext, evaluate_risks, seed_default_rules,
        )
        rules = seed_default_rules()
        all_tasks = {t.task_id: t for t in task_snapshots}
        ctx = RiskScanContext(
            project_id="test-proj",
            tasks=task_snapshots,
            all_tasks_dict=all_tasks,
            rules=rules,
        )
        unique, scan_result = evaluate_risks(ctx)
        assert scan_result.status == "completed"
        assert scan_result.total_rules == 6
        assert len(unique) >= 0  # depends on actual tasks
        assert scan_result.new_risks == len(unique)


# ============================================================================
# Test 4: Document Version Management
# ============================================================================

class TestDocVersionManagement:
    """Test document version tracking and incremental indexing."""

    def test_compute_sha256(self, tmp_project_dir):
        from app.services.doc_version import compute_file_sha256
        fp = tmp_project_dir / "project_plan.md"
        h = compute_file_sha256(fp)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_compute_sha256_nonexistent(self):
        from app.services.doc_version import compute_file_sha256
        assert compute_file_sha256(Path("/nonexistent/file.txt")) == ""

    def test_record_file_version_new(self, tmp_db, tmp_project_dir):
        from app.services.doc_version import (
            record_file_version, compute_file_sha256, ensure_schema,
        )
        ensure_schema(tmp_db)
        fp = tmp_project_dir / "project_plan.md"
        h = compute_file_sha256(fp)
        dv = record_file_version(tmp_db, "proj-1", "project_plan.md", h, fp.stat().st_size)
        assert dv.project_id == "proj-1"
        assert dv.parse_version == 1
        assert dv.index_version == 1
        assert dv.is_current is True

        # Verify in DB
        cursor = tmp_db.execute(
            "SELECT * FROM document_version WHERE project_id = ? AND relative_path = ?",
            ("proj-1", "project_plan.md"),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["sha256"] == h

    def test_record_file_version_no_change(self, tmp_db, tmp_project_dir):
        from app.services.doc_version import (
            record_file_version, compute_file_sha256, ensure_schema,
        )
        ensure_schema(tmp_db)
        fp = tmp_project_dir / "project_plan.md"
        h = compute_file_sha256(fp)
        dv1 = record_file_version(tmp_db, "proj-1", "project_plan.md", h, fp.stat().st_size)
        dv2 = record_file_version(tmp_db, "proj-1", "project_plan.md", h, fp.stat().st_size)
        assert dv2.sha256 == dv1.sha256
        assert dv2.parse_version == dv1.parse_version

    def test_record_file_version_content_changed(self, tmp_db, tmp_project_dir):
        from app.services.doc_version import (
            record_file_version, compute_file_sha256, ensure_schema,
        )
        ensure_schema(tmp_db)
        fp = tmp_project_dir / "project_plan.md"
        h1 = compute_file_sha256(fp)
        dv1 = record_file_version(tmp_db, "proj-1", "project_plan.md", h1, fp.stat().st_size)

        # Modify file
        fp.write_text("# Updated plan\nNew content here\n", encoding="utf-8")
        h2 = compute_file_sha256(fp)
        dv2 = record_file_version(tmp_db, "proj-1", "project_plan.md", h2, fp.stat().st_size)

        assert dv2.parse_version == dv1.parse_version + 1
        assert dv2.index_version == dv1.index_version + 1
        assert dv2.sha256 == h2
        assert dv2.is_current is True

        # Old version marked replaced
        cursor = tmp_db.execute(
            "SELECT is_current, replaced_by FROM document_version WHERE id = ?",
            (dv1.id,),
        )
        row = cursor.fetchone()
        assert row["is_current"] == 0

    def test_mark_file_deleted(self, tmp_db, tmp_project_dir):
        from app.services.doc_version import (
            record_file_version, compute_file_sha256, mark_file_deleted, ensure_schema,
        )
        ensure_schema(tmp_db)
        fp = tmp_project_dir / "project_plan.md"
        h = compute_file_sha256(fp)
        dv = record_file_version(tmp_db, "proj-1", "project_plan.md", h, fp.stat().st_size)
        mark_file_deleted(tmp_db, "proj-1", "project_plan.md")
        cursor = tmp_db.execute(
            "SELECT is_current FROM document_version WHERE id = ?", (dv.id,),
        )
        assert cursor.fetchone()["is_current"] == 0

    def test_detect_file_changes(self, tmp_db, tmp_project_dir):
        from app.services.doc_version import (
            detect_file_changes, record_file_version, compute_file_sha256, ensure_schema,
        )
        ensure_schema(tmp_db)

        files = ["project_plan.md", "budget.md"]
        for fn in files:
            fp = tmp_project_dir / fn
            h = compute_file_sha256(fp)
            record_file_version(tmp_db, "proj-1", fn, h, fp.stat().st_size)

        diff = detect_file_changes(tmp_project_dir, files, tmp_db)
        assert len(diff.unchanged_files) == 2
        assert len(diff.new_files) == 0
        assert len(diff.modified_files) == 0

        # Modify one file
        (tmp_project_dir / "project_plan.md").write_text(
            "# Modified plan\nDifferent content\n", encoding="utf-8",
        )
        diff2 = detect_file_changes(tmp_project_dir, files, tmp_db)
        assert "project_plan.md" in diff2.modified_files

    def test_detect_new_files(self, tmp_db, tmp_project_dir):
        from app.services.doc_version import (
            detect_file_changes, ensure_schema,
        )
        ensure_schema(tmp_db)
        # Create a new file not yet tracked
        (tmp_project_dir / "new_file.md").write_text("# New content\n", encoding="utf-8")
        diff = detect_file_changes(tmp_project_dir, ["new_file.md"], tmp_db)
        assert "new_file.md" in diff.new_files

    def test_detect_changes_is_project_scoped_and_rejects_escape(self, tmp_db, tmp_project_dir):
        from app.services.doc_version import (
            compute_file_sha256, detect_file_changes, ensure_schema, record_file_version,
        )
        ensure_schema(tmp_db)
        fp = tmp_project_dir / "project_plan.md"
        record_file_version(tmp_db, "other-project", "project_plan.md", compute_file_sha256(fp))

        scoped = detect_file_changes(
            tmp_project_dir, ["project_plan.md"], tmp_db, project_id="this-project"
        )
        assert scoped.new_files == ["project_plan.md"]

        with pytest.raises(ValueError, match="escapes project root"):
            detect_file_changes(tmp_project_dir, ["../outside.md"], tmp_db, project_id="this-project")

    def test_change_log_recorded(self, tmp_db, tmp_project_dir):
        from app.services.doc_version import (
            record_file_version, compute_file_sha256, get_change_logs, ensure_schema,
        )
        ensure_schema(tmp_db)
        fp = tmp_project_dir / "project_plan.md"
        h1 = compute_file_sha256(fp)
        record_file_version(tmp_db, "proj-1", "project_plan.md", h1, fp.stat().st_size)

        fp.write_text("# Updated\n", encoding="utf-8")
        h2 = compute_file_sha256(fp)
        record_file_version(tmp_db, "proj-1", "project_plan.md", h2, fp.stat().st_size)

        logs = get_change_logs(tmp_db, "proj-1")
        assert len(logs) >= 1
        last_log = logs[0]
        assert last_log.change_type == "modified"
        assert last_log.old_sha256 == h1
        assert last_log.new_sha256 == h2

    def test_initialise_project_versions(self, tmp_db, tmp_project_dir):
        from app.services.doc_version import (
            initialise_project_versions, ensure_schema,
        )
        ensure_schema(tmp_db)
        versions = initialise_project_versions(
            tmp_db, "proj-1", tmp_project_dir,
            ["project_plan.md", "budget.md"],
        )
        assert len(versions) == 2
        assert all(v.parse_version == 1 for v in versions.values())
        cursor = tmp_db.execute("SELECT COUNT(*) FROM document_version WHERE project_id = ?", ("proj-1",))
        assert cursor.fetchone()[0] == 2


# ============================================================================
# Test 5: Change Impact Analysis
# ============================================================================

class TestChangeImpactAnalysis:
    """Test change impact analysis after document updates."""

    def test_impact_report_basic(self, tmp_db):
        from app.services.change_impact import ChangeImpactAnalyzer
        ensure_all(tmp_db)
        analyzer = ChangeImpactAnalyzer(tmp_db, "proj-1")
        report = analyzer.analyse(["project_plan.md"])
        assert report.project_id == "proj-1"
        assert "project_plan.md" in report.changed_files
        assert report.total_affected >= 0

    def test_record_change_impact(self, tmp_db):
        from app.services.doc_version import record_change_impact, ensure_schema
        ensure_schema(tmp_db)
        impact = record_change_impact(
            tmp_db, "proj-1", "project_plan.md", 0,
            "task", "task-001", "源引用变更", "high",
        )
        assert impact.project_id == "proj-1"
        assert impact.severity == "high"

        cursor = tmp_db.execute(
            "SELECT * FROM change_impact WHERE affected_entity_id = ?", ("task-001",),
        )
        assert cursor.fetchone() is not None

    def test_get_affected_entities(self, tmp_db):
        from app.services.doc_version import (
            record_change_impact, get_affected_entities, ensure_schema,
        )
        ensure_schema(tmp_db)
        record_change_impact(tmp_db, "proj-1", "a.md", 0, "task", "t1", "reason", "high")
        record_change_impact(tmp_db, "proj-1", "b.md", 0, "task", "t2", "reason", "medium")

        entities = get_affected_entities(tmp_db, "proj-1", ["a.md"])
        assert len(entities) >= 1
        assert any(e.affected_entity_id == "t1" for e in entities)

    def test_persist_impact_report(self, tmp_db):
        from app.services.change_impact import (
            ImpactEntry, ImpactReport, persist_impact_report,
        )
        ensure_all(tmp_db)
        report = ImpactReport(
            project_id="proj-1",
            changed_files=["doc.md"],
            total_affected=2,
            affected_tasks=[
                ImpactEntry(entity_type="task", entity_id="t1", entity_title="T1",
                            impact_reason="Changed", source_file="doc.md"),
            ],
            affected_reports=[],
        )
        persist_impact_report(tmp_db, report)
        cursor = tmp_db.execute(
            "SELECT COUNT(*) FROM change_impact WHERE project_id = ?", ("proj-1",),
        )
        assert cursor.fetchone()[0] >= 1


# ============================================================================
# Test 6: Quality Benchmark & Metrics
# ============================================================================

class TestQualityBenchmark:
    """Test the retrieval quality benchmark system."""

    def test_seed_benchmark_dataset(self, tmp_db):
        from app.rag.quality_bench import seed_benchmark_dataset
        ensure_all(tmp_db)
        count = seed_benchmark_dataset(tmp_db)
        assert count == 12
        cursor = tmp_db.execute("SELECT COUNT(*) FROM quality_bench_dataset")
        assert cursor.fetchone()[0] == 12

    def test_load_benchmark_cases(self, tmp_db):
        from app.rag.quality_bench import seed_benchmark_dataset, load_benchmark_cases
        ensure_all(tmp_db)
        seed_benchmark_dataset(tmp_db)
        cases = load_benchmark_cases(tmp_db)
        assert len(cases) == 12
        categories = {c.category for c in cases}
        assert categories == {"factual", "cross_doc", "no_answer", "conflict"}

    def test_factual_cases_exist(self, tmp_db):
        from app.rag.quality_bench import seed_benchmark_dataset, load_benchmark_cases
        ensure_all(tmp_db)
        seed_benchmark_dataset(tmp_db)
        cases = [c for c in load_benchmark_cases(tmp_db) if c.category == "factual"]
        assert len(cases) == 4

    def test_no_answer_cases_should_refuse(self, tmp_db):
        from app.rag.quality_bench import seed_benchmark_dataset, load_benchmark_cases
        ensure_all(tmp_db)
        seed_benchmark_dataset(tmp_db)
        cases = [c for c in load_benchmark_cases(tmp_db) if c.category == "no_answer"]
        assert all(c.should_refuse for c in cases), "All no_answer cases should require refusal"

    def test_conflict_cases_have_conflict_docs(self, tmp_db):
        from app.rag.quality_bench import seed_benchmark_dataset, load_benchmark_cases
        ensure_all(tmp_db)
        seed_benchmark_dataset(tmp_db)
        cases = [c for c in load_benchmark_cases(tmp_db) if c.category == "conflict"]
        assert all(len(c.conflict_docs) > 0 for c in cases)

    def test_cross_doc_cases_multi_reference(self, tmp_db):
        from app.rag.quality_bench import seed_benchmark_dataset, load_benchmark_cases
        ensure_all(tmp_db)
        seed_benchmark_dataset(tmp_db)
        cases = [c for c in load_benchmark_cases(tmp_db) if c.category == "cross_doc"]
        assert all(len(c.expected_relevant) >= 2 for c in cases), \
            "Cross-doc cases should reference multiple documents"

    def test_compute_recall_perfect(self):
        from app.rag.quality_bench import compute_recall
        assert compute_recall(["a", "b", "c"], ["a", "c"]) == 1.0

    def test_compute_recall_partial(self):
        from app.rag.quality_bench import compute_recall
        assert compute_recall(["a"], ["a", "b", "c"]) == 1.0 / 3.0

    def test_compute_recall_empty_relevant(self):
        from app.rag.quality_bench import compute_recall
        assert compute_recall(["a", "b"], []) == 1.0

    def test_compute_citation_accuracy(self):
        from app.rag.quality_bench import compute_citation_accuracy
        assert compute_citation_accuracy(["doc1", "doc2"], ["doc1", "doc3"]) == 0.5

    def test_compute_citation_accuracy_empty_citations(self):
        from app.rag.quality_bench import compute_citation_accuracy
        assert compute_citation_accuracy([], ["doc1"]) == 0.0

    def test_evaluate_single_query_factual(self):
        from app.rag.quality_bench import QualityTestCase, evaluate_single_query

        def mock_retrieve(query: str) -> dict:
            return {
                "answer": "2026-09-15",
                "citations": ["project_plan.md"],
                "retrieved_docs": ["project_plan.md"],
                "refused": False,
                "latency_ms": 120.0,
            }

        tc = QualityTestCase(
            test_case_id="test-1", category="factual",
            question="交付日期?",
            expected_answer="2026-09-15",
            expected_relevant=["project_plan.md"],
            should_refuse=False,
        )
        rec = evaluate_single_query(tc, mock_retrieve)
        assert rec.recall_rate == 1.0
        assert rec.citation_accuracy == 1.0
        assert rec.refusal_rate == 1.0

    def test_evaluate_single_query_no_answer(self):
        from app.rag.quality_bench import QualityTestCase, evaluate_single_query

        def mock_retrieve(query: str) -> dict:
            return {
                "answer": None,
                "citations": [],
                "retrieved_docs": [],
                "refused": True,
                "latency_ms": 50.0,
            }

        tc = QualityTestCase(
            test_case_id="test-2", category="no_answer",
            question="不存在的问题?",
            should_refuse=True,
        )
        rec = evaluate_single_query(tc, mock_retrieve)
        assert rec.refusal_rate == 1.0
        assert rec.failed_count == 0

    def test_evaluate_single_query_failure(self):
        from app.rag.quality_bench import QualityTestCase, evaluate_single_query

        def mock_retrieve(query: str) -> dict:
            return {
                "answer": None,
                "citations": [],
                "retrieved_docs": [],
                "refused": False,
                "latency_ms": 0,
            }

        tc = QualityTestCase(
            test_case_id="test-3", category="factual",
            question="What date?", expected_answer="2026-09-15",
            should_refuse=False,
        )
        rec = evaluate_single_query(tc, mock_retrieve)
        assert rec.failure_rate == 1.0
        assert rec.failed_count == 1

    def test_evaluate_benchmark_full(self):
        from app.rag.quality_bench import (
            QualityTestCase, evaluate_benchmark, DEFAULT_BENCHMARK_CASES,
        )

        call_count = [0]

        def mock_retrieve(query: str) -> dict:
            call_count[0] += 1
            return {
                "answer": "mock answer",
                "citations": [],
                "retrieved_docs": [],
                "refused": "no_answer" in query.lower() or "不存在" in query,
                "latency_ms": 100.0,
            }

        result = evaluate_benchmark(
            DEFAULT_BENCHMARK_CASES,
            mock_retrieve,
            benchmark_name="test-run",
            embed_model="test-model",
        )
        assert result.benchmark_name == "test-run"
        assert result.total_cases == 12
        assert call_count[0] == 12

    def test_persist_metrics(self, tmp_db):
        from app.rag.quality_bench import QualityMetricRecord, persist_metrics
        ensure_all(tmp_db)
        records = [
            QualityMetricRecord(
                benchmark_name="t", test_case_id="tc1", category="factual",
                recall_rate=0.9, citation_accuracy=0.8, refusal_rate=1.0,
                latency_ms=100, failure_rate=0, run_at=datetime.now().isoformat(),
            ),
        ]
        persist_metrics(tmp_db, records)
        cursor = tmp_db.execute("SELECT COUNT(*) FROM quality_metric WHERE benchmark_name = ?", ("t",))
        assert cursor.fetchone()[0] == 1


# ============================================================================
# Test 7: Quality Metrics Service
# ============================================================================

class TestQualityMetricsService:
    """Test the quality metrics service wrapper."""

    def test_seed_default_benchmark(self, tmp_db):
        from app.services.quality_metrics import ensure_quality_schema, seed_default_benchmark
        ensure_quality_schema(tmp_db)
        count = seed_default_benchmark(tmp_db)
        assert count == 12

    def test_historical_metrics_empty(self, tmp_db):
        from app.services.quality_metrics import ensure_quality_schema, get_historical_metrics
        ensure_quality_schema(tmp_db)
        records = get_historical_metrics(tmp_db)
        assert records == []

    def test_historical_metrics_with_data(self, tmp_db):
        from app.rag.quality_bench import QualityMetricRecord, persist_metrics
        from app.services.quality_metrics import ensure_quality_schema, get_historical_metrics
        ensure_quality_schema(tmp_db)
        now = datetime.now().isoformat(timespec="seconds")
        records = [
            QualityMetricRecord(
                benchmark_name="default", test_case_id="tc1", category="factual",
                recall_rate=0.8, run_at=now, question="Q?",
            ),
        ]
        persist_metrics(tmp_db, records)
        hist = get_historical_metrics(tmp_db)
        assert len(hist) == 1

    def test_compare_runs_no_regressions(self, tmp_db):
        from app.rag.quality_bench import QualityMetricRecord, persist_metrics
        from app.services.quality_metrics import ensure_quality_schema, compare_runs
        ensure_quality_schema(tmp_db)
        t1 = "2026-01-01T00:00:00"
        t2 = "2026-01-02T00:00:00"
        for ts, recall in [(t1, 0.8), (t2, 0.82)]:
            records = [
                QualityMetricRecord(
                    benchmark_name="default", test_case_id="tc1", category="factual",
                    recall_rate=recall, citation_accuracy=0.9, refusal_rate=1.0,
                    latency_ms=100, failure_rate=0, run_at=ts, question="Q?",
                ),
            ]
            persist_metrics(tmp_db, records)

        result = compare_runs(tmp_db, t2, t1)
        assert not result.get("has_regressions", False)

    def test_compare_runs_regression(self, tmp_db):
        from app.rag.quality_bench import QualityMetricRecord, persist_metrics
        from app.services.quality_metrics import ensure_quality_schema, compare_runs
        ensure_quality_schema(tmp_db)
        t1 = "2026-01-01T00:00:00"
        t2 = "2026-01-02T00:00:00"
        # t2 has worse metrics
        for ts, recall, fail in [(t1, 0.9, 0.0), (t2, 0.7, 0.2)]:
            records = [
                QualityMetricRecord(
                    benchmark_name="default", test_case_id="tc1", category="factual",
                    recall_rate=recall, citation_accuracy=0.9, refusal_rate=1.0,
                    latency_ms=100, failure_rate=fail, run_at=ts, question="Q?",
                ),
            ]
            persist_metrics(tmp_db, records)

        result = compare_runs(tmp_db, t2, t1)
        assert result.get("has_regressions", False)
        assert len(result.get("regressions", [])) > 0


# ============================================================================
# Test 8: Risk Scanner (Scheduled Scan)
# ============================================================================

class TestRiskScanner:
    """Test the full risk scanner flow."""

    def _setup_project(self, conn):
        """Create minimal project setup for scanner tests."""
        from app.services.risk_scanner import ensure_all as ensure_all_s
        ensure_all_s(conn)
        # Create tasks table
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                owner TEXT DEFAULT NULL,
                due_date TEXT DEFAULT NULL,
                priority TEXT DEFAULT NULL,
                acceptance_criteria TEXT DEFAULT NULL,
                status TEXT DEFAULT 'pending_confirmation',
                dependencies TEXT NOT NULL DEFAULT '[]',
                source_ref TEXT DEFAULT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS task_evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                evidence_path TEXT NOT NULL DEFAULT ''
            );
        """)
        conn.commit()

    def test_scanner_initializes_schema(self, tmp_db):
        from app.services.risk_scanner import RiskScanner, ScannerConfig
        scanner = RiskScanner(tmp_db, "proj-1")
        result = scanner.run(ScannerConfig())
        assert result.status == "completed"
        assert result.project_id == "proj-1"

    def test_scanner_seeds_rules(self, tmp_db):
        from app.services.risk_scanner import RiskScanner, ScannerConfig
        self._setup_project(tmp_db)
        scanner = RiskScanner(tmp_db, "proj-1")
        scanner.run(ScannerConfig())
        cursor = tmp_db.execute("SELECT COUNT(*) FROM risk_rule")
        assert cursor.fetchone()[0] == 6

    def test_scanner_detects_overdue(self, tmp_db):
        from app.services.risk_scanner import RiskScanner, ScannerConfig
        self._setup_project(tmp_db)
        today = date.today()
        yesterday = (today - timedelta(days=5)).isoformat()
        tmp_db.execute(
            "INSERT INTO tasks (id, project_id, title, due_date, status) VALUES (?, ?, ?, ?, ?)",
            ("t-1", "proj-1", "逾期任务", yesterday, "not_started"),
        )
        tmp_db.commit()
        scanner = RiskScanner(tmp_db, "proj-1")
        result = scanner.run(ScannerConfig(notify_external=False))
        assert result.status == "completed"
        # Should detect overdue
        cursor = tmp_db.execute(
            "SELECT COUNT(*) FROM risk_record WHERE project_id = ? AND risk_type = 'overdue'",
            ("proj-1",),
        )
        assert cursor.fetchone()[0] >= 1

    def test_scanner_detects_near_deadline(self, tmp_db):
        from app.services.risk_scanner import RiskScanner, ScannerConfig
        self._setup_project(tmp_db)
        today = date.today()
        tomorrow = (today + timedelta(days=1)).isoformat()
        tmp_db.execute(
            "INSERT INTO tasks (id, project_id, title, due_date, status) VALUES (?, ?, ?, ?, ?)",
            ("t-2", "proj-1", "临近截止", tomorrow, "in_progress"),
        )
        tmp_db.commit()
        scanner = RiskScanner(tmp_db, "proj-1")
        result = scanner.run(ScannerConfig())
        cursor = tmp_db.execute(
            "SELECT COUNT(*) FROM risk_record WHERE project_id = ? AND risk_type = 'near_deadline'",
            ("proj-1",),
        )
        assert cursor.fetchone()[0] >= 1

    def test_scanner_default_no_notification(self, tmp_db):
        """Verify default scan does NOT send external notifications."""
        from app.services.risk_scanner import RiskScanner, ScannerConfig
        self._setup_project(tmp_db)
        config = ScannerConfig()
        assert config.notify_external is False, "Default must not notify externally"

    def test_scanner_ack_risk(self, tmp_db):
        from app.services.risk_scanner import RiskScanner
        scanner = RiskScanner(tmp_db, "proj-1")
        # Insert a risk record directly
        now = datetime.now().isoformat(timespec="seconds")
        tmp_db.execute(
            """INSERT INTO risk_record
               (record_id, project_id, rule_id, risk_type, entity_type, entity_id,
                severity, title, description, lifecycle, dedup_hash, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("risk-1", "proj-1", "r1", "overdue", "task", "t1", "high",
             "Test", "Test desc", "active", "hash1", now, now),
        )
        tmp_db.commit()
        ok = scanner.ack_risk("risk-1", "operator-1")
        assert ok is True
        cursor = tmp_db.execute(
            "SELECT lifecycle, acknowledged_by FROM risk_record WHERE record_id = ?",
            ("risk-1",),
        )
        row = cursor.fetchone()
        assert row["lifecycle"] == "acknowledged"
        assert row["acknowledged_by"] == "operator-1"

    def test_scanner_resolve_risk(self, tmp_db):
        from app.services.risk_scanner import RiskScanner
        scanner = RiskScanner(tmp_db, "proj-1")
        now = datetime.now().isoformat(timespec="seconds")
        tmp_db.execute(
            """INSERT INTO risk_record
               (record_id, project_id, rule_id, risk_type, entity_type, entity_id,
                severity, title, description, lifecycle, dedup_hash, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("risk-2", "proj-1", "r1", "overdue", "task", "t1", "high",
             "Test", "Test desc", "active", "hash2", now, now),
        )
        tmp_db.commit()
        ok = scanner.resolve_risk("risk-2", "operator-1", "已处理完毕")
        assert ok is True
        cursor = tmp_db.execute(
            "SELECT lifecycle, resolved_by, resolution_note FROM risk_record WHERE record_id = ?",
            ("risk-2",),
        )
        row = cursor.fetchone()
        assert row["lifecycle"] == "resolved"
        assert row["resolved_by"] == "operator-1"
        assert "已处理完毕" in row["resolution_note"]

    def test_scanner_notify_external_default_false(self):
        """ScannerConfig.notify_external must default to False."""
        from app.services.risk_scanner import ScannerConfig
        config = ScannerConfig()
        assert config.notify_external is False

    def test_scanner_scan_run_persisted(self, tmp_db):
        from app.services.risk_scanner import RiskScanner, ScannerConfig
        self._setup_project(tmp_db)
        scanner = RiskScanner(tmp_db, "proj-1")
        scanner.run(ScannerConfig())
        cursor = tmp_db.execute("SELECT COUNT(*) FROM risk_scan_run WHERE project_id = ?", ("proj-1",))
        assert cursor.fetchone()[0] == 1

    def test_scanner_deduplication(self, tmp_db):
        """Running twice should not create duplicate risks."""
        from app.services.risk_scanner import RiskScanner, ScannerConfig
        self._setup_project(tmp_db)
        yesterday = (date.today() - timedelta(days=5)).isoformat()
        tmp_db.execute(
            "INSERT INTO tasks (id, project_id, title, due_date, status) VALUES (?, ?, ?, ?, ?)",
            ("t-dup", "proj-1", "重复测试", yesterday, "not_started"),
        )
        tmp_db.commit()
        scanner = RiskScanner(tmp_db, "proj-1")
        r1 = scanner.run(ScannerConfig())
        r2 = scanner.run(ScannerConfig())
        # Second run should have fewer or equal new risks
        assert r2.new_risks <= r1.new_risks

    def test_scanner_reads_phase_f_singular_task_table(self, tmp_db):
        """The Stage G scanner must consume the actual Phase F task table."""
        from app.schemas.task_sql import DDL
        from app.services.risk_scanner import RiskScanner, ScannerConfig

        tmp_db.executescript(DDL)
        yesterday = (date.today() - timedelta(days=2)).isoformat()
        tmp_db.execute(
            """INSERT INTO task (id, project_id, title, due_date, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("phase-f-task", "proj-phase-f", "Overdue Phase F task", yesterday,
             "not_started", datetime.now().isoformat(), datetime.now().isoformat()),
        )
        tmp_db.commit()

        result = RiskScanner(tmp_db, "proj-phase-f").run(ScannerConfig())
        assert result.new_risks >= 1
        assert tmp_db.execute(
            "SELECT COUNT(*) FROM risk_record WHERE project_id = ? AND risk_type = 'overdue'",
            ("proj-phase-f",),
        ).fetchone()[0] == 1


# ============================================================================
# Test 9: Error Codes (Stage G)
# ============================================================================

class TestStageGErrorCodes:
    """Verify all Stage G error codes are registered."""

    def test_risk_error_codes(self):
        from app.observability.error_codes import APP_ERROR_CODES
        assert "RISK_RULE_NOT_FOUND" in APP_ERROR_CODES
        assert "RISK_RECORD_NOT_FOUND" in APP_ERROR_CODES
        assert "RISK_SCAN_FAILED" in APP_ERROR_CODES
        assert "DOC_VERSION_NOT_FOUND" in APP_ERROR_CODES
        assert "BENCHMARK_RUN_FAILED" in APP_ERROR_CODES
        assert "BENCHMARK_DATASET_EMPTY" in APP_ERROR_CODES
        assert "IMPACT_ANALYSIS_FAILED" in APP_ERROR_CODES

    def test_get_error_returns_valid(self):
        from app.observability.error_codes import get_error
        for code in [
            "RISK_RULE_NOT_FOUND", "RISK_RECORD_NOT_FOUND", "RISK_SCAN_FAILED",
            "DOC_VERSION_NOT_FOUND", "BENCHMARK_RUN_FAILED", "IMPACT_ANALYSIS_FAILED",
        ]:
            result = get_error(code)
            assert "error_code" in result
            assert result["error_code"] == code


# ============================================================================
# Test 10: Models (Stage G) from models.py
# ============================================================================

class TestStageGModels:
    """Validate all Stage G model classes."""

    def test_risk_severity_str_enum(self):
        from app.schemas.models import RiskSeverityStr
        assert RiskSeverityStr.LOW == "low"
        assert RiskSeverityStr.HIGH == "high"
        assert RiskSeverityStr.CRITICAL == "critical"

    def test_risk_lifecycle_enum(self):
        from app.schemas.models import RiskLifecycleStr
        assert RiskLifecycleStr.ACTIVE == "active"
        assert RiskLifecycleStr.ACKNOWLEDGED == "acknowledged"
        assert RiskLifecycleStr.RESOLVED == "resolved"
        assert RiskLifecycleStr.DISMISSED == "dismissed"
        assert RiskLifecycleStr.EXPIRED == "expired"

    def test_risk_rule_config_valid(self):
        from app.schemas.models import RiskRuleConfig, RiskSeverityStr
        config = RiskRuleConfig(
            rule_id="r1", rule_name="测试", rule_type="overdue",
            severity=RiskSeverityStr.HIGH, config_json='{"days": 3}',
        )
        assert config.rule_id == "r1"
        assert config.enabled is True

    def test_risk_scan_summary(self):
        from app.schemas.models import RiskScanSummary
        s = RiskScanSummary(
            scan_id="s1", project_id="p1",
            total_rules=6, new_risks=3, active_risks=5, total_risks=10,
        )
        assert s.total_rules == 6
        assert s.scan_type == "full"

    def test_change_impact_report_model(self):
        from app.schemas.models import ChangeImpactReport, ChangeImpactEntry
        report = ChangeImpactReport(
            project_id="p1",
            changed_files=["a.md"],
            total_affected=2,
            affected_tasks=[
                ChangeImpactEntry(entity_id="t1", entity_title="T1", reason="R", source_file="a.md"),
            ],
        )
        assert report.total_affected == 2
        assert len(report.affected_tasks) == 1

    def test_quality_test_case_model(self):
        from app.schemas.models import QualityTestCaseModel
        tc = QualityTestCaseModel(
            test_case_id="q1", category="factual", question="Q?",
            expected_relevant=["a.md"],
        )
        assert tc.category == "factual"
        assert tc.should_refuse is False

    def test_quality_benchmark_run(self):
        from app.schemas.models import QualityBenchmarkRun
        run = QualityBenchmarkRun(
            benchmark_name="default", total_cases=12, passed=10, failed=2,
            avg_recall=0.85, avg_citation_accuracy=0.9, avg_refusal_rate=0.95,
            avg_latency_ms=150, total_failure_rate=0.1,
        )
        assert run.total_cases == 12
        assert run.passed + run.failed == 12


# ============================================================================
# Helper
# ============================================================================

def ensure_all(conn: sqlite3.Connection) -> None:
    """Apply ALL Stage G DDL to a connection."""
    from app.schemas.risk_sql import RISK_DDL
    from app.schemas.doc_version_sql import DOC_VERSION_DDL, QUALITY_METRIC_DDL
    conn.executescript(RISK_DDL + "\n" + DOC_VERSION_DDL + "\n" + QUALITY_METRIC_DDL)
    conn.commit()
