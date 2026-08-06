"""FAISS index building: chunking → embedding → index → persistence.

Design-audit fixes:
- I4: FAISS id_map is reduced to the minimal faiss_id → record_ref mapping; chunk metadata belongs to the Workspace RecordStore
- Backward compatibility is kept: old-format id_map can still be loaded
"""
from __future__ import annotations

import json
import time
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

try:
    import faiss
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False
    logger.warning("faiss-cpu not installed, FAISS index features unavailable. pip install faiss-cpu")


class FaissIndexer:
    """FAISS vector index manager.

    I4 boundary division:
        - FAISS only stores the vector index + the minimal faiss_id → record_ref mapping
        - the full chunk metadata (chunk_id, doc_ref, chunk_summary, start_char, end_char) belongs to the Workspace Record
        - on retrieval, the full metadata is fetched from the Workspace through record_ref
    """

    def __init__(self, dimension: int = 1024, index_type: str = "IndexFlatIP"):
        if not HAS_FAISS:
            raise RuntimeError("faiss-cpu not installed")
        self.dimension = dimension
        self.index_type = index_type
        self.index: Any = faiss.IndexFlatIP(dimension)
        # I4: id_map is reduced to faiss_id → record_ref (no longer stores full metadata)
        self.id_map: dict[str, str] = {}
        # backward compatibility: if an old format is loaded, the metadata is cached here
        self._legacy_meta: dict[str, dict] = {}
        self._next_id = 0

    @property
    def total_vectors(self) -> int:
        return self.index.ntotal

    def build_from_chunks(self, chunks: list[Any], embeddings: np.ndarray) -> None:
        """Build the index in batch. embeddings shape: (N, dimension), already normalized.

        I4: only store faiss_id → chunk_id (as record_ref); the caller writes the full metadata into the Workspace.
        """
        assert embeddings.shape[0] == len(chunks), f"chunks={len(chunks)} vs embeddings={embeddings.shape[0]}"
        assert embeddings.shape[1] == self.dimension, f"embedding dim={embeddings.shape[1]} vs expected={self.dimension}"

        self.index.add(embeddings.astype(np.float32))
        for i, chunk in enumerate(chunks):
            # I4: only store record_ref (chunk_id as ref), not the full metadata
            self.id_map[str(self._next_id + i)] = chunk.chunk_id
        self._next_id += len(chunks)
        logger.info("index built: %d vectors, total %d", len(chunks), self.total_vectors)

    def add_chunk(self, chunk: Any, embedding: np.ndarray) -> None:
        """Incrementally add a single chunk (vector index update, required for the competition demo).

        I4: only store record_ref; the caller writes the metadata into the Workspace.
        """
        self.index.add(np.array([embedding.astype(np.float32)]))
        self.id_map[str(self._next_id)] = chunk.chunk_id
        self._next_id += 1
        logger.debug("incremental add: chunk_id=%s", chunk.chunk_id)

    def search(self, query_embedding: np.ndarray, top_k: int = 10) -> list[dict]:
        """ANN retrieval: return the top-K candidates.

        I4: the returned candidates only contain record_ref (chunk_id); the retriever fetches the full metadata from the Workspace.
        """
        actual_k = min(top_k, self.total_vectors)
        if actual_k == 0:
            return []

        scores, indices = self.index.search(
            np.array([query_embedding.astype(np.float32)]), actual_k
        )

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            faiss_id = str(int(idx))
            record_ref = self.id_map.get(faiss_id, "")
            result = {
                "score": float(score),
                "faiss_id": faiss_id,
                "chunk_id": record_ref,  # I4: returned as record_ref
            }
            # backward compatibility: if the old format has metadata, attach and return it
            if faiss_id in self._legacy_meta:
                meta = self._legacy_meta[faiss_id]
                result["doc_ref"] = meta.get("doc_ref", "")
                result["chunk_summary"] = meta.get("chunk_summary", "")
            results.append(result)

        return results

    def save(self, index_dir: str | Path) -> None:
        """Persist the index and mapping to disk."""
        index_dir = Path(index_dir)
        index_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(index_dir / "faiss.index"))
        with open(index_dir / "id_map.json", "w", encoding="utf-8") as f:
            json.dump(self.id_map, f, ensure_ascii=False)
        logger.info("index saved to %s (%d vectors)", index_dir, self.total_vectors)

    def load(self, index_dir: str | Path) -> None:
        """Load the index from disk.

        I4: compatible with both the new and old id_map formats:
            - new format: {faiss_id: "record_ref_string"}
            - old format: {faiss_id: {chunk_id, doc_ref, chunk_summary, ...}}
        """
        index_dir = Path(index_dir)
        self.index = faiss.read_index(str(index_dir / "faiss.index"))
        with open(index_dir / "id_map.json", encoding="utf-8") as f:
            raw_map = json.load(f)

        # detect the format
        self.id_map = {}
        self._legacy_meta = {}
        for k, v in raw_map.items():
            if isinstance(v, dict):
                # old format: extract chunk_id as record_ref, cache the full metadata
                self.id_map[k] = v.get("chunk_id", "")
                self._legacy_meta[k] = v
            else:
                # new format: directly the record_ref
                self.id_map[k] = v

        self._next_id = max(int(k) for k in self.id_map.keys()) + 1 if self.id_map else 0
        logger.info("index loaded: %s (%d vectors)", index_dir, self.total_vectors)