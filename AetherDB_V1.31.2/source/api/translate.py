"""Scoped entity translations and review-gated chapter translation tasks."""

from __future__ import annotations

import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.dependencies.auth import (
    get_current_user_role,
    require_capability,
)
from app.deployment import EffectivePrincipal
from services.audit_log import log_event
from services.database_registry import get_active_database_id
from services.db import get_db
from services.model_execution import ModelTaskRequest, get_default_gateway
from services.model_reliability import (
    FallbackRequired,
    ModelExecutionError,
    normalize_model_error,
)
from services.model_routing import ModelRouteError
from services.translation_service import (
    approve_chapter_translation,
    complete_chapter_translation,
    fail_chapter_translation,
    list_chapter_translations,
    mark_chapter_translation_stale,
    prepare_chapter_translation,
    reconcile_entity_translations,
    reject_chapter_translation,
    review_chapter_localization,
    review_entity_translation,
    save_entity_translation,
    translation_messages,
    update_chapter_translation_draft,
)


router = APIRouter(tags=["translation"])
log = logging.getLogger(__name__)
require_translation_management = require_capability("manage_translations")


class EntityTranslationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    book_id: str | None = Field(default=None, max_length=100)
    language: str = Field(min_length=2, max_length=35)
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(default="", max_length=500_000)
    full_content: str = Field(default="", max_length=2_000_000)
    ai_summary: str = Field(default="", max_length=20_000)


class EntityTranslationReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "reject"]
    expected_source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ChapterTranslationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    target_language_code: str = Field(min_length=2, max_length=35)
    model_profile_id: str | None = Field(default=None, max_length=128)
    cloud_upload_confirmed: bool = False
    request_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9:._-]+$",
    )


class ChapterTranslationDraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=2_000_000)


class TranslationApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_source_revision_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ChapterLocalizationReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "reject"]
    expected_source_revision_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def get_translation_gateway():
    return get_default_gateway()


def _audit(
    db,
    event_type: str,
    target: str,
    *,
    database_id: str,
    book_id: str,
    details: dict | None = None,
    success: bool = True,
) -> None:
    log_event(
        db,
        event_type,
        "Translation workflow state changed",
        target=target,
        database_id=database_id,
        book_id=book_id,
        details=json.dumps(details or {}, ensure_ascii=False, separators=(",", ":")),
        success=success,
    )


def _reviewer(principal: EffectivePrincipal) -> str:
    return principal.effective_role.value


@router.get("/api/translations/models")
def list_translation_models(
    _: EffectivePrincipal = Depends(require_translation_management),
):
    from services.model_registry import (
        get_provider,
        list_model_profiles,
    )

    models = []
    for profile in list_model_profiles():
        provider = get_provider(profile["provider_id"])
        if not provider or not provider["enabled"] or not profile["enabled"]:
            continue
        provider_type = provider["provider_type"]
        is_local = (
            profile["privacy_level"] == "local_only"
            or provider_type in {"local", "local_ollama", "ollama"}
        )
        models.append(
            {
                "model_profile_id": profile["id"],
                "display_name": profile["display_name"],
                "provider_id": provider["id"],
                "provider_name": provider["display_name"],
                "provider_model_name": profile["provider_model_name"],
                "privacy_level": profile["privacy_level"],
                "is_local": is_local,
                "health_status": profile["health_status"],
            }
        )
    models.sort(key=lambda item: (not item["is_local"], item["display_name"].lower()))
    return {
        "automatic_routing_available": True,
        "default_privacy": "local_only",
        "models": models,
    }


