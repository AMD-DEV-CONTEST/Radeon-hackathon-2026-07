"""Dashboard + health router."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Document, QueryLog
from ..security.jwt import get_current_user
from ..services.rag_service import rag

router = APIRouter(tags=["dashboard"])


@router.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "indusmind-ai",
        "version": "2.0.0",
    }


@router.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    docs = db.query(Document).count()
    ready = db.query(Document).filter(Document.status == "READY").count()
    queries = db.query(QueryLog).count()

    # Collect unique asset tags from indexed evidence
    asset_tags: set[str] = set()
    for rec in rag.all_records():
        for tag in filter(None, rec["metadata"].get("asset_tags", "").split(",")):
            asset_tags.add(tag)

    recent = (
        db.query(QueryLog)
        .order_by(QueryLog.id.desc())
        .limit(5)
        .all()
    )

    return {
        "documents": docs,
        "readyDocuments": ready,
        "assets": len(asset_tags),
        "queries": queries,
        "assetTags": sorted(asset_tags),
        "aiOnline": True,
        "recentQueries": [
            {
                "id": q.id,
                "question": q.question,
                "mode": q.mode or "",
                "confidence": q.confidence or 0,
                "createdAt": str(q.created_at) if q.created_at else "",
            }
            for q in recent
        ],
    }
