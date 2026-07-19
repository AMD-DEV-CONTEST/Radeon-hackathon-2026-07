# services/memory/__init__.py
"""Memory service — persistent memory storage and retrieval.

The Hermes-style store is `core.memory.markdown_memory.MarkdownMemoryManager`
(memory/user.md + memory/memory.md); `MemoryManager` (JSON-backed) is kept
importable for any code that still references it directly, but is no longer
the live path. `MemoryService`/`MemoryVectorStore` (ChromaDB-backed, and
never reachable from the live app) were removed.
"""

from .memory import MemoryManager
from .markdown_memory import MarkdownMemoryManager

__all__ = [
    "MemoryManager",
    "MarkdownMemoryManager",
]
