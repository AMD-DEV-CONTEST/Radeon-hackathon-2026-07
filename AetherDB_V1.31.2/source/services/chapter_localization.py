"""Language-neutral chapter identity and localization metadata."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from typing import Any


LANGUAGE_CODE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}$")
TRANSLATION_STATUSES = {
    "not_started",
    "draft",
    "generated",
    "review_required",
    "approved",
    "stale",
}


def normalize_language_code(value: str) -> str:
    raw = (value or "").strip()
    if len(raw) > 35 or not LANGUAGE_CODE_RE.fullmatch(raw):
        raise ValueError("language_code must be a bounded BCP-47 language tag")
    parts = raw.split("-")
    normalized = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            normalized.append(part.title())
        elif (len(part) == 2 and part.isalpha()) or (len(part) == 3 and part.isdigit()):
            normalized.append(part.upper())
        else:
            normalized.append(part.lower())
    return "-".join(normalized)


def chapter_content_hash(title: str | None, content: str | None) -> str:
    payload = json.dumps(
        {"title": title or "", "content": content or ""},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24].upper()
    return f"{prefix}_{digest}"


def new_content_group_id() -> str:
    return f"CG_{uuid.uuid4().hex[:24].upper()}"


def new_localization_id() -> str:
    return f"CL_{uuid.uuid4().hex[:24].upper()}"


def _book_source_language(cursor: sqlite3.Cursor, book_id: str) -> str:
    row = cursor.execute("SELECT metadata FROM books WHERE book_id=?", (book_id,)).fetchone()
    metadata: dict[str, Any] = {}
    if row and row["metadata"]:
        try:
            parsed = json.loads(row["metadata"])
            if isinstance(parsed, dict):
                metadata = parsed
        except (TypeError, ValueError):
            metadata = {}
    for key in ("source_language", "language_code", "default_language", "locale"):
        candidate = metadata.get(key)
        if isinstance(candidate, str):
            try:
                return normalize_language_code(candidate)
            except ValueError:
                continue
    return "zh-CN"


def initialize_chapter_localization_schema(
    connection: sqlite3.Connection,
    *,
    database_id: str,
) -> None:
    cursor = connection.cursor()
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS content_groups (
            content_group_id TEXT PRIMARY KEY,
            database_id TEXT NOT NULL,
            book_id TEXT NOT NULL,
            content_type TEXT NOT NULL DEFAULT 'chapter'
                CHECK(content_type='chapter'),
            canonical_order INTEGER NOT NULL DEFAULT 0,
            volume_id TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS chapter_localizations (
            localization_id TEXT PRIMARY KEY,
            content_group_id TEXT NOT NULL,
            chapter_id TEXT NOT NULL UNIQUE,
            language_code TEXT NOT NULL,
            is_source INTEGER NOT NULL DEFAULT 0 CHECK(is_source IN (0,1)),
            source_localization_id TEXT,
            content_revision INTEGER NOT NULL DEFAULT 1 CHECK(content_revision >= 1),
            content_hash TEXT NOT NULL,
            source_revision_hash TEXT NOT NULL,
            translation_status TEXT NOT NULL DEFAULT 'draft' CHECK(
                translation_status IN (
                    'not_started','draft','generated','review_required','approved','stale'
                )
            ),
            approval_status TEXT NOT NULL DEFAULT 'pending_review' CHECK(
                approval_status IN ('pending_review','approved','rejected','outdated')
            ),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(content_group_id,language_code),
            FOREIGN KEY(content_group_id) REFERENCES content_groups(content_group_id)
                ON DELETE CASCADE,
            FOREIGN KEY(chapter_id) REFERENCES chapters(chapter_id)
                ON DELETE CASCADE,
            FOREIGN KEY(source_localization_id) REFERENCES chapter_localizations(localization_id)
                ON DELETE RESTRICT
        )"""
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_chapter_localizations_one_source "
        "ON chapter_localizations(content_group_id) WHERE is_source=1"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_chapter_localizations_language "
        "ON chapter_localizations(language_code,content_group_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_content_groups_book_order "
        "ON content_groups(book_id,canonical_order,content_group_id)"
    )
    cursor.execute(
        """CREATE TRIGGER IF NOT EXISTS trg_localized_chapter_order_update
        AFTER UPDATE OF chapter_index,volume_id ON chapters
        WHEN EXISTS(
            SELECT 1 FROM chapter_localizations
             WHERE chapter_id=NEW.chapter_id AND is_source=1
        )
        BEGIN
            UPDATE chapters
               SET chapter_index=NEW.chapter_index,
                   volume_id=NEW.volume_id
             WHERE chapter_id IN (
                SELECT target.chapter_id
                  FROM chapter_localizations source
                  JOIN chapter_localizations target
                    ON target.content_group_id=source.content_group_id
                 WHERE source.chapter_id=NEW.chapter_id
                   AND target.chapter_id!=NEW.chapter_id
             );
            UPDATE content_groups
               SET canonical_order=NEW.chapter_index,
                   volume_id=NEW.volume_id,
                   updated_at=CURRENT_TIMESTAMP
             WHERE content_group_id=(
                SELECT content_group_id FROM chapter_localizations
                 WHERE chapter_id=NEW.chapter_id
             );
        END"""
    )
    cursor.execute(
        """CREATE TRIGGER IF NOT EXISTS trg_localized_temporal_context_insert
        AFTER INSERT ON chapter_temporal_contexts
        BEGIN
            INSERT INTO chapter_temporal_contexts(
                chapter_id,book_id,timeline_id,branch_id,anchor_id,phase_id,
                viewpoint_entity_id,include_future_knowledge,updated_at
            )
            SELECT target.chapter_id,NEW.book_id,NEW.timeline_id,NEW.branch_id,
                   NEW.anchor_id,NEW.phase_id,NEW.viewpoint_entity_id,
                   NEW.include_future_knowledge,NEW.updated_at
              FROM chapter_localizations source
              JOIN chapter_localizations target
                ON target.content_group_id=source.content_group_id
             WHERE source.chapter_id=NEW.chapter_id
               AND target.chapter_id!=NEW.chapter_id
            ON CONFLICT(chapter_id) DO UPDATE SET
                book_id=excluded.book_id,
                timeline_id=excluded.timeline_id,
                branch_id=excluded.branch_id,
                anchor_id=excluded.anchor_id,
                phase_id=excluded.phase_id,
                viewpoint_entity_id=excluded.viewpoint_entity_id,
                include_future_knowledge=excluded.include_future_knowledge,
                updated_at=excluded.updated_at;
        END"""
    )
    cursor.execute(
        """CREATE TRIGGER IF NOT EXISTS trg_localized_temporal_context_update
        AFTER UPDATE ON chapter_temporal_contexts
        WHEN OLD.book_id IS NOT NEW.book_id
          OR OLD.timeline_id IS NOT NEW.timeline_id
          OR OLD.branch_id IS NOT NEW.branch_id
          OR OLD.anchor_id IS NOT NEW.anchor_id
          OR OLD.phase_id IS NOT NEW.phase_id
          OR OLD.viewpoint_entity_id IS NOT NEW.viewpoint_entity_id
          OR OLD.include_future_knowledge IS NOT NEW.include_future_knowledge
        BEGIN
            UPDATE chapter_temporal_contexts
               SET book_id=NEW.book_id,
                   timeline_id=NEW.timeline_id,
                   branch_id=NEW.branch_id,
                   anchor_id=NEW.anchor_id,
                   phase_id=NEW.phase_id,
                   viewpoint_entity_id=NEW.viewpoint_entity_id,
                   include_future_knowledge=NEW.include_future_knowledge,
                   updated_at=NEW.updated_at
             WHERE chapter_id IN (
                SELECT target.chapter_id
                  FROM chapter_localizations source
                  JOIN chapter_localizations target
                    ON target.content_group_id=source.content_group_id
                 WHERE source.chapter_id=NEW.chapter_id
                   AND target.chapter_id!=NEW.chapter_id
             );
        END"""
    )
    ensure_chapter_localizations(connection, database_id=database_id)


