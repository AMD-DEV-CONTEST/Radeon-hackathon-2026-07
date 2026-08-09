from __future__ import annotations
from pathlib import Path
from collections import Counter
import hashlib
import json
import math
import re
from .config import settings


TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9-]{2,}")
VECTOR_SIZE = 384


def embedding(text: str) -> list[float]:
    vector = [0.0] * VECTOR_SIZE
    tokens = TOKEN_PATTERN.findall(text.lower())
    for token, count in Counter(tokens).items():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % VECTOR_SIZE
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign * (1.0 + math.log(count))
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def chunk_pages(pages: list[dict], size: int = 900, overlap: int = 150) -> list[dict]:
    chunks = []
    for page in pages:
        text = " ".join(page["text"].split())
        start = 0
        while start < len(text):
            end = min(len(text), start + size)
            if end < len(text):
                split = text.rfind(" ", start, end)
                if split > start + size // 2:
                    end = split
            content = text[start:end].strip()
            if content:
                chunks.append({"page": page["page"], "text": content})
            if end >= len(text):
                break
            start = max(start + 1, end - overlap)
    return chunks


class IndexStore:
    def __init__(self) -> None:
        self._chroma = None
        self._collection = None
        try:
            import chromadb
            from chromadb.config import Settings
            settings.chroma_path.mkdir(parents=True, exist_ok=True)
            self._chroma = chromadb.PersistentClient(
                path=str(settings.chroma_path),
                settings=Settings(anonymized_telemetry=False)
            )
            self._collection = self._chroma.get_or_create_collection(
                "industrial_knowledge", metadata={"hnsw:space": "cosine"}
            )
        except Exception:
            self._load_json()

    @property
    def engine(self) -> str:
        return "chromadb" if self._collection is not None else "json-cosine-fallback"

    def add(self, document_id: str, name: str, chunks: list[dict], entities: dict, document_type: str) -> None:
        records = []
        for index, chunk in enumerate(chunks):
            records.append({
                "id": f"{document_id}-{index}",
                "text": chunk["text"],
                "embedding": embedding(chunk["text"]),
                "metadata": {
                    "document_id": document_id,
                    "source": name,
                    "page": int(chunk["page"]),
                    "asset_tags": ",".join(entities["asset_tags"]),
                    "failures": ",".join(entities["failures"]),
                    "actions": ",".join(entities["actions"]),
                    "dates": ",".join(entities["dates"]),
                    "measurements": ",".join(entities["measurements"]),
                    "document_type": document_type,
                }
            })
        if self._collection is not None:
            old = self._collection.get(where={"document_id": document_id})
            if old.get("ids"):
                self._collection.delete(ids=old["ids"])
            if records:
                self._collection.add(
                    ids=[r["id"] for r in records],
                    documents=[r["text"] for r in records],
                    embeddings=[r["embedding"] for r in records],
                    metadatas=[r["metadata"] for r in records],
                )
        else:
            self._records = [r for r in self._records if r["metadata"]["document_id"] != document_id]
            self._records.extend(records)
            self._save_json()

    def search(self, question: str, asset_tag: str = "", limit: int = 5) -> list[dict]:
        query = embedding(f"{question} {asset_tag}")
        if self._collection is not None:
            where = {"asset_tags": {"$contains": asset_tag.upper()}} if asset_tag else None
            try:
                result = self._collection.query(
                    query_embeddings=[query], n_results=limit, where=where,
                    include=["documents", "metadatas", "distances"]
                )
            except Exception:
                result = self._collection.query(
                    query_embeddings=[query], n_results=limit,
                    include=["documents", "metadatas", "distances"]
                )
            items = []
            for text, metadata, distance in zip(
                    result.get("documents", [[]])[0],
                    result.get("metadatas", [[]])[0],
                    result.get("distances", [[]])[0]):
                if asset_tag and asset_tag.upper() not in metadata.get("asset_tags", ""):
                    continue
                items.append({"text": text, "metadata": metadata, "score": round(max(0, 1 - distance), 4)})
            return items
        scored = []
        for record in self._records:
            if asset_tag and asset_tag.upper() not in record["metadata"].get("asset_tags", ""):
                continue
            score = sum(a * b for a, b in zip(query, record["embedding"]))
            scored.append({"text": record["text"], "metadata": record["metadata"], "score": round(score, 4)})
        return sorted(scored, key=lambda item: item["score"], reverse=True)[:limit]

    def search_by_source(self, name_fragment: str, limit: int = 5) -> list[dict]:
        """Search for chunks whose source filename contains the given fragment."""
        name_lower = name_fragment.lower().strip()
        if not name_lower:
            return []
        if self._collection is not None:
            all_data = self._collection.get(include=["documents", "metadatas"])
            items = []
            for text, metadata in zip(all_data.get("documents", []), all_data.get("metadatas", [])):
                source = metadata.get("source", "").lower()
                if name_lower in source:
                    items.append({"text": text, "metadata": metadata, "score": 0.85})
            return items[:limit]
        return [
            {"text": r["text"], "metadata": r["metadata"], "score": 0.85}
            for r in self._records if name_lower in r["metadata"].get("source", "").lower()
        ][:limit]

    def asset(self, tag: str) -> list[dict]:
        tag = tag.upper()
        if self._collection is not None:
            all_data = self._collection.get(include=["documents", "metadatas"])
            return [
                {"text": text, "metadata": metadata, "score": 1.0}
                for text, metadata in zip(all_data.get("documents", []), all_data.get("metadatas", []))
                if tag in metadata.get("asset_tags", "")
            ]
        return [
            {"text": r["text"], "metadata": r["metadata"], "score": 1.0}
            for r in self._records if tag in r["metadata"].get("asset_tags", "")
        ]

    def count(self) -> int:
        if self._collection is not None:
            return self._collection.count()
        return len(self._records)

    def all_records(self) -> list[dict]:
        if self._collection is not None:
            all_data = self._collection.get(include=["documents", "metadatas"])
            return [
                {"text": text, "metadata": metadata}
                for text, metadata in zip(all_data.get("documents", []), all_data.get("metadatas", []))
            ]
        return [{"text": r["text"], "metadata": r["metadata"]} for r in self._records]

    def delete(self, document_id: str) -> None:
        if self._collection is not None:
            try:
                old = self._collection.get(where={"document_id": str(document_id)})
                if old and old.get("ids"):
                    self._collection.delete(ids=old["ids"])
            except Exception:
                pass
        else:
            self._records = [r for r in self._records if str(r["metadata"].get("document_id")) != str(document_id)]
            self._save_json()

    def _load_json(self) -> None:
        settings.index_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._records = json.loads(settings.index_path.read_text(encoding="utf-8"))
        except Exception:
            self._records = []

    def _save_json(self) -> None:
        settings.index_path.write_text(json.dumps(self._records), encoding="utf-8")


store = IndexStore()

