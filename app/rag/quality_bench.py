"""Retrieval Quality Benchmark Dataset (Stage G).

Provides a curated benchmark set for evaluating RAG retrieval quality with
four question categories:
- factual    : single-document fact lookup
- cross_doc  : requires combining info from multiple documents
- no_answer  : question whose answer is NOT in the corpus (tests refusal)
- conflict   : contradictory info across documents (tests conflict detection)

Metrics tracked:
- recall_rate        : retrieved relevant / total relevant
- citation_accuracy  : correctly cited / total citations
- refusal_rate       : correctly refused / should-refuse total
- latency_ms         : average query latency
- failure_rate       : failed queries / total queries
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class QualityTestCase(BaseModel):
    """A single benchmark test case."""
    test_case_id: str
    category: str = "factual"
    question: str = ""
    expected_answer: str | None = None
    expected_relevant: list[str] = Field(default_factory=list)
    should_refuse: bool = False
    conflict_docs: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class QualityMetricRecord(BaseModel):
    """A single quality metric measurement (matches quality_metric table)."""
    benchmark_name: str = "default"
    test_case_id: str = ""
    category: str = "factual"
    question: str = ""
    expected_answer: str | None = None
    actual_answer: str | None = None
    recall_count: int = 0
    total_relevant: int = 0
    recall_rate: float = 0.0
    citation_correct: int = 0
    citation_accuracy: float = 0.0
    refused: int = 0
    should_refuse: int = 0
    refusal_rate: float = 0.0
    latency_ms: float = 0.0
    total_queries: int = 1
    failed_count: int = 0
    failure_rate: float = 0.0
    run_at: str = ""
    embed_model: str = ""


class QualityBenchmarkResult(BaseModel):
    """Aggregated benchmark run result."""
    benchmark_name: str
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    avg_recall: float = 0.0
    avg_citation_accuracy: float = 0.0
    avg_refusal_rate: float = 0.0
    avg_latency_ms: float = 0.0
    total_failure_rate: float = 0.0
    run_at: str = ""
    per_category: dict[str, dict[str, float]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Built-in benchmark dataset
# ---------------------------------------------------------------------------

DEFAULT_BENCHMARK_CASES: list[QualityTestCase] = [
    # ---- Factual questions ----
    QualityTestCase(
        test_case_id="factual-001",
        category="factual",
        question="项目计划书中A模块的交付日期是什么？",
        expected_answer="2026-09-15",
        expected_relevant=["project_plan.md"],
        should_refuse=False,
        tags=["date", "single_doc"],
    ),
    QualityTestCase(
        test_case_id="factual-002",
        category="factual",
        question="项目总预算是多少万元？",
        expected_answer="500",
        expected_relevant=["budget.md"],
        should_refuse=False,
        tags=["number", "single_doc"],
    ),
    QualityTestCase(
        test_case_id="factual-003",
        category="factual",
        question="项目负责人的姓名是什么？",
        expected_answer="张三",
        expected_relevant=["project_plan.md", "team.md"],
        should_refuse=False,
        tags=["person", "single_doc"],
    ),
    QualityTestCase(
        test_case_id="factual-004",
        category="factual",
        question="B模块的验收标准包含哪几个指标？",
        expected_answer="通过率≥95%，错误率≤2%，响应时间≤200ms",
        expected_relevant=["acceptance_criteria.md"],
        should_refuse=False,
        tags=["criteria", "single_doc"],
    ),
    # ---- Cross-document questions ----
    QualityTestCase(
        test_case_id="cross-001",
        category="cross_doc",
        question="A模块的交付时间是否早于B模块的开始时间？",
        expected_answer="是，A模块交付于2026-09-15，B模块开始于2026-10-01",
        expected_relevant=["project_plan.md", "schedule.md"],
        should_refuse=False,
        tags=["comparison", "cross_doc"],
    ),
    QualityTestCase(
        test_case_id="cross-002",
        category="cross_doc",
        question="预算分配与技术方案中的人力需求是否一致？",
        expected_answer=None,
        expected_relevant=["budget.md", "tech_spec.md"],
        should_refuse=False,
        tags=["consistency", "cross_doc"],
    ),
    QualityTestCase(
        test_case_id="cross-003",
        category="cross_doc",
        question="请汇总所有模块的风险项和对应的缓解措施。",
        expected_answer=None,
        expected_relevant=["risk_register.md", "mitigation_plan.md"],
        should_refuse=False,
        tags=["summary", "cross_doc"],
    ),
    # ---- No-answer questions ----
    QualityTestCase(
        test_case_id="noanswer-001",
        category="no_answer",
        question="项目使用了哪个云服务商？",
        expected_answer=None,
        expected_relevant=[],
        should_refuse=True,
        tags=["absent", "no_answer"],
    ),
    QualityTestCase(
        test_case_id="noanswer-002",
        category="no_answer",
        question="Q4季度的营收预测是多少？",
        expected_answer=None,
        expected_relevant=[],
        should_refuse=True,
        tags=["out_of_scope", "no_answer"],
    ),
    QualityTestCase(
        test_case_id="noanswer-003",
        category="no_answer",
        question="合同中第12条的违约责任条款是什么？",
        expected_answer=None,
        expected_relevant=[],
        should_refuse=True,
        tags=["absent_doc", "no_answer"],
    ),
    # ---- Conflict questions ----
    QualityTestCase(
        test_case_id="conflict-001",
        category="conflict",
        question="项目总预算是多少？",
        expected_answer="存在冲突：预算文档显示500万，会议纪要显示调整为450万",
        expected_relevant=["budget.md", "meeting_notes.md"],
        should_refuse=False,
        conflict_docs=["budget.md", "meeting_notes.md"],
        tags=["number_conflict", "conflict"],
    ),
    QualityTestCase(
        test_case_id="conflict-002",
        category="conflict",
        question="项目交付日期是否已变更？",
        expected_answer="存在冲突：计划文档显示2026-12-01，进度报告显示延期至2026-12-15",
        expected_relevant=["project_plan.md", "progress_report.md"],
        should_refuse=False,
        conflict_docs=["project_plan.md", "progress_report.md"],
        tags=["date_conflict", "conflict"],
    ),
]

DEFAULT_BENCHMARK_JSON: str = json.dumps(
    [tc.model_dump() for tc in DEFAULT_BENCHMARK_CASES],
    ensure_ascii=False,
    indent=2,
)


# ---------------------------------------------------------------------------
# Benchmark seeding
# ---------------------------------------------------------------------------

def seed_benchmark_dataset(
    conn: sqlite3.Connection,
    cases: list[QualityTestCase] | None = None,
) -> int:
    """Insert benchmark test cases into quality_bench_dataset table.

    Args:
        conn: SQLite connection.
        cases: Test cases to seed; defaults to :data:`DEFAULT_BENCHMARK_CASES`.

    Returns:
        Number of cases inserted.
    """
    if cases is None:
        cases = DEFAULT_BENCHMARK_CASES

    count = 0
    for tc in cases:
        conn.execute(
            """INSERT OR REPLACE INTO quality_bench_dataset
               (test_case_id, category, question, expected_answer,
                expected_relevant, should_refuse, conflict_docs, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                tc.test_case_id, tc.category, tc.question,
                tc.expected_answer,
                json.dumps(tc.expected_relevant, ensure_ascii=False),
                int(tc.should_refuse),
                json.dumps(tc.conflict_docs, ensure_ascii=False),
                json.dumps(tc.tags, ensure_ascii=False),
            ),
        )
        count += 1
    conn.commit()
    return count