def ensure_chapter_localizations(
    connection: sqlite3.Connection,
    *,
    database_id: str,
) -> dict[str, int]:
    cursor = connection.cursor()
    created = 0
    reconciled = 0
    language_by_book: dict[str, str] = {}
    missing = cursor.execute(
        """SELECT c.*
             FROM chapters c
             LEFT JOIN chapter_localizations l ON l.chapter_id=c.chapter_id
            WHERE l.chapter_id IS NULL
            ORDER BY c.book_id,c.chapter_index,c.chapter_id"""
    ).fetchall()
    for chapter in missing:
        book_id = chapter["book_id"]
        language_code = language_by_book.setdefault(
            book_id,
            _book_source_language(cursor, book_id),
        )
        group_id = _stable_id(
            "CG",
            database_id,
            book_id,
            chapter["chapter_id"],
        )
        localization_id = _stable_id(
            "CL",
            database_id,
            book_id,
            chapter["chapter_id"],
            language_code,
        )
        content_hash = chapter_content_hash(chapter["title"], chapter["content"])
        cursor.execute(
            """INSERT OR IGNORE INTO content_groups(
                content_group_id,database_id,book_id,content_type,
                canonical_order,volume_id
            ) VALUES (?,?,?,'chapter',?,?)""",
            (
                group_id,
                database_id,
                book_id,
                chapter["chapter_index"] or 0,
                chapter["volume_id"],
            ),
        )
        cursor.execute(
            """INSERT OR IGNORE INTO chapter_localizations(
                localization_id,content_group_id,chapter_id,language_code,
                is_source,source_localization_id,content_revision,content_hash,
                source_revision_hash,translation_status,approval_status
            ) VALUES (?,?,?,?,1,NULL,1,?,?,'approved','approved')""",
            (
                localization_id,
                group_id,
                chapter["chapter_id"],
                language_code,
                content_hash,
                content_hash,
            ),
        )
        created += cursor.rowcount

    rows = cursor.execute(
        """SELECT l.*,c.title,c.content,c.book_id,c.chapter_index,c.volume_id
             FROM chapter_localizations l
             JOIN chapters c ON c.chapter_id=l.chapter_id
            ORDER BY l.content_group_id,l.is_source DESC,l.language_code"""
    ).fetchall()
    for row in rows:
        current_hash = chapter_content_hash(row["title"], row["content"])
        if current_hash != row["content_hash"]:
            _update_localization_for_content(
                cursor,
                row,
                current_hash=current_hash,
            )
            reconciled += 1
        if row["is_source"]:
            cursor.execute(
                """UPDATE content_groups
                      SET database_id=?,book_id=?,canonical_order=?,volume_id=?,
                          updated_at=CASE
                              WHEN database_id!=? OR book_id!=? OR canonical_order!=?
                                   OR volume_id IS NOT ?
                              THEN CURRENT_TIMESTAMP ELSE updated_at END
                    WHERE content_group_id=?""",
                (
                    database_id,
                    row["book_id"],
                    row["chapter_index"] or 0,
                    row["volume_id"],
                    database_id,
                    row["book_id"],
                    row["chapter_index"] or 0,
                    row["volume_id"],
                    row["content_group_id"],
                ),
            )
    return {"created": created, "reconciled": reconciled}


