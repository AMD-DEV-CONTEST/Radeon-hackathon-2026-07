"""
Knowledge ingestion API (Phase 9) — how an SRE team seeds Aegis with their
existing runbooks/postmortems so the Runbook Retriever agent has real
precedent to draw on from day one, not just incidents Aegis has handled itself.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.db.models.user import Role, User
from app.db.session import get_db
from app.schemas.knowledge import RunbookIngestRequest, RunbookIngestResponse
from app.services.rag_service import RagIngestionService

router = APIRouter()
_rag_service = RagIngestionService()


@router.post("/runbooks", response_model=RunbookIngestResponse, status_code=201)
async def ingest_runbook(
    payload: RunbookIngestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(Role.SRE)),
) -> RunbookIngestResponse:
    chunk_count = await _rag_service.ingest_document(
        db, title=payload.title, raw_text=payload.content, source_metadata=payload.metadata
    )
    return RunbookIngestResponse(title=payload.title, chunks_ingested=chunk_count)
