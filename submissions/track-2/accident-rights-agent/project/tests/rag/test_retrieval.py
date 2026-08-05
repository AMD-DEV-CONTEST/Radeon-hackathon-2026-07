from __future__ import annotations

import json
from pathlib import Path

from app.rag.reranker import HeuristicReranker


def test_fifteen_regression_questions_recall_and_citation_completeness(
    legal_retriever,
):
    questions = json.loads(
        Path("data/laws/regression_questions.json").read_text(encoding="utf-8")
    )
    reciprocal_ranks = []
    complete = 0
    for question in questions:
        citations = legal_retriever.citations(
            question["question"], top_k=4, candidate_k=10
        )
        expected = {
            (item["document_id"], item["article_no"]) for item in question["expected"]
        }
        ranks = [
            index
            for index, citation in enumerate(citations, start=1)
            if (citation.document_id, citation.article_no) in expected
        ]
        assert ranks, question["id"]
        reciprocal_ranks.append(1 / ranks[0])
        complete += all(
            (
                citation.title,
                citation.version,
                citation.effective_date,
                citation.source_id,
                citation.text_source_url,
                citation.quote_type,
                citation.quote,
            )
            for citation in citations
        )
    assert len(questions) == 15
    assert len(reciprocal_ranks) / len(questions) == 1.0
    assert sum(reciprocal_ranks) / len(questions) >= 0.75
    assert complete / len(questions) == 1.0


def test_heuristic_reranker_rewards_title_and_standard_identifier(legal_retriever):
    chunks = legal_retriever.corpus.list_chunks()
    standard = next(
        item for item in chunks if item.document_id == "CN-GB-17761-2024"
    )
    unrelated = next(
        item for item in chunks if item.document_id == "CN-LAW-INSURANCE-2015"
    )
    scores = HeuristicReranker().score(
        "GB 17761 电动自行车安全技术规范最高设计车速",
        [standard, unrelated],
    )
    assert scores[0] > scores[1]