def _update_localization_for_content(
    cursor: sqlite3.Cursor,
    localization: sqlite3.Row,
    *,
    current_hash: str,
) -> dict[str, Any]:
    revision = int(localization["content_revision"] or 0) + 1
    stale_count = 0
    if localization["is_source"]:
        cursor.execute(
            """UPDATE chapter_localizations
                  SET content_revision=?,content_hash=?,source_revision_hash=?,
                      translation_status='approved',approval_status='approved',
                      updated_at=CURRENT_TIMESTAMP
                WHERE localization_id=?""",
            (revision, current_hash, current_hash, localization["localization_id"]),
        )
        stale_cursor = cursor.execute(
            """UPDATE chapter_localizations
                  SET translation_status='stale',approval_status='outdated',
                      updated_at=CURRENT_TIMESTAMP
                WHERE content_group_id=? AND is_source=0
                  AND source_revision_hash!=?""",
            (localization["content_group_id"], current_hash),
        )
        stale_count = stale_cursor.rowcount
        if cursor.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='chapter_translation_tasks'"
        ).fetchone():
            cursor.execute(
                """UPDATE chapter_translation_tasks
                      SET task_status='stale',approval_status='outdated',
                          updated_at=CURRENT_TIMESTAMP
                    WHERE content_group_id=? AND source_revision_hash!=?
                      AND task_status IN ('running','review_required','approved')""",
                (localization["content_group_id"], current_hash),
            )
    else:
        translation_status = (
            "stale" if localization["translation_status"] == "stale" else "draft"
        )
        approval_status = (
            "outdated" if translation_status == "stale" else "pending_review"
        )
        cursor.execute(
            """UPDATE chapter_localizations
                  SET content_revision=?,content_hash=?,translation_status=?,
                      approval_status=?,updated_at=CURRENT_TIMESTAMP
                WHERE localization_id=?""",
            (
                revision,
                current_hash,
                translation_status,
                approval_status,
                localization["localization_id"],
            ),
        )
    return {
        "content_revision": revision,
        "content_hash": current_hash,
        "source_revision_hash": current_hash
        if localization["is_source"]
        else localization["source_revision_hash"],
        "translation_status": "approved"
        if localization["is_source"]
        else translation_status,
        "approval_status": "approved"
        if localization["is_source"]
        else approval_status,
        "stale_localization_count": stale_count,
    }


