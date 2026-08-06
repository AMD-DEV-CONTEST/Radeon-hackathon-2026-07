from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.dependencies.auth import get_current_user_role, require_admin
from services.database_registry import get_database, get_db_path
from services.vector_store import VectorStore
from services.embedding_tasks import (
    EmbeddingTaskError,
    cancel_embedding_task,
    create_embedding_task,
    get_embedding_task,
    list_embedding_tasks,
    retry_failed_embedding_items,
)
from services.hardware_acceleration import get_hardware_acceleration_status
from services.model_runtime.core_service import get_core_embedding_service


router = APIRouter(prefix="/api/vector-index", tags=["vector_index"])


class EmbeddingTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: str = Field(min_length=1, max_length=100)
    book_id: str | None = Field(default=None, max_length=100)
    entity_ids: list[str] | None = Field(default=None, max_length=5000)


class VectorSpaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: str = Field(min_length=1, max_length=100)


class VectorSpaceAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: str = Field(min_length=1, max_length=100)


class VectorSpaceGarbageCollect(VectorSpaceAction):
    confirm_space_id: str = Field(min_length=1, max_length=80)


def _task_error(exc: EmbeddingTaskError):
    status = 404 if exc.code in {"DATABASE_NOT_FOUND", "EMBEDDING_TASK_NOT_FOUND"} else 409
    return HTTPException(status, detail={"code": exc.code, "message": str(exc)})


def _scoped_store(request: Request, database_id: str) -> VectorStore:
    if not get_database(database_id):
        raise HTTPException(404, "Database not found")
    root_store = request.app.state.vector_store
    if root_store is None:
        raise HTTPException(503, "Vector store is not initialized")
    status = root_store.embedding.status()
    if not status.available:
        raise HTTPException(503, {
            "code": "EMBEDDING_RUNTIME_UNAVAILABLE",
            "message": status.detail,
            "model_id": status.model_id,
        })
    if getattr(root_store.embedding, "manifest", None) is not None:
        core_status = get_core_embedding_service().status()
        if core_status.get("state") == "unavailable":
            raise HTTPException(503, {
                "code": "EMBEDDING_RUNTIME_UNAVAILABLE",
                "message": core_status.get("detail") or "Embedding runtime is unavailable",
                "model_id": status.model_id,
                "runtime_state": core_status.get("state"),
                "last_error_code": core_status.get("last_error_code"),
            })
    store = VectorStore(get_db_path(database_id), root_store.embedding)
    store.init_db()
    return store


@router.get("/runtime-status")
def vector_runtime_status(role: str = Depends(get_current_user_role)):
    return get_hardware_acceleration_status()


@router.post("/runtime/recover")
def recover_vector_runtime(_: None = Depends(require_admin)):
    return get_core_embedding_service().recover()


@router.get("/status")
def vector_index_status(
    database_id: str,
    request: Request,
    role: str = Depends(get_current_user_role),
):
    store = _scoped_store(request, database_id)
    return {
        **store.index_status(),
        "vector_spaces": store.list_vector_spaces(),
    }


@router.get("/spaces")
def get_vector_spaces(
    database_id: str,
    request: Request,
    role: str = Depends(get_current_user_role),
):
    return _scoped_store(request, database_id).list_vector_spaces()


@router.post("/spaces", status_code=202)
def create_vector_space(
    payload: VectorSpaceCreate,
    request: Request,
    _: None = Depends(require_admin),
):
    store = _scoped_store(request, payload.database_id)
    space = None
    try:
        space = store.create_vector_space()
        task = create_embedding_task(
            payload.database_id,
            task_kind="rebuild",
            target_space_id=space["space_id"],
        )
    except (EmbeddingTaskError, ValueError, RuntimeError) as exc:
        if space is not None:
            store.mark_vector_space_failed(
                space["space_id"],
                "BUILD_TASK_CREATE_FAILED",
            )
        if isinstance(exc, EmbeddingTaskError):
            raise _task_error(exc) from exc
        raise HTTPException(
            409,
            detail={"code": "VECTOR_SPACE_CREATE_FAILED", "message": str(exc)},
        ) from exc
    return {"space": space, "task": task}


