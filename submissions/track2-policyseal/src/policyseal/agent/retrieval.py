from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from policyseal.agent.embeddings import TextEncoder, cosine_similarity
from policyseal.policy.schema import EvidenceRecord, PolicyPack

_EVIDENCE_MARKER = re.compile(r"<!--\s*evidence-id:\s*(EV-[A-Z0-9-]+)\s*-->")
_TOKEN = re.compile(r"[A-Za-z0-9]+")
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "can",
    "does",
    "for",
    "from",
    "how",
    "if",
    "in",
    "into",
    "is",
    "it",
    "of",
    "or",
    "should",
    "the",
    "this",
    "to",
    "what",
    "when",
    "which",
    "why",
}


@dataclass(frozen=True, slots=True)
class EvidenceDocument:
    id: str
    path: str
    title: str
    tags: tuple[str, ...]
    text: str


@dataclass(frozen=True, slots=True)
class EvidenceHit:
    evidence_id: str
    title: str
    path: str
    excerpt: str
    score: float


def _sections(path: Path) -> dict[str, str]:
    content = path.read_text(encoding="utf-8")
    matches = tuple(_EVIDENCE_MARKER.finditer(content))
    return {
        match.group(1): content[
            match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(content)
        ].strip()
        for index, match in enumerate(matches)
    }


def load_evidence_documents(pack: PolicyPack) -> tuple[EvidenceDocument, ...]:
    sections_by_path: dict[str, dict[str, str]] = {}
    documents: list[EvidenceDocument] = []
    for record in pack.evidence:
        sections = sections_by_path.setdefault(record.path, _sections(pack.root / record.path))
        try:
            text = sections[record.id]
        except KeyError as error:
            raise ValueError(
                f"evidence section {record.id} is missing from {record.path}"
            ) from error
        documents.append(_document(record, text))
    return tuple(documents)


def _document(record: EvidenceRecord, text: str) -> EvidenceDocument:
    return EvidenceDocument(record.id, record.path, record.title, record.tags, text)


class HybridEvidenceRetriever:
    def __init__(
        self,
        documents: tuple[EvidenceDocument, ...],
        *,
        encoder: TextEncoder | None = None,
    ) -> None:
        if not documents:
            raise ValueError("evidence retrieval requires at least one document")
        self.documents = documents
        self.encoder = encoder
        self._by_id = {document.id: document for document in documents}
        if len(self._by_id) != len(documents):
            raise ValueError("evidence IDs must be unique")
        self._connection = sqlite3.connect(":memory:")
        self._connection.execute(
            "CREATE VIRTUAL TABLE evidence_fts USING fts5(id UNINDEXED, title, tags, body)"
        )
        self._connection.executemany(
            "INSERT INTO evidence_fts(id, title, tags, body) VALUES (?, ?, ?, ?)",
            (
                (document.id, document.title, " ".join(document.tags), document.text)
                for document in documents
            ),
        )
        self._passage_vectors: tuple[tuple[float, ...], ...] | None = None

    @classmethod
    def from_policy_pack(
        cls,
        pack: PolicyPack,
        *,
        encoder: TextEncoder | None = None,
    ) -> HybridEvidenceRetriever:
        return cls(load_evidence_documents(pack), encoder=encoder)

    def search(
        self,
        query: str,
        *,
        tags: tuple[str, ...] = (),
        top_k: int = 3,
    ) -> tuple[EvidenceHit, ...]:
        if not query.strip() or top_k < 1:
            return ()
        candidate_ids = self._metadata_candidates(tags)
        lexical_ids = self._lexical_ranking(query, tags, candidate_ids)
        dense_ids = self._dense_ranking(query, candidate_ids)
        scores = {evidence_id: 0.0 for evidence_id in candidate_ids}
        for rank, evidence_id in enumerate(lexical_ids, start=1):
            scores[evidence_id] += 1 / (30 + rank)
        for rank, evidence_id in enumerate(dense_ids, start=1):
            scores[evidence_id] += 1 / (30 + rank)
        requested_tags = {tag.casefold() for tag in tags}
        for evidence_id in candidate_ids:
            document_tags = {tag.casefold() for tag in self._by_id[evidence_id].tags}
            scores[evidence_id] += 0.02 * len(requested_tags & document_tags)
        ranked = sorted(scores, key=lambda item: (-scores[item], item))[:top_k]
        return tuple(
            EvidenceHit(
                evidence_id=evidence_id,
                title=self._by_id[evidence_id].title,
                path=self._by_id[evidence_id].path,
                excerpt=self._excerpt(self._by_id[evidence_id].text),
                score=scores[evidence_id],
            )
            for evidence_id in ranked
        )

    def get(self, evidence_id: str) -> EvidenceDocument:
        try:
            return self._by_id[evidence_id]
        except KeyError as error:
            raise KeyError("policy evidence does not exist") from error

    def _metadata_candidates(self, tags: tuple[str, ...]) -> tuple[str, ...]:
        format_tags = {tag.casefold() for tag in tags} & {"xlsx", "docx", "pdf"}
        if not format_tags:
            return tuple(self._by_id)
        return tuple(
            document.id
            for document in self.documents
            if format_tags & {tag.casefold() for tag in document.tags}
        )

    def _lexical_ranking(
        self,
        query: str,
        tags: tuple[str, ...],
        candidate_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        terms = [
            token.casefold()
            for token in _TOKEN.findall(f"{query} {' '.join(tags)}")
            if token.casefold() not in _STOP_WORDS and len(token) > 1
        ]
        if not terms:
            return candidate_ids
        match_query = " OR ".join(f'"{term}"' for term in dict.fromkeys(terms))
        rows = self._connection.execute(
            "SELECT id FROM evidence_fts WHERE evidence_fts MATCH ? ORDER BY bm25(evidence_fts)",
            (match_query,),
        ).fetchall()
        return tuple(str(row[0]) for row in rows if str(row[0]) in candidate_ids)

    def _dense_ranking(
        self,
        query: str,
        candidate_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        if self.encoder is None:
            return ()
        try:
            if self._passage_vectors is None:
                self._passage_vectors = self.encoder.encode_passages(
                    [f"{document.title}\n{document.text}" for document in self.documents]
                )
            query_vector = self.encoder.encode_query(query)
        except Exception:
            return ()
        similarities = {
            document.id: cosine_similarity(query_vector, self._passage_vectors[index])
            for index, document in enumerate(self.documents)
            if document.id in candidate_ids
        }
        return tuple(sorted(similarities, key=lambda item: (-similarities[item], item)))

    @staticmethod
    def _excerpt(text: str, limit: int = 360) -> str:
        compact = " ".join(line.strip() for line in text.splitlines() if line.strip())
        return compact if len(compact) <= limit else f"{compact[: limit - 3]}..."


__all__ = [
    "EvidenceDocument",
    "EvidenceHit",
    "HybridEvidenceRetriever",
    "load_evidence_documents",
]
