"""Candidate API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from api.candidate.schema import CandidateCreate, CandidateResponse, CandidateUpdate
from api.candidate.service import CandidateService
from api.common.schema import MessageResponse, PaginatedResponse
from core.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from api.auth.deps import CurrentUser
from db.database import get_db

router = APIRouter(prefix="/candidates", tags=["candidate"])


def get_candidate_service(db: Annotated[Session, Depends(get_db)]) -> CandidateService:
    return CandidateService(db)


@router.post(
    "",
    response_model=CandidateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_candidate(
    payload: CandidateCreate,
    current_user: CurrentUser,
    service: Annotated[CandidateService, Depends(get_candidate_service)],
) -> CandidateResponse:
    return service.create(payload, current_user)


@router.get("", response_model=PaginatedResponse[CandidateResponse])
def list_candidates(
    current_user: CurrentUser,
    service: Annotated[CandidateService, Depends(get_candidate_service)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> PaginatedResponse[CandidateResponse]:
    return service.list(current_user, skip=skip, limit=limit)


@router.get("/{candidate_id}", response_model=CandidateResponse)
def get_candidate(
    candidate_id: UUID,
    current_user: CurrentUser,
    service: Annotated[CandidateService, Depends(get_candidate_service)],
) -> CandidateResponse:
    return service.get(candidate_id, current_user)


@router.patch("/{candidate_id}", response_model=CandidateResponse)
def update_candidate(
    candidate_id: UUID,
    payload: CandidateUpdate,
    current_user: CurrentUser,
    service: Annotated[CandidateService, Depends(get_candidate_service)],
) -> CandidateResponse:
    return service.update(candidate_id, payload, current_user)


@router.delete("/{candidate_id}", response_model=MessageResponse)
def delete_candidate(
    candidate_id: UUID,
    current_user: CurrentUser,
    service: Annotated[CandidateService, Depends(get_candidate_service)],
) -> MessageResponse:
    return service.delete(candidate_id, current_user)