@router.post("/api/entity/{entity_id}/translate")
def set_entity_translation(
    entity_id: str,
    body: EntityTranslationCreate,
    principal: EffectivePrincipal = Depends(require_translation_management),
):
    database_id = get_active_database_id()
    db = get_db(database_id)
    try:
        try:
            row = save_entity_translation(
                db,
                entity_id=entity_id,
                language_code=body.language,
                title=body.title,
                content=body.content,
                full_content=body.full_content,
                ai_summary=body.ai_summary,
                requested_book_id=body.book_id,
            )
        except LookupError as exc:
            raise HTTPException(404, "Entity not found") from exc
        except PermissionError as exc:
            raise HTTPException(
                409,
                detail={
                    "code": "ENTITY_TRANSLATION_SCOPE_MISMATCH",
                    "message": "Entity does not belong to the requested book",
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                422,
                detail={"code": "INVALID_TRANSLATION", "message": str(exc)},
            ) from exc
        db.commit()
        _audit(
            db,
            "entity.translation.draft",
            str(row["id"]),
            database_id=database_id,
            book_id=row["book_id"],
            details={
                "entity_id": entity_id,
                "target_language": row["language"],
                "status": row["translation_status"],
                "reviewer_role": _reviewer(principal),
            },
        )
        return row
    finally:
        db.close()


@router.get("/api/entity/{entity_id}/translations")
def get_entity_translations(
    entity_id: str,
    role: str = Depends(get_current_user_role),
):
    database_id = get_active_database_id()
    db = get_db(database_id)
    try:
        try:
            _, translations = reconcile_entity_translations(db, entity_id)
        except LookupError as exc:
            raise HTTPException(404, "Entity not found") from exc
        db.commit()
        return translations
    finally:
        db.close()


@router.post("/api/entity-translations/{translation_id}/review")
def review_entity_translation_api(
    translation_id: int,
    body: EntityTranslationReview,
    principal: EffectivePrincipal = Depends(require_translation_management),
):
    database_id = get_active_database_id()
    db = get_db(database_id)
    try:
        try:
            row = review_entity_translation(
                db,
                translation_id=translation_id,
                action=body.action,
                expected_source_hash=body.expected_source_hash,
                reviewed_by=_reviewer(principal),
            )
        except LookupError as exc:
            raise HTTPException(404, "Entity translation not found") from exc
        except RuntimeError as exc:
            db.commit()
            raise HTTPException(
                409,
                detail={
                    "code": "TRANSLATION_SOURCE_CHANGED",
                    "message": "The source entity changed before review",
                },
            ) from exc
        db.commit()
        _audit(
            db,
            f"entity.translation.{body.action}",
            str(translation_id),
            database_id=database_id,
            book_id=row["book_id"],
            details={
                "entity_id": row["entity_id"],
                "target_language": row["language"],
                "status": row["translation_status"],
            },
        )
        return row
    finally:
        db.close()


def _fail_and_raise(
    database_id: str,
    translation_id: str,
    *,
    code: str,
    message: str,
    status_code: int,
    detail: dict | None = None,
) -> None:
    db = get_db(database_id)
    try:
        task = fail_chapter_translation(
            db,
            translation_id=translation_id,
            error_code=code,
            error_message=message,
        )
        db.commit()
        _audit(
            db,
            "chapter.translation.failed",
            translation_id,
            database_id=database_id,
            book_id=task["book_id"],
            details={"error_code": code},
            success=False,
        )
    finally:
        db.close()
    payload = detail or {"code": code, "message": message}
    raise HTTPException(status_code, detail=payload)


@router.post("/api/chapters/{chapter_id}/translations")
async def create_chapter_translation(
    chapter_id: str,
    body: ChapterTranslationCreate,
    principal: EffectivePrincipal = Depends(require_translation_management),
    gateway=Depends(get_translation_gateway),
):
    database_id = get_active_database_id()
    db = get_db(database_id)
    try:
        try:
            prepared = prepare_chapter_translation(
                db,
                chapter_id=chapter_id,
                target_language_code=body.target_language_code,
                request_id=body.request_id,
                database_id=database_id,
                cloud_upload_confirmed=body.cloud_upload_confirmed,
            )
        except LookupError as exc:
            raise HTTPException(404, "Chapter not found") from exc
        except ValueError as exc:
            raise HTTPException(
                422,
                detail={"code": "INVALID_TRANSLATION_REQUEST", "message": str(exc)},
            ) from exc
        db.commit()
        task = prepared["task"]
        source = prepared["source"]
        if prepared["reused"]:
            if task["task_status"] == "running":
                raise HTTPException(
                    409,
                    detail={
                        "code": "TRANSLATION_ALREADY_RUNNING",
                        "message": "The idempotent translation request is already running",
                        "translation_id": task["translation_id"],
                    },
                )
            return {"status": "replayed", "translation": task}
        _audit(
            db,
            "chapter.translation.start",
            task["translation_id"],
            database_id=database_id,
            book_id=task["book_id"],
            details={
                "source_chapter_id": task["source_chapter_id"],
                "target_language": task["target_language_code"],
                "cloud_upload_confirmed": task["cloud_upload_confirmed"],
                "reviewer_role": _reviewer(principal),
            },
        )
    finally:
        db.close()

    model_request = ModelTaskRequest(
        task_id=task["translation_id"],
        task_type="translation.chapter",
        database_id=database_id,
        book_id=task["book_id"],
        messages=translation_messages(
            source,
            target_language_code=task["target_language_code"],
        ),
        user_selected_model_id=body.model_profile_id,
        privacy_level="private" if body.cloud_upload_confirmed else "local_only",
        requires_json=False,
        requires_streaming=False,
        metadata={"ui_source": "chapter_translation"},
    )
    try:
        result = await gateway.execute(model_request)
    except ModelRouteError as exc:
        route = exc.result
        _fail_and_raise(
            database_id,
            task["translation_id"],
            code=f"MODEL_ROUTE_{route.status.value.upper()}",
            message="A unique compatible translation model could not be selected",
            status_code=409,
            detail={
                "code": f"MODEL_ROUTE_{route.status.value.upper()}",
                "message": "Choose one compatible model before translating",
                "reason": route.reason,
                "candidates": [
                    {"model_profile_id": candidate.model_profile_id}
                    for candidate in route.candidates
                ],
                "translation_id": task["translation_id"],
            },
        )
    except FallbackRequired as exc:
        _fail_and_raise(
            database_id,
            task["translation_id"],
            code="FALLBACK_CONFIRMATION_REQUIRED",
            message="The selected model failed and fallback requires confirmation",
            status_code=409,
            detail={
                "code": "FALLBACK_CONFIRMATION_REQUIRED",
                "message": "Fallback was not performed; choose another model explicitly",
                "candidates": [
                    {"model_profile_id": model_id}
                    for model_id in exc.candidate_model_ids
                ],
                "translation_id": task["translation_id"],
            },
        )
    except Exception as exc:
        normalized = (
            exc if isinstance(exc, ModelExecutionError) else normalize_model_error(exc)
        )
        _fail_and_raise(
            database_id,
            task["translation_id"],
            code=normalized.code.value,
            message="Translation model execution failed",
            status_code=502,
        )

    db = get_db(database_id)
    try:
        try:
            translation = complete_chapter_translation(
                db,
                translation_id=task["translation_id"],
                output=result.content,
                source_title=source["title"],
                model_profile_id=result.model_profile_id,
                provider_id=result.provider_id,
                provider_model_name=result.provider_model_name,
                provider_request_id=result.raw_provider_request_id,
            )
        except ValueError as exc:
            db.rollback()
            _fail_and_raise(
                database_id,
                task["translation_id"],
                code="OUTPUT_SCHEMA_INVALID",
                message=str(exc),
                status_code=502,
            )
        except RuntimeError as exc:
            db.rollback()
            raise HTTPException(
                409,
                detail={
                    "code": "TRANSLATION_SOURCE_CHANGED",
                    "message": "The source chapter changed while translation was running",
                },
            ) from exc
        db.commit()
        _audit(
            db,
            "chapter.translation.generated",
            translation["translation_id"],
            database_id=database_id,
            book_id=translation["book_id"],
            details={
                "model_profile_id": translation["model_profile_id"],
                "provider_id": translation["provider_id"],
                "provider_model_name": translation["provider_model_name"],
                "output_format": translation["output_format"],
            },
        )
        return {"status": "review_required", "translation": translation}
    finally:
        db.close()


@router.get("/api/chapters/{chapter_id}/translations")
def get_chapter_translations(
    chapter_id: str,
    role: str = Depends(get_current_user_role),
):
    database_id = get_active_database_id()
    db = get_db(database_id)
    try:
        try:
            source, translations = list_chapter_translations(
                db,
                chapter_id=chapter_id,
                database_id=database_id,
            )
        except LookupError as exc:
            raise HTTPException(404, "Chapter not found") from exc
        db.commit()
        return {
            "source": source,
            "translations": translations,
        }
    finally:
        db.close()


@router.put("/api/translations/{translation_id}")
def update_chapter_translation(
    translation_id: str,
    body: ChapterTranslationDraftUpdate,
    principal: EffectivePrincipal = Depends(require_translation_management),
):
    database_id = get_active_database_id()
    db = get_db(database_id)
    try:
        try:
            task = update_chapter_translation_draft(
                db,
                translation_id=translation_id,
                title=body.title,
                content=body.content,
            )
        except RuntimeError as exc:
            raise HTTPException(
                409,
                detail={
                    "code": "TRANSLATION_DRAFT_NOT_EDITABLE",
                    "message": "This translation draft is no longer editable",
                },
            ) from exc
        db.commit()
        _audit(
            db,
            "chapter.translation.draft.save",
            translation_id,
            database_id=database_id,
            book_id=task["book_id"],
            details={"reviewer_role": _reviewer(principal)},
        )
        return {"translation": task}
    finally:
        db.close()


@router.post("/api/translations/{translation_id}/approve")
def approve_chapter_translation_api(
    translation_id: str,
    body: TranslationApproval,
    principal: EffectivePrincipal = Depends(require_translation_management),
):
    database_id = get_active_database_id()
    db = get_db(database_id)
    try:
        try:
            task, chapter, localizations = approve_chapter_translation(
                db,
                translation_id=translation_id,
                expected_source_revision_hash=body.expected_source_revision_hash,
                reviewed_by=_reviewer(principal),
                database_id=database_id,
            )
        except LookupError as exc:
            raise HTTPException(404, "Translation task not found") from exc
        except RuntimeError as exc:
            if str(exc) == "source revision changed":
                db.commit()
                raise HTTPException(
                    409,
                    detail={
                        "code": "TRANSLATION_SOURCE_CHANGED",
                        "message": "The source chapter changed before approval",
                    },
                ) from exc
            raise HTTPException(
                409,
                detail={
                    "code": "TRANSLATION_NOT_REVIEWABLE",
                    "message": "Translation is not ready for approval",
                },
            ) from exc
        db.commit()
        _audit(
            db,
            "chapter.translation.approve",
            translation_id,
            database_id=database_id,
            book_id=task["book_id"],
            details={
                "source_chapter_id": task["source_chapter_id"],
                "target_chapter_id": chapter["chapter_id"],
                "target_language": task["target_language_code"],
            },
        )
        return {
            "status": "approved",
            "translation": task,
            "chapter": chapter,
            "localizations": localizations,
        }
    finally:
        db.close()


@router.post("/api/translations/{translation_id}/reject")
def reject_chapter_translation_api(
    translation_id: str,
    principal: EffectivePrincipal = Depends(require_translation_management),
):
    database_id = get_active_database_id()
    db = get_db(database_id)
    try:
        try:
            task = reject_chapter_translation(
                db,
                translation_id=translation_id,
                reviewed_by=_reviewer(principal),
            )
        except RuntimeError as exc:
            raise HTTPException(
                409,
                detail={
                    "code": "TRANSLATION_NOT_REVIEWABLE",
                    "message": "Translation cannot be rejected in its current state",
                },
            ) from exc
        db.commit()
        _audit(
            db,
            "chapter.translation.reject",
            translation_id,
            database_id=database_id,
            book_id=task["book_id"],
        )
        return {"status": "rejected", "translation": task}
    finally:
        db.close()


@router.post("/api/translations/{translation_id}/mark-stale")
def mark_chapter_translation_stale_api(
    translation_id: str,
    principal: EffectivePrincipal = Depends(require_translation_management),
):
    database_id = get_active_database_id()
    db = get_db(database_id)
    try:
        try:
            task = mark_chapter_translation_stale(
                db,
                translation_id=translation_id,
            )
        except RuntimeError as exc:
            raise HTTPException(
                409,
                detail={
                    "code": "TRANSLATION_ALREADY_STALE",
                    "message": "Translation cannot be marked stale in its current state",
                },
            ) from exc
        db.commit()
        _audit(
            db,
            "chapter.translation.mark_stale",
            translation_id,
            database_id=database_id,
            book_id=task["book_id"],
            details={"reviewer_role": _reviewer(principal)},
        )
        return {"status": "stale", "translation": task}
    finally:
        db.close()


@router.post("/api/chapters/{chapter_id}/translation-review")
def review_chapter_localization_api(
    chapter_id: str,
    body: ChapterLocalizationReview,
    principal: EffectivePrincipal = Depends(require_translation_management),
):
    database_id = get_active_database_id()
    db = get_db(database_id)
    try:
        try:
            chapter = review_chapter_localization(
                db,
                chapter_id=chapter_id,
                action=body.action,
                expected_source_revision_hash=body.expected_source_revision_hash,
                database_id=database_id,
            )
        except LookupError as exc:
            raise HTTPException(404, "Chapter localization not found") from exc
        except ValueError as exc:
            raise HTTPException(
                422,
                detail={"code": "INVALID_TRANSLATION_REVIEW", "message": str(exc)},
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                409,
                detail={
                    "code": "TRANSLATION_SOURCE_CHANGED",
                    "message": "The source chapter changed before review",
                },
            ) from exc
        db.commit()
        _audit(
            db,
            f"chapter.localization.{body.action}",
            chapter_id,
            database_id=database_id,
            book_id=chapter["book_id"],
            details={
                "target_language": chapter["language_code"],
                "reviewer_role": _reviewer(principal),
            },
        )
        return {"status": body.action, "chapter": chapter}
    finally:
        db.close()