def synchronize_chapter_localization(
    connection: sqlite3.Connection,
    chapter_id: str,
    *,
    database_id: str,
) -> dict[str, Any]:
    row = connection.execute(
        """SELECT l.*,c.title,c.content
             FROM chapter_localizations l
             JOIN chapters c ON c.chapter_id=l.chapter_id
            WHERE l.chapter_id=?""",
        (chapter_id,),
    ).fetchone()
    if not row:
        ensure_chapter_localizations(connection, database_id=database_id)
        row = connection.execute(
            """SELECT l.*,c.title,c.content
                 FROM chapter_localizations l
                 JOIN chapters c ON c.chapter_id=l.chapter_id
                WHERE l.chapter_id=?""",
            (chapter_id,),
        ).fetchone()
    if not row:
        raise LookupError("chapter localization not found")
    current_hash = chapter_content_hash(row["title"], row["content"])
    if current_hash == row["content_hash"]:
        return {
            "content_revision": row["content_revision"],
            "content_hash": row["content_hash"],
            "source_revision_hash": row["source_revision_hash"],
            "translation_status": row["translation_status"],
            "approval_status": row["approval_status"],
            "stale_localization_count": 0,
        }
    return _update_localization_for_content(
        connection.cursor(),
        row,
        current_hash=current_hash,
    )


def chapter_with_localization(
    connection: sqlite3.Connection,
    chapter_id: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        """SELECT c.*,l.localization_id,l.content_group_id,l.language_code,
                  l.is_source,l.source_localization_id,l.content_revision,
                  l.content_hash,l.source_revision_hash,l.translation_status,
                  l.approval_status,l.updated_at AS localization_updated_at,
                  source.chapter_id AS source_chapter_id
             FROM chapters c
             JOIN chapter_localizations l ON l.chapter_id=c.chapter_id
             LEFT JOIN chapter_localizations source
               ON source.content_group_id=l.content_group_id AND source.is_source=1
            WHERE c.chapter_id=?""",
        (chapter_id,),
    ).fetchone()
    return dict(row) if row else None


