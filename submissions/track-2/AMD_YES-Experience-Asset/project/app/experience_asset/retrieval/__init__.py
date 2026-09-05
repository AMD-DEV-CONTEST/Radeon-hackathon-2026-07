"""Phase-scoped local retrieval contracts."""

from .repository import (
    FakeScopedRetrievalRepository,
    RetrievalRequest,
    RetrievalResult,
    ScopedRetrievalRepository,
    SQLiteCurrentSourceRetrievalRepository,
    SQLiteSummaryLexicalRepository,
    SummaryLexicalHit,
    SummaryLexicalResult,
)

__all__ = [
    "FakeScopedRetrievalRepository",
    "RetrievalRequest",
    "RetrievalResult",
    "SQLiteCurrentSourceRetrievalRepository",
    "SQLiteSummaryLexicalRepository",
    "ScopedRetrievalRepository",
    "SummaryLexicalHit",
    "SummaryLexicalResult",
]
