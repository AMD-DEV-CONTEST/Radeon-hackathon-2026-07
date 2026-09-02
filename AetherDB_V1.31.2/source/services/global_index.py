# -*- coding: utf-8 -*-
"""Global Index: cross-database search index and sync management.

V1.21 Phase 3+4: Global FTS5 index, entity/relation/timeline sync.
"""
import sqlite3, os, json, logging
from typing import Optional, List

log = logging.getLogger(__name__)

def _get_registry():
    from services.database_registry import REGISTRY_PATH
    conn = sqlite3.connect(REGISTRY_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ── Init ────────────────────────────────────────────────────────────────────

def init_global_index():
    """Ensure all global index tables exist.
    Called automatically by init_registry() via SCHEMA_SQL.
    """
    pass  # Tables are created by init_registry() in database_registry.py

# ── Rebuild ─────────────────────────────────────────────────────────────────

def rebuild_all() -> dict:
    """Rebuild global index from ALL registered databases."""
    from services.database_registry import list_databases
    dbs = list_databases()
    total = {"entities": 0, "relations": 0, "timeline": 0, "errors": 0}
    for db in dbs:
        try:
            result = rebuild_database(db["database_id"])
            for k in total:
                if k != "errors":
                    total[k] += result.get(k, 0)
        except Exception as e:
            log.error("Rebuild failed for %s: %s", db["database_id"], e)
            total["errors"] += 1
    return total

def rebuild_database(database_id: str) -> dict:
    """Rebuild global index for ONE database. Reads source data, writes to registry."""
    from services.db import get_db
    from services.database_registry import REGISTRY_PATH
    biz = get_db(database_id)
    reg = sqlite3.connect(REGISTRY_PATH)
    try:
        # Clear existing index for this database
        reg.execute("DELETE FROM entities_global_index WHERE database_id = ?", (database_id,))
        reg.execute("DELETE FROM relations_global_index WHERE database_id = ?", (database_id,))
        reg.execute("DELETE FROM timeline_global_index WHERE database_id = ?", (database_id,))
        reg.execute("DELETE FROM fts_global WHERE database_id = ?", (database_id,))

        # Books
        books = biz.execute("SELECT * FROM books").fetchall()
        for book in books:
            global_book_id = database_id + ":" + book["book_id"]
            reg.execute("""
                INSERT OR REPLACE INTO books_global
                (global_book_id, database_id, book_id, title, author, description)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (global_book_id, database_id, book["book_id"], book["title"],
                  book["author"] or "", book["description"] or ""))

        # Entities
        entities = biz.execute("SELECT * FROM entities WHERE is_active = 1").fetchall()
        for ent in entities:
            bid = ent["book_id"] or "default"
            gid = database_id + ":" + bid + ":" + ent["entity_id"]
            tags = json.dumps(json.loads(ent["tags"] or "[]"), ensure_ascii=False)
            reg.execute("""
                INSERT INTO entities_global_index
                (global_id, database_id, book_id, entity_id, entity_type, title,
                 content_preview, ai_summary, tags, importance, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (gid, database_id, bid, ent["entity_id"], ent["entity_type"],
                  ent["title"], (ent["content"] or "")[:200],
                  ent["ai_summary"] or "", tags, ent["importance"]))
            # FTS5
            try:
                reg.execute("""
                    INSERT INTO fts_global(global_id, database_id, book_id, entity_id,
                        entity_type, title, content_preview, ai_summary, tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (gid, database_id, bid, ent["entity_id"], ent["entity_type"],
                      ent["title"], (ent["content"] or "")[:200],
                      ent["ai_summary"] or "", tags))
            except Exception as fts_err:
                log.warning("FTS insert failed for %s: %s", gid, fts_err)

        # Relations
        relations = biz.execute("SELECT * FROM relations").fetchall()
        for rel in relations:
            bid = rel["book_id"] or "default"
            grel_id = database_id + ":" + bid + ":" + str(rel["id"])
            reg.execute("""
                INSERT INTO relations_global_index
                (global_relation_id, database_id, book_id, source_entity_id,
                 target_entity_id, relation_type, description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (grel_id, database_id, bid, rel["source_id"],
                  rel["target_id"], rel["relation_type"], rel["description"] or ""))

        # Timeline events
        events = biz.execute("SELECT * FROM timeline_events").fetchall()
        for evt in events:
            bid = evt["book_id"] or "default"
            gevt_id = database_id + ":" + bid + ":" + str(evt["id"])
            reg.execute("""
                INSERT INTO timeline_global_index
                (global_event_id, database_id, book_id, event_id, title,
                 description, timeline_year, timeline_era)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (gevt_id, database_id, bid, str(evt["id"]), evt["title"] or "",
                  evt["description"] or "", evt["year"], evt["era"] or ""))

        # Update sync status
        reg.execute("""
            INSERT OR REPLACE INTO sync_status
            (database_id, status, last_full_sync_at, updated_at)
            VALUES (?, 'clean', datetime("now"), datetime("now"))
        """, (database_id,))

        reg.commit()
        return {"entities": len(entities), "relations": len(relations),
                "timeline": len(events), "errors": 0}
    except Exception as e:
        reg.rollback()
        raise
    finally:
        biz.close()
        reg.close()

# ── Search ──────────────────────────────────────────────────────────────────

def search_global(query: str, scope: str = "all",
                  database_id: str = None, book_id: str = None,
                  limit: int = 20) -> list:
    """Cross-database FTS5 search.
    scope: all | database | book
    """
    reg = _get_registry()
    try:
        safe = query.replace('"', '""')
        sql = ("SELECT global_id, database_id, book_id, entity_id, entity_type, "
               "title, content_preview FROM fts_global WHERE fts_global MATCH ?")
        params = ['"' + safe + '"']

        if scope == "database" and database_id:
            sql += " AND database_id = ?"
            params.append(database_id)
        elif scope == "book" and database_id and book_id:
            sql += " AND database_id = ? AND book_id = ?"
            params.extend([database_id, book_id])

        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        results = []
        for row in reg.execute(sql, params).fetchall():
            results.append({
                "global_id": row[0],
                "database_id": row[1],
                "book_id": row[2],
                "entity_id": row[3],
                "entity_type": row[4],
                "title": row[5],
                "snippet": (row[6] or "")[:200],
                "source": "fts_global"
            })
        return results
    finally:
        reg.close()

# ── Sync Status ─────────────────────────────────────────────────────────────

def get_sync_status(database_id: str = None) -> list:
    """Get sync status for one or all databases."""
    reg = _get_registry()
    try:
        if database_id:
            rows = reg.execute(
                "SELECT * FROM sync_status WHERE database_id = ?",
                (database_id,)).fetchall()
        else:
            rows = reg.execute("SELECT * FROM sync_status").fetchall()
        return [dict(r) for r in rows]
    finally:
        reg.close()

def mark_database_dirty(database_id: str, reason: str = ""):
    """Mark a database's global index as stale."""
    reg = _get_registry()
    try:
        reg.execute("""
            INSERT OR REPLACE INTO sync_status
            (database_id, status, dirty_reason, updated_at)
            VALUES (?, 'stale', ?, datetime("now"))
        """, (database_id, reason))
        reg.commit()
    finally:
        reg.close()

def get_entity_count(database_id: str = None) -> int:
    """Count indexed entities, optionally filtered by database."""
    reg = _get_registry()
    try:
        if database_id:
            row = reg.execute(
                "SELECT COUNT(*) FROM entities_global_index WHERE database_id = ?",
                (database_id,)).fetchone()
        else:
            row = reg.execute("SELECT COUNT(*) FROM entities_global_index").fetchone()
        return row[0] if row else 0
    finally:
        reg.close()