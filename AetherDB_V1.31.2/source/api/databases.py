"""Database management API endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query
from services.database_registry import (
    init_registry, list_databases, get_database, get_db_path,
    get_active_database_id, set_active_database_id,
    create_database, remove_database, validate_database
)
from app.dependencies.auth import get_current_user_role, require_admin
from services.audit_log import log_event
from services.db import get_db
import logging

log = logging.getLogger(__name__)

router = APIRouter(tags=["databases"])

def _audit(event_type: str, description: str):
    db = get_db()
    try:
        log_event(db, event_type, description)
    finally:
        db.close()

@router.get("/api/databases")
def api_list_databases(role: str = Depends(get_current_user_role)):
    """List all registered databases."""
    return {"databases": list_databases()}

@router.post("/api/databases")
def api_create_database(name: str, author: str = "", description: str = "", _: None = Depends(require_admin)):
    """Create a new business database."""
    try:
        result = create_database(name, author, description)
        _audit("database.create", f"Database {result.get('database_id', name)} created")
        return {"status": "ok", "database": result}
    except ValueError as e:
        log.warning("Database create rejected: %s", e)
        raise HTTPException(status_code=400, detail="Invalid database request")

@router.get("/api/databases/active")
def api_get_active(role: str = Depends(get_current_user_role)):
    """Get the currently active database ID."""
    return {"active_database_id": get_active_database_id()}

@router.get("/api/databases/{database_id}")
def api_get_database(database_id: str, role: str = Depends(get_current_user_role)):
    """Get database info."""
    db = get_database(database_id)
    if not db:
        raise HTTPException(status_code=404, detail=f"Database '{database_id}' not found")
    return {"database": db}

@router.post("/api/databases/{database_id}/activate")
def api_activate_database(database_id: str, role: str = Depends(get_current_user_role)):
    """Switch the active database."""
    db = get_database(database_id)
    if not db:
        raise HTTPException(status_code=404, detail=f"Database '{database_id}' not found")
    set_active_database_id(database_id)
    return {"status": "ok", "active_database_id": database_id}

@router.delete("/api/databases/{database_id}")
def api_remove_database(database_id: str, _: None = Depends(require_admin)):
    """Remove a database from registry (not the default)."""
    try:
        remove_database(database_id)
        _audit("database.delete", f"Database {database_id} deleted")
        return {"status": "ok", "removed": database_id}
    except ValueError as e:
        log.warning("Database remove rejected: %s", e)
        raise HTTPException(status_code=400, detail="Invalid database request")

@router.post("/api/databases/{database_id}/init-db")
def api_init_database(database_id: str, _: None = Depends(require_admin)):
    """Initialize a database's schema (entities, relations, etc.)."""
    from services.db import init_db
    try:
        get_db_path(database_id)
        init_db(database_id)
        _audit("database.init", f"Database {database_id} initialized")
        return {"status": "ok", "message": f"Database '{database_id}' is ready"}
    except Exception as e:
        log.error("Database init failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Database initialization failed")

@router.get("/api/databases/{database_id}/validate")
def api_validate_database(database_id: str, role: str = Depends(get_current_user_role)):
    """Check if a database file exists and is accessible."""
    valid = validate_database(database_id)
    return {"database_id": database_id, "valid": valid}
