"""Namespace long-term memory recall: scope filtering → cosine ranking."""
from __future__ import annotations

import math
import logging
from typing import Any

from src.memory.layers import MemoryRecord

logger = logging.getLogger(__name__)


async def recall_namespace(
    embedding_agent: Any,
    memory_store: list[MemoryRecord],
    query: str,
    scope: dict[str, str] | None = None,
    top_k: int = 3,
) -> list[MemoryRecord]:
    """Namespace long-term memory recall.

    Args:
        embedding_agent: the embedding Agent instance
        memory_store: the list of memory records
        query: the query text
        scope: scope filter conditions
        top_k: number of records to return

    Returns:
        The list of memory records sorted by similarity
    """
    # 1. scope filtering
    eligible = []
    for record in memory_store:
        if scope:
            if all(record.scope.get(k) == v for k, v in scope.items()):
                eligible.append(record)
        else:
            eligible.append(record)

    if not eligible:
        return []

    # 2. separate records that have vectors and those that need recomputation
    has_vector = [r for r in eligible if r.vector is not None]
    no_vector = [r for r in eligible if r.vector is None]

    # 3. generate embeddings for records without vectors
    if no_vector:
        try:
            texts = [r.summary for r in no_vector]
            vectors = await embedding_agent.input(texts).async_start()
            for record, vector in zip(no_vector, vectors):
                record.vector = [float(v) for v in vector]
            has_vector.extend(no_vector)
        except Exception as e:
            logger.warning("embedding generation failed: %s", e)

    # 4. query embedding
    try:
        query_vec = await embedding_agent.input([query]).async_start()
        query_vec = [float(v) for v in query_vec[0]]
    except Exception as e:
        logger.error("query embedding failed: %s", e)
        return []

    # 5. cosine ranking
    def cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    ranked = sorted(
        [r for r in has_vector if r.vector],
        key=lambda r: cosine(query_vec, r.vector),
        reverse=True,
    )

    logger.info("Namespace recall: %d/%d records, top-%d", len(ranked), len(memory_store), top_k)
    return ranked[:top_k]
