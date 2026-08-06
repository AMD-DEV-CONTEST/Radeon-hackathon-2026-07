"""Global search API endpoint."""
from fastapi import APIRouter, Query, Depends
from app.dependencies.auth import get_current_user_role
from fastapi import Depends
from services.global_index import search_global

router = APIRouter(tags=["global_search"])

@router.get("/api/search/global")
def api_search_global(
    q: str = Query("", description="Search query"),
    scope: str = Query("all", description="Search scope: all | database | book"),
    database_id: str = Query(None, description="Filter by database"),
    book_id: str = Query(None, description="Filter by book"),
    limit: int = Query(20, description="Max results"),
    role: str = Depends(get_current_user_role),
):
    """Cross-database full-text search via FTS5 global index."""
    if not q or len(q.strip()) < 2:
        return {"query": q, "scope": scope, "results": [], "total": 0}

    results = search_global(q.strip(), scope, database_id, book_id, limit)
    return {
        "query": q,
        "scope": scope,
        "database_id": database_id,
        "book_id": book_id,
        "results": results,
        "total": len(results)
    }