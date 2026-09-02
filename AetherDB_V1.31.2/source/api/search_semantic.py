import sqlite3
from fastapi import APIRouter, HTTPException, Request, Depends
from typing import List, Optional
from pydantic import BaseModel
from app.dependencies.auth import get_current_user_role
from services.database_registry import get_database, get_db_path
from services.vector_store import VectorStore

router = APIRouter(tags=['semantic_search'])

class SemanticSearchRequest(BaseModel):
    lang: Optional[str] = None
    query: str
    top_k: int = 10
    filter_type: Optional[str] = None
    database_id: str
    book_id: str
    use_hybrid: bool = True

@router.post('/api/search/semantic')
async def semantic_search(req: SemanticSearchRequest, request: Request, role: str = Depends(get_current_user_role)):
    store = request.app.state.vector_store
    if not store:
        raise HTTPException(500, 'Vector store not initialized')
    embedding_status = store.embedding.status()
    if not store.embedding.is_aetherdb_local:
        raise HTTPException(503, {
            "code": "AETHERDB_LOCAL_EMBEDDING_REQUIRED",
            "message": "Semantic retrieval requires the AetherDB-owned local embedding runtime",
        })
    if not embedding_status.available:
        raise HTTPException(503, {
            "code": "EMBEDDING_RUNTIME_UNAVAILABLE",
            "message": embedding_status.detail,
            "model_id": embedding_status.model_id,
        })
    if not get_database(req.database_id):
        raise HTTPException(404, 'Database not found')
    db_path = get_db_path(req.database_id)
    with sqlite3.connect(db_path) as scope_db:
        if not scope_db.execute("SELECT 1 FROM books WHERE book_id=?", (req.book_id,)).fetchone():
            raise HTTPException(404, 'Book not found in database')
    scoped_store = VectorStore(db_path, store.embedding)
    vec_results = scoped_store.search(
        query=req.query,
        top_k=req.top_k,
        filter_type=req.filter_type,
        book_id=req.book_id,
        lang=req.lang
    )
    # Convert SearchResult objects to dicts for RRF merge
    vec_dicts = [{
        "entity_id": r.entity_id,
        "title": r.title,
        "entity_type": r.entity_type,
        "importance": r.importance,
        "content_preview": r.chunk_text[:200],
        "score": round(r.score, 4),
        "book_id": r.book_id
    } for r in vec_results]
    fts_results = _fts_search(req.query, req.top_k * 2, db_path, req.book_id) if len(req.query) >= 2 else []
    merged = _rrf_merge([vec_dicts, fts_results], req.top_k)
    return {
        "results": merged,
        "total": len(merged),
        "search_method": "hybrid",
        "query": req.query
    }



def _fts_search(query, top_k, db_path, book_id):
    """FTS5 full-text search on entities_fts table."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        safe = query.replace('"', '""')
        cursor.execute(
            "SELECT e.rowid, e.entity_id, e.title, e.entity_type, e.importance, e.content "
            "FROM entities_fts f JOIN entities e ON f.rowid = e.rowid "
            "WHERE entities_fts MATCH ? AND e.book_id=? ORDER BY rank LIMIT ?",
            ('"' + safe + '"', book_id, top_k)
        )
        results = []
        for row in cursor.fetchall():
            results.append({
                "entity_id": row[1],
                "title": row[2],
                "entity_type": row[3],
                "importance": row[4],
                "content_preview": (row[5] or "")[:200],
                "source": "fts",
                "score": 0.3
            })
        return results
    finally:
        conn.close()

def _rrf_merge(results_lists, top_k=10, k=60):
    """Reciprocal Rank Fusion merge."""
    scores = {}
    data = {}
    for results in results_lists:
        for i, r in enumerate(results):
            eid = r["entity_id"]
            if eid not in scores:
                scores[eid] = 0
                data[eid] = r
            scores[eid] += 1.0 / (k + i + 1)
    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:top_k]
    for eid in sorted_ids:
        data[eid]["score"] = scores[eid]
        data[eid]["search_method"] = "hybrid"
    return [data[eid] for eid in sorted_ids]
