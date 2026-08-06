"""BM25 index building and retrieval — sparse retrieval covers the recall blind spots of vector retrieval.

Reference the BM25Retriever in lesson 8 retrieval.py and the BM25Ingestor in ingestion.py.
BM25 is based on term-frequency statistics and outperforms vector retrieval for exact matches (product names, clause numbers).
"""
from __future__ import annotations

import json
import logging
import pickle
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from rank_bm25 import BM25Okapi
    HAS_BM25 = True
except ImportError:
    HAS_BM25 = False
    logger.warning("rank-bm25 not installed, BM25 retrieval unavailable. pip install rank-bm25")

try:
    import jieba
    HAS_JIEBA = True
    # preload the tokenizer (the first call triggers dictionary loading)
    jieba.initialize()
except ImportError:
    HAS_JIEBA = False
    logger.info("jieba not installed; BM25 will use character-level tokenization. pip install jieba can improve Chinese retrieval")

def _tokenize(text: str) -> list[str]:
    """Chinese tokenization: jieba word segmentation + English split by spaces.

    jieba tokenizes insurance documents better than character-level segmentation:
    - "雇主责任险理赔流程" → ["雇主", "责任", "险", "理赔", "流程"]
    - character-level: ["雇", "主", "责", "任", "险", ...] (semantic granularity too fine)
    """
    if HAS_JIEBA:
        # jieba handles both Chinese and English, returning a list of words
        tokens = [w.lower().strip() for w in jieba.cut(text) if w.strip()]
        return tokens
    else:
        # fallback: split English by spaces, Chinese by character
        tokens: list[str] = []
        for word in text.split():
            if word.isascii():
                tokens.append(word.lower())
            else:
                tokens.extend(list(word))
        return tokens


class BM25Indexer:
    """BM25 index manager.

    Complementary to FAISS:
    - FAISS: semantic-similarity retrieval (vector distance)
    - BM25: term-frequency-matching retrieval (exact keyword match)
    The results of both paths are fused during hybrid retrieval to improve recall.
    """

    def __init__(self):
        if not HAS_BM25:
            raise RuntimeError("rank-bm25 not installed. pip install rank-bm25")
        self.bm25: BM25Okapi | None = None
        self.chunk_ids: list[str] = []  # token position → chunk_id mapping
        self.chunk_texts: list[str] = []  # original text (used to return results)

    def build_from_chunks(self, chunks: list[Any]) -> None:
        """Build the BM25 index from a list of Chunk objects.

        Args:
            chunks: list of Chunk objects (need chunk_id and chunk_text attributes)
        """
        tokenized_chunks = []
        self.chunk_ids = []
        self.chunk_texts = []

        for chunk in chunks:
            tokens = _tokenize(chunk.chunk_text)
            tokenized_chunks.append(tokens)
            self.chunk_ids.append(chunk.chunk_id)
            self.chunk_texts.append(chunk.chunk_text)

        self.bm25 = BM25Okapi(tokenized_chunks)
        logger.info("BM25 index built: %d documents", len(chunks))

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        """BM25 retrieval, returning the top-K candidates.

        Args:
            query: the query text
            top_k: the number of candidates to return

        Returns:
            a candidate list, each candidate contains chunk_id, score, chunk_text
        """
        if not self.bm25:
            return []

        tokenized_query = _tokenize(query)
        scores = self.bm25.get_scores(tokenized_query)

        actual_k = min(top_k, len(scores))
        if actual_k == 0:
            return []

        # take the top_k indices
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:actual_k]

        results = []
        for idx in top_indices:
            if scores[idx] <= 0:
                continue
            results.append({
                "chunk_id": self.chunk_ids[idx],
                "score": float(scores[idx]),
                "chunk_text": self.chunk_texts[idx],
                "source": "bm25",
            })

        return results

    def save(self, index_dir: str | Path) -> None:
        """Persist the BM25 index to disk."""
        index_dir = Path(index_dir)
        index_dir.mkdir(parents=True, exist_ok=True)

        with open(index_dir / "bm25_index.pkl", "wb") as f:
            pickle.dump({
                "bm25": self.bm25,
                "chunk_ids": self.chunk_ids,
                "chunk_texts": self.chunk_texts,
            }, f)
        logger.info("BM25 index saved: %s (%d documents)", index_dir, len(self.chunk_ids))

    def load(self, index_dir: str | Path) -> None:
        """Load the BM25 index from disk."""
        index_dir = Path(index_dir)
        bm25_path = index_dir / "bm25_index.pkl"
        if not bm25_path.exists():
            logger.warning("BM25 index file does not exist: %s", bm25_path)
            return

        with open(bm25_path, "rb") as f:
            data = pickle.load(f)
            self.bm25 = data["bm25"]
            self.chunk_ids = data["chunk_ids"]
            self.chunk_texts = data["chunk_texts"]
        logger.info("BM25 index loaded: %s (%d documents)", index_dir, len(self.chunk_ids))