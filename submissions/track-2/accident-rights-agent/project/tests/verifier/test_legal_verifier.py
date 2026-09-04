from __future__ import annotations

from datetime import date

from app.rules.repository import RuleRepository
from app.schemas.legal import LegalCitation
from app.verifier.legal import LegalCitationVerifier


def test_unknown_law_id_and_citation_are_blocked(legal_retriever):
    chunk = legal_retriever.corpus.list_chunks()[0]
    good = LegalCitation.from_chunk(chunk, 1.0).model_dump(mode="json")
    bad = {**good, "source_id": "LAW-NOT-FOUND"}
    result = LegalCitationVerifier(
        legal_retriever.corpus, RuleRepository()
    ).verify(
        state={
            "legal_citations": [bad],
            "rights_tasks": [{"related_law_ids": ["CN-LAW-NOT-FOUND"]}],
        },
        as_of_date=date(2026, 7, 20),
    )
    assert result.passed is False
    assert {item.code for item in result.issues} >= {
        "LEGAL-CITATION-INVALID",
        "LEGAL-LAW-ID-NOT-FOUND",
    }


def test_effective_indexed_citation_passes(legal_retriever):
    chunk = next(
        item
        for item in legal_retriever.corpus.list_chunks()
        if item.document_id == "CN-LAW-RTSA-2021"
    )
    result = LegalCitationVerifier(
        legal_retriever.corpus, RuleRepository()
    ).verify(
        state={
            "legal_citations": [
                LegalCitation.from_chunk(chunk, 1.0).model_dump(mode="json")
            ]
        },
        as_of_date=date(2026, 7, 20),
    )
    assert result.passed is True


def test_expired_legal_version_is_blocked(legal_retriever):
    chunk = next(
        item
        for item in legal_retriever.corpus.list_chunks()
        if item.document_id == "CN-LAW-RTSA-2021"
    )
    payload = LegalCitation.from_chunk(chunk, 1.0).model_dump(mode="json")
    payload["status"] = "expired"
    result = LegalCitationVerifier(
        legal_retriever.corpus, RuleRepository()
    ).verify(
        state={"legal_citations": [payload]},
        as_of_date=date(2026, 7, 20),
    )
    assert result.passed is False
    assert "LEGAL-CITATION-INVALID" in {item.code for item in result.issues}
