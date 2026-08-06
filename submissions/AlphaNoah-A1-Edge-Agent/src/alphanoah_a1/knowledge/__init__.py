"""Structured, retrieval-neutral knowledge context foundation."""

from .context import ContextBuilder
from .deterministic import DeterministicKnowledgeRetriever
from .models import (
    KnowledgeContext,
    KnowledgeDocument,
    KnowledgeDocumentStatus,
    KnowledgeDocumentType,
)
from .repository import JsonKnowledgeRepository, KnowledgeRepository
from .retrieval import KnowledgeMatch, KnowledgeQuery, KnowledgeRetriever

__all__ = [
    "ContextBuilder",
    "DeterministicKnowledgeRetriever",
    "JsonKnowledgeRepository",
    "KnowledgeContext",
    "KnowledgeDocument",
    "KnowledgeDocumentStatus",
    "KnowledgeDocumentType",
    "KnowledgeMatch",
    "KnowledgeQuery",
    "KnowledgeRepository",
    "KnowledgeRetriever",
]
