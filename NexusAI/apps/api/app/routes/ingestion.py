from uuid import UUID
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.repository import WorldRepository
from app.source_repository import SourceRepository
from nexus.ingestion import UnsupportedFileType, ingest
from nexus.world import Source

router = APIRouter(prefix="/worlds/{world_id}", tags=["ingestion"])

@router.post("/sources/upload", status_code=status.HTTP_201_CREATED)
async def upload_source(
    world_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if WorldRepository(db).get(world_id) is None:
        raise HTTPException(404, "World not found")

    filename = file.filename or "upload"
    content = await file.read()

    if not content:
        raise HTTPException(400, "Uploaded file is empty")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "File exceeds the 10 MB MVP limit")

    try:
        result = ingest(filename, content)
    except UnsupportedFileType as exc:
        raise HTTPException(415, str(exc))
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(400, f"Could not parse file: {exc}")

    if not result.text.strip():
        raise HTTPException(422, "No extractable text found")

    source = Source(
        world_id=world_id,
        name=result.filename,
        source_type=result.source_type,
        metadata={"character_count": len(result.text), "chunk_count": len(result.chunks)},
    )
    SourceRepository(db).create_with_chunks(source, result.checksum, result.chunks)

    return {
        "source_id": source.id,
        "world_id": world_id,
        "filename": result.filename,
        "source_type": result.source_type,
        "checksum": result.checksum,
        "character_count": len(result.text),
        "chunk_count": len(result.chunks),
        "status": "ingested",
    }

@router.get("/sources")
async def list_sources(world_id: UUID, db: Session = Depends(get_db)):
    if WorldRepository(db).get(world_id) is None:
        raise HTTPException(404, "World not found")
    records = SourceRepository(db).list_sources(world_id)
    return [
        {
            "id": r.id,
            "world_id": r.world_id,
            "name": r.name,
            "source_type": r.source_type,
            "checksum": r.checksum,
            "metadata": r.metadata_json,
        }
        for r in records
    ]

@router.get("/sources/{source_id}/chunks")
async def source_chunks(world_id: UUID, source_id: UUID, db: Session = Depends(get_db)):
    if WorldRepository(db).get(world_id) is None:
        raise HTTPException(404, "World not found")
    records = SourceRepository(db).list_chunks(source_id)
    return [
        {"id": r.id, "chunk_index": r.chunk_index, "text": r.text, "metadata": r.metadata_json}
        for r in records if r.world_id == str(world_id)
    ]