@router.post("/spaces/{space_id}/validate")
def validate_vector_space(
    space_id: str,
    payload: VectorSpaceAction,
    request: Request,
    _: None = Depends(require_admin),
):
    try:
        return _scoped_store(request, payload.database_id).validate_vector_space(
            space_id
        )
    except KeyError as exc:
        raise HTTPException(404, "Vector space not found") from exc
    except ValueError as exc:
        raise HTTPException(
            409,
            detail={"code": "VECTOR_SPACE_VALIDATION_REJECTED", "message": str(exc)},
        ) from exc


@router.post("/spaces/{space_id}/activate")
def activate_vector_space(
    space_id: str,
    payload: VectorSpaceAction,
    request: Request,
    _: None = Depends(require_admin),
):
    try:
        return _scoped_store(request, payload.database_id).activate_vector_space(
            space_id
        )
    except KeyError as exc:
        raise HTTPException(404, "Vector space not found") from exc
    except ValueError as exc:
        raise HTTPException(
            409,
            detail={"code": "VECTOR_SPACE_ACTIVATION_REJECTED", "message": str(exc)},
        ) from exc


@router.post("/spaces/rollback")
def rollback_vector_space(
    payload: VectorSpaceAction,
    request: Request,
    _: None = Depends(require_admin),
):
    try:
        return _scoped_store(request, payload.database_id).rollback_vector_space()
    except ValueError as exc:
        raise HTTPException(
            409,
            detail={"code": "VECTOR_SPACE_ROLLBACK_UNAVAILABLE", "message": str(exc)},
        ) from exc


@router.post("/spaces/{space_id}/garbage-collect")
def garbage_collect_vector_space(
    space_id: str,
    payload: VectorSpaceGarbageCollect,
    request: Request,
    _: None = Depends(require_admin),
):
    try:
        return _scoped_store(
            request,
            payload.database_id,
        ).garbage_collect_vector_space(
            space_id,
            confirm_space_id=payload.confirm_space_id,
        )
    except KeyError as exc:
        raise HTTPException(404, "Vector space not found") from exc
    except ValueError as exc:
        raise HTTPException(
            409,
            detail={"code": "VECTOR_SPACE_GC_REJECTED", "message": str(exc)},
        ) from exc


@router.post("/rebuild", status_code=202)
def rebuild_vector_index(
    database_id: str,
    request: Request,
    book_id: str | None = None,
    _: None = Depends(require_admin),
):
    store = None
    space = None
    try:
        store = _scoped_store(request, database_id)
        if book_id is not None:
            raise HTTPException(
                409,
                detail={
                    "code": "VECTOR_SPACE_REQUIRES_FULL_SCOPE",
                    "message": "Immutable vector-space rebuilds cover the complete database.",
                },
            )
        space = store.create_vector_space()
        task = create_embedding_task(
            database_id,
            task_kind="rebuild",
            target_space_id=space["space_id"],
        )
        return {"space": space, "task": task}
    except EmbeddingTaskError as exc:
        if store is not None and space is not None:
            store.mark_vector_space_failed(
                space["space_id"],
                "BUILD_TASK_CREATE_FAILED",
            )
        raise _task_error(exc) from exc


@router.post("/tasks", status_code=202)
def create_vector_task(
    payload: EmbeddingTaskCreate,
    _: None = Depends(require_admin),
):
    try:
        return create_embedding_task(
            payload.database_id,
            entity_ids=payload.entity_ids,
            book_id=payload.book_id,
            task_kind="entity_sync" if payload.entity_ids else "rebuild",
        )
    except EmbeddingTaskError as exc:
        raise _task_error(exc) from exc


@router.get("/tasks")
def get_vector_tasks(
    database_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    _: None = Depends(require_admin),
):
    return {"tasks": list_embedding_tasks(database_id, status, limit=limit)}


@router.get("/tasks/{task_id}")
def get_vector_task(task_id: str, _: None = Depends(require_admin)):
    try:
        return get_embedding_task(task_id)
    except EmbeddingTaskError as exc:
        raise _task_error(exc) from exc


@router.post("/tasks/{task_id}/cancel")
def cancel_vector_task(task_id: str, _: None = Depends(require_admin)):
    try:
        return cancel_embedding_task(task_id)
    except EmbeddingTaskError as exc:
        raise _task_error(exc) from exc


@router.post("/tasks/{task_id}/retry-failed", status_code=202)
def retry_vector_task_failures(task_id: str, _: None = Depends(require_admin)):
    try:
        return retry_failed_embedding_items(task_id)
    except EmbeddingTaskError as exc:
        raise _task_error(exc) from exc