def load_benchmark_cases(
    conn: sqlite3.Connection,
) -> list[QualityTestCase]:
    """Load all benchmark test cases from the database."""
    cursor = conn.execute("SELECT * FROM quality_bench_dataset ORDER BY category, test_case_id")
    cases: list[QualityTestCase] = []
    cols = [
        "id", "test_case_id", "category", "question", "expected_answer",
        "expected_relevant", "should_refuse", "conflict_docs", "tags",
    ]
    for row in cursor.fetchall():
        d = dict(zip(cols, row))
        d["expected_relevant"] = json.loads(d.get("expected_relevant", "[]") or "[]")
        d["should_refuse"] = bool(d.get("should_refuse", 0))
        d["conflict_docs"] = json.loads(d.get("conflict_docs", "[]") or "[]")
        d["tags"] = json.loads(d.get("tags", "[]") or "[]")
        cases.append(QualityTestCase(**d))
    return cases


# ---------------------------------------------------------------------------
# Metrics evaluation
# ---------------------------------------------------------------------------

@dataclass
class RetrieveFn:
    """Minimal retriever contract for benchmark evaluation.

    The benchmark runner calls ``retrieve(query)`` which must return a dict
    with keys: ``answer``, ``citations``, ``latency_ms``, ``refused``,
    and optionally ``retrieved_docs``.
    """

    retrieve: Callable[[str], dict[str, Any]]


def compute_recall(
    retrieved_doc_ids: list[str],
    relevant_doc_ids: list[str],
) -> float:
    """Compute recall = |retrieved ∩ relevant| / |relevant|."""
    if not relevant_doc_ids:
        return 1.0  # Nothing relevant expected → perfect recall
    retrieved_set = set(retrieved_doc_ids)
    relevant_set = set(relevant_doc_ids)
    intersection = retrieved_set & relevant_set
    return len(intersection) / len(relevant_set)


def compute_citation_accuracy(
    citations: list[str],
    expected_sources: list[str],
) -> float:
    """Compute citation accuracy = correct_citations / total_citations."""
    if not citations:
        return 0.0
    cited_set = set(citations)
    expected_set = set(expected_sources)
    correct = len(cited_set & expected_set)
    return correct / len(cited_set)


