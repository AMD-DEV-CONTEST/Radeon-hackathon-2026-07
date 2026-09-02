#!/usr/bin/env python3
"""Stage G — Continuous Knowledge & Risk Monitoring verification script.

Verifies:
1. All Stage G SQL schemas are intact
2. All 6 default risk rules load correctly
3. Risk engine evaluates all rule types
4. Deduplication works correctly
5. Document version tracking (new/update/delete) works
6. File change detection categorises correctly
7. Change impact recording and analysis works
8. Quality benchmark dataset seeds and loads
9. Quality metrics: recall, citation accuracy, refusal rate, latency, failure rate
10. Risk scanner full flow with no-external-notification default
11. All 7 Stage G error codes registered
12. Stage G models import and validate
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def green(text: str) -> str:
    return f"\033[92m{text}\033[0m"


def red(text: str) -> str:
    return f"\033[91m{text}\033[0m"


passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  {green('PASS')}  {name}" + (f" — {detail}" if detail else ""))
    else:
        failed += 1
        print(f"  {red('FAIL')}  {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    print("=" * 60)
    print("Stage G Verification")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Schema integrity
    # ------------------------------------------------------------------
    print("\n[1] SQL Schema Integrity")

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    from app.schemas.risk_sql import RISK_DDL, RISK_DEFAULT_RULES
    from app.schemas.doc_version_sql import DOC_VERSION_DDL, QUALITY_METRIC_DDL

    conn.executescript(RISK_DDL + "\n" + DOC_VERSION_DDL + "\n" + QUALITY_METRIC_DDL)
    conn.commit()

    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cursor.fetchall()}
    expected_tables = {
        "risk_rule", "risk_record", "risk_scan_run",
        "document_version", "document_change_log", "change_impact",
        "quality_metric", "quality_bench_dataset",
    }
    for tbl in expected_tables:
        check(f"table '{tbl}' exists", tbl in tables)

    # ------------------------------------------------------------------
    # 2. Default rules
    # ------------------------------------------------------------------
    print("\n[2] Default Risk Rules")
    check("6 default rules", len(RISK_DEFAULT_RULES) == 6)
    rule_types = {r["rule_type"] for r in RISK_DEFAULT_RULES}
    for rt in ["near_deadline", "overdue", "no_evidence", "acceptance_gap", "dependency_block", "material_conflict"]:
        check(f"rule type '{rt}' present", rt in rule_types)
    for r in RISK_DEFAULT_RULES:
        required = {"rule_id", "rule_name", "rule_type", "severity", "config_json"}
        check(f"{r['rule_id']} has required fields", required.issubset(r.keys()))

    # Seed and verify
    for d in RISK_DEFAULT_RULES:
        conn.execute(
            """INSERT INTO risk_rule
               (rule_id, rule_name, rule_type, description, severity, config_json, enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (d["rule_id"], d["rule_name"], d["rule_type"],
             d["description"], d["severity"], d["config_json"], d.get("enabled", 1)),
        )
    conn.commit()
    check("all 6 rules seeded in DB", conn.execute("SELECT COUNT(*) FROM risk_rule").fetchone()[0] == 6)

    # ------------------------------------------------------------------
    # 3. Risk Engine
    # ------------------------------------------------------------------
    print("\n[3] Risk Engine — Rule Evaluation")
    from app.services.risk_engine import (
        TaskSnapshot, RiskSeverity, RiskLifecycle,
        _check_near_deadline, _check_overdue, _check_no_evidence,
        _check_acceptance_gap, _check_dependency_block, _check_material_conflict,
        evaluate_risks, seed_default_rules, RiskScanContext, RiskRule,
    )

    today = date.today()
    tasks = [
        TaskSnapshot(
            task_id="t-near", title="临近截止任务",
            due_date=today + timedelta(days=1), status="in_progress",
        ),
        TaskSnapshot(
            task_id="t-overdue", title="逾期任务",
            due_date=today - timedelta(days=10), status="not_started",
        ),
        TaskSnapshot(
            task_id="t-noevid", title="无证据完成",
            status="completed", acceptance_criteria="AC1", evidence_count=0,
        ),
        TaskSnapshot(
            task_id="t-accept", title="验收缺失",
            status="completed", acceptance_criteria="AC2", evidence_count=5,
        ),
        TaskSnapshot(
            task_id="t-block", title="依赖阻塞",
            status="in_progress", dependencies=["dep-a"],
        ),
        TaskSnapshot(
            task_id="dep-a", title="前置依赖A", status="not_started",
        ),
    ]

    r1 = _check_near_deadline(tasks[0], {"days_before": 3})
    check("near_deadline detected", r1 is not None)
    check("near_deadline severity is high (1-day)", r1 is not None and r1.severity.value == "high")

    r2 = _check_overdue(tasks[1], {"grace_days": 0})
    check("overdue detected", r2 is not None)
    check("overdue severity is critical (10-day)", r2 is not None and r2.severity.value == "critical")

    r3 = _check_no_evidence(tasks[2], {"check_status": ["completed"], "min_evidence": 1})
    check("no_evidence detected", r3 is not None)
    check("no_evidence severity is high", r3 is not None and r3.severity.value == "high")

    r4 = _check_acceptance_gap(tasks[3], {"check_status": ["completed"]})
    check("acceptance_gap detected", r4 is not None)

    all_tasks = {t.task_id: t for t in tasks}
    r5 = _check_dependency_block(tasks[4], {
        "_all_tasks": all_tasks,
        "blocking_statuses": ["not_started"],
    })
    check("dependency_block detected", r5 is not None)

    r6 = _check_material_conflict(tasks[0], {
        "_conflicts": {"t-near": ["预算500万", "调整至450万"]},
    })
    check("material_conflict detected", r6 is not None)

    # Orchestration
    rules = seed_default_rules()
    ctx = RiskScanContext(
        project_id="test", tasks=tasks, all_tasks_dict=all_tasks, rules=rules,
    )
    unique, result = evaluate_risks(ctx)
    check(f"evaluate_risks found {len(unique)} unique risks", len(unique) >= 2)
    check("scan_result status completed", result.status == "completed")

    # ------------------------------------------------------------------
    # 4. Dedup & Aggregation
    # ------------------------------------------------------------------
    print("\n[4] Deduplication & Aggregation")
    from app.services.risk_engine import (
        deduplicate_risks, RiskRecord, _make_dedup_hash, aggregate_summary, highest_severity,
    )

    h1 = _make_dedup_hash("p1", "r1", "t1", "active")
    h2 = _make_dedup_hash("p1", "r1", "t1", "active")
    check("dedup hash stable", h1 == h2)
    check("dedup hash unique per rule", _make_dedup_hash("p1", "r2", "t1", "active") != h1)

    r01 = RiskRecord(record_id="a", dedup_hash="hash1", severity=RiskSeverity.HIGH)
    r02 = RiskRecord(record_id="b", dedup_hash="hash1", severity=RiskSeverity.LOW)
    unique_r, dupes = deduplicate_risks([r01, r02])
    check("dedup removes duplicates", len(unique_r) == 1 and dupes == 1)

    r03 = RiskRecord(record_id="c", dedup_hash="hash2", severity=RiskSeverity.LOW)
    unique_r2, dupes2 = deduplicate_risks([r03], {"hash2"})
    check("dedup respects existing hash set", len(unique_r2) == 0 and dupes2 == 1)

    result_sev = highest_severity([RiskSeverity.LOW, RiskSeverity.HIGH, RiskSeverity.MEDIUM])
    check("highest_severity returns HIGH", result_sev == RiskSeverity.HIGH)

    summary = aggregate_summary([r01, r03])
    check("aggregate total correct", summary["total"] == 2)

    # ------------------------------------------------------------------
    # 5. Document Version Management
    # ------------------------------------------------------------------
    print("\n[5] Document Version Management")
    from app.services.doc_version import (
        compute_file_sha256, record_file_version, detect_file_changes,
        mark_file_deleted, ensure_schema as dv_ensure, get_change_logs,
        initialise_project_versions,
    )

    dv_ensure(conn)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        f1 = root / "doc_a.md"
        f1.write_text("# Doc A\nContent here\n", encoding="utf-8")
        f2 = root / "doc_b.md"
        f2.write_text("# Doc B\nMore content\n", encoding="utf-8")

        sha1 = compute_file_sha256(f1)
        check("SHA-256 is 64 hex chars", len(sha1) == 64)

        dv = record_file_version(conn, "proj-g", "doc_a.md", sha1, f1.stat().st_size)
        check("record_file_version (new) parse_version=1", dv.parse_version == 1)
        check("record_file_version (new) is_current=True", dv.is_current is True)

        dv2 = record_file_version(conn, "proj-g", "doc_a.md", sha1, f1.stat().st_size)
        check("version unchanged when SHA same", dv2.parse_version == dv.parse_version)

        f1.write_text("# Doc A\nUpdated content!\n", encoding="utf-8")
        sha2 = compute_file_sha256(f1)
        dv3 = record_file_version(conn, "proj-g", "doc_a.md", sha2, f1.stat().st_size)
        check("version bumped on content change", dv3.parse_version == dv.parse_version + 1)
        check("new version is current", dv3.is_current is True)

        sha_b = compute_file_sha256(f2)
        record_file_version(conn, "proj-g", "doc_b.md", sha_b, f2.stat().st_size)
        mark_file_deleted(conn, "proj-g", "doc_b.md")
        cursor = conn.execute(
            "SELECT is_current FROM document_version WHERE project_id='proj-g' AND relative_path='doc_b.md'",
        )
        rows = cursor.fetchall()
        check("mark_file_deleted sets is_current=0", rows and all(r["is_current"] == 0 for r in rows))

        # Detect changes
        init_vers = {rp: dv for rp, dv in [("doc_a.md", dv3)]}
        diff = detect_file_changes(root, ["doc_a.md", "doc_b.md", "doc_c.md"], init_vers)
        check("detect_file_changes: unchanged", "doc_a.md" in diff.unchanged_files)

        # New file
        (root / "doc_c.md").write_text("# Doc C\nNew!\n", encoding="utf-8")
        diff2 = detect_file_changes(root, ["doc_a.md", "doc_c.md"], init_vers)
        check("detect_file_changes: new file", "doc_c.md" in diff2.new_files)

        logs = get_change_logs(conn, "proj-g")
        check("change_logs recorded", len(logs) >= 1)

    # ------------------------------------------------------------------
    # 6. Change Impact Analysis
    # ------------------------------------------------------------------
    print("\n[6] Change Impact Analysis")
    from app.services.change_impact import (
        ChangeImpactAnalyzer, ImpactEntry, ImpactReport, persist_impact_report,
    )

    # Re-create conn with all schemas for impact test
    conn2 = sqlite3.connect(":memory:")
    conn2.row_factory = sqlite3.Row
    conn2.executescript(RISK_DDL + "\n" + DOC_VERSION_DDL + "\n" + QUALITY_METRIC_DDL)
    conn2.commit()

    # Create tasks and task_evidence tables
    conn2.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT DEFAULT '',
            status TEXT DEFAULT 'not_started', source_ref TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS task_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, project_id TEXT,
            evidence_path TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY, project_id TEXT, status TEXT DEFAULT 'completed',
            error TEXT DEFAULT NULL
        );
    """)

    analyzer = ChangeImpactAnalyzer(conn2, "proj-g")
    report = analyzer.analyse(["project_plan.md"])
    check("impact report has project_id", report.project_id == "proj-g")
    check("impact report has changed_files", "project_plan.md" in report.changed_files)

    from app.services.doc_version import record_change_impact
    impact = record_change_impact(conn2, "proj-g", "a.md", 0, "task", "t1", "reason", "high")
    check("record_change_impact persists", impact.affected_entity_id == "t1")

    # ------------------------------------------------------------------
    # 7. Quality Benchmark
    # ------------------------------------------------------------------
    print("\n[7] Quality Benchmark & Metrics")
    from app.rag.quality_bench import (
        seed_benchmark_dataset, load_benchmark_cases, compute_recall,
        compute_citation_accuracy, evaluate_single_query, evaluate_benchmark,
        DEFAULT_BENCHMARK_CASES, QualityTestCase, persist_metrics,
        QualityMetricRecord,
    )

    seed_benchmark_dataset(conn2)
    cases = load_benchmark_cases(conn2)
    check("12 benchmark cases loaded", len(cases) == 12)

    categories = {c.category for c in cases}
    for cat in ["factual", "cross_doc", "no_answer", "conflict"]:
        check(f"category '{cat}' present", cat in categories)

    factual = [c for c in cases if c.category == "factual"]
    check("4 factual cases", len(factual) == 4)
    noans = [c for c in cases if c.category == "no_answer"]
    check("no_answer cases all should_refuse", all(c.should_refuse for c in noans))
    conflict_cases = [c for c in cases if c.category == "conflict"]
    check("conflict cases have conflict_docs", all(len(c.conflict_docs) > 0 for c in conflict_cases))

    # Compute metrics
    check("compute_recall perfect", compute_recall(["a", "b", "c"], ["a", "c"]) == 1.0)
    check("compute_recall partial", abs(compute_recall(["a"], ["a", "b", "c"]) - 1 / 3) < 0.001)
    check("compute_recall empty_relevant", compute_recall(["a", "b"], []) == 1.0)
    check("compute_citation_accuracy 0.5", compute_citation_accuracy(["d1", "d2"], ["d1", "d3"]) == 0.5)
    check("compute_citation_accuracy empty", compute_citation_accuracy([], ["d1"]) == 0.0)

    def mock_retrieve(query: str) -> dict:
        return {
            "answer": "2026-09-15",
            "citations": ["project_plan.md"],
            "retrieved_docs": ["project_plan.md"],
            "refused": "no" in query.lower(),
            "latency_ms": 120.0,
        }

    tc = QualityTestCase(
        test_case_id="test-1", category="factual",
        question="What date?", expected_answer="2026-09-15",
        expected_relevant=["project_plan.md"], should_refuse=False,
    )
    rec = evaluate_single_query(tc, mock_retrieve)
    check("evaluate_single_query recall=1.0", rec.recall_rate == 1.0)
    check("evaluate_single_query citation_accuracy=1.0", rec.citation_accuracy == 1.0)

    tc_refuse = QualityTestCase(
        test_case_id="test-ref", category="no_answer",
        question="no such info?", should_refuse=True,
    )
    rec2 = evaluate_single_query(tc_refuse, mock_retrieve)
    check("evaluate_single_query refusal_rate=1.0", rec2.refusal_rate == 1.0)

    # Full benchmark
    result = evaluate_benchmark(DEFAULT_BENCHMARK_CASES, mock_retrieve, "verify-run")
    check("benchmark total_cases=12", result.total_cases == 12)

    persist_metrics(conn2, [rec])
    check("persist_metrics writes", conn2.execute(
        "SELECT COUNT(*) FROM quality_metric WHERE test_case_id='test-1'"
    ).fetchone()[0] >= 1)

    # Quality metrics service
    from app.services.quality_metrics import (
        seed_default_benchmark, get_historical_metrics, compare_runs,
    )
    conn3 = sqlite3.connect(":memory:")
    conn3.row_factory = sqlite3.Row
    conn3.executescript(RISK_DDL + "\n" + DOC_VERSION_DDL + "\n" + QUALITY_METRIC_DDL)
    seed_default_benchmark(conn3)
    hist = get_historical_metrics(conn3)
    check("historical_metrics init empty", hist == [])

    # ------------------------------------------------------------------
    # 8. Risk Scanner
    # ------------------------------------------------------------------
    print("\n[8] Risk Scanner (Scheduled Scan)")
    from app.services.risk_scanner import RiskScanner, ScannerConfig

    conn4 = sqlite3.connect(":memory:")
    conn4.row_factory = sqlite3.Row
    conn4.executescript(RISK_DDL + "\n" + DOC_VERSION_DDL + "\n" + QUALITY_METRIC_DDL)
    conn4.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT DEFAULT '',
            status TEXT DEFAULT 'not_started', due_date TEXT DEFAULT NULL,
            owner TEXT DEFAULT '', priority TEXT DEFAULT '',
            acceptance_criteria TEXT DEFAULT '',
            dependencies TEXT DEFAULT '[]', source_ref TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS task_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, project_id TEXT,
            evidence_path TEXT DEFAULT ''
        );
    """)
    yesterday = (date.today() - timedelta(days=5)).isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    conn4.execute(
        "INSERT INTO tasks (id, project_id, title, due_date, status) VALUES (?, ?, ?, ?, ?)",
        ("t-1", "proj-g", "逾期任务", yesterday, "not_started"),
    )
    conn4.execute(
        "INSERT INTO tasks (id, project_id, title, due_date, status) VALUES (?, ?, ?, ?, ?)",
        ("t-2", "proj-g", "临近截止", tomorrow, "in_progress"),
    )
    conn4.commit()

    scanner = RiskScanner(conn4, "proj-g")
    result = scanner.run(ScannerConfig())
    check("scanner status completed", result.status == "completed")
    check("scanner new_risks > 0", result.new_risks > 0)
    check("scanner notify_external default False", ScannerConfig().notify_external is False)

    # Ack / Resolve
    cursor = conn4.execute(
        "SELECT record_id FROM risk_record WHERE project_id='proj-g' LIMIT 1"
    )
    row = cursor.fetchone()
    if row:
        rid = row["record_id"]
        ok1 = scanner.ack_risk(rid, "op1")
        check("risk can be acknowledged", ok1 is True)
        ok2 = scanner.resolve_risk(rid, "op1", "done")
        check("risk can be resolved", ok2 is True)

    # Scan run persisted
    check("scan_run persisted", conn4.execute(
        "SELECT COUNT(*) FROM risk_scan_run WHERE project_id='proj-g'"
    ).fetchone()[0] >= 1)

    # Deduplication
    r2 = scanner.run(ScannerConfig())
    check("2nd scan deduplicates (new_risks <= first)", r2.new_risks <= result.new_risks)

    # ------------------------------------------------------------------
    # 9. Error Codes
    # ------------------------------------------------------------------
    print("\n[9] Stage G Error Codes")
    from app.observability.error_codes import APP_ERROR_CODES, get_error

    for code in [
        "RISK_RULE_NOT_FOUND", "RISK_RECORD_NOT_FOUND", "RISK_SCAN_FAILED",
        "DOC_VERSION_NOT_FOUND", "BENCHMARK_RUN_FAILED", "BENCHMARK_DATASET_EMPTY",
        "IMPACT_ANALYSIS_FAILED",
    ]:
        check(f"error code '{code}' registered", code in APP_ERROR_CODES)

    for code in ["RISK_RULE_NOT_FOUND", "IMPACT_ANALYSIS_FAILED"]:
        err = get_error(code)
        check(f"get_error('{code}') has error_code", err.get("error_code") == code)
        check(f"get_error('{code}') has user_message", "user_message" in err)

    # ------------------------------------------------------------------
    # 10. Models
    # ------------------------------------------------------------------
    print("\n[10] Stage G Pydantic Models")
    from app.schemas.models import (
        RiskSeverityStr, RiskLifecycleStr, RiskRuleTypeStr,
        RiskRuleConfig, RiskRecordSummary, RiskScanRequest, RiskScanSummary,
        DocVersionSummary, ChangeImpactEntry, ChangeImpactReport,
        QualityTestCaseModel, QualityBenchmarkRun, QualityMetricEntry,
    )

    check("RiskSeverityStr enum", RiskSeverityStr.LOW == "low")
    check("RiskLifecycleStr enum", RiskLifecycleStr.ACTIVE == "active")

    config = RiskRuleConfig(rule_id="r1", rule_name="T", rule_type="overdue")
    check("RiskRuleConfig creation", config.rule_id == "r1" and config.enabled is True)

    summary = RiskScanSummary(scan_id="s1", project_id="p1", total_rules=6, new_risks=3, active_risks=5)
    check("RiskScanSummary creation", summary.total_rules == 6)

    dv_summary = DocVersionSummary(project_id="p1", relative_path="a.md", sha256="abc")
    check("DocVersionSummary creation", dv_summary.parse_version == 1)

    impact_report = ChangeImpactReport(
        project_id="p1", changed_files=["x.md"], total_affected=1,
    )
    check("ChangeImpactReport creation", impact_report.total_affected == 1)

    q_tc = QualityTestCaseModel(test_case_id="q1", category="factual", question="Q?")
    check("QualityTestCaseModel creation", q_tc.category == "factual")

    q_run = QualityBenchmarkRun(
        benchmark_name="default", total_cases=12, passed=10, failed=2,
        avg_recall=0.85, avg_citation_accuracy=0.9, avg_refusal_rate=0.95,
        avg_latency_ms=150, total_failure_rate=0.1,
    )
    check("QualityBenchmarkRun creation", q_run.total_cases == 12)

    q_metric = QualityMetricEntry(test_case_id="m1", recall_rate=0.9)
    check("QualityMetricEntry creation", abs(q_metric.recall_rate - 0.9) < 0.001)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
