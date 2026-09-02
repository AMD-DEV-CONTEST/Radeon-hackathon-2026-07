"""Statistics and Timeline API endpoints."""
from fastapi import APIRouter, Depends, Query
from app.config import ENTITY_TYPES
from services.db import get_db
from app.dependencies.auth import get_current_user_role

router = APIRouter(tags=["stats"])

@router.get("/api/stats")
def get_stats(book_id: str = None, role: str = Depends(get_current_user_role)):
    """Entity statistics, optionally filtered by book_id."""
    conn = get_db()
    c = conn.cursor()
    sql = "SELECT COUNT(*) FROM entities WHERE is_active = 1"
    params = []
    if book_id:
        sql += " AND book_id = ?"
        params.append(book_id)
    c.execute(sql, params)
    total = c.fetchone()[0]

    sql2 = "SELECT entity_type, COUNT(*) as count FROM entities WHERE is_active = 1 GROUP BY entity_type"
    if book_id:
        sql2 += " AND book_id = ?"
    c.execute(sql2, params)
    type_dist = {ENTITY_TYPES.get(r["entity_type"], r["entity_type"]): r["count"] for r in c.fetchall()}

    c.execute("SELECT COUNT(*) FROM relations")
    rels = c.fetchone()[0]

    c.execute("SELECT tag, COUNT(*) as count FROM tag_index GROUP BY tag ORDER BY count DESC LIMIT 20")
    tags_list = [{"tag": r["tag"], "count": r["count"]} for r in c.fetchall()]

    c.execute("SELECT COUNT(*) FROM timeline_events")
    tl = c.fetchone()[0]

    return {"total_entities": total, "type_distribution": type_dist,
            "total_relations": rels, "top_tags": tags_list, "timeline_events": tl}

@router.get("/api/timeline")
def get_timeline_events(era: str = None, book_id: str = None,
                        role: str = Depends(get_current_user_role)):
    """Timeline events, optionally filtered by era and/or book_id."""
    conn = get_db()
    cursor = conn.cursor()
    conditions = []
    params = []
    sql = "SELECT te.*, e.title as entity_title FROM timeline_events te LEFT JOIN entities e ON te.entity_id = e.entity_id"
    if era:
        conditions.append("te.era = ?")
        params.append(era)
    if book_id:
        conditions.append("te.book_id = ?")
        params.append(book_id)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY te.year, te.id ASC"
    cursor.execute(sql, params)
    return [dict(r) for r in cursor.fetchall()]
