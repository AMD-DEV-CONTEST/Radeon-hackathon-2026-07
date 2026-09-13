"""
Runbook/precedent search tool — the tool the Runbook Retriever agent calls.
Wraps MemoryService.find_similar_precedent so agent code depends on the tool
interface, not the memory internals directly (keeps the agent layer swappable
and the memory layer independently testable).
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.service import MemoryService
from app.tools.base import BaseTool


class RunbookSearchTool(BaseTool):
    name = "runbook_search"
    description = (
        "Semantically search past incident postmortems and operational runbooks "
        "for precedent relevant to the current incident."
    )

    def __init__(self, db: AsyncSession, memory_service: MemoryService | None = None) -> None:
        self.db = db
        self.memory_service = memory_service or MemoryService()

    async def _execute(self, query: str, top_k: int = 5) -> dict:
        results = await self.memory_service.find_similar_precedent(self.db, query_text=query, top_k=top_k)
        return {
            "query": query,
            "matches": [
                {
                    "title": record.title,
                    "content": record.content,
                    "kind": record.kind.value,
                    "similarity": round(score, 4),
                    "metadata": record.memory_metadata,
                }
                for record, score in results
            ],
        }
