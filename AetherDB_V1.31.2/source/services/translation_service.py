"""Translation persistence, scope validation, review, and staleness rules."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from typing import Any

from services.chapter_localization import (
    chapter_content_hash,
    chapter_with_localization,
    create_linked_localization,
    ensure_chapter_localizations,
    list_group_localizations,
    normalize_language_code,
    synchronize_chapter_localization,
)


ENTITY_TRANSLATION_STATUSES = {
    "draft",
    "review_required",
    "approved",
    "stale",
    "rejected",
}
CHAPTER_TRANSLATION_TASK_STATUSES = {
    "running",
    "review_required",
    "approved",
    "rejected",
    "stale",
    "failed",
}
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9:._-]{1,128}$")


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return bool(
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    )


def _canonical_hash(payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def entity_source_hash(entity: sqlite3.Row | dict[str, Any]) -> str:
    return _canonical_hash(
        {
            "title": entity["title"] or "",
            "content": entity["content"] or "",
            "full_content": entity["full_content"] or "",
            "ai_summary": entity["ai_summary"] or "",
        }
    )


def _book_source_language(
    connection: sqlite3.Connection,
    book_id: str,
    *,
    fallback: str = "zh-CN",
) -> str:
    row = connection.execute(
        "SELECT metadata FROM books WHERE book_id=?",
        (book_id,),
    ).fetchone()
    if row:
        try:
            metadata = json.loads(row["metadata"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            metadata = {}
        for key in ("source_language", "language_code", "default_language", "locale"):
            value = metadata.get(key)
            if value:
                try:
                    return normalize_language_code(str(value))
                except ValueError:
                    continue
    return normalize_language_code(fallback)


def initialize_translation_schema(
    connection: sqlite3.Connection,
    *,
    database_id: str,
) -> None:
    """Upgrade old entity translations and create durable chapter translation tasks."""
    entity_columns = _table_columns(connection, "entity_translations")
    additions = {
        "source_language_code": "TEXT NOT NULL DEFAULT 'zh-CN'",
        "source_revision": "INTEGER NOT NULL DEFAULT 1",
        "source_hash": "TEXT NOT NULL DEFAULT ''",
        "translation_status": "TEXT NOT NULL DEFAULT 'approved'",
        "approval_status": "TEXT NOT NULL DEFAULT 'approved'",
        "translation_origin": "TEXT NOT NULL DEFAULT 'legacy'",
        "reviewed_at": "TIMESTAMP",
        "reviewed_by": "TEXT",
    }
    for column, ddl in additions.items():
        if column not in entity_columns:
            connection.execute(
                f"ALTER TABLE entity_translations ADD COLUMN {column} {ddl}"
            )

    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_et_scope "
        "ON entity_translations(book_id,language,translation_status,approval_status)"
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS chapter_translation_tasks (
            translation_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL UNIQUE,
            database_id TEXT NOT NULL,
            book_id TEXT NOT NULL,
            content_group_id TEXT NOT NULL,
            source_chapter_id TEXT NOT NULL,
            target_chapter_id TEXT,
            source_language_code TEXT NOT NULL,
            target_language_code TEXT NOT NULL,
            source_revision_hash TEXT NOT NULL,
            task_status TEXT NOT NULL CHECK(
                task_status IN (
                    'running','review_required','approved','rejected','stale','failed'
                )
            ),
            approval_status TEXT NOT NULL DEFAULT 'pending_review' CHECK(
                approval_status IN ('pending_review','approved','rejected','outdated')
            ),
            draft_title TEXT NOT NULL DEFAULT '',
            draft_content TEXT NOT NULL DEFAULT '',
            output_format TEXT NOT NULL DEFAULT 'pending',
            model_profile_id TEXT,
            provider_id TEXT,
            provider_model_name TEXT,
            provider_request_id TEXT,
            cloud_upload_confirmed INTEGER NOT NULL DEFAULT 0,
            error_code TEXT,
            error_message TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TIMESTAMP,
            reviewed_by TEXT
        )"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_chapter_translation_group "
        "ON chapter_translation_tasks(content_group_id,target_language_code,created_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_chapter_translation_source "
        "ON chapter_translation_tasks(source_chapter_id,task_status,created_at DESC)"
    )
    connection.execute(
        """UPDATE chapter_translation_tasks
              SET task_status='failed',approval_status='pending_review',
                  error_code='INTERRUPTED',
                  error_message='Translation execution was interrupted by restart',
                  updated_at=CURRENT_TIMESTAMP
            WHERE task_status='running'"""
    )

    rows = connection.execute(
        """SELECT t.id,t.entity_id,t.book_id,t.source_hash,t.source_revision,
                  t.source_language_code,e.book_id AS entity_book_id,e.title,e.content,
                  e.full_content,e.ai_summary,e.version
             FROM entity_translations t
             JOIN entities e ON e.entity_id=t.entity_id"""
    ).fetchall()
    for row in rows:
        book_id = row["entity_book_id"] or row["book_id"] or "default"
        source_language = _book_source_language(connection, book_id)
        current_hash = entity_source_hash(row)
        connection.execute(
            """UPDATE entity_translations
                  SET book_id=?,source_language_code=?,source_revision=?,source_hash=?
                WHERE id=?""",
            (
                book_id,
                source_language,
                int(row["version"] or 1),
                row["source_hash"] or current_hash,
                row["id"],
            ),
        )


def reconcile_entity_translations(
    connection: sqlite3.Connection,
    entity_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    entity = connection.execute(
        "SELECT * FROM entities WHERE entity_id=? AND is_active=1",
        (entity_id,),
    ).fetchone()
    if not entity:
        raise LookupError("entity not found")
    current_hash = entity_source_hash(entity)
    current_revision = int(entity["version"] or 1)
    connection.execute(
        """UPDATE entity_translations
              SET translation_status='stale',approval_status='outdated',
                  updated_at=CURRENT_TIMESTAMP
            WHERE entity_id=? AND source_hash!=?
              AND translation_status NOT IN ('stale','rejected')""",
        (entity_id, current_hash),
    )
    connection.execute(
        """UPDATE entity_translations
              SET source_revision=?
            WHERE entity_id=? AND source_hash=?""",
        (current_revision, entity_id, current_hash),
    )
    rows = connection.execute(
        "SELECT * FROM entity_translations WHERE entity_id=? ORDER BY language,id",
        (entity_id,),
    ).fetchall()
    return dict(entity), [dict(row) for row in rows]


def save_entity_translation(
    connection: sqlite3.Connection,
    *,
    entity_id: str,
    language_code: str,
    title: str,
    content: str,
    full_content: str,
    ai_summary: str,
    requested_book_id: str | None,
) -> dict[str, Any]:
    entity, _ = reconcile_entity_translations(connection, entity_id)
    book_id = entity["book_id"] or "default"
    if requested_book_id and requested_book_id != book_id:
        raise PermissionError("entity does not belong to requested book")
    target_language = normalize_language_code(language_code)
    source_language = _book_source_language(connection, book_id)
    if target_language == source_language:
        raise ValueError("target language must differ from the source language")
    source_hash = entity_source_hash(entity)
    connection.execute(
        """INSERT INTO entity_translations(
            entity_id,language,title,content,full_content,ai_summary,book_id,
            source_language_code,source_revision,source_hash,
            translation_status,approval_status,translation_origin,
            reviewed_at,reviewed_by
        ) VALUES (?,?,?,?,?,?,?,?,?,?,'draft','pending_review','manual',NULL,NULL)
        ON CONFLICT(entity_id,language) DO UPDATE SET
            title=excluded.title,
            content=excluded.content,
            full_content=excluded.full_content,
            ai_summary=excluded.ai_summary,
            book_id=excluded.book_id,
            source_language_code=excluded.source_language_code,
            source_revision=excluded.source_revision,
            source_hash=excluded.source_hash,
            translation_status='draft',
            approval_status='pending_review',
            translation_origin='manual',
            reviewed_at=NULL,
            reviewed_by=NULL,
            updated_at=CURRENT_TIMESTAMP""",
        (
            entity_id,
            target_language,
            title.strip(),
            content,
            full_content,
            ai_summary,
            book_id,
            source_language,
            int(entity["version"] or 1),
            source_hash,
        ),
    )
    return dict(
        connection.execute(
            "SELECT * FROM entity_translations WHERE entity_id=? AND language=?",
            (entity_id, target_language),
        ).fetchone()
    )


def review_entity_translation(
    connection: sqlite3.Connection,
    *,
    translation_id: int,
    action: str,
    expected_source_hash: str,
    reviewed_by: str,
) -> dict[str, Any]:
    row = connection.execute(
        """SELECT t.*,e.title AS source_title,e.content AS source_content,
                  e.full_content AS source_full_content,e.ai_summary AS source_ai_summary,
                  e.version AS current_source_revision
             FROM entity_translations t
             JOIN entities e ON e.entity_id=t.entity_id
            WHERE t.id=? AND e.is_active=1""",
        (translation_id,),
    ).fetchone()
    if not row:
        raise LookupError("entity translation not found")
    current_hash = _canonical_hash(
        {
            "title": row["source_title"] or "",
            "content": row["source_content"] or "",
            "full_content": row["source_full_content"] or "",
            "ai_summary": row["source_ai_summary"] or "",
        }
    )
    if action == "approve":
        if expected_source_hash != current_hash or row["source_hash"] != current_hash:
            connection.execute(
                """UPDATE entity_translations
                      SET translation_status='stale',approval_status='outdated',
                          updated_at=CURRENT_TIMESTAMP
                    WHERE id=?""",
                (translation_id,),
            )
            raise RuntimeError("source revision changed")
        connection.execute(
            """UPDATE entity_translations
                  SET source_revision=?,translation_status='approved',
                      approval_status='approved',reviewed_at=CURRENT_TIMESTAMP,
                      reviewed_by=?,updated_at=CURRENT_TIMESTAMP
                WHERE id=?""",
            (int(row["current_source_revision"] or 1), reviewed_by, translation_id),
        )
    elif action == "reject":
        connection.execute(
            """UPDATE entity_translations
                  SET translation_status='rejected',approval_status='rejected',
                      reviewed_at=CURRENT_TIMESTAMP,reviewed_by=?,
                      updated_at=CURRENT_TIMESTAMP
                WHERE id=?""",
            (reviewed_by, translation_id),
        )
    else:
        raise ValueError("unsupported review action")
    return dict(
        connection.execute(
            "SELECT * FROM entity_translations WHERE id=?",
            (translation_id,),
        ).fetchone()
    )


def mark_entity_translations_stale(
    connection: sqlite3.Connection,
    entity_id: str,
) -> int:
    entity = connection.execute(
        "SELECT * FROM entities WHERE entity_id=?",
        (entity_id,),
    ).fetchone()
    if not entity:
        return 0
    current_hash = entity_source_hash(entity)
    current_revision = int(entity["version"] or 1)
    cursor = connection.execute(
        """UPDATE entity_translations
              SET translation_status='stale',approval_status='outdated',
                  updated_at=CURRENT_TIMESTAMP
            WHERE entity_id=? AND source_hash!=?
              AND translation_status!='rejected'""",
        (entity_id, current_hash),
    )
    connection.execute(
        "UPDATE entity_translations SET source_revision=? "
        "WHERE entity_id=? AND source_hash=?",
        (current_revision, entity_id, current_hash),
    )
    return cursor.rowcount


def _next_sequence(cursor: sqlite3.Cursor, prefix: str) -> int:
    cursor.execute(
        "INSERT INTO id_sequence(prefix,next_id) VALUES (?,1) "
        "ON CONFLICT(prefix) DO UPDATE SET next_id=next_id+1",
        (prefix,),
    )
    return int(
        cursor.execute(
            "SELECT next_id FROM id_sequence WHERE prefix=?",
            (prefix,),
        ).fetchone()[0]
    )


def _new_chapter_id(cursor: sqlite3.Cursor) -> str:
    return f"CHP_{_next_sequence(cursor, 'CHP'):04d}"


def _translation_task(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["cloud_upload_confirmed"] = bool(data["cloud_upload_confirmed"])
    return data


def prepare_chapter_translation(
    connection: sqlite3.Connection,
    *,
    chapter_id: str,
    target_language_code: str,
    request_id: str | None,
    database_id: str,
    cloud_upload_confirmed: bool,
) -> dict[str, Any]:
    ensure_chapter_localizations(connection, database_id=database_id)
    base = chapter_with_localization(connection, chapter_id)
    if not base or not base["is_active"]:
        raise LookupError("chapter not found")
    source = connection.execute(
        """SELECT c.*,l.localization_id,l.content_group_id,l.language_code,
                  l.content_revision,l.content_hash
             FROM chapter_localizations selected
             JOIN chapter_localizations l
               ON l.content_group_id=selected.content_group_id AND l.is_source=1
             JOIN chapters c ON c.chapter_id=l.chapter_id
            WHERE selected.chapter_id=?""",
        (chapter_id,),
    ).fetchone()
    if not source or not source["is_active"]:
        raise LookupError("source chapter not found")
    synchronize_chapter_localization(
        connection,
        source["chapter_id"],
        database_id=database_id,
    )
    source = connection.execute(
        """SELECT c.*,l.localization_id,l.content_group_id,l.language_code,
                  l.content_revision,l.content_hash
             FROM chapter_localizations l
             JOIN chapters c ON c.chapter_id=l.chapter_id
            WHERE l.chapter_id=?""",
        (source["chapter_id"],),
    ).fetchone()
    target_language = normalize_language_code(target_language_code)
    if target_language == source["language_code"]:
        raise ValueError("target language must differ from source language")

    normalized_request_id = request_id or f"translation:{uuid.uuid4().hex}"
    if not _REQUEST_ID_RE.fullmatch(normalized_request_id):
        raise ValueError("invalid translation request id")
    existing = connection.execute(
        "SELECT * FROM chapter_translation_tasks WHERE request_id=?",
        (normalized_request_id,),
    ).fetchone()
    if existing:
        return {
            "task": _translation_task(existing),
            "source": dict(source),
            "reused": True,
        }

    target = connection.execute(
        """SELECT l.chapter_id
             FROM chapter_localizations l
            WHERE l.content_group_id=? AND l.language_code=?""",
        (source["content_group_id"], target_language),
    ).fetchone()
    translation_id = f"TR_{uuid.uuid4().hex.upper()[:24]}"
    connection.execute(
        """INSERT INTO chapter_translation_tasks(
            translation_id,request_id,database_id,book_id,content_group_id,
            source_chapter_id,target_chapter_id,source_language_code,
            target_language_code,source_revision_hash,task_status,
            approval_status,cloud_upload_confirmed
        ) VALUES (?,?,?,?,?,?,?,?,?,?,'running','pending_review',?)""",
        (
            translation_id,
            normalized_request_id,
            database_id,
            source["book_id"],
            source["content_group_id"],
            source["chapter_id"],
            target["chapter_id"] if target else None,
            source["language_code"],
            target_language,
            source["content_hash"],
            int(cloud_upload_confirmed),
        ),
    )
    task = connection.execute(
        "SELECT * FROM chapter_translation_tasks WHERE translation_id=?",
        (translation_id,),
    ).fetchone()
    return {"task": _translation_task(task), "source": dict(source), "reused": False}


def translation_messages(
    source: dict[str, Any],
    *,
    target_language_code: str,
) -> tuple[dict[str, str], ...]:
    system = (
        "Translate the supplied fiction chapter faithfully. Preserve names, facts, "
        "paragraph order, tone, and omissions. Do not add commentary or new story facts. "
        "Return only one JSON object with string fields title and content."
    )
    user = json.dumps(
        {
            "source_language": source["language_code"],
            "target_language": target_language_code,
            "title": source["title"] or "",
            "content": source["content"] or "",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return ({"role": "system", "content": system}, {"role": "user", "content": user})


def parse_translation_output(
    output: str,
    *,
    source_title: str,
) -> tuple[str, str, str]:
    text = (output or "").strip()
    if not text:
        raise ValueError("model returned an empty translation")
    candidate = text
    if candidate.startswith("```") and candidate.endswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)
    def load_payload(raw: str):
        try:
            return json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    payload = load_payload(candidate)
    if not isinstance(payload, dict):
        match = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
        if match:
            payload = load_payload(match.group(0))
    if isinstance(payload, dict):
        title = (
            payload.get("title")
            or payload.get("translated_title")
            or payload.get("target_title")
        )
        content = (
            payload.get("content")
            or payload.get("translated_content")
            or payload.get("translation")
            or payload.get("text")
        )
        if isinstance(title, str) and isinstance(content, str) and content.strip():
            title = title.strip() or source_title
            if len(title) > 300 or len(content) > 2_000_000:
                raise ValueError("translation output exceeds limits")
            return title, content, "json"
        if isinstance(content, str) and content.strip():
            if len(content) > 2_000_000:
                raise ValueError("translation output exceeds limits")
            return source_title[:300], content, "json_content_only"
    if len(text) > 2_000_000:
        raise ValueError("translation output exceeds limits")
    return source_title[:300], text, "plain_text_recovery"


def complete_chapter_translation(
    connection: sqlite3.Connection,
    *,
    translation_id: str,
    output: str,
    source_title: str,
    model_profile_id: str,
    provider_id: str,
    provider_model_name: str | None,
    provider_request_id: str | None,
) -> dict[str, Any]:
    title, content, output_format = parse_translation_output(
        output,
        source_title=source_title,
    )
    cursor = connection.execute(
        """UPDATE chapter_translation_tasks
              SET task_status='review_required',approval_status='pending_review',
                  draft_title=?,draft_content=?,output_format=?,
                  model_profile_id=?,provider_id=?,provider_model_name=?,
                  provider_request_id=?,error_code=NULL,error_message=NULL,
                  updated_at=CURRENT_TIMESTAMP
            WHERE translation_id=? AND task_status='running'""",
        (
            title,
            content,
            output_format,
            model_profile_id,
            provider_id,
            provider_model_name,
            provider_request_id,
            translation_id,
        ),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("translation task is not running")
    return _translation_task(
        connection.execute(
            "SELECT * FROM chapter_translation_tasks WHERE translation_id=?",
            (translation_id,),
        ).fetchone()
    )


def fail_chapter_translation(
    connection: sqlite3.Connection,
    *,
    translation_id: str,
    error_code: str,
    error_message: str,
) -> dict[str, Any]:
    connection.execute(
        """UPDATE chapter_translation_tasks
              SET task_status='failed',approval_status='pending_review',
                  error_code=?,error_message=?,updated_at=CURRENT_TIMESTAMP
            WHERE translation_id=? AND task_status='running'""",
        (error_code[:80], error_message[:300], translation_id),
    )
    row = connection.execute(
        "SELECT * FROM chapter_translation_tasks WHERE translation_id=?",
        (translation_id,),
    ).fetchone()
    if not row:
        raise LookupError("translation task not found")
    return _translation_task(row)


def reconcile_chapter_translation_tasks(
    connection: sqlite3.Connection,
    *,
    content_group_id: str,
    database_id: str,
) -> None:
    source = connection.execute(
        """SELECT l.chapter_id,l.content_hash
             FROM chapter_localizations l
            WHERE l.content_group_id=? AND l.is_source=1""",
        (content_group_id,),
    ).fetchone()
    if not source:
        return
    synchronize_chapter_localization(
        connection,
        source["chapter_id"],
        database_id=database_id,
    )
    current = connection.execute(
        "SELECT content_hash FROM chapter_localizations WHERE chapter_id=?",
        (source["chapter_id"],),
    ).fetchone()
    connection.execute(
        """UPDATE chapter_translation_tasks
              SET task_status='stale',approval_status='outdated',
                  updated_at=CURRENT_TIMESTAMP
            WHERE content_group_id=? AND source_revision_hash!=?
              AND task_status IN ('review_required','approved')""",
        (content_group_id, current["content_hash"]),
    )


def list_chapter_translations(
    connection: sqlite3.Connection,
    *,
    chapter_id: str,
    database_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    chapter = chapter_with_localization(connection, chapter_id)
    if not chapter:
        raise LookupError("chapter not found")
    reconcile_chapter_translation_tasks(
        connection,
        content_group_id=chapter["content_group_id"],
        database_id=database_id,
    )
    rows = connection.execute(
        """SELECT * FROM chapter_translation_tasks
            WHERE content_group_id=?
            ORDER BY created_at DESC,translation_id DESC""",
        (chapter["content_group_id"],),
    ).fetchall()
    source = connection.execute(
        """SELECT l.chapter_id,l.language_code,l.content_hash,l.content_revision
             FROM chapter_localizations l
            WHERE l.content_group_id=? AND l.is_source=1""",
        (chapter["content_group_id"],),
    ).fetchone()
    return dict(source), [_translation_task(row) for row in rows]


def update_chapter_translation_draft(
    connection: sqlite3.Connection,
    *,
    translation_id: str,
    title: str,
    content: str,
) -> dict[str, Any]:
    cursor = connection.execute(
        """UPDATE chapter_translation_tasks
              SET draft_title=?,draft_content=?,task_status='review_required',
                  approval_status='pending_review',output_format='author_edited',
                  updated_at=CURRENT_TIMESTAMP
            WHERE translation_id=? AND task_status IN ('review_required','failed')""",
        (title.strip(), content, translation_id),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("translation draft is not editable")
    return _translation_task(
        connection.execute(
            "SELECT * FROM chapter_translation_tasks WHERE translation_id=?",
            (translation_id,),
        ).fetchone()
    )


def approve_chapter_translation(
    connection: sqlite3.Connection,
    *,
    translation_id: str,
    expected_source_revision_hash: str,
    reviewed_by: str,
    database_id: str,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    task = connection.execute(
        "SELECT * FROM chapter_translation_tasks WHERE translation_id=?",
        (translation_id,),
    ).fetchone()
    if not task:
        raise LookupError("translation task not found")
    source = chapter_with_localization(connection, task["source_chapter_id"])
    if not source:
        raise LookupError("source chapter not found")
    synchronize_chapter_localization(
        connection,
        source["chapter_id"],
        database_id=database_id,
    )
    source = chapter_with_localization(connection, source["chapter_id"])
    if (
        expected_source_revision_hash != source["content_hash"]
        or task["source_revision_hash"] != source["content_hash"]
    ):
        connection.execute(
            """UPDATE chapter_translation_tasks
                  SET task_status='stale',approval_status='outdated',
                      updated_at=CURRENT_TIMESTAMP
                WHERE translation_id=?""",
            (translation_id,),
        )
        raise RuntimeError("source revision changed")
    if task["task_status"] not in {"review_required"}:
        raise RuntimeError("translation task is not ready for approval")

    target = connection.execute(
        """SELECT c.*,l.localization_id,l.content_revision
             FROM chapter_localizations l
             JOIN chapters c ON c.chapter_id=l.chapter_id
            WHERE l.content_group_id=? AND l.language_code=?""",
        (task["content_group_id"], task["target_language_code"]),
    ).fetchone()
    if not target:
        target_id = _new_chapter_id(connection.cursor())
        created = create_linked_localization(
            connection,
            base_chapter_id=source["chapter_id"],
            chapter_id=target_id,
            language_code=task["target_language_code"],
            title=task["draft_title"],
            database_id=database_id,
        )
        target = connection.execute(
            """SELECT c.*,l.localization_id,l.content_revision
                 FROM chapter_localizations l
                 JOIN chapters c ON c.chapter_id=l.chapter_id
                WHERE l.chapter_id=?""",
            (created["chapter_id"],),
        ).fetchone()
    else:
        target_id = target["chapter_id"]

    if target["title"] or target["content"]:
        version = _next_sequence(connection.cursor(), f"CHVER_{target_id}")
        connection.execute(
            """INSERT INTO chapter_versions(
                chapter_id,version,title,content,word_count,book_id
            ) VALUES (?,?,?,?,?,?)""",
            (
                target_id,
                version,
                target["title"],
                target["content"],
                int(target["word_count"] or 0),
                target["book_id"],
            ),
        )
    target_hash = chapter_content_hash(task["draft_title"], task["draft_content"])
    connection.execute(
        """UPDATE chapters
              SET title=?,content=?,word_count=?,updated_at=CURRENT_TIMESTAMP
            WHERE chapter_id=?""",
        (
            task["draft_title"],
            task["draft_content"],
            len(task["draft_content"]),
            target_id,
        ),
    )
    connection.execute(
        """UPDATE chapter_localizations
              SET content_revision=content_revision+1,content_hash=?,
                  source_revision_hash=?,translation_status='approved',
                  approval_status='approved',updated_at=CURRENT_TIMESTAMP
            WHERE chapter_id=?""",
        (target_hash, source["content_hash"], target_id),
    )
    connection.execute(
        """UPDATE chapter_translation_tasks
              SET target_chapter_id=?,task_status='approved',
                  approval_status='approved',reviewed_at=CURRENT_TIMESTAMP,
                  reviewed_by=?,updated_at=CURRENT_TIMESTAMP
            WHERE translation_id=?""",
        (target_id, reviewed_by, translation_id),
    )
    connection.execute(
        """UPDATE chapter_translation_tasks
              SET task_status='rejected',approval_status='rejected',
                  reviewed_at=CURRENT_TIMESTAMP,reviewed_by=?,
                  updated_at=CURRENT_TIMESTAMP
            WHERE content_group_id=? AND target_language_code=?
              AND translation_id!=? AND task_status='review_required'""",
        (
            reviewed_by,
            task["content_group_id"],
            task["target_language_code"],
            translation_id,
        ),
    )
    approved_task = _translation_task(
        connection.execute(
            "SELECT * FROM chapter_translation_tasks WHERE translation_id=?",
            (translation_id,),
        ).fetchone()
    )
    chapter = chapter_with_localization(connection, target_id)
    return (
        approved_task,
        chapter,
        list_group_localizations(
            connection,
            content_group_id=task["content_group_id"],
        ),
    )


def reject_chapter_translation(
    connection: sqlite3.Connection,
    *,
    translation_id: str,
    reviewed_by: str,
) -> dict[str, Any]:
    cursor = connection.execute(
        """UPDATE chapter_translation_tasks
              SET task_status='rejected',approval_status='rejected',
                  reviewed_at=CURRENT_TIMESTAMP,reviewed_by=?,
                  updated_at=CURRENT_TIMESTAMP
            WHERE translation_id=? AND task_status IN ('review_required','failed','stale')""",
        (reviewed_by, translation_id),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("translation task cannot be rejected")
    return _translation_task(
        connection.execute(
            "SELECT * FROM chapter_translation_tasks WHERE translation_id=?",
            (translation_id,),
        ).fetchone()
    )


def mark_chapter_translation_stale(
    connection: sqlite3.Connection,
    *,
    translation_id: str,
) -> dict[str, Any]:
    cursor = connection.execute(
        """UPDATE chapter_translation_tasks
              SET task_status='stale',approval_status='outdated',
                  updated_at=CURRENT_TIMESTAMP
            WHERE translation_id=? AND task_status NOT IN ('rejected','stale')""",
        (translation_id,),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("translation task cannot be marked stale")
    return _translation_task(
        connection.execute(
            "SELECT * FROM chapter_translation_tasks WHERE translation_id=?",
            (translation_id,),
        ).fetchone()
    )


def review_chapter_localization(
    connection: sqlite3.Connection,
    *,
    chapter_id: str,
    action: str,
    expected_source_revision_hash: str,
    database_id: str,
) -> dict[str, Any]:
    target = chapter_with_localization(connection, chapter_id)
    if not target:
        raise LookupError("chapter localization not found")
    if target["is_source"]:
        raise ValueError("source chapter does not require translation review")
    source = chapter_with_localization(connection, target["source_chapter_id"])
    if not source:
        raise LookupError("source chapter not found")
    synchronize_chapter_localization(
        connection,
        source["chapter_id"],
        database_id=database_id,
    )
    source = chapter_with_localization(connection, source["chapter_id"])
    if expected_source_revision_hash != source["content_hash"]:
        raise RuntimeError("source revision changed")
    if action == "approve":
        target_hash = chapter_content_hash(target["title"], target["content"])
        connection.execute(
            """UPDATE chapter_localizations
                  SET content_hash=?,source_revision_hash=?,
                      translation_status='approved',approval_status='approved',
                      updated_at=CURRENT_TIMESTAMP
                WHERE chapter_id=?""",
            (target_hash, source["content_hash"], chapter_id),
        )
    elif action == "reject":
        connection.execute(
            """UPDATE chapter_localizations
                  SET translation_status='draft',approval_status='rejected',
                      updated_at=CURRENT_TIMESTAMP
                WHERE chapter_id=?""",
            (chapter_id,),
        )
    else:
        raise ValueError("unsupported review action")
    reviewed = chapter_with_localization(connection, chapter_id)
    return reviewed
