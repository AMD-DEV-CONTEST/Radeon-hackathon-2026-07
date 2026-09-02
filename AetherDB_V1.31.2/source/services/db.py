import sqlite3
import threading
import asyncio
from typing import Any, List, Optional, Tuple
from app.config import ENTITY_PREFIXES

_local = threading.local()

def get_connection(db_path="novel_world_zh.db"):
    """Thread-local pooled connection with auto-reconnect.
    
    Safe for sync endpoints (FastAPI runs them in thread pool).
    If an endpoint closes the connection, it will be re-opened on next access.
    """
    conn = getattr(_local, "conn", None)
    
    # Check if existing connection is still alive
    if conn is not None and getattr(_local, "db_path", None) != db_path:
        conn.close()
        conn = None
    if conn is not None:
        try:
            conn.execute("SELECT 1")
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            conn = None
    
    if conn is None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA cache_size=-8000")
        _local.conn = conn
        _local.db_path = db_path
    
    return conn

def close_connection():
    """Close the thread-local connection. Call on app shutdown."""
    conn = getattr(_local, "conn", None)
    if conn:
        try:
            conn.close()
        except Exception:
            pass
        _local.conn = None
        _local.db_path = None

async def db_execute(sql: str, params: tuple = None, fetchone: bool = False,
                     fetchall: bool = True, commit: bool = False,
                     db_path: str = "novel_world_zh.db") -> Any:
    """Execute a DB query in a thread pool. Non-blocking for async endpoints."""
    def _run():
        conn = get_connection(db_path)
        c = conn.cursor()
        if params:
            c.execute(sql, params)
        else:
            c.execute(sql)
        if commit:
            conn.commit()
        if fetchone:
            return c.fetchone()
        if fetchall:
            return c.fetchall()
        return None
    return await asyncio.to_thread(_run)

async def db_execute_many(sql: str, params_list: List[tuple], db_path: str = "novel_world_zh.db"):
    """Execute multiple statements in a thread pool."""
    def _run():
        conn = get_connection(db_path)
        c = conn.cursor()
        c.executemany(sql, params_list)
        conn.commit()
    return await asyncio.to_thread(_run)


def add_book_filter(sql, params, book_id=None, table_alias="e"):
    """Add book_id WHERE clause to a SQL statement if book_id is provided.

    Args:
        sql: Original SQL string (may or may not have WHERE clause).
        params: List of query parameters (mutated in place).
        book_id: Optional book_id to filter by.
        table_alias: Table alias to prefix book_id with (default "e").

    Returns:
        Modified SQL string with AND book_id = ? appended.
    """
    if book_id:
        clause = " AND " + table_alias + ".book_id = ?"
        sql += clause
        params.append(book_id)
    return sql

# ── DB functions moved from main.py ─────────────────────────────
DB_PATH = "novel_world_zh.db"

def get_db(database_id=None):
    """Get DB connection for active or specified database.
    Supports multi-database via registry.
    """
    path = DB_PATH
    if database_id:
        from services.database_registry import get_db_path
        path = get_db_path(database_id)
    else:
        try:
            from services.database_registry import get_active_database_id
            from services.database_registry import get_db_path as _gdp
            path = _gdp(get_active_database_id())
        except Exception:
            path = DB_PATH
    conn = get_connection(path)
    conn.row_factory = sqlite3.Row
    stmts = "PRAGMA encoding='UTF-8';PRAGMA journal_mode=WAL;PRAGMA foreign_keys=ON;"
    conn.executescript(stmts)
    return conn


def generate_entity_id(entity_type, cursor):
    prefix = ENTITY_PREFIXES.get(entity_type, "GEN")
    cursor.execute(
        "INSERT INTO id_sequence (prefix, next_id) VALUES (?, 1) ON CONFLICT(prefix) DO UPDATE SET next_id = next_id + 1",
        (prefix,)
    )
    nid = cursor.execute("SELECT next_id FROM id_sequence WHERE prefix = ?", (prefix,)).fetchone()[0]
    return f"{prefix}_{nid:04d}"

