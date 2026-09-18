from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from buildguard.api.app import create_app
from buildguard.config import AdvancedRagConfig, RagConfig, load_settings
from buildguard.llm.mock_backend import MockLLMBackend
from buildguard.rag.advanced.answer_grounding import AnswerGrounder
from buildguard.rag.advanced.corrective_retriever import AdvancedRagPipeline
from buildguard.rag.advanced.evaluation import (
    AdvancedEvaluationExample,
    AdvancedRagEvaluator,
)
from buildguard.rag.advanced.quality_evaluator import (
    RetrievalQuality,
    RetrievalQualityEvaluator,
)
from buildguard.rag.advanced.query_rewriter import QueryRewriter
from buildguard.rag.advanced.retrieval_gate import (
    RetrievalGate,
    RetrievalGateDecision,
)
from buildguard.rag.embedding_backend import MockEmbeddingBackend
from buildguard.rag.reranker import MockReranker
from buildguard.rag.schemas import DocumentChunk, RagSearchInput
from buildguard.rag.service import RagService


def advanced_config(**updates: Any) -> AdvancedRagConfig:
    values: dict[str, Any] = {
        "use_llm_gate": False,
        "use_llm_rewriter": False,
        "quality_generate_threshold": 0.75,
        "quality_correct_threshold": 0.45,
        "initial_top_k": 5,
        "corrective_top_k": 15,
        "max_corrections": 1,
    }
    values.update(updates)
    return AdvancedRagConfig.model_validate(values)


def chunk(tmp_path: Path, *, content: str = "第一条 临边作业应设置可靠防护栏杆。") -> DocumentChunk:
    return DocumentChunk(
        chunk_id="a" * 64,
        document_name="GB 50000-2020 施工安全规范",
        source_path=tmp_path / "standard.pdf",
        document_checksum="b" * 64,
        page=3,
        article="第一条",
        title="临边防护",
        content=content,
    )


def rag_service(tmp_path: Path, config: AdvancedRagConfig | None = None) -> RagService:
    rag = RagConfig(
        index_dir=tmp_path / "indexes",
        allowed_source_roots=[tmp_path / "knowledge"],
        chunk_min_chars=50,
        chunk_max_chars=200,
        chunk_overlap_chars=10,
        embedding_dimension=64,
        bm25_top_k=20,
        dense_top_k=20,
        fusion_top_k=15,
        final_top_k=5,
        min_top_score=0,
        min_keyword_coverage=0,
        advanced=config or advanced_config(),
    )
    return RagService(
        rag,
        MockEmbeddingBackend(64, seed=42),
        MockReranker(),
    )


def test_retrieval_gate_mandatory_rules_and_local_llm() -> None:
    gate = RetrievalGate(advanced_config())
    standard = gate.decide("请给出临边防护的规范条款依据")
    assert standard.need_retrieval
    assert standard.query_type == "standard"
    assert standard.requested_sources == ["construction_standards"]
    history = gate.decide("查询上一任务历史")
    assert history.need_retrieval
    assert history.query_type == "history"
    assert history.requested_sources == ["task_history"]
    risk = gate.decide("这个事件的风险等级是什么")
    assert risk.need_retrieval
    assert risk.query_type == "risk"
    assert "risk_events" in risk.requested_sources
    domain = gate.decide("临边应该怎么防护")
    assert domain.need_retrieval
    assert domain.query_type == "standard"

    backend = Mock()
    backend.structured_chat.return_value = RetrievalGateDecision(
        need_retrieval=True,
        query_type="standard",
        reason="Local structured judgement",
        requested_sources=["construction_standards"],
    )
    llm_gate = RetrievalGate(
        advanced_config(use_llm_gate=True),
        backend,
    )
    decision = llm_gate.decide("现场如何处理")
    assert decision.need_retrieval
    backend.structured_chat.assert_called_once()


def test_query_rewriter_has_at_most_three_meaning_preserving_queries() -> None:
    result = QueryRewriter(advanced_config()).rewrite(
        "GB 50000-2020 第一条安全帽如何检查"
    )
    assert 1 <= len(result.queries) <= 3
    assert result.queries[0] == result.original_query
    assert len(result.queries) == len(set(result.queries))
    assert all("GB 50000-2020" in query for query in result.queries)
    assert any("个体防护装备" in query for query in result.queries)
    assert any("规范 条款" in query for query in result.queries)