def list_chapters_with_localization(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    volume_id: str | None = None,
    language_code: str | None = None,
) -> list[dict[str, Any]]:
    clauses = ["c.book_id=?", "c.is_active=1"]
    params: list[Any] = [book_id]
    if volume_id:
        clauses.append("c.volume_id=?")
        params.append(volume_id)
    if language_code:
        clauses.append("l.language_code=?")
        params.append(normalize_language_code(language_code))
    else:
        clauses.append("l.is_source=1")
    rows = connection.execute(
        f"""SELECT c.*,l.localization_id,l.content_group_id,l.language_code,
                   l.is_source,l.source_localization_id,l.content_revision,
                   l.content_hash,l.source_revision_hash,l.translation_status,
                   l.approval_status,source.chapter_id AS source_chapter_id
              FROM chapters c
              JOIN chapter_localizations l ON l.chapter_id=c.chapter_id
              JOIN content_groups g ON g.content_group_id=l.content_group_id
              LEFT JOIN chapter_localizations source
                ON source.content_group_id=l.content_group_id AND source.is_source=1
             WHERE {' AND '.join(clauses)}
             ORDER BY g.canonical_order,c.chapter_index,c.chapter_id""",
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def list_group_localizations(
    connection: sqlite3.Connection,
    *,
    content_group_id: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT l.localization_id,l.content_group_id,l.chapter_id,l.language_code,
                  l.is_source,l.source_localization_id,l.content_revision,
                  l.content_hash,l.source_revision_hash,l.translation_status,
                  l.approval_status,l.created_at,l.updated_at,
                  c.title,c.word_count,c.status,c.is_active,c.chapter_index,
                  c.volume_id
             FROM chapter_localizations l
             JOIN chapters c ON c.chapter_id=l.chapter_id
            WHERE l.content_group_id=?
            ORDER BY l.is_source DESC,l.language_code""",
        (content_group_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def register_source_chapter(
    connection: sqlite3.Connection,
    *,
    chapter_id: str,
    language_code: str | None,
    database_id: str,
) -> dict[str, Any]:
    ensure_chapter_localizations(connection, database_id=database_id)
    row = connection.execute(
        "SELECT localization_id,language_code FROM chapter_localizations WHERE chapter_id=?",
        (chapter_id,),
    ).fetchone()
    if not row:
        raise LookupError("chapter not found")
    if language_code is not None:
        normalized = normalize_language_code(language_code)
        if normalized != row["language_code"]:
            connection.execute(
                """UPDATE chapter_localizations
                      SET language_code=?,updated_at=CURRENT_TIMESTAMP
                    WHERE localization_id=?""",
                (normalized, row["localization_id"]),
            )
    registered = chapter_with_localization(connection, chapter_id)
    if not registered:
        raise RuntimeError("registered source chapter could not be read")
    return registered


def create_linked_localization(
    connection: sqlite3.Connection,
    *,
    base_chapter_id: str,
    chapter_id: str,
    language_code: str,
    title: str | None,
    database_id: str,
) -> dict[str, Any]:
    ensure_chapter_localizations(connection, database_id=database_id)
    language_code = normalize_language_code(language_code)
    base = connection.execute(
        """SELECT l.content_group_id
             FROM chapter_localizations l
            WHERE l.chapter_id=?""",
        (base_chapter_id,),
    ).fetchone()
    if not base:
        raise LookupError("chapter not found")
    source = connection.execute(
        """SELECT l.*,c.book_id,c.volume_id,c.chapter_index,c.title
             FROM chapter_localizations l
             JOIN chapters c ON c.chapter_id=l.chapter_id
            WHERE l.content_group_id=? AND l.is_source=1""",
        (base["content_group_id"],),
    ).fetchone()
    if not source:
        raise RuntimeError("content group has no source localization")
    duplicate = connection.execute(
        "SELECT chapter_id FROM chapter_localizations "
        "WHERE content_group_id=? AND language_code=?",
        (source["content_group_id"], language_code),
    ).fetchone()
    if duplicate:
        raise FileExistsError(duplicate["chapter_id"])

    resolved_title = (title or source["title"]).strip()
    content_hash = chapter_content_hash(resolved_title, "")
    localization_id = new_localization_id()
    connection.execute(
        """INSERT INTO chapters(
            chapter_id,book_id,volume_id,chapter_index,title,content,word_count,status,is_active
        ) VALUES (?,?,?,?,?,'',0,'draft',1)""",
        (
            chapter_id,
            source["book_id"],
            source["volume_id"],
            source["chapter_index"],
            resolved_title,
        ),
    )
    connection.execute(
        """INSERT INTO chapter_localizations(
            localization_id,content_group_id,chapter_id,language_code,is_source,
            source_localization_id,content_revision,content_hash,
            source_revision_hash,translation_status,approval_status
        ) VALUES (?,?,?,?,0,?,1,?,?,'draft','pending_review')""",
        (
            localization_id,
            source["content_group_id"],
            chapter_id,
            language_code,
            source["localization_id"],
            content_hash,
            source["content_hash"],
        ),
    )
    connection.execute(
        """INSERT INTO chapter_temporal_contexts(
            chapter_id,book_id,timeline_id,branch_id,anchor_id,phase_id,
            viewpoint_entity_id,include_future_knowledge,updated_at
        )
        SELECT ?,book_id,timeline_id,branch_id,anchor_id,phase_id,
               viewpoint_entity_id,include_future_knowledge,updated_at
          FROM chapter_temporal_contexts
         WHERE chapter_id=?
        ON CONFLICT(chapter_id) DO UPDATE SET
            book_id=excluded.book_id,
            timeline_id=excluded.timeline_id,
            branch_id=excluded.branch_id,
            anchor_id=excluded.anchor_id,
            phase_id=excluded.phase_id,
            viewpoint_entity_id=excluded.viewpoint_entity_id,
            include_future_knowledge=excluded.include_future_knowledge,
            updated_at=excluded.updated_at""",
        (chapter_id, source["chapter_id"]),
    )
    created = chapter_with_localization(connection, chapter_id)
    if not created:
        raise RuntimeError("created localization could not be read")
    return created
