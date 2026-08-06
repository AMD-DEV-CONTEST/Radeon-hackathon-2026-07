"""Document router — upload, list, delete."""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from pathlib import Path
import uuid
from ..database import get_db
from ..models import Document
from ..security.jwt import get_current_user
from ..config import settings
from ..services.extraction import extract_text, extract_entities, classify_document
from ..services.rag_service import rag, chunk_pages

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    doc_id = str(uuid.uuid4())
    suffix = Path(file.filename or "file.txt").suffix
    file_path = Path(settings.UPLOAD_DIR) / f"{doc_id}{suffix}"

    content = await file.read()
    file_path.write_bytes(content)

    try:
        full_text, pages = extract_text(file_path)
        entities = extract_entities(full_text)
        doc_type = classify_document(file.filename or "", full_text)
        chunks = chunk_pages(pages)
        indexed = rag.index_document(doc_id, file.filename or "untitled", chunks, entities, doc_type)
        status_val = "READY"
        error_msg = None
        summary = f"Indexed {indexed} evidence chunks and found {len(entities.get('asset_tags', []))} asset tags."
    except Exception as e:
        status_val = "FAILED"
        error_msg = str(e)
        entities = {"asset_tags": []}
        doc_type = "Industrial Document"
        summary = ""

    doc = Document(
        document_id=doc_id,
        original_name=file.filename or "untitled",
        content_type=file.content_type or "",
        size_bytes=len(content),
        status=status_val,
        document_type=doc_type,
        asset_tags=",".join(entities.get("asset_tags", [])),
        summary=summary,
        error_message=error_msg,
        uploaded_by=user.get("sub", ""),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    return {
        "id": str(doc.id),
        "documentId": doc.document_id,
        "originalName": doc.original_name,
        "filename": doc.original_name,
        "contentType": doc.content_type,
        "sizeBytes": doc.size_bytes,
        "size": doc.size_bytes or 0,
        "status": (doc.status or "ready").lower(),
        "documentType": doc.document_type,
        "assetTags": doc.asset_tags,
        "summary": doc.summary,
        "uploadedBy": doc.uploaded_by,
        "uploadedAt": str(doc.uploaded_at) if doc.uploaded_at else "",
        "uploadDate": str(doc.uploaded_at) if doc.uploaded_at else "",
    }


@router.get("")
def list_documents(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    docs = db.query(Document).order_by(Document.id.desc()).all()
    return [
        {
            "id": str(d.id),
            "documentId": d.document_id,
            "originalName": d.original_name,
            "filename": d.original_name or "untitled",
            "contentType": d.content_type or "",
            "sizeBytes": d.size_bytes or 0,
            "size": d.size_bytes or 0,
            "status": (d.status or "ready").lower(),
            "documentType": d.document_type or "",
            "assetTags": d.asset_tags or "",
            "summary": d.summary or "",
            "errorMessage": d.error_message,
            "uploadedBy": d.uploaded_by or "",
            "uploadedAt": str(d.uploaded_at) if d.uploaded_at else "",
            "uploadDate": str(d.uploaded_at) if d.uploaded_at else "",
        }
        for d in docs
    ]


@router.delete("/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db),
                    user: dict = Depends(get_current_user)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    rag.delete_document(doc.document_id)
    db.delete(doc)
    db.commit()
    return {"ok": True}
