"""Search API endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query
from app.config import ENTITY_TYPES
from app.models import SearchQuery
from services.db import get_db
from app.dependencies.auth import get_current_user_role
import json

router = APIRouter(tags=["search"])

@router.post("/api/search")
def search_entities(query: SearchQuery, role: str = Depends(get_current_user_role)):
    conn = get_db()
    try:
        cursor = conn.cursor()
        conditions = ["e.is_active = 1"]
        params = []
        if query.book_id:
            conditions.append("e.book_id = ?")
            params.append(query.book_id)
        
        if query.keyword:
            keyword = f"%{query.keyword}%"
            conditions.append("(e.title LIKE ? OR e.content LIKE ? OR e.full_content LIKE ? OR e.ai_summary LIKE ?)")
            params.extend([keyword, keyword, keyword, keyword])
        
        if query.entity_type:
            conditions.append("e.entity_type = ?")
            params.append(query.entity_type)
        
        if query.tags:
            for tag in query.tags:
                conditions.append("e.entity_id IN (SELECT entity_id FROM tag_index WHERE tag = ?)")
                params.append(tag)
        
        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT e.*, (SELECT COUNT(*) FROM relations WHERE source_id = e.entity_id OR target_id = e.entity_id) as relation_count
            FROM entities e WHERE {where_clause}
            ORDER BY e.importance DESC, e.updated_at DESC LIMIT ?
        """
        params.append(query.limit)
        
        cursor.execute(sql, params)
        results = []
        for row in cursor.fetchall():
            result = dict(row)
            result["tags"] = json.loads(result["tags"]) if result["tags"] else []
            results.append(result)
        
        return {"total": len(results), "results": results, "query": query.keyword}
    finally:
        conn.close()

@router.get("/api/search/quick")
def quick_search(q: str = Query(""), limit: int = 5, role: str = Depends(get_current_user_role)):
    """快速搜索实体，返回精简结果（给前端自动补全用）。"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        keyword = f"%{q}%"
        cursor.execute(
            "SELECT entity_id, title, entity_type, importance FROM entities WHERE is_active = 1 AND title LIKE ? AND book_id = ? ORDER BY importance DESC LIMIT ?",
            (keyword, limit),
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()
