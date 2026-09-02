"""Global Index management API endpoints."""
from fastapi import APIRouter, Query, HTTPException, Depends
from services.global_index import (
    rebuild_all, rebuild_database, get_sync_status,
    get_entity_count, mark_database_dirty, search_global
)
from app.dependencies.auth import get_current_user_role, require_admin
from services.db import get_db
from services.audit_log import log_event
from services.database_registry import list_databases

router = APIRouter(tags=["global_index"])
import time

_last_rebuild_time = 0
REBUILD_COOLDOWN = 60  # seconds

@router.get("/api/index/status")
def api_index_status(database_id: str = None, role: str = Depends(get_current_user_role)):
    """Get sync status for all or one database."""
    status = get_sync_status(database_id)
    count = get_entity_count(database_id)
    return {
        "sync_status": status,
        "indexed_entities": count,
        "databases_total": len(list_databases())
    }

@router.post("/api/index/rebuild")
def api_rebuild_all(_: None = Depends(require_admin)):
    global _last_rebuild_time
    now = time.time()
    if now - _last_rebuild_time < REBUILD_COOLDOWN:
        remaining = int(REBUILD_COOLDOWN - (now - _last_rebuild_time))
        raise HTTPException(status_code=429, detail=f"Rebuild too frequent. Wait {remaining}s")
    _last_rebuild_time = now
    result = rebuild_all()
    log_event(get_db(), "index.rebuild", "Global index rebuilt")
    return {"status": "ok", "result": result}

@router.post("/api/index/rebuild/{database_id}")
def api_rebuild_database(database_id: str, _: None = Depends(require_admin)):
    """Rebuild global index for ONE database."""
    from services.database_registry import get_database
    db = get_database(database_id)
    if not db:
        raise HTTPException(status_code=404, detail=f"Database '{database_id}' not found")
    result = rebuild_database(database_id)
    log_event(get_db(), "index.rebuild", f"Global index rebuilt for {database_id}")
    return {"status": "ok", "database_id": database_id, "result": result}

@router.post("/api/index/sync/{database_id}/{book_id}")
def api_sync_book(database_id: str, book_id: str = "default", _: None = Depends(require_admin)):
    """Sync one book's data to global index."""
    result = rebuild_database(database_id)
    log_event(get_db(), "index.sync", f"Global index synced for {database_id}/{book_id}")
    return {"status": "ok", "database_id": database_id, "book_id": book_id, "result": result}
