"""Chapter Writing & Analysis API - V1.31.2 Core Creative Loop."""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.dependencies.auth import get_current_user_role, require_admin, require_capability
import json
import logging
import uuid
from services.chapter_localization import (
    chapter_with_localization,
    create_linked_localization,
    ensure_chapter_localizations,
    list_chapters_with_localization,
    list_group_localizations,
    normalize_language_code,
    register_source_chapter,
    synchronize_chapter_localization,
)
from services.db import get_db
from services.import_pipeline import ImportPipeline, ImportChangeSet, ChapterAnalysis
from services.audit_log import log_event
from services.database_registry import get_active_database_id

router = APIRouter(tags=["chapters"])
log = logging.getLogger(__name__)


class ChapterCreateRequest(BaseModel):
    title: str = Field(default="新章节", min_length=1, max_length=300)
    volume_id: str | None = Field(default=None, max_length=128)
    language_code: str | None = Field(default=None, max_length=35)

    @field_validator("language_code")
    @classmethod
    def validate_language_code(cls, value):
        return normalize_language_code(value) if value is not None else None


class ChapterSaveRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    content: str | None = Field(default=None, max_length=2_000_000)
    status: str | None = Field(default=None, pattern=r"^(draft|completed|archived)$")


class ChapterAutosaveRequest(BaseModel):
    content: str = Field(default="", max_length=2_000_000)
    title: str | None = Field(default=None, min_length=1, max_length=300)


class ChapterAnalyzeRequest(BaseModel):
    analysis_mode: str | None = Field(default=None, pattern=r"^(ask|local_rules|cloud_model)$")


class ChapterLocalizationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language_code: str = Field(min_length=2, max_length=35)
    title: str | None = Field(default=None, min_length=1, max_length=300)

    @field_validator("language_code")
    @classmethod
    def validate_language_code(cls, value):
        return normalize_language_code(value)


def _next_sequence(cursor, prefix: str) -> int:
    cursor.execute(
        "INSERT INTO id_sequence (prefix, next_id) VALUES (?, 1) "
        "ON CONFLICT(prefix) DO UPDATE SET next_id = next_id + 1",
        (prefix,),
    )
    return cursor.execute(
        "SELECT next_id FROM id_sequence WHERE prefix = ?",
        (prefix,),
    ).fetchone()[0]


def _new_chapter_id(cursor):
    return f"CHP_{_next_sequence(cursor, 'CHP'):04d}"


def _ensure_localizations(db) -> str:
    database_id = get_active_database_id()
    ensure_chapter_localizations(db, database_id=database_id)
    return database_id


