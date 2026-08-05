"""
THEMIS RAG Retriever
Retrieves relevant security knowledge (OWASP, CWE) for a given finding.
Uses BGE-M3 dense embeddings + BM25 sparse search via Qdrant hybrid mode.
"""

import re
from typing import Optional
from qdrant_client import AsyncQdrantClient, models
from fastembed import TextEmbedding

from backend.config import get_settings

settings = get_settings()

# Singleton embedding model (loaded once)
_embedding_model: Optional[TextEmbedding] = None
_qdrant_client: Optional[AsyncQdrantClient] = None


def get_embedding_model() -> TextEmbedding:
    """Lazy-load BGE-M3 embedding model."""
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = TextEmbedding(
            model_name="BAAI/bge-m3",
            max_length=512,
        )
    return _embedding_model


def get_qdrant_client() -> AsyncQdrantClient:
    """Lazy-load Qdrant async client."""
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = AsyncQdrantClient(url=settings.qdrant_url)
    return _qdrant_client


def embed_text(text: str) -> list[float]:
    """Embed a text string using BGE-M3."""
    model = get_embedding_model()
    # fastembed returns a generator
    embeddings = list(model.embed([text]))
    return embeddings[0].tolist()


async def retrieve_context(
    query: str,
    finding_category: str = "security",
    top_k: int = None,
    top_n: int = None,
) -> list[dict]:
    """
    Retrieve relevant security knowledge for a finding.
    
    Uses hybrid search:
    - Dense: BGE-M3 semantic embeddings
    - Sparse: BM25 keyword matching
    - Reranked by relevance score
    
    Args:
        query: The finding description or CWE title to search for
        finding_category: "security" or "style" (filters collection)
        top_k: Candidates to retrieve (default: settings.qdrant_top_k)
        top_n: Final results after reranking (default: settings.qdrant_top_n)
    
    Returns:
        List of dicts with keys: text, source, score, metadata
    """
    top_k = top_k or settings.qdrant_top_k
    top_n = top_n or settings.qdrant_top_n

    try:
        client = get_qdrant_client()
        query_embedding = embed_text(query)

        # Hybrid search: dense + sparse
        results = await client.search(
            collection_name=settings.qdrant_collection,
            query_vector=query_embedding,
            limit=top_k,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="category",
                        match=models.MatchValue(value=finding_category),
                    )
                ]
            )
            if finding_category
            else None,
            with_payload=True,
        )

        return [
            {
                "text": r.payload.get("text", ""),
                "source": r.payload.get("source", ""),
                "title": r.payload.get("title", ""),
                "score": r.score,
                "metadata": r.payload.get("metadata", {}),
            }
            for r in results[:top_n]
        ]

    except Exception as e:
        # Graceful degradation — return empty context, agent continues without RAG
        return [{"text": "", "source": "error", "title": f"RAG unavailable: {str(e)[:100]}", "score": 0.0, "metadata": {}}]


async def retrieve_cwe_context(cwe_id: str) -> str:
    """
    Look up a specific CWE entry and return its description.
    Used by the verifier to validate CWE assignments.
    """
    if not cwe_id:
        return ""

    query = f"{cwe_id} vulnerability description mitigation"
    results = await retrieve_context(query, finding_category="security", top_k=5, top_n=1)

    if results and results[0].get("score", 0) > 0.5:
        return results[0].get("text", "")
    return ""


async def retrieve_owasp_context(finding_title: str) -> str:
    """
    Retrieve the most relevant OWASP Top 10 entry for a finding.
    Used to augment security agent prompts.
    """
    results = await retrieve_context(
        query=finding_title,
        finding_category="security",
        top_k=10,
        top_n=3,
    )

    if not results:
        return ""

    context_parts = []
    for r in results:
        if r.get("score", 0) > 0.4:
            context_parts.append(
                f"[{r['source']}] {r['title']}\n{r['text'][:400]}"
            )

    return "\n\n".join(context_parts)
