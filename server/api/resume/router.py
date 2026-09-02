"""Resume API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from api.common.schema import MessageResponse, PaginatedResponse
from api.resume.schema import ResumeCreate, ResumeResponse, ResumeUpdate
from api.resume.service import ResumeService
from core.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from api.auth.deps import CurrentUser
from db.database import get_db

router = APIRouter(prefix="/resumes", tags=["resume"])


def get_resume_service(db: Annotated[Session, Depends(get_db)]) -> ResumeService:
    return ResumeService(db)


@router.post("", response_model=ResumeResponse, status_code=status.HTTP_201_CREATED)
def create_resume(
    payload: ResumeCreate,
    current_user: CurrentUser,
    service: Annotated[ResumeService, Depends(get_resume_service)],
) -> ResumeResponse:
    return service.create(payload, current_user)


@router.get("", response_model=PaginatedResponse[ResumeResponse])
def list_resumes(
    current_user: CurrentUser,
    service: Annotated[ResumeService, Depends(get_resume_service)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    candidate_id: Annotated[UUID | None, Query()] = None,
) -> PaginatedResponse[ResumeResponse]:
    return service.list(
        current_user,
        skip=skip,
        limit=limit,
        candidate_id=candidate_id,
    )


@router.get("/{resume_id}", response_model=ResumeResponse)
def get_resume(
    resume_id: UUID,
    current_user: CurrentUser,
    service: Annotated[ResumeService, Depends(get_resume_service)],
) -> ResumeResponse:
    return service.get(resume_id, current_user)


@router.patch("/{resume_id}", response_model=ResumeResponse)
def update_resume(
    resume_id: UUID,
    payload: ResumeUpdate,
    current_user: CurrentUser,
    service: Annotated[ResumeService, Depends(get_resume_service)],
) -> ResumeResponse:
    return service.update(resume_id, payload, current_user)


@router.delete("/{resume_id}", response_model=MessageResponse)
def delete_resume(
    resume_id: UUID,
    current_user: CurrentUser,
    service: Annotated[ResumeService, Depends(get_resume_service)],
) -> MessageResponse:
    return service.delete(resume_id, current_user)
