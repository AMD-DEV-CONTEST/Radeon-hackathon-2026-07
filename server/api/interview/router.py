"""Interview API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from api.common.schema import MessageResponse, PaginatedResponse
from api.interview.schema import InterviewCreate, InterviewResponse, InterviewUpdate
from api.interview.service import InterviewService
from core.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from api.auth.deps import CurrentUser
from db.database import get_db
from models.enums import InterviewStatus

router = APIRouter(prefix="/interviews", tags=["interview"])


def get_interview_service(db: Annotated[Session, Depends(get_db)]) -> InterviewService:
    return InterviewService(db)


@router.post(
    "",
    response_model=InterviewResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_interview(
    payload: InterviewCreate,
    current_user: CurrentUser,
    service: Annotated[InterviewService, Depends(get_interview_service)],
) -> InterviewResponse:
    return service.create(payload, current_user)


@router.get("", response_model=PaginatedResponse[InterviewResponse])
def list_interviews(
    current_user: CurrentUser,
    service: Annotated[InterviewService, Depends(get_interview_service)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    candidate_id: Annotated[UUID | None, Query()] = None,
    status_filter: Annotated[
        InterviewStatus | None,
        Query(alias="status"),
    ] = None,
) -> PaginatedResponse[InterviewResponse]:
    return service.list(
        current_user,
        skip=skip,
        limit=limit,
        candidate_id=candidate_id,
        status_filter=status_filter,
    )


@router.get("/{interview_id}", response_model=InterviewResponse)
def get_interview(
    interview_id: UUID,
    current_user: CurrentUser,
    service: Annotated[InterviewService, Depends(get_interview_service)],
) -> InterviewResponse:
    return service.get(interview_id, current_user)


@router.patch("/{interview_id}", response_model=InterviewResponse)
def update_interview(
    interview_id: UUID,
    payload: InterviewUpdate,
    current_user: CurrentUser,
    service: Annotated[InterviewService, Depends(get_interview_service)],
) -> InterviewResponse:
    return service.update(interview_id, payload, current_user)


@router.delete("/{interview_id}", response_model=MessageResponse)
def delete_interview(
    interview_id: UUID,
    current_user: CurrentUser,
    service: Annotated[InterviewService, Depends(get_interview_service)],
) -> MessageResponse:
    return service.delete(interview_id, current_user)