def evaluate_single_query(
    test_case: QualityTestCase,
    retrieve_fn: Callable[[str], dict[str, Any]],
) -> QualityMetricRecord:
    """Evaluate a single benchmark query.

    Args:
        test_case: The benchmark test case to evaluate.
        retrieve_fn: A callable that takes a question string and returns
            a dict with keys answer, citations, latency_ms, refused.

    Returns:
        :class:`QualityMetricRecord` with computed metrics.
    """
    start = time.perf_counter()
    result = retrieve_fn(test_case.question)
    elapsed_ms = (time.perf_counter() - start) * 1000

    answer: str | None = result.get("answer")
    citations: list[str] = result.get("citations", [])
    refused: bool = result.get("refused", False)
    retrieved_docs: list[str] = result.get("retrieved_docs", [])

    recall = compute_recall(retrieved_docs, test_case.expected_relevant)
    cit_acc = compute_citation_accuracy(citations, test_case.expected_relevant)
    ref_rate = 1.0 if bool(refused) == test_case.should_refuse else 0.0

    failed = 0
    if test_case.expected_answer and (answer is None or not answer):
        failed = 1

    return QualityMetricRecord(
        test_case_id=test_case.test_case_id,
        category=test_case.category,
        question=test_case.question,
        expected_answer=test_case.expected_answer,
        actual_answer=answer,
        recall_count=len([d for d in retrieved_docs if d in test_case.expected_relevant]),
        total_relevant=len(test_case.expected_relevant),
        recall_rate=recall,
        citation_correct=len([c for c in citations if c in test_case.expected_relevant]),
        citation_accuracy=cit_acc,
        refused=int(refused),
        should_refuse=int(test_case.should_refuse),
        refusal_rate=ref_rate,
        latency_ms=elapsed_ms,
        total_queries=1,
        failed_count=failed,
        failure_rate=float(failed),
        run_at=datetime.now().isoformat(timespec="seconds"),
    )


def evaluate_benchmark(
    cases: list[QualityTestCase],
    retrieve_fn: Callable[[str], dict[str, Any]],
    benchmark_name: str = "default",
    embed_model: str = "",
) -> QualityBenchmarkResult:
    """Run a full benchmark evaluation and return aggregated metrics.

    Args:
        cases: Test cases to evaluate.
        retrieve_fn: Retrieval callable (see :func:`evaluate_single_query`).
        benchmark_name: Label for this benchmark run.
        embed_model: Name of the embedding model used (for record).

    Returns:
        :class:`QualityBenchmarkResult` with per-category breakdowns.
    """
    records: list[QualityMetricRecord] = []
    for tc in cases:
        rec = evaluate_single_query(tc, retrieve_fn)
        rec.benchmark_name = benchmark_name
        rec.embed_model = embed_model
        records.append(rec)

    # Aggregate
    total = len(records)
    passed = sum(1 for r in records if r.failure_rate == 0.0 and r.recall_rate >= 0.5)
    failed = total - passed
    avg_recall = sum(r.recall_rate for r in records) / total if total else 0.0
    avg_cit_acc = sum(r.citation_accuracy for r in records) / total if total else 0.0
    avg_ref = sum(r.refusal_rate for r in records) / total if total else 0.0
    avg_lat = sum(r.latency_ms for r in records) / total if total else 0.0
    fail_ratio = sum(r.failure_rate for r in records) / total if total else 0.0

    # Per-category
    by_cat: dict[str, list[QualityMetricRecord]] = {}
    for r in records:
        by_cat.setdefault(r.category, []).append(r)

    per_category: dict[str, dict[str, float]] = {}
    for cat, cat_recs in by_cat.items():
        n = len(cat_recs)
        per_category[cat] = {
            "count": float(n),
            "avg_recall": sum(r.recall_rate for r in cat_recs) / n,
            "avg_citation_accuracy": sum(r.citation_accuracy for r in cat_recs) / n,
            "avg_refusal_rate": sum(r.refusal_rate for r in cat_recs) / n,
            "avg_latency_ms": sum(r.latency_ms for r in cat_recs) / n,
        }

    return QualityBenchmarkResult(
        benchmark_name=benchmark_name,
        total_cases=total,
        passed=passed,
        failed=failed,
        avg_recall=avg_recall,
        avg_citation_accuracy=avg_cit_acc,
        avg_refusal_rate=avg_ref,
        avg_latency_ms=avg_lat,
        total_failure_rate=fail_ratio,
        run_at=datetime.now().isoformat(timespec="seconds"),
        per_category=per_category,
    )


def persist_metrics(
    conn: sqlite3.Connection,
    records: list[QualityMetricRecord],
) -> None:
    """Persist benchmark metric records to the quality_metric table."""
    for r in records:
        conn.execute(
            """INSERT INTO quality_metric
               (benchmark_name, test_case_id, category, question,
                expected_answer, actual_answer, recall_count, total_relevant,
                recall_rate, citation_correct, citation_accuracy,
                refused, should_refuse, refusal_rate,
                latency_ms, total_queries, failed_count, failure_rate,
                run_at, embed_model)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r.benchmark_name, r.test_case_id, r.category, r.question,
                r.expected_answer, r.actual_answer, r.recall_count, r.total_relevant,
                r.recall_rate, r.citation_correct, r.citation_accuracy,
                r.refused, r.should_refuse, r.refusal_rate,
                r.latency_ms, r.total_queries, r.failed_count, r.failure_rate,
                r.run_at, r.embed_model,
            ),
        )
    conn.commit()
