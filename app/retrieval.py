"""
Retrieval: Query → relevant chunks from ChromaDB.
"""
import logging
from typing import List, Tuple
from langchain.schema import Document
from app.vectorstore import get_vectorstore
from config import TOP_K

logger = logging.getLogger(__name__)


def retrieve_relevant_chunks(query: str, k: int = TOP_K) -> List[Tuple[Document, float]]:
    """Retrieve top-k most relevant chunks with relevance scores."""
    vectorstore = get_vectorstore()
    
    try:
        results = vectorstore.similarity_search_with_relevance_scores(query, k=k)
    except Exception as e:
        logger.error(f"Retrieval failed: {e}")
        return []
    
    return results


def format_context(chunks: List[Tuple[Document, float]]) -> str:
    """Combine retrieved chunks into a single context block."""
    if not chunks:
        return ""
    
    parts = []
    for doc, score in chunks:
        source = doc.metadata.get("source", "unknown")
        idx = doc.metadata.get("chunk_index", "?")
        parts.append(f"[Source: {source}, chunk {idx}]\n{doc.page_content}")
    
    return "\n\n---\n\n".join(parts)


def format_sources_markdown(chunks: List[Tuple[Document, float]]) -> str:
    """Build markdown summary of retrieved chunks for UI."""
    if not chunks:
        return "_No relevant chunks retrieved (upload documents first)._ "
    
    lines = ["**Retrieved chunks:**"]
    for i, (doc, score) in enumerate(chunks, start=1):
        source = doc.metadata.get("source", "unknown")
        idx = doc.metadata.get("chunk_index", "?")
        preview = doc.page_content[:180].replace("\n", " ")
        lines.append(
            f"{i}. `{source}` (chunk {idx}, relevance={score:.3f}): {preview}..."
        )
    
    return "\n".join(lines)