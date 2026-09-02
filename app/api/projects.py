from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.schemas import Project, ProjectCreate
from app.services.projects import (
    ProjectAlreadyExistsError,
    ProjectNotFoundError,
    create_project,
    get_project,
    list_projects,
)
from app.security.permissions import (
    get_project_api_user,
    get_project_role,
    has_min_role,
    require_project_creation_permission,
)


router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[Project])
def list_all(request: Request, user: dict | None = Depends(get_project_api_user)) -> list[Project]:
    settings = request.app.state.settings
    projects = list_projects(settings.project_root, settings.output_root)
    if not settings.enforce_project_authorization:
        return projects
    assert user is not None
    return [
        project for project in projects
        if has_min_role(get_project_role(request.app.state.db_path, project.project_id, user["user_id"]), "guest")
    ]


@router.post(
    "",
    response_model=Project,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_project_creation_permission)],
)
def create(payload: ProjectCreate, request: Request, user: dict | None = Depends(get_project_api_user)) -> Project:
    settings = request.app.state.settings
    try:
        project = create_project(settings.project_root, settings.output_root, payload)
        if settings.enforce_project_authorization:
            assert user is not None
            request.app.state.membership_service.add_member(project.project_id, user["user_id"], "admin")
        return project
    except ProjectAlreadyExistsError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="project already exists") from error


@router.get("/{project_id}", response_model=Project)
def get(project_id: str, request: Request, user: dict | None = Depends(get_project_api_user)) -> Project:
    if request.app.state.settings.enforce_project_authorization:
        assert user is not None
        role = get_project_role(request.app.state.db_path, project_id, user["user_id"])
        if not has_min_role(role, "guest"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="access denied")
    settings = request.app.state.settings
    try:
        return get_project(settings.project_root, settings.output_root, project_id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    except ProjectNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found") from error