def test_query_rewriter_rejects_llm_standard_number_change() -> None:
    backend = Mock()
    proposal = Mock()
    proposal.queries = [
        "GB 99999-2099 第九条量子护栏",
        "GB 50000-2020 第一条安全帽 个体防护装备",
    ]
    backend.structured_chat.return_value = proposal
    result = QueryRewriter(
        advanced_config(use_llm_rewriter=True),
        backend,
    ).rewrite("GB 50000-2020 第一条安全帽")
    assert all("GB 99999-2099" not in query for query in result.queries)
    assert all("GB 50000-2020" in query for query in result.queries)


def test_quality_formula_and_boundaries(tmp_path: Path) -> None:
    evaluator = RetrievalQualityEvaluator(advanced_config())
    matching = chunk(tmp_path, content="custom")
    generate = evaluator.evaluate("custom", [matching], [0.5])
    assert generate.reranker_score == pytest.approx(0.5)
    assert generate.keyword_coverage == 1
    assert generate.entity_coverage == 1
    assert generate.score == pytest.approx(0.75)
    assert generate.action == "generate"

    unrelated = chunk(tmp_path, content="irrelevant")
    correct = evaluator.evaluate("custom", [unrelated], [0.5])
    assert correct.score == pytest.approx(0.45)
    assert correct.action == "correct"

    refuse = evaluator.evaluate("custom", [unrelated], [0.49])
    assert refuse.score == pytest.approx(0.445)
    assert refuse.action == "refuse"


class SequenceQuality:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate(
        self,
        query: str,
        chunks: list[DocumentChunk],
        scores: list[float],
    ) -> RetrievalQuality:
        self.calls += 1
        action = "correct" if self.calls == 1 else "generate"
        return RetrievalQuality(
            reranker_score=0.6 if action == "correct" else 0.9,
            keyword_coverage=0.6 if action == "correct" else 1,
            entity_coverage=0.6 if action == "correct" else 1,
            score=0.6 if action == "correct" else 0.95,
            action=action,
        )


def test_corrective_retrieval_runs_at_most_once(tmp_path: Path) -> None:
    config = advanced_config()
    service = rag_service(tmp_path, config)
    corpus = [chunk(tmp_path)]
    service.bm25.build(corpus)
    service.dense.build(corpus)
    quality = SequenceQuality()
    pipeline = AdvancedRagPipeline(
        service,
        RetrievalGate(config),
        QueryRewriter(config),
        quality,  # type: ignore[arg-type]
        config,
    )
    result = pipeline.retrieve(
        RagSearchInput(query="临边防护规范依据", top_k=5)
    )
    assert result.retrieval_attempts == 2
    assert result.correction_count == 1
    assert quality.calls == 2
    assert 1 <= len(result.rewritten_queries) <= 3
    assert not result.internet_search_used


def test_no_evidence_refuses_without_correction(tmp_path: Path) -> None:
    config = advanced_config()
    service = rag_service(tmp_path, config)
    pipeline = AdvancedRagPipeline(
        service,
        RetrievalGate(config),
        QueryRewriter(config),
        RetrievalQualityEvaluator(config),
        config,
    )
    result = pipeline.retrieve(
        RagSearchInput(query="GB 99999-2099 量子护栏规范依据")
    )
    assert result.evidence_status == "insufficient_evidence"
    assert result.retrieval_attempts == 1
    assert result.correction_count == 0
    assert result.chunks == []


def test_history_gate_routes_to_local_history_source(tmp_path: Path) -> None:
    config = advanced_config()
    service = rag_service(tmp_path, config)
    pipeline = AdvancedRagPipeline(
        service,
        RetrievalGate(config),
        QueryRewriter(config),
        RetrievalQualityEvaluator(config),
        config,
    )
    result = pipeline.retrieve(RagSearchInput(query="查询任务历史"))
    assert result.gate.need_retrieval
    assert result.evidence_status == "local_source_required"
    assert result.retrieval_attempts == 0
    assert result.gate.requested_sources == ["task_history"]


def test_grounding_removes_fabricated_standard_article_page_and_mandate(
    tmp_path: Path,
) -> None:
    evidence = [chunk(tmp_path)]
    answer = (
        "GB 50000-2020第一条规定临边作业应设置可靠防护栏杆，见第3页。"
        "GB 99999-2099第九条规定必须使用量子护栏，见第99页。"
        "建议必须每天使用无人机强制检查。"
    )
    result = AnswerGrounder(advanced_config()).validate(answer, evidence)
    assert len(result.supported_claims) == 1
    assert len(result.unsupported_claims) == 2
    assert "GB 50000-2020" in result.final_safe_answer
    assert "GB 99999-2099" not in result.final_safe_answer
    assert "量子护栏" not in result.final_safe_answer
    issues = {
        issue
        for reasons in result.issues.values()
        for issue in reasons
    }
    assert any(item.startswith("unretrieved_standard") for item in issues)
    assert any(item.startswith("nonexistent_article") for item in issues)
    assert any(item.startswith("incorrect_page") for item in issues)
    assert "suggestion_presented_as_mandatory" in issues


