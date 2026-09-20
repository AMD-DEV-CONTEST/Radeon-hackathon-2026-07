"""Retrieval Agent — multi-path knowledge retrieval with confidence gating.

Input:  query + optional metadata filter (strategy, asset, timeframe)
Output: reference_docs + has_valid_docs flag

If has_valid_docs=false, the pipeline short-circuits: the reasoning agent
must output neutral, and no trade is executed.
"""

from __future__ import annotations

from .protocol import AgentMessage


def run_retrieval_agent(msg: AgentMessage) -> AgentMessage:
    """Execute retrieval and return enriched message.

    Uses MultiRetriever (keyword + BM25 + dense + reranking + confidence gate).
    """
    query = msg.payload.get("query", "")
    filter_meta = msg.payload.get("filter_meta", {})

    if not query:
        return AgentMessage(
            payload={"reference_docs": [], "has_valid_docs": False, "max_confidence_score": 0.0},
            status="error",
            error_msg="Missing 'query' in payload",
            source_agent="retrieval_agent",
            target_agent="reasoning_agent",
            session_id=msg.session_id,
            asset=msg.asset,
            timeframe=msg.timeframe,
        )

    try:
        from ..knowledge_base.multi_retriever import retrieve_with_confidence
        result = retrieve_with_confidence(query, filter_meta=filter_meta)

        return AgentMessage(
            payload={
                "reference_docs": result.reference_docs,
                "has_valid_docs": result.has_valid_docs,
                "max_confidence_score": result.max_confidence_score,
                "total_candidates": result.total_candidates,
                "query": query,
            },
            status="success" if result.has_valid_docs else "success",
            source_agent="retrieval_agent",
            target_agent="reasoning_agent",
            session_id=msg.session_id,
            asset=msg.asset,
            timeframe=msg.timeframe,
        )
    except Exception as e:
        return AgentMessage(
            payload={"reference_docs": [], "has_valid_docs": False, "max_confidence_score": 0.0},
            status="error",
            error_msg=str(e),
            source_agent="retrieval_agent",
            target_agent="reasoning_agent",
            session_id=msg.session_id,
            asset=msg.asset,
            timeframe=msg.timeframe,
        )
