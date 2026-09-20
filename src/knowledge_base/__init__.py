"""RAG knowledge base for crypto trading strategy generation.

Two retrieval layers:
  1. Keyword/alias retriever (default, CPU-only, zero deps) — see `retriever`.
  2. Optional semantic (embedding) retriever — see `semantic` (needs
     sentence-transformers; fails safe to the keyword path).

Knowledge entries (knowledge_entries.py) carry `keywords` + `aliases` so the
retriever survives rephrasing ("横盘" -> Mean Reversion, "双均线" -> MA
Crossover).

Usage:
    from src.knowledge_base import KnowledgeRetriever, retrieve_knowledge
    from src.knowledge_base import SemanticRetriever, semantic_available

    kr = KnowledgeRetriever()
    context = kr.retrieve("BTC RSI超卖策略，止损3%")   # keyword path
    if semantic_available():
        sr = SemanticRetriever(kr)                    # true-RAG path (opt-in)
        context = sr.retrieve_as_context("市场横盘时怎么操作")
"""

from .retriever import KnowledgeRetriever, KnowledgeEntry, retrieve_knowledge
from . import semantic
from .semantic import SemanticRetriever, semantic_available

__all__ = [
    "KnowledgeRetriever",
    "KnowledgeEntry",
    "retrieve_knowledge",
    "semantic",
    "SemanticRetriever",
    "semantic_available",
]