def init_db(database_id=None):
    conn = get_db(database_id)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS id_sequence (
            prefix TEXT PRIMARY KEY,
            next_id INTEGER NOT NULL DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT DEFAULT '',
            full_content TEXT DEFAULT '',
            ai_summary TEXT DEFAULT '',
            tags TEXT DEFAULT '[]',
            timeline_year INTEGER,
            timeline_era TEXT,
            importance INTEGER DEFAULT 5,
            version INTEGER DEFAULT 1,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            book_id TEXT DEFAULT 'default'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            description TEXT DEFAULT '',
            book_id TEXT DEFAULT 'default',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (source_id) REFERENCES entities(entity_id),
            FOREIGN KEY (target_id) REFERENCES entities(entity_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tag_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            tag TEXT NOT NULL,
            book_id TEXT DEFAULT 'default',
            FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS entity_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            title TEXT,
            content TEXT,
            full_content TEXT,
            ai_summary TEXT,
            tags TEXT,
            importance INTEGER,
            archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            book_id TEXT DEFAULT 'default',
            FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS references_map (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            book_id TEXT DEFAULT 'default',
            FOREIGN KEY (source_id) REFERENCES entities(entity_id),
            FOREIGN KEY (target_id) REFERENCES entities(entity_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS timeline_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT,
            year INTEGER,
            era TEXT,
            title TEXT,
            description TEXT,
            importance INTEGER DEFAULT 5,
            book_id TEXT DEFAULT 'default',
            FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
        )
    """)

    cursor.execute("""CREATE TABLE IF NOT EXISTS timelines (
        id TEXT PRIMARY KEY,
        book_id TEXT NOT NULL,
        name TEXT NOT NULL,
        parent_timeline_id TEXT,
        divergence_anchor_id TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        is_default INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(parent_timeline_id) REFERENCES timelines(id)
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS temporal_anchors (
        id TEXT PRIMARY KEY,
        book_id TEXT NOT NULL,
        timeline_id TEXT NOT NULL,
        branch_id TEXT,
        anchor_type TEXT NOT NULL,
        label TEXT NOT NULL,
        chapter_id TEXT,
        event_id TEXT,
        phase_id TEXT,
        absolute_time TEXT,
        order_hint REAL,
        confidence TEXT NOT NULL DEFAULT 'confirmed',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(timeline_id) REFERENCES timelines(id),
        FOREIGN KEY(chapter_id) REFERENCES chapters(chapter_id)
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS temporal_relations (
        id TEXT PRIMARY KEY,
        book_id TEXT NOT NULL,
        timeline_id TEXT NOT NULL,
        branch_id TEXT,
        source_anchor_id TEXT NOT NULL,
        relation_type TEXT NOT NULL,
        target_anchor_id TEXT NOT NULL,
        confidence TEXT NOT NULL DEFAULT 'confirmed',
        source_chapter_id TEXT,
        review_status TEXT NOT NULL DEFAULT 'accepted',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(timeline_id) REFERENCES timelines(id),
        FOREIGN KEY(source_anchor_id) REFERENCES temporal_anchors(id),
        FOREIGN KEY(target_anchor_id) REFERENCES temporal_anchors(id),
        FOREIGN KEY(source_chapter_id) REFERENCES chapters(chapter_id),
        UNIQUE(timeline_id, branch_id, source_anchor_id, relation_type, target_anchor_id)
    )""")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_temporal_anchors_scope ON temporal_anchors(book_id,timeline_id,branch_id,order_hint)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_temporal_relations_scope ON temporal_relations(book_id,timeline_id,branch_id,source_anchor_id,target_anchor_id)")
    cursor.execute("""CREATE TABLE IF NOT EXISTS chapter_temporal_contexts (
        chapter_id TEXT PRIMARY KEY,
        book_id TEXT NOT NULL,
        timeline_id TEXT NOT NULL,
        branch_id TEXT,
        anchor_id TEXT,
        phase_id TEXT,
        viewpoint_entity_id TEXT,
        include_future_knowledge INTEGER NOT NULL DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(chapter_id) REFERENCES chapters(chapter_id),
        FOREIGN KEY(timeline_id) REFERENCES timelines(id),
        FOREIGN KEY(anchor_id) REFERENCES temporal_anchors(id),
        FOREIGN KEY(viewpoint_entity_id) REFERENCES entities(entity_id)
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS entity_state_segments (
        id TEXT PRIMARY KEY,
        book_id TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        timeline_id TEXT NOT NULL,
        branch_id TEXT,
        valid_from_anchor_id TEXT,
        valid_to_anchor_id TEXT,
        state_type TEXT NOT NULL,
        state_payload_json TEXT NOT NULL,
        source_chapter_id TEXT,
        source_event_id TEXT,
        confidence TEXT NOT NULL DEFAULT 'confirmed',
        superseded_by TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(entity_id) REFERENCES entities(entity_id),
        FOREIGN KEY(timeline_id) REFERENCES timelines(id),
        FOREIGN KEY(valid_from_anchor_id) REFERENCES temporal_anchors(id),
        FOREIGN KEY(valid_to_anchor_id) REFERENCES temporal_anchors(id),
        FOREIGN KEY(source_chapter_id) REFERENCES chapters(chapter_id),
        FOREIGN KEY(superseded_by) REFERENCES entity_state_segments(id)
    )""")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_entity_state_scope ON entity_state_segments(book_id,entity_id,timeline_id,branch_id,state_type)")
    cursor.execute("""CREATE TABLE IF NOT EXISTS temporal_event_metadata (
        event_id TEXT PRIMARY KEY,
        book_id TEXT NOT NULL,
        timeline_id TEXT NOT NULL,
        branch_id TEXT,
        world_anchor_id TEXT,
        subjective_sequence REAL,
        viewpoint_entity_id TEXT,
        causal_parent_event_id TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(timeline_id) REFERENCES timelines(id),
        FOREIGN KEY(world_anchor_id) REFERENCES temporal_anchors(id),
        FOREIGN KEY(viewpoint_entity_id) REFERENCES entities(entity_id)
    )""")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_entity_type ON entities(entity_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_entity_tags ON entities(tags)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_relation_source ON relations(source_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_relation_target ON relations(target_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tag_entity ON tag_index(entity_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tag_name ON tag_index(tag)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_entity_version ON entity_versions(entity_id)")
    # === V1.1.5-V1.2.0 Migration: book_id + entity_translations + FTS5 ===
    book_migrations = {
        "entities": (
            "ALTER TABLE entities ADD COLUMN book_id TEXT DEFAULT 'default'",
            "CREATE INDEX IF NOT EXISTS idx_entities_book ON entities(book_id)",
        ),
        "relations": (
            "ALTER TABLE relations ADD COLUMN book_id TEXT DEFAULT 'default'",
            "CREATE INDEX IF NOT EXISTS idx_relations_book ON relations(book_id)",
        ),
        "tag_index": (
            "ALTER TABLE tag_index ADD COLUMN book_id TEXT DEFAULT 'default'",
            "CREATE INDEX IF NOT EXISTS idx_tag_index_book ON tag_index(book_id)",
        ),
        "entity_versions": (
            "ALTER TABLE entity_versions ADD COLUMN book_id TEXT DEFAULT 'default'",
            "CREATE INDEX IF NOT EXISTS idx_entity_versions_book ON entity_versions(book_id)",
        ),
        "references_map": (
            "ALTER TABLE references_map ADD COLUMN book_id TEXT DEFAULT 'default'",
            "CREATE INDEX IF NOT EXISTS idx_references_map_book ON references_map(book_id)",
        ),
        "timeline_events": (
            "ALTER TABLE timeline_events ADD COLUMN book_id TEXT DEFAULT 'default'",
            "CREATE INDEX IF NOT EXISTS idx_timeline_events_book ON timeline_events(book_id)",
        ),
    "chapter_versions": (
        "ALTER TABLE chapter_versions ADD COLUMN book_id TEXT DEFAULT 'default'",
        "CREATE INDEX IF NOT EXISTS idx_chapter_versions_book ON chapter_versions(book_id)",
    ),
    "prompt_profiles": (
        "ALTER TABLE prompt_profiles ADD COLUMN book_id TEXT DEFAULT 'default'",
        "CREATE INDEX IF NOT EXISTS idx_prompt_profiles_book ON prompt_profiles(book_id)",
    ),
}
    for alter_sql, index_sql in book_migrations.values():
        try:
            cursor.execute(alter_sql)
            cursor.execute(index_sql)
        except:
            pass
    cursor.execute("CREATE TABLE IF NOT EXISTS entity_translations ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id TEXT NOT NULL, "
        "language TEXT NOT NULL, title TEXT NOT NULL, "
        "content TEXT, full_content TEXT, ai_summary TEXT, book_id TEXT, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE(entity_id, language))")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_et_entity ON entity_translations(entity_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_et_lang ON entity_translations(language)")
    cursor.execute("CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5("
        "entity_id UNINDEXED, title, content, full_content, "
        "tokenize='unicode61 remove_diacritics 2')")

    # V1.21: books table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS books (
            book_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            author TEXT DEFAULT '',
            description TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT DEFAULT '{}'
        )
    """)
    existing = cursor.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    if existing == 0:
        cursor.execute("INSERT OR IGNORE INTO books (book_id, title) VALUES ('default', '默认作品')")


    cursor.execute("""CREATE TABLE IF NOT EXISTS prompt_profiles (
        profile_id TEXT PRIMARY KEY, name TEXT NOT NULL,
        book_id TEXT DEFAULT 'default',
        description TEXT DEFAULT '', scope_type TEXT NOT NULL DEFAULT 'global',
        scope_id TEXT DEFAULT '', task_type TEXT DEFAULT 'all',
        content TEXT NOT NULL, is_active INTEGER DEFAULT 1,
        is_builtin INTEGER DEFAULT 0, version INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS prompt_profile_versions (
        version_id INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id TEXT NOT NULL, version INTEGER NOT NULL,
        content TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS volumes (
        volume_id TEXT, book_id TEXT NOT NULL,
        title TEXT NOT NULL, volume_index INTEGER DEFAULT 0,
        description TEXT DEFAULT '', status TEXT DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (volume_id, book_id)
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS chapters (
        chapter_id TEXT PRIMARY KEY, book_id TEXT NOT NULL,
        volume_id TEXT, chapter_index INTEGER DEFAULT 0,
        title TEXT NOT NULL, content TEXT DEFAULT '',
        word_count INTEGER DEFAULT 0, status TEXT DEFAULT 'draft',
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_analyzed_at TIMESTAMP, analysis_status TEXT DEFAULT 'none'
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS chapter_versions (
        version_id INTEGER PRIMARY KEY AUTOINCREMENT,
        chapter_id TEXT NOT NULL, version INTEGER NOT NULL,
        title TEXT, content TEXT DEFAULT '',
        word_count INTEGER DEFAULT 0, book_id TEXT DEFAULT 'default', saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS chapter_analyses (
        analysis_id TEXT PRIMARY KEY, chapter_id TEXT NOT NULL,
        book_id TEXT NOT NULL, summary TEXT DEFAULT '',
        appearing_entities_json TEXT DEFAULT '[]',
        new_facts_json TEXT DEFAULT '[]',
        relation_changes_json TEXT DEFAULT '[]',
        timeline_events_json TEXT DEFAULT '[]',
        conflicts_json TEXT DEFAULT '[]',
        emotion_tone TEXT DEFAULT '', plot_function TEXT DEFAULT '',
        raw_response TEXT DEFAULT '', model TEXT DEFAULT '',
        prompt_profile_id TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS import_changesets (
        changeset_id TEXT PRIMARY KEY, book_id TEXT NOT NULL,
        source_type TEXT DEFAULT 'chapter', source_chapter_id TEXT DEFAULT '',
        entities_json TEXT DEFAULT '[]', relations_json TEXT DEFAULT '[]',
        warnings_json TEXT DEFAULT '[]', conflicts_json TEXT DEFAULT '[]',
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        confirmed_at TIMESTAMP
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS import_task_receipts (
        task_id TEXT PRIMARY KEY,
        mode TEXT NOT NULL,
        result_json TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS chapter_chunks (
        chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
        chapter_id TEXT NOT NULL, chunk_index INTEGER DEFAULT 0,
        chunk_text TEXT NOT NULL, chunk_type TEXT DEFAULT 'content',
        is_in_rag INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    localization_database_id = database_id
    if not localization_database_id:
        try:
            from services.database_registry import get_active_database_id
            localization_database_id = get_active_database_id()
        except Exception:
            localization_database_id = "default"
    from services.chapter_localization import initialize_chapter_localization_schema
    initialize_chapter_localization_schema(
        conn,
        database_id=localization_database_id,
    )
    from services.translation_service import initialize_translation_schema
    initialize_translation_schema(
        conn,
        database_id=localization_database_id,
    )

    cursor.execute("""CREATE TABLE IF NOT EXISTS context_tasks (
        task_id TEXT PRIMARY KEY,
        database_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        task_type TEXT NOT NULL,
        owner_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'candidates_ready',
        profile_json TEXT NOT NULL DEFAULT '{}',
        temporal_context_json TEXT NOT NULL DEFAULT '{}',
        expires_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    context_task_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info(context_tasks)").fetchall()
    }
    if "temporal_context_json" not in context_task_columns:
        cursor.execute("ALTER TABLE context_tasks ADD COLUMN temporal_context_json TEXT NOT NULL DEFAULT '{}'")
    if "expires_at" not in context_task_columns:
        cursor.execute("ALTER TABLE context_tasks ADD COLUMN expires_at TIMESTAMP")
    cursor.execute(
        "UPDATE context_tasks SET expires_at=datetime('now','+24 hours') WHERE expires_at IS NULL"
    )
    cursor.execute("""CREATE TABLE IF NOT EXISTS context_candidates (
        candidate_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        database_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        source_type TEXT NOT NULL,
        source_id TEXT NOT NULL,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        relevance_score REAL NOT NULL DEFAULT 0,
        confidence REAL NOT NULL DEFAULT 0,
        priority INTEGER NOT NULL DEFAULT 2,
        estimated_tokens INTEGER NOT NULL DEFAULT 0,
        contains_raw_text INTEGER NOT NULL DEFAULT 0,
        risk_flags_json TEXT NOT NULL DEFAULT '[]',
        content_snapshot TEXT NOT NULL DEFAULT '',
        source_hash TEXT NOT NULL,
        approved INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(task_id, source_type, source_id)
    )""")
    context_candidate_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info(context_candidates)").fetchall()
    }
    if "priority" not in context_candidate_columns:
        cursor.execute("ALTER TABLE context_candidates ADD COLUMN priority INTEGER NOT NULL DEFAULT 2")
    if "modality" not in context_candidate_columns:
        cursor.execute("ALTER TABLE context_candidates ADD COLUMN modality TEXT NOT NULL DEFAULT 'text'")
    if "metadata_json" not in context_candidate_columns:
        cursor.execute("ALTER TABLE context_candidates ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_context_candidates_task ON context_candidates(task_id, approved)")
    cursor.execute("""CREATE TABLE IF NOT EXISTS context_approvals (
        approval_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        candidate_id TEXT NOT NULL,
        approved INTEGER NOT NULL,
        approved_by TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(task_id, candidate_id)
    )""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS audit_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        event_type TEXT NOT NULL,
        action TEXT DEFAULT "",
        target TEXT DEFAULT "",
        database_id TEXT DEFAULT "",
        book_id TEXT DEFAULT "",
        success INTEGER DEFAULT 1,
        description TEXT NOT NULL,
        details TEXT DEFAULT "",
        severity TEXT DEFAULT "info",
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    # V1.31.2 MM-01: per-database media metadata. Binary payloads are kept in the
    # registered database runtime directory and only relative paths are stored.
    cursor.execute("""CREATE TABLE IF NOT EXISTS media_assets (
        asset_id TEXT PRIMARY KEY,
        database_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        modality TEXT NOT NULL CHECK(modality IN ('image','audio','video')),
        mime_type TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        original_filename TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        file_size_bytes INTEGER NOT NULL CHECK(file_size_bytes > 0),
        source_type TEXT NOT NULL CHECK(source_type IN ('imported','generated','captured','derived')),
        lifecycle_status TEXT NOT NULL DEFAULT 'temporary'
            CHECK(lifecycle_status IN ('temporary','pending_review','approved','archived','soft_deleted','rejected')),
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_by_task_id TEXT,
        approved_at TIMESTAMP,
        archived_at TIMESTAMP,
        deleted_at TIMESTAMP,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(book_id) REFERENCES books(book_id) ON DELETE RESTRICT
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_assets_scope "
        "ON media_assets(database_id,book_id,lifecycle_status,modality,created_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_assets_hash "
        "ON media_assets(database_id,content_hash)"
    )
    cursor.execute("""CREATE TABLE IF NOT EXISTS media_asset_versions (
        version_id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL,
        database_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        version_number INTEGER NOT NULL CHECK(version_number > 0),
        mime_type TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        file_size_bytes INTEGER NOT NULL CHECK(file_size_bytes > 0),
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(asset_id,version_number),
        FOREIGN KEY(asset_id) REFERENCES media_assets(asset_id) ON DELETE CASCADE
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_versions_scope "
        "ON media_asset_versions(database_id,book_id,asset_id,version_number)"
    )
    cursor.execute("""CREATE TABLE IF NOT EXISTS media_asset_derivatives (
        derivative_id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL,
        source_version_id TEXT,
        database_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        derivative_type TEXT NOT NULL,
        mime_type TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        file_size_bytes INTEGER NOT NULL CHECK(file_size_bytes > 0),
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_by_task_id TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(asset_id) REFERENCES media_assets(asset_id) ON DELETE CASCADE,
        FOREIGN KEY(source_version_id) REFERENCES media_asset_versions(version_id) ON DELETE SET NULL
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_derivatives_scope "
        "ON media_asset_derivatives(database_id,book_id,asset_id,derivative_type)"
    )
    cursor.execute("""CREATE TABLE IF NOT EXISTS media_annotations (
        annotation_id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL,
        version_id TEXT,
        database_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        annotation_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        source_type TEXT NOT NULL DEFAULT 'manual'
            CHECK(source_type IN ('manual','model','imported')),
        approval_status TEXT NOT NULL DEFAULT 'pending'
            CHECK(approval_status IN ('pending','approved','rejected')),
        model_profile_id TEXT,
        source_task_id TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(asset_id) REFERENCES media_assets(asset_id) ON DELETE CASCADE,
        FOREIGN KEY(version_id) REFERENCES media_asset_versions(version_id) ON DELETE SET NULL
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_annotations_scope "
        "ON media_annotations(database_id,book_id,asset_id,approval_status)"
    )
    media_annotation_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info(media_annotations)").fetchall()
    }
    if "language_code" not in media_annotation_columns:
        cursor.execute(
            "ALTER TABLE media_annotations "
            "ADD COLUMN language_code TEXT NOT NULL DEFAULT 'und'"
        )
    if "source_revision_hash" not in media_annotation_columns:
        cursor.execute(
            "ALTER TABLE media_annotations "
            "ADD COLUMN source_revision_hash TEXT NOT NULL DEFAULT ''"
        )
    if "is_stale" not in media_annotation_columns:
        cursor.execute(
            "ALTER TABLE media_annotations "
            "ADD COLUMN is_stale INTEGER NOT NULL DEFAULT 0 CHECK(is_stale IN (0,1))"
        )
    cursor.execute(
        """UPDATE media_annotations
              SET version_id=COALESCE(
                    version_id,
                    (
                        SELECT v.version_id
                          FROM media_asset_versions v
                         WHERE v.asset_id=media_annotations.asset_id
                         ORDER BY v.version_number DESC
                         LIMIT 1
                    )
                  ),
                  source_revision_hash=CASE
                    WHEN source_revision_hash='' THEN COALESCE(
                        (
                            SELECT v.content_hash
                              FROM media_asset_versions v
                             WHERE v.version_id=COALESCE(
                                media_annotations.version_id,
                                (
                                    SELECT latest.version_id
                                      FROM media_asset_versions latest
                                     WHERE latest.asset_id=media_annotations.asset_id
                                     ORDER BY latest.version_number DESC
                                     LIMIT 1
                                )
                             )
                        ),
                        ''
                    )
                    ELSE source_revision_hash
                  END"""
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_annotations_language "
        "ON media_annotations(database_id,book_id,asset_id,language_code,approval_status,is_stale)"
    )
    cursor.execute("""CREATE TABLE IF NOT EXISTS media_asset_bindings (
        binding_id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL,
        database_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        target_type TEXT NOT NULL,
        target_id TEXT NOT NULL,
        binding_type TEXT NOT NULL,
        timeline_id TEXT,
        branch_id TEXT,
        valid_from_anchor_id TEXT,
        valid_to_anchor_id TEXT,
        entity_state_segment_id TEXT,
        sort_order INTEGER NOT NULL DEFAULT 0,
        notes TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(asset_id,target_type,target_id,binding_type,timeline_id,branch_id),
        FOREIGN KEY(asset_id) REFERENCES media_assets(asset_id) ON DELETE RESTRICT,
        FOREIGN KEY(timeline_id) REFERENCES timelines(id) ON DELETE RESTRICT,
        FOREIGN KEY(valid_from_anchor_id) REFERENCES temporal_anchors(id) ON DELETE RESTRICT,
        FOREIGN KEY(valid_to_anchor_id) REFERENCES temporal_anchors(id) ON DELETE RESTRICT,
        FOREIGN KEY(entity_state_segment_id) REFERENCES entity_state_segments(id) ON DELETE RESTRICT
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_bindings_scope "
        "ON media_asset_bindings(database_id,book_id,target_type,target_id,sort_order)"
    )
    media_binding_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info(media_asset_bindings)").fetchall()
    }
    if "language_code" not in media_binding_columns:
        cursor.execute("ALTER TABLE media_asset_bindings ADD COLUMN language_code TEXT")
    cursor.execute(
        """UPDATE media_asset_bindings
              SET language_code=(
                    SELECT l.language_code
                      FROM chapter_localizations l
                     WHERE l.chapter_id=media_asset_bindings.target_id
                  )
            WHERE target_type='chapter' AND language_code IS NULL"""
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_bindings_language_scope "
        "ON media_asset_bindings("
        "database_id,book_id,target_type,target_id,language_code,sort_order"
        ")"
    )
    cursor.execute("""CREATE TABLE IF NOT EXISTS media_vector_records (
        vector_id INTEGER PRIMARY KEY AUTOINCREMENT,
        asset_id TEXT NOT NULL,
        version_id TEXT NOT NULL,
        database_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        channel TEXT NOT NULL CHECK(channel IN ('visual','caption')),
        vector_space_id TEXT NOT NULL,
        model_id TEXT NOT NULL,
        model_revision TEXT NOT NULL,
        source_hash TEXT NOT NULL,
        source_annotation_ids_json TEXT NOT NULL DEFAULT '[]',
        dimensions INTEGER NOT NULL CHECK(dimensions IN (512,1024)),
        normalized INTEGER NOT NULL DEFAULT 1 CHECK(normalized IN (0,1)),
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(asset_id,version_id,channel,vector_space_id),
        FOREIGN KEY(asset_id) REFERENCES media_assets(asset_id) ON DELETE CASCADE,
        FOREIGN KEY(version_id) REFERENCES media_asset_versions(version_id) ON DELETE CASCADE
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_vectors_scope "
        "ON media_vector_records(database_id,book_id,channel,vector_space_id,asset_id)"
    )
    cursor.execute("""CREATE TABLE IF NOT EXISTS media_generation_tasks (
        task_id TEXT PRIMARY KEY,
        database_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        operation TEXT NOT NULL
            CHECK(operation IN ('image.generate','image.img2img','image.enhance')),
        status TEXT NOT NULL DEFAULT 'queued'
            CHECK(status IN (
                'queued','running','cancelling','completed','failed','cancelled'
            )),
        target_kind TEXT NOT NULL
            CHECK(target_kind IN ('native_package','external_provider')),
        package_id TEXT,
        model_profile_id TEXT,
        provider_id TEXT,
        provider_model_name TEXT,
        prompt TEXT NOT NULL,
        prompt_hash TEXT NOT NULL,
        negative_prompt TEXT NOT NULL DEFAULT '',
        parameters_json TEXT NOT NULL DEFAULT '{}',
        seed INTEGER NOT NULL CHECK(seed >= 0),
        source_asset_id TEXT,
        output_asset_id TEXT,
        requested_backend TEXT NOT NULL DEFAULT 'auto',
        effective_backend TEXT,
        device_id TEXT,
        runtime_job_id TEXT,
        progress REAL NOT NULL DEFAULT 0 CHECK(progress >= 0 AND progress <= 1),
        cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1)),
        allow_cloud_upload INTEGER NOT NULL DEFAULT 0 CHECK(allow_cloud_upload IN (0,1)),
        retry_of TEXT,
        error_code TEXT,
        error_message TEXT,
        elapsed_ms REAL,
        output_hash TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        started_at TEXT,
        completed_at TEXT,
        CHECK(
            (target_kind='native_package' AND package_id IS NOT NULL)
            OR
            (target_kind='external_provider' AND model_profile_id IS NOT NULL)
        ),
        FOREIGN KEY(book_id) REFERENCES books(book_id) ON DELETE RESTRICT,
        FOREIGN KEY(source_asset_id) REFERENCES media_assets(asset_id) ON DELETE SET NULL,
        FOREIGN KEY(output_asset_id) REFERENCES media_assets(asset_id) ON DELETE SET NULL,
        FOREIGN KEY(retry_of) REFERENCES media_generation_tasks(task_id) ON DELETE SET NULL
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_generation_tasks_scope "
        "ON media_generation_tasks(database_id,book_id,status,created_at DESC)"
    )
    cursor.execute("""CREATE TABLE IF NOT EXISTS media_generation_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL,
        sequence INTEGER NOT NULL CHECK(sequence >= 0),
        event_type TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        UNIQUE(task_id,sequence),
        FOREIGN KEY(task_id) REFERENCES media_generation_tasks(task_id) ON DELETE CASCADE
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_generation_events_task "
        "ON media_generation_events(task_id,sequence)"
    )
    cursor.execute("""CREATE TABLE IF NOT EXISTS audio_voice_profiles (
        voice_profile_id TEXT PRIMARY KEY,
        database_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        name TEXT NOT NULL,
        locale TEXT NOT NULL DEFAULT 'und',
        voice_kind TEXT NOT NULL
            CHECK(voice_kind IN ('provider_voice','local_reference')),
        model_profile_id TEXT,
        provider_voice_name TEXT,
        reference_asset_id TEXT,
        consent_confirmed INTEGER NOT NULL DEFAULT 0 CHECK(consent_confirmed IN (0,1)),
        enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(book_id) REFERENCES books(book_id) ON DELETE RESTRICT,
        FOREIGN KEY(reference_asset_id) REFERENCES media_assets(asset_id) ON DELETE RESTRICT
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_audio_voice_profiles_scope "
        "ON audio_voice_profiles(database_id,book_id,enabled,name)"
    )
    audio_voice_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(audio_voice_profiles)").fetchall()
    }
    if "package_id" not in audio_voice_columns:
        cursor.execute("ALTER TABLE audio_voice_profiles ADD COLUMN package_id TEXT")
    if "package_voice_name" not in audio_voice_columns:
        cursor.execute(
            "ALTER TABLE audio_voice_profiles ADD COLUMN package_voice_name TEXT"
        )
    cursor.execute("""CREATE TABLE IF NOT EXISTS audio_tasks (
        task_id TEXT PRIMARY KEY,
        database_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        operation TEXT NOT NULL CHECK(operation IN (
            'audio.tts.chapter','audio.tts.segment','audio.asr.transcribe',
            'audio.preview','audio.enhance','audio.merge'
        )),
        required_capability TEXT NOT NULL CHECK(required_capability IN (
            'audio.tts','audio.asr','audio.preview','audio.enhance','audio.merge'
        )),
        status TEXT NOT NULL DEFAULT 'planned' CHECK(status IN (
            'planned','in_progress','pending_review','completed',
            'cancelled','failed','outdated'
        )),
        target_kind TEXT NOT NULL DEFAULT 'unresolved' CHECK(target_kind IN (
            'unresolved','native_package','external_provider'
        )),
        chapter_id TEXT,
        source_revision TEXT,
        source_text_hash TEXT,
        input_asset_ids_json TEXT NOT NULL DEFAULT '[]',
        voice_profile_id TEXT,
        model_profile_id TEXT,
        route_model_profile_id TEXT,
        package_id TEXT,
        requested_backend TEXT NOT NULL DEFAULT 'auto' CHECK(requested_backend IN (
            'auto','cpu','rocm_pytorch','cuda'
        )),
        effective_backend TEXT,
        runtime_job_id TEXT,
        output_asset_id TEXT,
        error_code TEXT,
        error_message TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        completed_at TEXT,
        CHECK(
            (target_kind='unresolved' AND model_profile_id IS NULL AND package_id IS NULL)
            OR (target_kind='external_provider' AND model_profile_id IS NOT NULL AND package_id IS NULL)
            OR (target_kind='native_package' AND package_id IS NOT NULL AND model_profile_id IS NULL)
        ),
        FOREIGN KEY(book_id) REFERENCES books(book_id) ON DELETE RESTRICT,
        FOREIGN KEY(chapter_id) REFERENCES chapters(chapter_id) ON DELETE SET NULL,
        FOREIGN KEY(voice_profile_id) REFERENCES audio_voice_profiles(voice_profile_id) ON DELETE RESTRICT,
        FOREIGN KEY(output_asset_id) REFERENCES media_assets(asset_id) ON DELETE SET NULL
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_audio_tasks_scope "
        "ON audio_tasks(database_id,book_id,status,created_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_audio_tasks_chapter "
        "ON audio_tasks(database_id,book_id,chapter_id,status)"
    )
    audio_task_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info(audio_tasks)").fetchall()
    }
    audio_task_additions = {
        "progress": "REAL NOT NULL DEFAULT 0",
        "cancel_requested": "INTEGER NOT NULL DEFAULT 0",
        "heartbeat_at": "TEXT",
        "execution_config_json": "TEXT NOT NULL DEFAULT '{}'",
        "dictionary_snapshot_json": "TEXT NOT NULL DEFAULT '[]'",
        "dictionary_hash": "TEXT",
        "normalization_version": (
            "TEXT NOT NULL DEFAULT 'aetherdb-tts-normalize-v1'"
        ),
        "model_package_version": "TEXT",
        "model_revision": "TEXT",
        "route_model_profile_id": "TEXT",
    }
    for column, declaration in audio_task_additions.items():
        if column not in audio_task_columns:
            cursor.execute(
                f"ALTER TABLE audio_tasks ADD COLUMN {column} {declaration}"
            )
    cursor.execute("""CREATE TABLE IF NOT EXISTS audio_task_segments (
        segment_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        segment_index INTEGER NOT NULL CHECK(segment_index >= 0),
        source_text TEXT NOT NULL,
        source_text_hash TEXT NOT NULL,
        char_start INTEGER NOT NULL CHECK(char_start >= 0),
        char_end INTEGER NOT NULL CHECK(char_end >= char_start),
        status TEXT NOT NULL DEFAULT 'planned' CHECK(status IN (
            'planned','completed','cancelled','failed','outdated'
        )),
        output_asset_id TEXT,
        duration_ms INTEGER CHECK(duration_ms IS NULL OR duration_ms >= 0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(task_id,segment_index),
        FOREIGN KEY(task_id) REFERENCES audio_tasks(task_id) ON DELETE CASCADE,
        FOREIGN KEY(output_asset_id) REFERENCES media_assets(asset_id) ON DELETE SET NULL
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_audio_segments_task "
        "ON audio_task_segments(task_id,segment_index)"
    )
    audio_segment_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(audio_task_segments)").fetchall()
    }
    audio_segment_additions = {
        "attempts": "INTEGER NOT NULL DEFAULT 0",
        "error_code": "TEXT",
        "error_message": "TEXT",
        "deterministic_key": "TEXT",
        "normalized_text_hash": "TEXT",
        "runtime_job_id": "TEXT",
        "effective_backend": "TEXT",
        "generated_at": "TEXT",
    }
    for column, declaration in audio_segment_additions.items():
        if column not in audio_segment_columns:
            cursor.execute(
                f"ALTER TABLE audio_task_segments ADD COLUMN {column} {declaration}"
            )
    cursor.execute("""CREATE TABLE IF NOT EXISTS audio_task_results (
        result_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        segment_id TEXT,
        result_type TEXT NOT NULL CHECK(result_type IN ('transcript','metadata')),
        content_text TEXT NOT NULL DEFAULT '',
        content_hash TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        approval_status TEXT NOT NULL DEFAULT 'pending_review' CHECK(approval_status IN (
            'pending_review','approved','rejected','outdated'
        )),
        created_at TEXT NOT NULL,
        reviewed_at TEXT,
        FOREIGN KEY(task_id) REFERENCES audio_tasks(task_id) ON DELETE CASCADE,
        FOREIGN KEY(segment_id) REFERENCES audio_task_segments(segment_id) ON DELETE SET NULL
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_audio_results_task "
        "ON audio_task_results(task_id,approval_status,created_at)"
    )
    cursor.execute("""CREATE TABLE IF NOT EXISTS audio_asset_outputs (
        output_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        segment_id TEXT,
        asset_id TEXT NOT NULL,
        output_kind TEXT NOT NULL CHECK(output_kind IN (
            'segment','preview','final','merged','enhanced'
        )),
        source_text_hash TEXT,
        source_revision TEXT,
        voice_profile_id TEXT,
        freshness TEXT NOT NULL DEFAULT 'current' CHECK(freshness IN (
            'current','outdated'
        )),
        created_at TEXT NOT NULL,
        UNIQUE(task_id,asset_id,output_kind),
        FOREIGN KEY(task_id) REFERENCES audio_tasks(task_id) ON DELETE CASCADE,
        FOREIGN KEY(segment_id) REFERENCES audio_task_segments(segment_id) ON DELETE SET NULL,
        FOREIGN KEY(asset_id) REFERENCES media_assets(asset_id) ON DELETE CASCADE,
        FOREIGN KEY(voice_profile_id) REFERENCES audio_voice_profiles(voice_profile_id) ON DELETE SET NULL
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_audio_outputs_asset "
        "ON audio_asset_outputs(asset_id,freshness,created_at)"
    )
    cursor.execute("""CREATE TABLE IF NOT EXISTS audio_pronunciation_entries (
        entry_id TEXT PRIMARY KEY,
        database_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        locale TEXT NOT NULL,
        term TEXT NOT NULL,
        pronunciation TEXT NOT NULL,
        entry_kind TEXT NOT NULL DEFAULT 'replacement' CHECK(entry_kind IN (
            'replacement','kokoro_phoneme'
        )),
        enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(database_id,book_id,locale,term),
        FOREIGN KEY(book_id) REFERENCES books(book_id) ON DELETE CASCADE
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_audio_pronunciation_scope "
        "ON audio_pronunciation_entries(database_id,book_id,locale,enabled,term)"
    )
    cursor.execute("""CREATE TABLE IF NOT EXISTS audio_task_events (
        event_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        UNIQUE(task_id,sequence),
        FOREIGN KEY(task_id) REFERENCES audio_tasks(task_id) ON DELETE CASCADE
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_audio_task_events_task "
        "ON audio_task_events(task_id,sequence)"
    )
    cursor.execute("""CREATE TRIGGER IF NOT EXISTS trg_audio_chapter_content_outdated
        AFTER UPDATE OF content ON chapters
        WHEN OLD.content IS NOT NEW.content
        BEGIN
            UPDATE audio_tasks
               SET status='outdated',updated_at=CURRENT_TIMESTAMP
             WHERE chapter_id=NEW.chapter_id
               AND status NOT IN ('cancelled','failed','outdated');
            UPDATE audio_task_segments
               SET status='outdated',updated_at=CURRENT_TIMESTAMP
             WHERE task_id IN (
                SELECT task_id FROM audio_tasks WHERE chapter_id=NEW.chapter_id
             )
               AND status NOT IN ('cancelled','failed','outdated');
            UPDATE audio_task_results
               SET approval_status='outdated'
             WHERE task_id IN (
                SELECT task_id FROM audio_tasks WHERE chapter_id=NEW.chapter_id
             )
               AND approval_status != 'outdated';
            UPDATE audio_asset_outputs
               SET freshness='outdated'
             WHERE task_id IN (
                SELECT task_id FROM audio_tasks WHERE chapter_id=NEW.chapter_id
             );
        END""")
    conn.commit()
    conn.close()


def sync_entity_fts(conn, entity_id: str) -> None:
    """Sync one entity row into the entities_fts FTS5 index."""
    row = conn.execute(
        "SELECT rowid, entity_id, title, content, full_content "
        "FROM entities WHERE entity_id=?",
        (entity_id,),
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM entities_fts WHERE rowid=?", (row[0],))
    conn.execute(
        "INSERT INTO entities_fts (rowid, entity_id, title, content, full_content) "
        "VALUES (?,?,?,?,?)",
        (row[0], row[1], row[2] or "", row[3] or "", row[4] or ""),
    )


def remove_entity_fts(conn, entity_id: str) -> None:
    """Remove an entity from the entities_fts FTS5 index."""
    conn.execute(
        "DELETE FROM entities_fts WHERE rowid IN "
        "(SELECT rowid FROM entities WHERE entity_id=?)",
        (entity_id,),
    )


def rebuild_entity_fts(conn) -> int:
    """Rebuild the entities_fts FTS5 index from all active entities."""
    conn.execute("DELETE FROM entities_fts")
    rows = conn.execute(
        "SELECT rowid, entity_id, title, content, full_content "
        "FROM entities WHERE is_active=1"
    ).fetchall()
    for row in rows:
        conn.execute(
            "INSERT INTO entities_fts (rowid, entity_id, title, content, full_content) "
            "VALUES (?,?,?,?,?)",
            (row[0], row[1], row[2] or "", row[3] or "", row[4] or ""),
        )
    return len(rows)
