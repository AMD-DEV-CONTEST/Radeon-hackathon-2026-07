from __future__ import annotations

from pathlib import Path

from policyseal.agent.retrieval import HybridEvidenceRetriever
from policyseal.evals.assets import load_eval_assets
from policyseal.policy.loader import load_policy_pack


class KeywordEncoder:
    def encode_passages(self, texts: list[str]) -> tuple[tuple[float, ...], ...]:
        return tuple(self._vector(text) for text in texts)

    def encode_query(self, text: str) -> tuple[float, ...]:
        return self._vector(text)

    @staticmethod
    def _vector(text: str) -> tuple[float, ...]:
        lowered = text.casefold()
        return (
            float("credential" in lowered or "password" in lowered),
            float("contract" in lowered or "sla" in lowered),
            float("supplier" in lowered or "bidder" in lowered),
        )


def test_frozen_retrieval_questions_reach_recall_at_three_target() -> None:
    assets = load_eval_assets()
    retriever = HybridEvidenceRetriever.from_policy_pack(load_policy_pack(Path("policies/v1")))
    hits = 0
    for question in assets.retrieval_questions:
        returned = {
            hit.evidence_id
            for hit in retriever.search(question.question, tags=question.tags, top_k=3)
        }
        hits += bool(returned & set(question.expected_evidence_ids))

    recall_at_three = hits / len(assets.retrieval_questions)
    assert recall_at_three >= 0.9
    assert hits == 20


def test_hybrid_retrieval_uses_dense_rank_without_replacing_policy_evidence() -> None:
    pack = load_policy_pack(Path("policies/v1"))
    retriever = HybridEvidenceRetriever.from_policy_pack(
        pack,
        encoder=KeywordEncoder(),
    )

    hits = retriever.search("Why can a password never be included?", top_k=3)

    assert hits[0].evidence_id == "EV-DOCX-003"
    assert all(hit.evidence_id.startswith("EV-") for hit in hits)
    assert "Crimson-Falcon-47!" not in repr(hits)


def test_metadata_filter_keeps_document_family_local() -> None:
    retriever = HybridEvidenceRetriever.from_policy_pack(load_policy_pack(Path("policies/v1")))

    hits = retriever.search("approval and source metadata", tags=("pdf",), top_k=3)

    assert hits
    assert all(hit.evidence_id.startswith("EV-PDF-") for hit in hits)