@router.get("/api/books/{book_id}/chapters")
def list_chapters(
    book_id: str,
    volume_id: str = None,
    language_code: str = None,
    role: str = Depends(get_current_user_role),
):
    db = get_db()
    try:
        _ensure_localizations(db)
        try:
            chapters = list_chapters_with_localization(
                db,
                book_id=book_id,
                volume_id=volume_id,
                language_code=language_code,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        db.commit()
        return {
            "book_id": book_id,
            "language_code": normalize_language_code(language_code)
            if language_code
            else None,
            "chapters": chapters,
        }
    finally:
        db.close()


@router.post("/api/books/{book_id}/chapters")
def create_chapter(
    book_id: str,
    payload: ChapterCreateRequest | None = None,
    title: str = "新章节",
    volume_id: str = None,
    role: str = Depends(get_current_user_role),
):
    if payload is not None:
        title = payload.title
        volume_id = payload.volume_id
        language_code = payload.language_code
    else:
        language_code = None
    db = get_db()
    try:
        cursor = db.cursor()
        chapter_id = _new_chapter_id(cursor)
        chapter_index = _next_sequence(cursor, f"CHIDX_{book_id}")
        cursor.execute(
            "INSERT INTO chapters(chapter_id,book_id,volume_id,title,chapter_index) VALUES (?,?,?,?,?)",
            (chapter_id, book_id, volume_id, title, chapter_index),
        )
        chapter = register_source_chapter(
            db,
            chapter_id=chapter_id,
            language_code=language_code,
            database_id=get_active_database_id(),
        )
        db.commit()
        return {"chapter_id": chapter_id, "title": title, "book_id": book_id, **chapter}
    finally:
        db.close()


@router.get("/api/chapters/{chapter_id}")
def get_chapter(chapter_id: str, role: str = Depends(get_current_user_role)):
    db = get_db()
    try:
        _ensure_localizations(db)
        chapter = chapter_with_localization(db, chapter_id)
        if not chapter:
            raise HTTPException(404, "Not found")
        db.commit()
        return {"chapter": chapter}
    finally:
        db.close()


@router.get("/api/chapters/{chapter_id}/localizations")
def get_chapter_localizations(
    chapter_id: str,
    role: str = Depends(get_current_user_role),
):
    db = get_db()
    try:
        _ensure_localizations(db)
        chapter = chapter_with_localization(db, chapter_id)
        if not chapter:
            raise HTTPException(404, "Not found")
        localizations = list_group_localizations(
            db,
            content_group_id=chapter["content_group_id"],
        )
        db.commit()
        return {
            "content_group_id": chapter["content_group_id"],
            "source_chapter_id": chapter["source_chapter_id"],
            "active_chapter_id": chapter_id,
            "localizations": localizations,
        }
    finally:
        db.close()


@router.get("/api/content-groups/{content_group_id}/localizations")
def get_content_group_localizations(
    content_group_id: str,
    role: str = Depends(get_current_user_role),
):
    db = get_db()
    try:
        _ensure_localizations(db)
        localizations = list_group_localizations(
            db,
            content_group_id=content_group_id,
        )
        if not localizations:
            raise HTTPException(404, "Content group not found")
        db.commit()
        source = next((item for item in localizations if item["is_source"]), None)
        return {
            "content_group_id": content_group_id,
            "source_chapter_id": source["chapter_id"] if source else None,
            "localizations": localizations,
        }
    finally:
        db.close()


@router.post("/api/chapters/{chapter_id}/localizations")
def create_chapter_localization(
    chapter_id: str,
    payload: ChapterLocalizationCreateRequest,
    _=Depends(require_capability("manage_translations")),
):
    db = get_db()
    try:
        cursor = db.cursor()
        localized_chapter_id = _new_chapter_id(cursor)
        try:
            chapter = create_linked_localization(
                db,
                base_chapter_id=chapter_id,
                chapter_id=localized_chapter_id,
                language_code=payload.language_code,
                title=payload.title,
                database_id=get_active_database_id(),
            )
        except LookupError as exc:
            db.rollback()
            raise HTTPException(404, "Chapter not found") from exc
        except FileExistsError as exc:
            db.rollback()
            raise HTTPException(
                409,
                detail={
                    "code": "CHAPTER_LOCALIZATION_EXISTS",
                    "message": "This language version already exists",
                    "chapter_id": str(exc),
                },
            ) from exc
        db.commit()
        log_event(
            db,
            "chapter.localization.create",
            f"Chapter localization {localized_chapter_id} created",
            target=localized_chapter_id,
            database_id=get_active_database_id(),
            book_id=chapter["book_id"],
            success=True,
        )
        return {
            "status": "created",
            "chapter": chapter,
            "localizations": list_group_localizations(
                db,
                content_group_id=chapter["content_group_id"],
            ),
        }
    finally:
        db.close()


@router.put("/api/chapters/{chapter_id}")
def save_chapter(
    chapter_id: str,
    payload: ChapterSaveRequest | None = None,
    title: str = None,
    content: str = None,
    status: str = None,
    _: None = Depends(require_admin),
):
    if payload is not None:
        title = payload.title
        content = payload.content
        status = payload.status
    db = get_db()
    try:
        cursor = db.cursor()
        database_id = _ensure_localizations(db)
        current = cursor.execute("SELECT * FROM chapters WHERE chapter_id=?", (chapter_id,)).fetchone()
        if not current:
            raise HTTPException(404, "Not found")

        updates, params = [], []
        if title is not None:
            updates.append("title=?")
            params.append(title)
        if content is not None:
            updates.append("content=?")
            updates.append("word_count=?")
            params.extend([content, len(content)])
        if status is not None:
            updates.append("status=?")
            params.append(status)
        if not updates:
            raise HTTPException(400, "No fields")

        updates.append("updated_at=CURRENT_TIMESTAMP")
        params.append(chapter_id)
        cursor.execute(f"UPDATE chapters SET {','.join(updates)} WHERE chapter_id=?", params)
        localization = synchronize_chapter_localization(
            db,
            chapter_id,
            database_id=database_id,
        )

        if content and len(content) >= 100:
            version = _next_sequence(cursor, f"CHVER_{chapter_id}")
            cursor.execute(
                "INSERT INTO chapter_versions(chapter_id,version,title,content,word_count,book_id) VALUES (?,?,?,?,?,?)",
                (
                    chapter_id,
                    version,
                    title if title is not None else current["title"],
                    content,
                    len(content),
                    current["book_id"],
                ),
            )
        db.commit()
        log_event(
            db,
            "chapter.save",
            f"Chapter {chapter_id} saved",
            target=chapter_id,
            database_id=get_active_database_id(),
            book_id=current["book_id"],
            success=True,
        )
        return {
            "status": "saved",
            "chapter_id": chapter_id,
            "word_count": len(content) if content is not None else current["word_count"],
            "localization": localization,
        }
    finally:
        db.close()


@router.post("/api/chapters/{chapter_id}/autosave")
def autosave_chapter(
    chapter_id: str,
    payload: ChapterAutosaveRequest | None = None,
    content: str = "",
    title: str = None,
    role: str = Depends(get_current_user_role),
):
    if payload is not None:
        content = payload.content
        title = payload.title
    db = get_db()
    try:
        database_id = _ensure_localizations(db)
        word_count = len(content)
        if title is None:
            cursor = db.execute(
                "UPDATE chapters SET content=?,word_count=?,updated_at=CURRENT_TIMESTAMP WHERE chapter_id=? AND is_active=1",
                (content, word_count, chapter_id),
            )
        else:
            cursor = db.execute(
                "UPDATE chapters SET title=?,content=?,word_count=?,updated_at=CURRENT_TIMESTAMP WHERE chapter_id=? AND is_active=1",
                (title, content, word_count, chapter_id),
            )
        if cursor.rowcount != 1:
            raise HTTPException(404, "Not found")
        localization = synchronize_chapter_localization(
            db,
            chapter_id,
            database_id=database_id,
        )
        db.commit()
        return {
            "status": "autosaved",
            "chapter_id": chapter_id,
            "word_count": word_count,
            "localization": localization,
        }
    finally:
        db.close()


@router.post("/api/chapters/{chapter_id}/versions")
def list_versions(chapter_id: str, role: str = Depends(get_current_user_role)):
    db = get_db()
    try:
        rows = db.execute(
            "SELECT * FROM chapter_versions WHERE chapter_id=? ORDER BY version DESC",
            (chapter_id,),
        ).fetchall()
        return {"versions": [dict(row) for row in rows]}
    finally:
        db.close()


@router.post("/api/chapters/{chapter_id}/analyze")
def analyze_chapter(
    chapter_id: str,
    payload: ChapterAnalyzeRequest | None = None,
    analysis_mode: str = None,
    role: str = Depends(get_current_user_role),
):
    if payload is not None:
        analysis_mode = payload.analysis_mode
    db = get_db()
    try:
        row = db.execute("SELECT * FROM chapters WHERE chapter_id=?", (chapter_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Not found")
        text = row["content"] or ""
        if len(text) < 50:
            raise HTTPException(400, "Chapter too short (min 50 chars)")
        if analysis_mode is None:
            from services.llm_engine.manager import AIEngineManager

            analysis_mode = AIEngineManager.get_analysis_preferences()["default_mode"]
        if analysis_mode == "ask":
            raise HTTPException(
                409,
                detail={
                    "code": "ANALYSIS_MODE_REQUIRED",
                    "message": "Choose local rules or cloud model analysis before analyzing this chapter",
                },
            )
        if analysis_mode not in {"local_rules", "cloud_model"}:
            raise HTTPException(422, "Unsupported analysis mode")
        changeset = ImportPipeline(analysis_mode=analysis_mode).preview(text, book_id=row["book_id"])
        raw_response = "\n\n".join(
            analysis.get("raw_response", "")
            for analysis in changeset.chapter_analyses
            if isinstance(analysis, dict) and analysis.get("raw_response")
        )[:200_000]
        analysis_id = f"ANL_{chapter_id}"
        db.execute(
            "INSERT INTO chapter_analyses(analysis_id,chapter_id,book_id,summary,appearing_entities_json,relation_changes_json,conflicts_json,raw_response,model) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                analysis_id,
                chapter_id,
                row["book_id"],
                text[:200],
                json.dumps(changeset.entities, ensure_ascii=False),
                json.dumps(changeset.relations, ensure_ascii=False),
                json.dumps(changeset.conflicts, ensure_ascii=False),
                raw_response,
                changeset.model,
            ),
        )
        db.execute(
            "UPDATE chapters SET last_analyzed_at=CURRENT_TIMESTAMP,analysis_status='completed' WHERE chapter_id=?",
            (chapter_id,),
        )
        db.commit()
        return {
            "analysis_id": analysis_id,
            "entities_found": len(changeset.entities),
            "relations_found": len(changeset.relations),
            "changeset_ready": True,
            "analysis_mode": analysis_mode,
        }
    except HTTPException:
        raise
    except Exception as exc:
        log.error("Analysis: %s", exc)
        db.rollback()
        raise HTTPException(500, "Analysis failed")
    finally:
        db.close()


@router.post("/api/chapters/{chapter_id}/changeset")
def build_changeset(chapter_id: str, role: str = Depends(get_current_user_role)):
    db = get_db()
    try:
        row = db.execute("SELECT * FROM chapters WHERE chapter_id=?", (chapter_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        analysis = db.execute(
            "SELECT * FROM chapter_analyses WHERE chapter_id=? ORDER BY created_at DESC LIMIT 1",
            (chapter_id,),
        ).fetchone()
        if not analysis:
            raise HTTPException(400, "Run analyze first")
        entities = json.loads(analysis["appearing_entities_json"] or "[]")
        relations = json.loads(analysis["relation_changes_json"] or "[]")
        conflicts = json.loads(analysis["conflicts_json"] or "[]")
        changeset_id = f"CHS_{uuid.uuid4().hex}"
        db.execute(
            "INSERT INTO import_changesets(changeset_id,book_id,source_type,source_chapter_id,entities_json,relations_json,conflicts_json,status) VALUES (?,?,'chapter',?,?,?,?,'pending')",
            (
                changeset_id,
                row["book_id"],
                chapter_id,
                json.dumps(entities, ensure_ascii=False),
                json.dumps(relations, ensure_ascii=False),
                json.dumps(conflicts, ensure_ascii=False),
            ),
        )
        db.commit()
        return {
            "changeset_id": changeset_id,
            "entities": entities,
            "relations": relations,
            "conflicts": conflicts,
            "status": "pending",
        }
    finally:
        db.close()


def _changeset_payload(db, changeset):
    receipt = db.execute(
        "SELECT result_json FROM import_task_receipts WHERE task_id=?",
        (changeset["changeset_id"],),
    ).fetchone()
    result = json.loads(receipt["result_json"]) if receipt else None
    return {
        "changeset_id": changeset["changeset_id"],
        "book_id": changeset["book_id"],
        "source_type": changeset["source_type"],
        "source_chapter_id": changeset["source_chapter_id"],
        "entities": json.loads(changeset["entities_json"] or "[]"),
        "relations": json.loads(changeset["relations_json"] or "[]"),
        "warnings": json.loads(changeset["warnings_json"] or "[]"),
        "conflicts": json.loads(changeset["conflicts_json"] or "[]"),
        "status": changeset["status"],
        "created_at": changeset["created_at"],
        "confirmed_at": changeset["confirmed_at"],
        "result": result,
    }


@router.get("/api/changesets/{changeset_id}")
def get_changeset(changeset_id: str, role: str = Depends(get_current_user_role)):
    db = get_db()
    try:
        changeset = db.execute(
            "SELECT * FROM import_changesets WHERE changeset_id=?",
            (changeset_id,),
        ).fetchone()
        if not changeset:
            raise HTTPException(404, "Changeset not found")
        return _changeset_payload(db, changeset)
    finally:
        db.close()


def _confirm_changeset_id(changeset_id: str):
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        changeset = db.execute(
            "SELECT * FROM import_changesets WHERE changeset_id=?",
            (changeset_id,),
        ).fetchone()
        if not changeset:
            raise HTTPException(404, "Changeset not found")
        if changeset["status"] not in {"pending", "confirmed"}:
            raise HTTPException(409, "Changeset cannot be confirmed")
        entities = json.loads(changeset["entities_json"] or "[]")
        relations = json.loads(changeset["relations_json"] or "[]")
        book_id = changeset["book_id"]
        import_changeset = ImportChangeSet(
            entities=entities,
            relations=relations,
            book_id=book_id,
            source_chapter_id=changeset["source_chapter_id"],
        )
        pipeline = ImportPipeline()
        receipt = db.execute(
            "SELECT result_json FROM import_task_receipts WHERE task_id=?",
            (changeset_id,),
        ).fetchone()
        if receipt:
            if changeset["status"] == "pending":
                db.execute(
                    "UPDATE import_changesets SET status='confirmed',"
                    "confirmed_at=COALESCE(confirmed_at,CURRENT_TIMESTAMP) WHERE changeset_id=?",
                    (changeset_id,),
                )
            db.commit()
            result = pipeline.commit(
                import_changeset,
                db=db,
                idempotency_key=changeset_id,
            )
            return {
                "changeset_id": changeset_id,
                "status": "confirmed",
                "idempotent_replay": True,
                "result": result,
            }
        if changeset["status"] == "confirmed":
            db.rollback()
            raise HTTPException(
                409,
                detail={
                    "code": "CONFIRMATION_RECEIPT_MISSING",
                    "message": "Legacy confirmed changeset has no replay receipt",
                },
            )
        def mark_confirmed(connection):
            cursor = connection.execute(
                "UPDATE import_changesets SET status='confirmed',confirmed_at=CURRENT_TIMESTAMP "
                "WHERE changeset_id=? AND status='pending'",
                (changeset_id,),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Changeset confirmation state changed")

        result = pipeline.commit(
            import_changeset,
            db=db,
            idempotency_key=changeset_id,
            before_commit=mark_confirmed,
        )
        log_event(db, "changeset.confirm", f"Changeset {changeset_id} confirmed")
        return {
            "changeset_id": changeset_id,
            "status": "confirmed",
            "idempotent_replay": False,
            "result": result,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        log.error("Confirm: %s", exc)
        raise HTTPException(500, "Confirm failed")
    finally:
        db.close()


@router.post("/api/changesets/{changeset_id}/confirm")
def confirm_changeset_by_id(
    changeset_id: str,
    role: str = Depends(get_current_user_role),
):
    return _confirm_changeset_id(changeset_id)


@router.post("/api/chapters/{chapter_id}/changeset/confirm")
def confirm_changeset(chapter_id: str, role: str = Depends(get_current_user_role)):
    db = get_db()
    try:
        changeset = db.execute(
            "SELECT changeset_id FROM import_changesets WHERE source_chapter_id=? "
            "ORDER BY created_at DESC,changeset_id DESC LIMIT 1",
            (chapter_id,),
        ).fetchone()
        if not changeset:
            raise HTTPException(404, "Changeset not found")
        changeset_id = changeset["changeset_id"]
    finally:
        db.close()
    return _confirm_changeset_id(changeset_id)


@router.delete("/api/chapters/{chapter_id}")
def delete_chapter(chapter_id: str, _: None = Depends(require_admin)):
    """Soft-delete one localization, or the whole group when deleting its source."""
    db = get_db()
    try:
        _ensure_localizations(db)
        localization = db.execute(
            "SELECT * FROM chapter_localizations WHERE chapter_id=?",
            (chapter_id,),
        ).fetchone()
        if not localization:
            raise HTTPException(404, "Not found")
        if localization["is_source"]:
            cursor = db.execute(
                """UPDATE chapters
                      SET is_active=0,updated_at=CURRENT_TIMESTAMP
                    WHERE chapter_id IN (
                        SELECT chapter_id FROM chapter_localizations
                         WHERE content_group_id=?
                    ) AND is_active=1""",
                (localization["content_group_id"],),
            )
        else:
            cursor = db.execute(
                "UPDATE chapters SET is_active=0,updated_at=CURRENT_TIMESTAMP "
                "WHERE chapter_id=? AND is_active=1",
                (chapter_id,),
            )
        if cursor.rowcount == 0:
            raise HTTPException(404, "Not found")
        db.commit()
        log_event(db, "chapter.delete", f"Chapter {chapter_id} deleted", target=chapter_id, database_id=get_active_database_id(), success=True)
        return {
            "status": "deleted",
            "chapter_id": chapter_id,
            "content_group_id": localization["content_group_id"],
            "deleted_localizations": cursor.rowcount,
        }
    finally:
        db.close()
