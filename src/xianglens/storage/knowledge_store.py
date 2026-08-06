"""Milvus Lite knowledge-card ingestion and retrieval."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from xianglens.schemas import LENS_PACKS, EvidenceCard

TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)?")
LEXICAL_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """Small offline baseline for scaffolding and deterministic tests.

    The submission configuration should use FastEmbed for semantic retrieval. This
    baseline still produces normalized dense vectors and keeps the app functional
    before the embedding model has been downloaded.
    """

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        tokens = TOKEN_PATTERN.findall(text.lower())
        features = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False)]
        vector = [0.0] * self.dimension
        for feature in features:
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class FastEmbedder:
    """CPU semantic embeddings loaded only when explicitly configured."""

    def __init__(self, model_name: str) -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("FastEmbed is not installed. Run: uv sync --extra semantic") from exc
        self._model = TextEmbedding(model_name=model_name)
        probe = list(self._model.embed(["dimension probe"]))[0]
        self.dimension = len(probe)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(texts)]


def create_embedder(provider: str, model: str, dimension: int) -> Embedder:
    if provider == "fastembed":
        return FastEmbedder(model)
    return HashingEmbedder(dimension)


def rerank_cards(query: str, cards: list[EvidenceCard], limit: int) -> list[EvidenceCard]:
    """Add a small IDF-weighted lexical signal to the dense score.

    The compact corpus contains exact platform and risk terms such as ``badge``
    and ``circle crop``. This deterministic tie-breaker makes those terms stable
    without introducing a separate search service or reranker model.
    """

    if not cards:
        return []
    query_tokens = set(LEXICAL_TOKEN_PATTERN.findall(query.lower()))
    documents = [
        set(LEXICAL_TOKEN_PATTERN.findall(f"{card.text} {' '.join(card.tags)}".lower()))
        for card in cards
    ]
    document_frequency = Counter(token for document in documents for token in document)
    count = len(documents)
    rescored: list[EvidenceCard] = []
    for card, document in zip(cards, documents, strict=True):
        lexical = sum(
            math.log((count + 1) / (document_frequency[token] + 1)) + 1
            for token in query_tokens.intersection(document)
        ) / max(1, len(query_tokens))
        rescored.append(card.model_copy(update={"score": card.score + 0.7 * lexical}))
    return sorted(rescored, key=lambda card: card.score, reverse=True)[:limit]


@dataclass(slots=True)
class KnowledgeRecord:
    card_id: str
    text: str
    pack: str
    source_title: str
    source_url: str
    license: str
    tags: list[str]

    @property
    def embedding_text(self) -> str:
        return f"{self.text} Tags: {' '.join(self.tags)} Pack: {self.pack}"


def load_knowledge_records(cards_path: Path, sources_path: Path) -> list[KnowledgeRecord]:
    cards = yaml.safe_load(cards_path.read_text(encoding="utf-8"))
    sources = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
    if not isinstance(cards, list) or not isinstance(sources, dict):
        raise ValueError("Knowledge YAML files have an invalid top-level structure")
    records: list[KnowledgeRecord] = []
    for card in cards:
        if set(card) != {"text", "pack", "source", "tags"}:
            raise ValueError("Every card must contain exactly text, pack, source, and tags")
        if card["pack"] not in LENS_PACKS:
            raise ValueError(f"Unknown Lens Pack: {card['pack']}")
        source = sources.get(card["source"])
        if source is None:
            raise ValueError(f"Unknown source key: {card['source']}")
        stable = "\n".join((card["pack"], card["source"], card["text"]))
        card_id = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]
        records.append(
            KnowledgeRecord(
                card_id=card_id,
                text=card["text"],
                pack=card["pack"],
                source_title=source["title"],
                source_url=source["url"],
                license=source["license"],
                tags=list(card["tags"]),
            )
        )
    return records


class KnowledgeStore(Protocol):
    def is_ready(self) -> bool: ...

    def search(self, query: str, enabled_packs: list[str], limit: int) -> list[EvidenceCard]: ...


class MilvusKnowledgeStore:
    collection_name = "knowledge_cards_v1"

    def __init__(self, uri: Path, embedder: Embedder) -> None:
        self.uri = uri
        self.embedder = embedder
        self._milvus_client: Any | None = None

    def _client(self):
        if self._milvus_client is not None:
            return self._milvus_client
        try:
            from pymilvus import MilvusClient
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("pymilvus is not installed") from exc
        self.uri.parent.mkdir(parents=True, exist_ok=True)
        self._milvus_client = MilvusClient(str(self.uri))
        return self._milvus_client

    def is_ready(self) -> bool:
        if not self.uri.exists():
            return False
        try:
            return self._client().has_collection(self.collection_name)
        except Exception:
            return False

    def rebuild(self, records: list[KnowledgeRecord]) -> int:
        client = self._client()
        if client.has_collection(self.collection_name):
            client.drop_collection(self.collection_name)
        client.create_collection(
            collection_name=self.collection_name,
            dimension=self.embedder.dimension,
            metric_type="COSINE",
            consistency_level="Strong",
        )
        vectors = self.embedder.embed([record.embedding_text for record in records])
        rows: list[dict[str, Any]] = []
        for index, (record, vector) in enumerate(zip(records, vectors, strict=True), start=1):
            rows.append(
                {
                    "id": index,
                    "vector": vector,
                    "card_id": record.card_id,
                    "text": record.text,
                    "pack": record.pack,
                    "source_title": record.source_title,
                    "source_url": record.source_url,
                    "license": record.license,
                    "tags": record.tags,
                }
            )
        client.insert(collection_name=self.collection_name, data=rows)
        client.load_collection(self.collection_name)
        return len(rows)

    def search(self, query: str, enabled_packs: list[str], limit: int) -> list[EvidenceCard]:
        if not self.is_ready():
            return []
        allowed = [pack for pack in enabled_packs if pack in LENS_PACKS]
        if not allowed:
            return []
        escaped = ", ".join(f'"{pack}"' for pack in allowed)
        candidate_limit = max(limit * 4, 16)
        client = self._client()
        client.load_collection(self.collection_name)
        results = client.search(
            collection_name=self.collection_name,
            data=self.embedder.embed([query]),
            filter=f"pack in [{escaped}]",
            limit=candidate_limit,
            output_fields=[
                "card_id",
                "text",
                "pack",
                "source_title",
                "source_url",
                "license",
                "tags",
            ],
            search_params={"metric_type": "COSINE"},
        )
        cards: list[EvidenceCard] = []
        for hit in results[0]:
            entity = hit.get("entity", hit)
            cards.append(
                EvidenceCard(
                    card_id=entity["card_id"],
                    text=entity["text"],
                    pack=entity["pack"],
                    source_title=entity["source_title"],
                    source_url=entity["source_url"],
                    license=entity["license"],
                    tags=list(entity["tags"]),
                    score=float(hit.get("distance", 0.0)),
                )
            )
        return rerank_cards(query, cards, limit)


class InMemoryKnowledgeStore:
    """Test adapter with the same retrieval contract as Milvus."""

    def __init__(self, records: list[KnowledgeRecord], embedder: Embedder) -> None:
        self.records = records
        self.embedder = embedder
        self.vectors = embedder.embed([record.embedding_text for record in records])

    def is_ready(self) -> bool:
        return bool(self.records)

    def search(self, query: str, enabled_packs: list[str], limit: int) -> list[EvidenceCard]:
        query_vector = self.embedder.embed([query])[0]
        scored: list[tuple[float, KnowledgeRecord]] = []
        for record, vector in zip(self.records, self.vectors, strict=True):
            if record.pack not in enabled_packs:
                continue
            score = sum(left * right for left, right in zip(query_vector, vector, strict=True))
            scored.append((score, record))
        scored.sort(key=lambda item: item[0], reverse=True)
        cards = [
            EvidenceCard(
                card_id=record.card_id,
                text=record.text,
                pack=record.pack,
                source_title=record.source_title,
                source_url=record.source_url,
                license=record.license,
                tags=record.tags,
                score=score,
            )
            for score, record in scored
        ]
        return rerank_cards(query, cards, limit)
