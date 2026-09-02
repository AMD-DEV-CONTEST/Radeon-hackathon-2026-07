from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse

from app.observability.error_codes import get_error
from app.schemas.models import ProjectFileEntry, UploadResult
from app.security.paths import ensure_project_path
from app.security.permissions import get_current_user, require_project_api_role
from app.services.files import (
    UploadConflictError,
    UploadValidationError,
    list_project_files,
    save_project_upload,
)
from app.services.projects import ProjectNotFoundError


router = APIRouter(
    prefix="/api/projects/{project_id}/files",
    tags=["files"],
)


@router.get("", response_model=list[ProjectFileEntry], dependencies=[Depends(require_project_api_role("guest"))])
def list_files(project_id: str, request: Request) -> list[ProjectFileEntry]:
    try:
        return list_project_files(request.app.state.settings, project_id)
    except ProjectNotFoundError as error:
        err = get_error("PROJECT_NOT_FOUND")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err) from error


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_project_api_role("member"))])
async def upload(
    project_id: str,
    request: Request,
    file: UploadFile = File(...),
    task_file: bool = Form(default=False),
) -> UploadResult:
    try:
        relative_path, result = save_project_upload(
            request.app.state.settings,
            project_id,
            file.filename or "",
            await file.read(),
            task_file=task_file,
        )
        return result
    except ProjectNotFoundError as error:
        err = get_error("PROJECT_NOT_FOUND")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err) from error
    except UploadConflictError as error:
        err = get_error("VALIDATION_ERROR")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=err) from error
    except UploadValidationError as error:
        err = get_error(error.validation.error_code)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=err) from error


@router.get("/download/{filename:path}")
async def download_file(
    project_id: str,
    filename: str,
    request: Request,
    _: dict = Depends(get_current_user),
    __: None = Depends(require_project_api_role("member")),
):
    """Download a file from a project. Requires authenticated user with member+ role.

    Guest users cannot download files.
    """
    settings = request.app.state.settings
    try:
        file_path = ensure_project_path(settings.project_root, project_id, "source", filename)
    except ValueError as error:
        raise HTTPException(status_code=403, detail="Path traversal detected") from error

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="application/octet-stream",
    )
