"""Entity CRUD API endpoints."""
import json, logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.dependencies.auth import get_current_user_role, require_admin
from services.audit_log import log_event
from services.db import get_db, generate_entity_id, sync_entity_fts, remove_entity_fts
from app.config import ENTITY_TYPES
from services.vector_store import connection_db_path
from services.embedding_tasks import enqueue_entity_sync_task_by_path
from services.translation_service import mark_entity_translations_stale

router = APIRouter(tags=['entity'])
log = logging.getLogger(__name__)


def _schedule_vector_task(db, entity_ids, operation="upsert"):
    try:
        return enqueue_entity_sync_task_by_path(
            connection_db_path(db),
            entity_ids,
            operation=operation,
        )
    except Exception as exc:
        log.warning("Embedding task scheduling failed: %s", type(exc).__name__)
        return None

def _row_get(row, key, default=None):
    return row[key] if row and key in row.keys() else default

class EntityCreate(BaseModel):
    entity_type: str = Field(..., pattern='^(character|faction|location|rule|event|item|concept|system)$')
    title: str = Field(..., min_length=1, max_length=200)
    content: str = ''
    tags: list = []
    importance: int = 5
    book_id: str = 'default'

class EntityUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    content: Optional[str] = None
    tags: Optional[list] = None
    importance: Optional[int] = None

@router.post('/api/entity')
def create_entity(entity: EntityCreate, role: str = Depends(get_current_user_role)):
    db = get_db()
    try:
        c = db.cursor()
        eid = generate_entity_id(entity.entity_type, c)
        tj = json.dumps(entity.tags, ensure_ascii=False)
        c.execute('INSERT INTO entities (entity_id, entity_type, title, content, tags, importance, book_id) VALUES (?,?,?,?,?,?,?)', (eid, entity.entity_type, entity.title, entity.content, tj, entity.importance, entity.book_id))
        for tag in entity.tags:
            c.execute('INSERT INTO tag_index (entity_id, tag, book_id) VALUES (?,?,?)', (eid, tag.strip(), entity.book_id))
        sync_entity_fts(db, eid)
        db.commit()
        vector_task = _schedule_vector_task(db, [eid])
        log_event(db, 'entity.create', f'Entity {eid} created')
        return {
            'entity_id': eid,
            'message': 'create success',
            'vector_indexed': bool(vector_task and vector_task['status'] == 'completed'),
            'vector_task_id': vector_task['id'] if vector_task else None,
        }
    except Exception as e:
        db.rollback(); log.error('Entity create: %s', e)
        raise HTTPException(500, 'Entity creation failed')


@router.get('/api/entity')
def list_entities(
    entity_type: Optional[str] = None,
    book_id: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    role: str = Depends(get_current_user_role),
):
    """Return a bounded entity collection for reader, graph and management UIs."""
    if entity_type and entity_type not in {
        'character', 'faction', 'location', 'rule', 'event', 'item', 'concept', 'system'
    }:
        raise HTTPException(422, 'Unsupported entity type')
    if not 1 <= limit <= 200 or offset < 0:
        raise HTTPException(422, 'Invalid pagination')

    conditions = ['e.is_active=1']
    params = []
    if entity_type:
        conditions.append('e.entity_type=?')
        params.append(entity_type)
    if book_id:
        conditions.append('e.book_id=?')
        params.append(book_id)
    if q:
        query = q.strip()
        if len(query) > 200:
            raise HTTPException(422, 'Query too long')
        if query:
            conditions.append('(e.title LIKE ? OR e.content LIKE ? OR e.ai_summary LIKE ?)')
            pattern = f'%{query}%'
            params.extend([pattern, pattern, pattern])

    where = ' AND '.join(conditions)
    db = get_db()
    try:
        total = db.execute(
            f'SELECT COUNT(*) FROM entities e WHERE {where}',
            params,
        ).fetchone()[0]
        rows = db.execute(
            'SELECT e.*, '
            '(SELECT COUNT(*) FROM relations r '
            'WHERE r.source_id=e.entity_id OR r.target_id=e.entity_id) AS relation_count '
            f'FROM entities e WHERE {where} '
            'ORDER BY e.updated_at DESC, e.entity_id ASC LIMIT ? OFFSET ?',
            [*params, limit, offset],
        ).fetchall()
        entities = [dict(row) for row in rows]
        return {
            'entities': entities,
            'results': entities,
            'total': total,
            'limit': limit,
            'offset': offset,
        }
    finally:
        db.close()

