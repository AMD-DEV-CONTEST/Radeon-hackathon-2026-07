"""RAG retrieval entrypoint: query → [rewrite] → hybrid retrieval (FAISS+BM25) → reranking → supplement chunk_text.

Design-audit fixes:
- C4: fail-closed when Workspace records are missing (marked failed), rather than silently skipping
- I3: assign a short citation key (selection_key) to each candidate, not exposing chunk_id
- Evidence Grounding Chain: read chunk metadata from the Workspace RecordStore (records/*.json)

New capabilities:
- hybrid retrieval: FAISS (semantic retrieval) + BM25 (term-frequency matching), fusing the results of both paths
- reranking: Cross-Encoder precisely ranks the top-K, selecting the top-N
- Query rewriting: LLM expansion for fuzzy queries (called by the pipeline layer)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from src.rag.indexer import FaissIndexer

logger = logging.getLogger(__name__)


class EvidenceResolutionError(Exception):
    """Raised when none of the candidates can be resolved in the Workspace (C4 fail-closed)."""


def _normalize_score(score: float, source: str) -> float:
    """Normalize scores from different sources to the [0, 1] range.

    FAISS IndexFlatIP returns the inner product (cosine similarity of normalized vectors), range [-1, 1]
    BM25 returns a non-negative score with no upper bound
    """
    if source == "bm25":
        # BM25 score normalization: compress to [0, 1] with sigmoid
        return float(1.0 / (1.0 + np.exp(-score / 5.0)))
    else:
        # FAISS cosine similarity, mapped from [-1, 1] to [0, 1]
        return float((score + 1.0) / 2.0)


class RAGRetriever:
    """A retriever integrating embedding + FAISS + BM25 + reranking + Workspace.

    Hybrid retrieval flow:
    1. query → embedding → FAISS ANN retrieval (top-K1 semantic candidates)
    2. query → BM25 retrieval (top-K2 term-frequency candidates)
    3. fuse and deduplicate the two candidate paths
    4. Cross-Encoder / LLM reranking, selecting the top-N
    5. supplement the full chunk_text and metadata from the Workspace

    The workspace parameter can be:
    - an Agently Workspace instance (has a get_data method)
    - None (no Workspace, candidates are marked as ref_only)
    - a Path or str (Workspace root, read from records/*.json)
    """

    def __init__(
        self,
        embedding_agent: Any,
        indexer: FaissIndexer,
        workspace: Any = None,
        top_k: int = 10,
        bm25_indexer: Any = None,
        reranker: Any = None,
        rerank_top_n: int = 5,
        bm25_weight: float = 0.3,
        faiss_weight: float = 0.7,
    ):
        self.embedding_agent = embedding_agent
        self.indexer = indexer
        self.workspace = workspace
        self.top_k = top_k
        self.bm25_indexer = bm25_indexer
        self.reranker = reranker
        self.rerank_top_n = rerank_top_n
        self.bm25_weight = bm25_weight
        self.faiss_weight = faiss_weight
        # if the workspace is a path, pre-resolve the records directory
        self._records_dir: Path | None = None
        if isinstance(workspace, (str, Path)):
            self._records_dir = Path(workspace) / "records"
            if not self._records_dir.exists():
                logger.warning("Workspace records directory does not exist: %s", self._records_dir)

    def _read_record_from_dir(self, chunk_id: str) -> dict | None:
        """Read a chunk record from the records directory (JSON files written by build_index.py)."""
        if not self._records_dir:
            return None
        record_path = self._records_dir / f"{chunk_id}.json"
        if not record_path.exists():
            return None
        try:
            return json.loads(record_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.debug("failed to read record %s: %s", chunk_id, e)
            return None

    def list_all_documents(self) -> list[dict]:
        """List all indexed documents (deduplicated), returning the document title and source file name.

        Read all chunk records from the records directory and extract unique document information.
        Each document may have multiple chunks, deduplicated by source (file name).

        Returns:
            [{"title": "document title", "source": "file name"}, ...]
        """
        if not self._records_dir or not self._records_dir.exists():
            logger.warning("records directory does not exist: %s", self._records_dir)
            return []

        doc_map: dict[str, dict] = {}  # deduplicate by source as the key

        for record_file in self._records_dir.glob("*.json"):
            try:
                record = json.loads(record_file.read_text(encoding="utf-8"))
                meta = record.get("meta", {})
                source = meta.get("source", record.get("doc_ref", record_file.stem))
                title = meta.get("title", source)

                if source not in doc_map:
                    doc_map[source] = {
                        "title": title,
                        "source": source,
                    }
            except Exception as e:
                logger.debug("failed to read record file %s: %s", record_file.name, e)
                continue

        logger.info("listed all documents: %d (read from %s)", len(doc_map), self._records_dir)
        return list(doc_map.values())

    def _hybrid_fuse(
        self,
        faiss_candidates: list[dict],
        bm25_candidates: list[dict],
    ) -> list[dict]:
        """Fuse hybrid retrieval results: weighted normalized scores + deduplication.

        Reference the hybrid retrieval strategy of the lesson 8 HybridRetriever.
        Use weighted score fusion:
        - fused_score = faiss_weight * normalized_faiss_score + bm25_weight * normalized_bm25_score
        """
        # aggregate by chunk_id
        fused_map: dict[str, dict] = {}

        for c in faiss_candidates:
            cid = c.get("chunk_id", "")
            if not cid:
                continue
            norm_score = _normalize_score(c.get("score", 0), "faiss")
            if cid not in fused_map:
                fused_map[cid] = {
                    "chunk_id": cid,
                    "faiss_score": norm_score,
                    "bm25_score": 0.0,
                    "chunk_text": c.get("chunk_text", ""),
                    "sources": ["faiss"],
                }
            else:
                fused_map[cid]["faiss_score"] = max(fused_map[cid]["faiss_score"], norm_score)

        for c in bm25_candidates:
            cid = c.get("chunk_id", "")
            if not cid:
                continue
            norm_score = _normalize_score(c.get("score", 0), "bm25")
            if cid not in fused_map:
                fused_map[cid] = {
                    "chunk_id": cid,
                    "faiss_score": 0.0,
                    "bm25_score": norm_score,
                    "chunk_text": c.get("chunk_text", ""),
                    "sources": ["bm25"],
                }
            else:
                fused_map[cid]["bm25_score"] = max(fused_map[cid]["bm25_score"], norm_score)
                fused_map[cid]["sources"].append("bm25")
                # if BM25 has text but FAISS does not, supplement it
                if not fused_map[cid].get("chunk_text") and c.get("chunk_text"):
                    fused_map[cid]["chunk_text"] = c["chunk_text"]

        # compute the fused scores
        for item in fused_map.values():
            item["fused_score"] = (
                self.faiss_weight * item["faiss_score"]
                + self.bm25_weight * item["bm25_score"]
            )

        # sort in descending order of fused score
        fused_list = sorted(
            fused_map.values(),
            key=lambda x: x["fused_score"],
            reverse=True,
        )

        logger.info(
            "hybrid retrieval fusion: FAISS=%d, BM25=%d, after fusion+dedup=%d",
            len(faiss_candidates), len(bm25_candidates), len(fused_list),
        )

        return fused_list

    async def retrieve(self, query: str) -> list[dict]:
        """Complete RAG retrieval chain: query → hybrid retrieval → reranking → supplement text.

        Flow:
        1. query embedding → FAISS ANN retrieval (top-K semantic candidates)
        2. query → BM25 retrieval (top-K term-frequency candidates) (if BM25 is available)
        3. fuse and deduplicate the two candidate paths
        4. Cross-Encoder / LLM reranking (if a reranker is available)
        5. supplement the full chunk_text and metadata from the Workspace — C4: fail-closed

        Args:
            query: the user query text

        Returns:
            a candidate list (including chunk_text, ref, score, evidence_state, etc.)

        Raises:
            EvidenceResolutionError: when none of the candidates can be resolved (C4 fail-closed)
        """
        # 1. query embedding + FAISS ANN retrieval
        result = await self.embedding_agent.input([query]).async_start()
        query_vec = np.array(result[0], dtype=np.float32)
        norm = np.linalg.norm(query_vec)
        if norm > 0:
            query_vec = query_vec / norm

        faiss_candidates = self.indexer.search(query_vec, self.top_k)
        logger.info("FAISS retrieval: query='%s...', %d candidates", query[:20], len(faiss_candidates))

        # 2. BM25 retrieval (if available)
        bm25_candidates = []
        if self.bm25_indexer and self.bm25_indexer.bm25:
            bm25_candidates = self.bm25_indexer.search(query, self.top_k)
            logger.info("BM25 retrieval: query='%s...', %d candidates", query[:20], len(bm25_candidates))

        # 3. hybrid fusion
        if bm25_candidates:
            candidates = self._hybrid_fuse(faiss_candidates, bm25_candidates)
        else:
            # without BM25, use only the FAISS results
            candidates = faiss_candidates

        if not candidates:
            logger.warning("retrieval result is empty: query='%s...'", query[:20])
            return []

        # 4. reranking (if a reranker is available)
        if self.reranker:
            if hasattr(self.reranker, "rerank"):
                # Cross-Encoder (sync) or LLM (async)
                rerank_method = self.reranker.rerank
                if hasattr(rerank_method, "__await__"):
                    # async method (LLMReranker)
                    candidates = await rerank_method(query, candidates, self.rerank_top_n)
                else:
                    # sync method (CrossEncoderReranker)
                    candidates = rerank_method(query, candidates, self.rerank_top_n)
            else:
                logger.warning("reranker has no rerank method, skipping reranking")
        else:
            # without a reranker, take the top-N
            candidates = candidates[:self.rerank_top_n]

        # 5. supplement chunk_text (from Workspace or the records directory) — C4: fail-closed
        if self._records_dir:
            for c in candidates:
                chunk_id = c.get("chunk_id")
                if not chunk_id:
                    c["chunk_text"] = None
                    c["ref"] = ""
                    c["evidence_state"] = "failed"
                    c["failure_reason"] = "missing chunk_id from FAISS id_map"
                    continue
                record = self._read_record_from_dir(chunk_id)
                if record:
                    # if the candidate already has chunk_text (from BM25), keep it; otherwise read from the record
                    if not c.get("chunk_text"):
                        c["chunk_text"] = record.get("content", "")
                    c["chunk_summary"] = record.get("chunk_summary", c.get("chunk_summary", ""))
                    c["ref"] = chunk_id
                    c["evidence_state"] = "bounded"
                    # supplement the source metadata
                    c["source"] = record.get("meta", {}).get("source", "")
                    c["title"] = record.get("meta", {}).get("title", "")
                    c["section_title"] = record.get("meta", {}).get("section_title", "")
                    c["section_type"] = record.get("meta", {}).get("section_type", "text")
                else:
                    c["chunk_text"] = c.get("chunk_text")  # keep the text provided by BM25
                    c["ref"] = chunk_id
                    c["evidence_state"] = "bounded" if c.get("chunk_text") else "failed"
                    if not c.get("chunk_text"):
                        c["failure_reason"] = f"Record file not found: {chunk_id}.json"
        elif self.workspace and hasattr(self.workspace, "get_data"):
            for c in candidates:
                chunk_id = c.get("chunk_id")
                if not chunk_id:
                    c["chunk_text"] = None
                    c["ref"] = ""
                    c["evidence_state"] = "failed"
                    c["failure_reason"] = "missing chunk_id from FAISS id_map"
                    continue
                try:
                    record = await self.workspace.get_data(chunk_id)
                    if record:
                        if not c.get("chunk_text"):
                            c["chunk_text"] = record.get("content", "")
                        c["ref"] = chunk_id
                        c["evidence_state"] = "bounded"
                    else:
                        c["chunk_text"] = c.get("chunk_text")
                        c["ref"] = chunk_id
                        c["evidence_state"] = "bounded" if c.get("chunk_text") else "failed"
                        if not c.get("chunk_text"):
                            c["failure_reason"] = f"Workspace record not found for chunk_id: {chunk_id}"
                except Exception as e:
                    c["chunk_text"] = c.get("chunk_text")
                    c["ref"] = chunk_id
                    c["evidence_state"] = "bounded" if c.get("chunk_text") else "failed"
                    if not c.get("chunk_text"):
                        c["failure_reason"] = f"Workspace lookup error: {e}"
        else:
            for c in candidates:
                c["evidence_state"] = "ref_only" if c.get("chunk_text") else "failed"
                if not c.get("chunk_text"):
                    c["evidence_state"] = "ref_only"

        # C4: if all candidates are failed, raise an exception
        valid = [c for c in candidates if c.get("evidence_state") in ("bounded", "ref_only")]
        failed = [c for c in candidates if c.get("evidence_state") == "failed"]
        if not valid and failed:
            raise EvidenceResolutionError(
                f"All {len(failed)} candidates failed to resolve in Workspace. "
                f"First failure: {failed[0].get('failure_reason', 'unknown')}"
            )

        if failed:
            logger.warning(
                "retrieval diagnostics: %d succeeded, %d failed (first failure reason: %s)",
                len(valid), len(failed), failed[0].get("failure_reason"),
            )

        return valid if valid else candidates