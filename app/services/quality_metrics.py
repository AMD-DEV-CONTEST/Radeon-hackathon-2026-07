"""Quality Metrics Service (Stage G).

Higher-level service wrapper around the quality benchmark module.
Provides functions to:
- Seed benchmark datasets
- Run benchmark evaluations
- Compare metric runs and detect regressions
- Store and retrieve historical metrics
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.rag.quality_bench import (
    DEFAULT_BENCHMARK_CASES,
    QualityBenchmarkResult,
    QualityMetricRecord,
    QualityTestCase,
    evaluate_benchmark,
    load_benchmark_cases,
    persist_metrics,
    seed_benchmark_dataset,
)


def ensure_quality_schema(conn: sqlite3.Connection) -> None:
    """Ensure quality-metric tables exist."""
    from app.schemas.doc_version_sql import QUALITY_METRIC_DDL
    conn.executescript(QUALITY_METRIC_DDL)
    conn.commit()


def seed_default_benchmark(conn: sqlite3.Connection) -> int:
    """Seed the built-in benchmark dataset.

    Returns the number of cases inserted.
    """
    ensure_quality_schema(conn)
    return seed_benchmark_dataset(conn, DEFAULT_BENCHMARK_CASES)


def run_benchmark(
    conn: sqlite3.Connection,
    retrieve_fn,
    benchmark_name: str = "default",
    embed_model: str = "",
) -> QualityBenchmarkResult:
    """Load benchmark cases from DB and run full evaluation.

    Args:
        conn: SQLite connection.
        retrieve_fn: Callable(query: str) -> dict with answer, citations, etc.
        benchmark_name: Label for this run.
        embed_model: Embedding model identifier.

    Returns:
        :class:`QualityBenchmarkResult` with aggregated metrics.
    """
    ensure_quality_schema(conn)
    cases = load_benchmark_cases(conn)
    if not cases:
        # Seed if empty
        seed_default_benchmark(conn)
        cases = load_benchmark_cases(conn)

    result = evaluate_benchmark(cases, retrieve_fn, benchmark_name, embed_model)

    # Persist per-case records
    records: list[QualityMetricRecord] = []
    for tc in cases:
        from app.rag.quality_bench import evaluate_single_query
        rec = evaluate_single_query(tc, retrieve_fn)
        rec.benchmark_name = benchmark_name
        rec.embed_model = embed_model
        records.append(rec)
    persist_metrics(conn, records)

    return result


def get_historical_metrics(
    conn: sqlite3.Connection,
    benchmark_name: str = "default",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Retrieve the most recent quality metric records.

    Returns a list of dicts suitable for comparison / charting.
    """
    cursor = conn.execute(
        """SELECT * FROM quality_metric
           WHERE benchmark_name = ?
           ORDER BY run_at DESC
           LIMIT ?""",
        (benchmark_name, limit),
    )
    cols = [
        "id", "benchmark_name", "test_case_id", "category", "question",
        "expected_answer", "actual_answer", "recall_count", "total_relevant",
        "recall_rate", "citation_correct", "citation_accuracy",
        "refused", "should_refuse", "refusal_rate",
        "latency_ms", "total_queries", "failed_count", "failure_rate",
        "run_at", "embed_model",
    ]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def compare_runs(
    conn: sqlite3.Connection,
    run_a: str,
    run_b: str,
) -> dict[str, Any]:
    """Compare two benchmark runs and identify regressions.

    Args:
        conn: SQLite connection.
        run_a: ISO timestamp of the newer run.
        run_b: ISO timestamp of the older run.

    Returns:
        Dict with per-metric comparison and regression flags.
    """
    a_records = _records_for_run(conn, run_a)
    b_records = _records_for_run(conn, run_b)

    if not a_records or not b_records:
        return {"error": "One or both runs not found"}

    a_avg = _avg_metrics(a_records)
    b_avg = _avg_metrics(b_records)

    regressions: list[str] = []
    if a_avg["recall_rate"] < b_avg["recall_rate"] - 0.05:
        regressions.append("recall_rate dropped")
    if a_avg["citation_accuracy"] < b_avg["citation_accuracy"] - 0.05:
        regressions.append("citation_accuracy dropped")
    if a_avg["failure_rate"] > b_avg["failure_rate"] + 0.05:
        regressions.append("failure_rate increased")
    if a_avg["avg_latency_ms"] > b_avg["avg_latency_ms"] * 1.2:
        regressions.append("latency increased >20%")

    return {
        "run_a": {"ts": run_a, "avg": a_avg},
        "run_b": {"ts": run_b, "avg": b_avg},
        "regressions": regressions,
        "has_regressions": len(regressions) > 0,
    }


def _records_for_run(
    conn: sqlite3.Connection,
    run_at: str,
) -> list[dict[str, Any]]:
    cursor = conn.execute(
        "SELECT * FROM quality_metric WHERE run_at = ?",
        (run_at,),
    )
    cols = [
        "id", "benchmark_name", "test_case_id", "category", "question",
        "expected_answer", "actual_answer", "recall_count", "total_relevant",
        "recall_rate", "citation_correct", "citation_accuracy",
        "refused", "should_refuse", "refusal_rate",
        "latency_ms", "total_queries", "failed_count", "failure_rate",
        "run_at", "embed_model",
    ]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _avg_metrics(records: list[dict[str, Any]]) -> dict[str, float]:
    n = max(len(records), 1)
    return {
        "recall_rate": sum(r.get("recall_rate", 0) or 0 for r in records) / n,
        "citation_accuracy": sum(r.get("citation_accuracy", 0) or 0 for r in records) / n,
        "refusal_rate": sum(r.get("refusal_rate", 0) or 0 for r in records) / n,
        "avg_latency_ms": sum(r.get("latency_ms", 0) or 0 for r in records) / n,
        "failure_rate": sum(r.get("failure_rate", 0) or 0 for r in records) / n,
    }