def test_all_unsupported_claims_return_configured_refusal(tmp_path: Path) -> None:
    config = advanced_config(refusal_message="LOCAL_EVIDENCE_INSUFFICIENT")
    result = AnswerGrounder(config).validate(
        "GB 99999-2099第九条要求使用量子护栏。",
        [chunk(tmp_path)],
    )
    assert result.supported_claims == []
    assert result.unsupported_claims
    assert result.final_safe_answer == "LOCAL_EVIDENCE_INSUFFICIENT"


def test_advanced_evaluation_compares_five_strategies(tmp_path: Path) -> None:
    config = advanced_config(
        quality_generate_threshold=0.5,
        quality_correct_threshold=0.2,
    )
    service = rag_service(tmp_path, config)
    corpus = [chunk(tmp_path)]
    service.bm25.build(corpus)
    service.dense.build(corpus)
    pipeline = AdvancedRagPipeline(
        service,
        RetrievalGate(config),
        QueryRewriter(config),
        RetrievalQualityEvaluator(config),
        config,
    )
    results = AdvancedRagEvaluator(
        service,
        pipeline,
        AnswerGrounder(config),
    ).evaluate(
        [
            AdvancedEvaluationExample(
                question="临边防护规范依据",
                relevant_chunk_ids=[corpus[0].chunk_id],
                candidate_answer="第一条规定临边作业应设置可靠防护栏杆。",
            )
        ]
    )
    assert set(results) == {
        "BM25",
        "Dense",
        "Hybrid",
        "Hybrid+Reranker",
        "Advanced Corrective RAG",
    }
    for metrics in results.values():
        assert metrics.evaluated_questions == 1
        assert 0 <= metrics.recall_at_5 <= 1
        assert 0 <= metrics.recall_at_10 <= 1
        assert 0 <= metrics.mrr <= 1
        assert 0 <= metrics.ndcg <= 1
        assert 0 <= metrics.citation_accuracy <= 1
        assert 0 <= metrics.unsupported_claim_rate <= 1
        assert 0 <= metrics.refusal_accuracy <= 1


def test_advanced_rag_api_and_grounding(
    config_tree: Path,
    tmp_path: Path,
) -> None:
    settings = load_settings(config_tree)
    workspace = tmp_path / "workspace"
    knowledge = workspace / "knowledge"
    knowledge.mkdir(parents=True)
    settings.app.workspace_dir = workspace
    settings.app.database_path = workspace / "database" / "test.db"
    settings.rag = RagConfig(
        index_dir=workspace / "indexes" / "rag",
        allowed_source_roots=[knowledge],
        chunk_min_chars=50,
        chunk_max_chars=200,
        chunk_overlap_chars=10,
        embedding_dimension=64,
        min_top_score=0,
        min_keyword_coverage=0,
        advanced=advanced_config(
            quality_generate_threshold=0.5,
            quality_correct_threshold=0.2,
        ),
    )
    application = create_app(settings, MockLLMBackend())
    rag = application.state.rag
    evidence = chunk(tmp_path)
    rag.bm25.build([evidence])
    rag.dense.build([evidence])
    client = TestClient(application)
    search = client.post(
        "/rag/advanced-search",
        json={"query": "临边防护规范依据", "top_k": 5},
    )
    assert search.status_code == 200
    assert search.json()["internet_search_used"] is False
    assert search.json()["chunks"]
    grounded = client.post(
        "/rag/ground-answer",
        json={
            "answer": "第一条规定临边作业应设置可靠防护栏杆。",
            "chunk_ids": [evidence.chunk_id],
        },
    )
    assert grounded.status_code == 200
    assert grounded.json()["unsupported_claims"] == []
    unknown = client.post(
        "/rag/ground-answer",
        json={
            "answer": "测试",
            "chunk_ids": ["f" * 64],
        },
    )
    assert unknown.status_code == 422


def test_advanced_config_quality_threshold_validation() -> None:
    with pytest.raises(ValidationError, match="must be below"):
        AdvancedRagConfig(
            quality_correct_threshold=0.75,
            quality_generate_threshold=0.75,
        )
    with pytest.raises(ValidationError, match="corrective_top_k"):
        AdvancedRagConfig(initial_top_k=20, corrective_top_k=10)
