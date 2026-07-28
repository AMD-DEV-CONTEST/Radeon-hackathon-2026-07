"""
RAG Retriever for searching ROCm documentation chunks.

Supports FAISS, ChromaDB, and a pure-Python TF-IDF fallback
so it works out-of-the-box without GPU/C++ dependencies during development.
"""

import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional


DEFAULT_INDEX_DIR = Path(__file__).parent.parent.parent / ".index"
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Lazy-loaded to avoid hard import errors
_model = None
_faiss_index = None
_embeddings = None
_chunks: Optional[list[dict]] = None
_tfidf_index: Optional[dict] = None


def retrieve(
    query: str,
    top_k: int = 5,
    index_dir: Optional[str] = None,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
) -> list[dict]:
    """
    Search the vector index for the most relevant documentation chunks.

    Args:
        query: The natural-language query (e.g., "LDS bank conflict mitigation").
        top_k: Number of top chunks to return.
        index_dir: Path to the persisted index directory.
        embedding_model: Name of the sentence-transformers model to use.

    Returns:
        List of dicts:
        [
            {
                "rank": int,
                "source": str,         # filename inside corpus/
                "section": str,        # section header
                "text": str,           # chunk content
                "score": float,        # similarity score (lower = more similar for L2)
            },
            ...
        ]
    """
    global _chunks

    idx_dir = Path(index_dir or DEFAULT_INDEX_DIR)
    chunks_path = idx_dir / "chunks.json"

    if not chunks_path.exists():
        return _fallback_retrieve(query, top_k)

    if _chunks is None:
        with open(chunks_path, "r", encoding="utf-8") as f:
            _chunks = json.load(f)

    # Try FAISS first, then Chroma, then TF-IDF
    results = _faiss_retrieve(query, top_k, idx_dir, embedding_model)
    if results is None:
        results = _chroma_retrieve(query, top_k, idx_dir)
    if results is None:
        results = _tfidf_retrieve(query, top_k, _chunks)

    return [
        {
            "rank": i + 1,
            "source": r.get("source", "unknown"),
            "section": r.get("section", ""),
            "text": r.get("text", ""),
            "score": r.get("score", 0.0),
        }
        for i, r in enumerate(results)
    ]


def format_retrieved_context(results: list[dict], max_chars: int = 3000) -> str:
    """
    Format retrieved chunks into a single context string for the LLM prompt.
    Respects a char budget so it fits comfortably in the context window.
    """
    if not results:
        return "[No relevant documentation found in corpus. Answer from general knowledge.]"

    sections = []
    total_chars = 0
    for r in results:
        header = f"[{r['rank']}] Source: {r['source']} § {r['section']}"
        body = r["text"].strip()
        entry = f"{header}\n{body}"
        if total_chars + len(entry) > max_chars:
            break
        sections.append(entry)
        total_chars += len(entry)

    return "\n\n---\n\n".join(sections)


# ------------------------------------------------------------------
# Backend implementations
# ------------------------------------------------------------------

def _faiss_retrieve(
    query: str,
    top_k: int,
    idx_dir: Path,
    model_name: str,
) -> Optional[list[dict]]:
    """Retrieve using FAISS flat L2 index."""
    global _model, _faiss_index, _embeddings, _chunks

    faiss_path = idx_dir / "faiss.index"
    if not faiss_path.exists():
        return None

    try:
        import faiss
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None

    if _model is None:
        _model = SentenceTransformer(model_name)
    if _faiss_index is None:
        _faiss_index = faiss.read_index(str(faiss_path))

    query_vec = _model.encode([query], convert_to_numpy=True).astype(np.float32)
    distances, indices = _faiss_index.search(query_vec, top_k)

    results = []
    for dist, idx in zip(distances[0], indices[0]):
        if idx < 0 or idx >= len(_chunks):
            continue
        chunk = _chunks[idx]
        results.append({**chunk, "score": float(dist)})
    return results


def _chroma_retrieve(
    query: str,
    top_k: int,
    idx_dir: Path,
) -> Optional[list[dict]]:
    """Retrieve using ChromaDB collection."""
    chroma_path = idx_dir / "chroma"
    if not chroma_path.exists():
        return None

    try:
        import chromadb
    except ImportError:
        return None

    client = chromadb.PersistentClient(path=str(chroma_path))
    try:
        collection = client.get_collection("rocm_docs")
    except Exception:
        return None

    res = collection.query(query_texts=[query], n_results=top_k)
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]

    results = []
    for doc, meta, dist in zip(docs, metas, dists):
        results.append({
            "source": meta.get("source", ""),
            "section": meta.get("section", ""),
            "text": doc,
            "score": float(dist),
        })
    return results


def _tfidf_retrieve(query: str, top_k: int, chunks: list[dict]) -> list[dict]:
    """
    Pure-Python TF-IDF retrieval — no GPU, no C++ libs required.
    Adequate for development and demo environments.
    Always builds a fresh index over the provided chunks so doc IDs are
    consistent with the chunk list indices (safe for both test and production use).
    """
    local_index = _build_tfidf_index(chunks)

    query_tokens = _tokenize(query)
    scores = defaultdict(float)

    for token in query_tokens:
        if token not in local_index["idf"]:
            continue
        idf = local_index["idf"][token]
        for doc_id, tf in local_index["tf"].get(token, {}).items():
            scores[doc_id] += tf * idf

    ranked = sorted(scores.items(), key=lambda x: -x[1])[:top_k]
    return [
        {**chunks[doc_id], "score": round(score, 4)}
        for doc_id, score in ranked
        if doc_id < len(chunks)
    ]


def _build_tfidf_index(chunks: list[dict]) -> dict:
    """Build a TF-IDF index over the chunk texts."""
    tf: dict[str, dict[int, float]] = defaultdict(dict)
    df: dict[str, int] = defaultdict(int)

    for doc_id, chunk in enumerate(chunks):
        tokens = _tokenize(chunk["text"])
        token_count = defaultdict(int)
        for t in tokens:
            token_count[t] += 1
        total = max(len(tokens), 1)
        for token, count in token_count.items():
            tf[token][doc_id] = count / total
            df[token] += 1

    num_docs = len(chunks)
    idf = {
        token: math.log((num_docs + 1) / (count + 1)) + 1
        for token, count in df.items()
    }

    return {"tf": dict(tf), "idf": idf}


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer."""
    return re.findall(r"[a-zA-Z0-9_]+", text.lower())


def _fallback_retrieve(query: str, top_k: int) -> list[dict]:
    """Return empty results with explanation if no index found."""
    return [{
        "rank": 1,
        "source": "system",
        "section": "No index found",
        "text": (
            "No RAG index found. Run `build_index()` from src/rag/index_builder.py "
            "after adding documents to the corpus/ directory."
        ),
        "score": 0.0,
    }]
