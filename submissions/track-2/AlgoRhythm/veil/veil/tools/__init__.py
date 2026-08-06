"""Importing this package registers every tool.

Registration is an import side effect, so anything that needs the registry
populated must import `veil.tools`, not `veil.tools.registry`.
"""
from veil.tools.registry import REGISTRY  # noqa: F401

from veil.tools import (  # noqa: F401  (imported for registration side effects)
    candidate_set,
    cooccurrence,
    corpus_search,
    date_math,
    doc_metadata,
    entity_ledger,
    layout_forensics,
    redact_apply,
)

__all__ = ["REGISTRY"]
