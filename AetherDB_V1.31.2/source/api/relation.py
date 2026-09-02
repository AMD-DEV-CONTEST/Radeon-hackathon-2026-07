"""Relation management API endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from app.models import RelationCreate
from services.db import get_db
from app.dependencies.auth import get_current_user_role

router = APIRouter(tags=["relations"])


@router.post("/api/relation")
def create_relation(
    relation: RelationCreate,
    book_id: str = "default",
    role: str = Depends(get_current_user_role),
):
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT entity_id FROM entities WHERE entity_id = ? AND (book_id = ? OR ? IS NULL)",
            (relation.source_id, book_id, book_id),
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Source entity not found")
        cursor.execute(
            "SELECT entity_id FROM entities WHERE entity_id = ? AND (book_id = ? OR ? IS NULL)",
            (relation.target_id, book_id, book_id),
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Target entity not found")

        cursor.execute(
            "INSERT INTO relations (source_id, target_id, relation_type, description, book_id) VALUES (?, ?, ?, ?, ?)",
            (relation.source_id, relation.target_id, relation.relation_type, relation.description, book_id),
        )
        conn.commit()
        return {
            "message": "Relation created",
            "source": relation.source_id,
            "target": relation.target_id,
            "type": relation.relation_type,
            "book_id": book_id,
        }
    finally:
        conn.close()


@router.get("/api/entity/{entity_id}/relations")
def get_entity_relations(
    entity_id: str,
    direction: str = "both",
    book_id: str = None,
    role: str = Depends(get_current_user_role),
):
    conn = get_db()
    try:
        cursor = conn.cursor()
        if direction == "out":
            sql = (
                "SELECT r.*, e.title as target_title "
                "FROM relations r LEFT JOIN entities e ON r.target_id = e.entity_id "
                "WHERE r.source_id = ?"
            )
            params = [entity_id]
        elif direction == "in":
            sql = (
                "SELECT r.*, e.title as source_title "
                "FROM relations r LEFT JOIN entities e ON r.source_id = e.entity_id "
                "WHERE r.target_id = ?"
            )
            params = [entity_id]
        else:
            sql = (
                "SELECT r.*, e1.title as source_title, e2.title as target_title "
                "FROM relations r "
                "LEFT JOIN entities e1 ON r.source_id = e1.entity_id "
                "LEFT JOIN entities e2 ON r.target_id = e2.entity_id "
                "WHERE (r.source_id = ? OR r.target_id = ?)"
            )
            params = [entity_id, entity_id]

        if book_id:
            sql += " AND r.book_id = ?"
            params.append(book_id)

        cursor.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()
