"""Phase F — Task lifecycle API endpoints.

Endpoint ordering matters: static paths MUST come before ``{task_id}``
to prevent ``confirmation-queue`` and ``audit-log`` from being captured
as a task identifier.

Endpoints
---------
POST   /projects/{project_id}/tasks                   create task
GET    /projects/{project_id}/tasks                    list tasks
GET    /projects/{project_id}/tasks/confirmation-queue pending confirmation queue
POST   /projects/{project_id}/tasks/confirmation/{task_id}  process confirmation
GET    /projects/{project_id}/tasks/audit-log          operation audit log
POST   /projects/{project_id}/tasks/extract            extract candidates from text
POST   /projects/{project_id}/tasks/submit-candidates  submit candidates to queue
POST   /projects/{project_id}/tasks/import-preview     preview CSV/XLSX import
POST   /projects/{project_id}/tasks/import-confirm     confirm and execute import
GET    /projects/{project_id}/tasks/{task_id}          get task  (dynamic — keep LAST among GETs)
PATCH  /projects/{project_id}/tasks/{task_id}          update task
POST   /projects/{project_id}/tasks/{task_id}/transition   change status
GET    /projects/{project_id}/tasks/{task_id}/history      status history
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Request, HTTPException, UploadFile, File, Form

from app.observability.error_codes import get_error
from app.schemas.models import (
    CandidateTask,
    ConfirmationAction,
    ConfirmationRecord,
    TaskChangeRecord,
    TaskCreate,
    TaskExtractionRequest,
    TaskExtractionResult,
    TaskImportConfirm,
    TaskImportDiff,
    TaskImportResult,
    TaskRecord,
    TaskStatusTransition,
    TaskUpdate,
    OperationAuditRecord,
)
from app.services.task_lifecycle import TaskLifecycleService
from app.services.projects import ProjectNotFoundError, get_project
from app.security.paths import validate_project_id
from app.security.permissions import get_project_api_user, require_project_api_role

logger = logging.getLogger(__name__)

def _validate_project_scope(project_id: str, request: Request) -> None:
    """Reject malformed or unregistered projects before opening a task DB."""
    settings = request.app.state.settings
    try:
        validate_project_id(project_id)
        get_project(settings.project_root, settings.output_root, project_id)
    except ValueError as error:
        raise _err("PROJECT_ID_INVALID", 422) from error
    except ProjectNotFoundError as error:
        raise _err("PROJECT_NOT_FOUND", 404) from error


router = APIRouter(
    tags=["Phase F — Task Lifecycle"],
    dependencies=[
        Depends(_validate_project_scope),
        Depends(require_project_api_role("guest")),
    ],
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _sqlite_base(sqlite_path: str | Path) -> Path:
    """Normalise *sqlite_path* to a directory (strip trailing filename if any)."""
    p = Path(sqlite_path)
    if not p.is_dir():
        p = p.parent
    return p


def _get_service(request: Request, project_id: str) -> TaskLifecycleService:
    settings = request.app.state.settings
    db_path = _sqlite_base(settings.sqlite_path) / "projects" / project_id / "tasks.db"
    return TaskLifecycleService(db_path)


def _err(code: str, status: int = 400) -> HTTPException:
    detail = get_error(code)
    return HTTPException(status_code=status, detail=detail)


def _authenticated_actor(user: dict | None, submitted_actor: str | None = None) -> str | None:
    """Use the signed-in identity for audit data, never a browser claim."""
    return str(user["username"]) if user is not None else submitted_actor


# ============================================================================
# Static-path routes (MUST come before dynamic {task_id} routes)
# ============================================================================


@router.post(
    "/api/projects/{project_id}/tasks",
    response_model=TaskRecord,
    status_code=201,
    dependencies=[Depends(require_project_api_role("member"))],
)
def create_task(project_id: str, body: TaskCreate, request: Request):
    """Create a new task. If created with *pending_confirmation* status,
    it enters the confirmation queue automatically."""
    try:
        svc = _get_service(request, project_id)
        return svc.create_task(project_id, body)
    except Exception as ex:
        logger.exception("task create failed: %s", ex)
        raise _err("INTERNAL_ERROR", 500)


@router.get("/api/projects/{project_id}/tasks", response_model=list[TaskRecord])
def list_tasks(project_id: str, request: Request, status: str | None = None):
    """List tasks for a project, optionally filtered by status."""
    try:
        svc = _get_service(request, project_id)
        return svc.list_tasks(project_id, status_filter=status)
    except Exception as ex:
        logger.exception("task list failed: %s", ex)
        raise _err("INTERNAL_ERROR", 500)


# -- static: confirmation queue (before {task_id} to avoid capture) ------------


@router.get(
    "/api/projects/{project_id}/tasks/confirmation-queue",
    response_model=list[ConfirmationRecord],
)
def list_confirmation_queue(project_id: str, request: Request, status: str | None = None):
    """List items in the human confirmation queue."""
    try:
        svc = _get_service(request, project_id)
        return svc.list_confirmation_queue(project_id, status_filter=status)
    except Exception as ex:
        logger.exception("confirmation queue list failed: %s", ex)
        raise _err("INTERNAL_ERROR", 500)


@router.post(
    "/api/projects/{project_id}/tasks/confirmation/{task_id}",
    response_model=ConfirmationRecord,
    dependencies=[Depends(require_project_api_role("member"))],
)
def process_confirmation(
    project_id: str,
    task_id: str,
    body: ConfirmationAction,
    request: Request,
    user: dict | None = Depends(get_project_api_user),
):
    """Process a confirmation action (accept / modify / ignore)."""
    try:
        svc = _get_service(request, project_id)
        body = body.model_copy(update={"confirmed_by": _authenticated_actor(user, body.confirmed_by)})
        return svc.process_confirmation(project_id, task_id, body)
    except LookupError:
        raise _err("CONFIRMATION_NOT_FOUND", 404)
    except ValueError:
        raise _err("CONFIRMATION_ALREADY_PROCESSED", 400)
    except Exception as ex:
        logger.exception("confirmation process failed: %s", ex)
        raise _err("INTERNAL_ERROR", 500)


# -- static: audit log (before {task_id} to avoid capture) ---------------------


@router.get(
    "/api/projects/{project_id}/tasks/audit-log",
    response_model=list[OperationAuditRecord],
)
def get_audit_log(project_id: str, request: Request, limit: int = 100):
    """Return recent operation audit entries for a project."""
    try:
        svc = _get_service(request, project_id)
        return svc.get_audit_log(project_id, limit)
    except Exception as ex:
        logger.exception("audit log failed: %s", ex)
        raise _err("INTERNAL_ERROR", 500)


# -- static: extraction & submit -----------------------------------------------


@router.post(
    "/api/projects/{project_id}/tasks/extract",
    response_model=TaskExtractionResult,
    dependencies=[Depends(require_project_api_role("member"))],
)
def extract_tasks(project_id: str, body: TaskExtractionRequest, request: Request):
    """Extract candidate tasks from unstructured text (meeting notes,
    requirements, reports)."""
    try:
        svc = _get_service(request, project_id)
        return svc.extract_candidates(project_id, body.source_text, body.source_kind)
    except Exception as ex:
        logger.exception("task extraction failed: %s", ex)
        raise _err("INTERNAL_ERROR", 500)


@router.post(
    "/api/projects/{project_id}/tasks/submit-candidates",
    response_model=list[ConfirmationRecord],
    status_code=201,
    dependencies=[Depends(require_project_api_role("member"))],
)
def submit_candidates(project_id: str, body: TaskExtractionResult, request: Request):
    """Submit extracted candidates to the confirmation queue."""
    try:
        svc = _get_service(request, project_id)
        return svc.submit_candidates(project_id, body.candidates)
    except Exception as ex:
        logger.exception("submit candidates failed: %s", ex)
        raise _err("INTERNAL_ERROR", 500)


# -- static: import ------------------------------------------------------------


@router.post(
    "/api/projects/{project_id}/tasks/import-preview",
    response_model=TaskImportDiff,
    dependencies=[Depends(require_project_api_role("member"))],
)
async def preview_import(project_id: str, request: Request, file: UploadFile = File(...)):
    """Preview a CSV or XLSX import: returns diff with new/duplicate/conflict
    counts and a row preview. Nothing is persisted."""
    if not file.filename:
        raise _err("IMPORT_FILE_UNSUPPORTED", 400)

    ext = Path(file.filename).suffix.lower()
    if ext not in (".csv", ".xlsx", ".xls"):
        raise _err("IMPORT_FILE_UNSUPPORTED", 400)

    try:
        content = await file.read()
    except Exception:
        raise _err("IMPORT_PARSE_ERROR", 400)

    try:
        svc = _get_service(request, project_id)
        diff, _ = svc.preview_import(project_id, content, file.filename)
        return diff
    except ValueError:
        raise _err("IMPORT_FILE_UNSUPPORTED", 400)
    except Exception as ex:
        logger.exception("import preview failed: %s", ex)
        raise _err("IMPORT_PARSE_ERROR", 400)


@router.post(
    "/api/projects/{project_id}/tasks/import-confirm",
    response_model=TaskImportResult,
    status_code=201,
    dependencies=[Depends(require_project_api_role("member"))],
)
async def confirm_import(
    project_id: str,
    request: Request,
    file: UploadFile = File(...),
    confirmed_by: str | None = Form(default=None),
    skip_duplicates: bool = Form(True),
    overwrite_conflicts: bool = Form(False),
    user: dict | None = Depends(get_project_api_user),
):
    """Confirm and execute a CSV/XLSX import. Use after preview_import."""
    if not file.filename:
        raise _err("IMPORT_FILE_UNSUPPORTED", 400)

    ext = Path(file.filename).suffix.lower()
    if ext not in (".csv", ".xlsx", ".xls"):
        raise _err("IMPORT_FILE_UNSUPPORTED", 400)

    try:
        content = await file.read()
    except Exception:
        raise _err("IMPORT_PARSE_ERROR", 400)

    try:
        svc = _get_service(request, project_id)
        _, candidates = svc.preview_import(project_id, content, file.filename)
        confirm = TaskImportConfirm(
            confirmed_by=_authenticated_actor(user, confirmed_by),
            skip_duplicates=skip_duplicates,
            overwrite_conflicts=overwrite_conflicts,
        )
        return svc.confirm_import(project_id, candidates, content, file.filename, confirm)
    except Exception as ex:
        logger.exception("import confirm failed: %s", ex)
        raise _err("IMPORT_PARSE_ERROR", 400)


# ============================================================================
# Dynamic {task_id} routes (MUST come AFTER all static paths)
# ============================================================================


@router.get("/api/projects/{project_id}/tasks/{task_id}", response_model=TaskRecord)
def get_task(project_id: str, task_id: str, request: Request):
    """Get a single task by id."""
    try:
        svc = _get_service(request, project_id)
        return svc.get_task(project_id, task_id)
    except LookupError:
        raise _err("TASK_NOT_FOUND", 404)
    except Exception as ex:
        logger.exception("task get failed: %s", ex)
        raise _err("INTERNAL_ERROR", 500)


@router.patch(
    "/api/projects/{project_id}/tasks/{task_id}",
    response_model=TaskRecord,
    dependencies=[Depends(require_project_api_role("member"))],
)
def update_task(project_id: str, task_id: str, body: TaskUpdate, request: Request):
    """Update mutable fields of a task."""
    try:
        svc = _get_service(request, project_id)
        return svc.update_task(project_id, task_id, body)
    except LookupError:
        raise _err("TASK_NOT_FOUND", 404)
    except Exception as ex:
        logger.exception("task update failed: %s", ex)
        raise _err("INTERNAL_ERROR", 500)


# -- state machine ------------------------------------------------------------


@router.post(
    "/api/projects/{project_id}/tasks/{task_id}/transition",
    response_model=TaskRecord,
    dependencies=[Depends(require_project_api_role("member"))],
)
def transition_task(
    project_id: str,
    task_id: str,
    body: TaskStatusTransition,
    request: Request,
    user: dict | None = Depends(get_project_api_user),
):
    """Transition a task's status via the allowed state machine."""
    try:
        svc = _get_service(request, project_id)
        body = body.model_copy(update={"changed_by": _authenticated_actor(user, body.changed_by)})
        return svc.transition_status(project_id, task_id, body)
    except LookupError:
        raise _err("TASK_NOT_FOUND", 404)
    except ValueError as ex:
        if "cancelled" in str(ex).lower():
            raise _err("TASK_CANCELLED_FINAL", 400)
        raise _err("TASK_INVALID_TRANSITION", 400)
    except Exception as ex:
        logger.exception("task transition failed: %s", ex)
        raise _err("INTERNAL_ERROR", 500)


@router.get(
    "/api/projects/{project_id}/tasks/{task_id}/history",
    response_model=list[TaskChangeRecord],
)
def get_task_history(project_id: str, task_id: str, request: Request):
    """Return all status change events for a task."""
    try:
        svc = _get_service(request, project_id)
        return svc.get_task_history(project_id, task_id)
    except LookupError:
        raise _err("TASK_NOT_FOUND", 404)
    except Exception as ex:
        logger.exception("task history failed: %s", ex)
        raise _err("INTERNAL_ERROR", 500)