@router.get('/api/entity/{entity_id}')
def get_entity(entity_id: str, role: str = Depends(get_current_user_role)):
    db = get_db()
    try:
        r = db.execute('SELECT * FROM entities WHERE entity_id=?', (entity_id,)).fetchone()
        if not r or not r['is_active']: raise HTTPException(404, 'Entity not found')
        return dict(r)
    except HTTPException: raise
    except Exception as e: log.error('Entity get: %s', e); raise HTTPException(500, 'Failed to get entity')
    finally: db.close()

ALLOWED_UPDATE_FIELDS = {'title', 'content', 'tags', 'importance', 'timeline_year', 'timeline_era'}

@router.put('/api/entity/{entity_id}')
def update_entity(entity_id: str, entity: EntityUpdate, _: None = Depends(require_admin)):
    updates = {
        key: value
        for key, value in entity.model_dump(exclude_unset=True).items()
        if key in ALLOWED_UPDATE_FIELDS and value is not None
    }
    if 'tags' in updates:
        updates['tags'] = json.dumps(updates['tags'], ensure_ascii=False)
    if not updates: raise HTTPException(400, 'No valid fields')
    db = get_db()
    try:
        c = db.cursor()
        current = c.execute('SELECT * FROM entities WHERE entity_id=?', (entity_id,)).fetchone()
        if not current:
            raise HTTPException(404, 'Entity not found')
        current_version = int(_row_get(current, 'version', 1) or 1)
        c.execute(
            'INSERT INTO entity_versions(entity_id,version,title,content,full_content,ai_summary,tags,importance,book_id) VALUES (?,?,?,?,?,?,?,?,?)',
            (
                entity_id,
                current_version,
                _row_get(current, 'title', ''),
                _row_get(current, 'content', ''),
                _row_get(current, 'full_content', ''),
                _row_get(current, 'ai_summary', ''),
                _row_get(current, 'tags', '[]'),
                _row_get(current, 'importance', 5),
                _row_get(current, 'book_id', 'default'),
            ),
        )
        sets = ', '.join(f'{k}=?' for k in updates)
        c.execute(f'UPDATE entities SET {sets}, version=?, updated_at=CURRENT_TIMESTAMP WHERE entity_id=?', list(updates.values()) + [current_version + 1, entity_id])
        mark_entity_translations_stale(db, entity_id)
        sync_entity_fts(db, entity_id)
        db.commit()
        vector_task = _schedule_vector_task(db, [entity_id])
        log_event(db, 'entity.update', f'Entity {entity_id} updated')
        return {
            'message': 'update success',
            'entity_id': entity_id,
            'vector_indexed': bool(vector_task and vector_task['status'] == 'completed'),
            'vector_task_id': vector_task['id'] if vector_task else None,
        }
    except Exception as e:
        db.rollback(); log.error('Entity update: %s', e)
        raise HTTPException(500, 'Entity update failed')
    finally: db.close()

@router.delete('/api/entity/{entity_id}')
def delete_entity(entity_id: str, _: None = Depends(require_admin)):
    db = get_db()
    try:
        c = db.cursor()
        c.execute('UPDATE entities SET is_active = 0 WHERE entity_id=?', (entity_id,))
        c.execute('DELETE FROM tag_index WHERE entity_id=?', (entity_id,))
        c.execute('DELETE FROM references_map WHERE source_id=? OR target_id=?', (entity_id, entity_id))
        remove_entity_fts(db, entity_id)
        db.commit()
        vector_task = _schedule_vector_task(db, [entity_id], operation='delete')
        log_event(db, 'entity.delete', f'Entity {entity_id} deleted')
        return {
            'message': 'delete success',
            'entity_id': entity_id,
            'vector_indexed': bool(vector_task and vector_task['status'] == 'completed'),
            'vector_task_id': vector_task['id'] if vector_task else None,
        }
    except Exception as e:
        db.rollback(); log.error('Entity delete: %s', e)
        raise HTTPException(500, 'Entity deletion failed')
    finally: db.close()
