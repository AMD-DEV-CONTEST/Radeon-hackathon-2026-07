from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.database.models import SourceChunkRecord
from app.repository import WorldRepository
from nexus.retrieval import SemanticRetriever

router = APIRouter(prefix="/worlds/{world_id}", tags=["retrieval"])
retriever = SemanticRetriever()

@router.get("/search")
async def semantic_search(
    world_id: UUID,
    q: str = Query(min_length=1),
    top_k: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    if WorldRepository(db).get(world_id) is None:
        raise HTTPException(404, "World not found")

    chunks = db.scalars(
        select(SourceChunkRecord)
        .where(SourceChunkRecord.world_id == str(world_id))
        .order_by(SourceChunkRecord.source_id, SourceChunkRecord.chunk_index)
    ).all()

    hits = retriever.search(q, [chunk.text for chunk in chunks], top_k=top_k)

    return {
        "world_id": world_id,
        "query": q,
        "results": [
            {
                "chunk_id": chunks[hit.index].id,
                "source_id": chunks[hit.index].source_id,
                "chunk_index": chunks[hit.index].chunk_index,
                "score": round(hit.score, 6),
                "text": chunks[hit.index].text,
            }
            for hit in hits
        ],
    }
