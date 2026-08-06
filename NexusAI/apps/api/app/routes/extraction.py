from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.extraction_service import extract_source_to_graph
from app.repository import WorldRepository

router = APIRouter(prefix="/worlds/{world_id}", tags=["extraction"])

@router.post("/sources/{source_id}/extract")
async def extract_source(world_id: UUID, source_id: UUID, db: Session = Depends(get_db)):
    if WorldRepository(db).get(world_id) is None:
        raise HTTPException(404, "World not found")

    result = extract_source_to_graph(db, world_id, source_id)
    if result is None:
        raise HTTPException(404, "Source or source chunks not found")

    return {
        "world_id": world_id,
        "source_id": source_id,
        "status": "extracted",
        **result,
    }
