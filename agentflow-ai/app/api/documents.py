from __future__ import annotations

from pathlib import Path
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
import multipart  # type: ignore  # validates python-multipart is installed

from app.config import config
from app.dependencies import AppServices, get_services
from app.schemas import DocumentRecord, UploadResponse

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[DocumentRecord])
def list_documents(services: AppServices = Depends(get_services)) -> list[DocumentRecord]:
    return [DocumentRecord(**row) for row in services.storage.list_documents()]


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    services: AppServices = Depends(get_services),
) -> UploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".pdf", ".txt", ".md"}:
        raise HTTPException(status_code=400, detail="Only PDF, TXT, and MD files are supported")

    payload = await file.read()
    max_bytes = config.max_upload_size_mb * 1024 * 1024
    if len(payload) > max_bytes:
        raise HTTPException(status_code=400, detail=f"File exceeds {config.max_upload_size_mb} MB limit")

    safe_name = f"{uuid.uuid4()}{suffix}"
    destination = config.uploads_dir / safe_name
    destination.write_bytes(payload)

    try:
        parsed = services.rag.ingest_file(destination, file.filename)
    except ValueError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return UploadResponse(
        document=DocumentRecord(
            id=parsed.document_id,
            filename=parsed.filename,
            mime_type=parsed.mime_type,
            page_count=parsed.page_count,
            chunk_count=len(parsed.chunks),
            created_at=services.storage.get_document(parsed.document_id)["created_at"],
        ),
        extracted_preview=parsed.text[:500] or "No text extracted from document.",
    )
