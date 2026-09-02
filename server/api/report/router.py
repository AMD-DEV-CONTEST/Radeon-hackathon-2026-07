"""Report API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from api.common.schema import MessageResponse, PaginatedResponse
from api.report.schema import ReportCreate, ReportResponse, ReportUpdate
from api.report.service import ReportService
from core.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from api.auth.deps import CurrentUser
from db.database import get_db

router = APIRouter(prefix="/reports", tags=["report"])


def get_report_service(db: Annotated[Session, Depends(get_db)]) -> ReportService:
    return ReportService(db)


@router.post("", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
def create_report(
    payload: ReportCreate,
    current_user: CurrentUser,
    service: Annotated[ReportService, Depends(get_report_service)],
) -> ReportResponse:
    return service.create(payload, current_user)


@router.get("", response_model=PaginatedResponse[ReportResponse])
def list_reports(
    current_user: CurrentUser,
    service: Annotated[ReportService, Depends(get_report_service)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    interview_id: Annotated[UUID | None, Query()] = None,
) -> PaginatedResponse[ReportResponse]:
    return service.list(
        current_user,
        skip=skip,
        limit=limit,
        interview_id=interview_id,
    )


@router.get("/by-interview/{interview_id}", response_model=ReportResponse)
def get_report_by_interview(
    interview_id: UUID,
    current_user: CurrentUser,
    service: Annotated[ReportService, Depends(get_report_service)],
) -> ReportResponse:
    return service.get_by_interview(interview_id, current_user)


@router.get("/{report_id}", response_model=ReportResponse)
def get_report(
    report_id: UUID,
    current_user: CurrentUser,
    service: Annotated[ReportService, Depends(get_report_service)],
) -> ReportResponse:
    return service.get(report_id, current_user)


@router.patch("/{report_id}", response_model=ReportResponse)
def update_report(
    report_id: UUID,
    payload: ReportUpdate,
    current_user: CurrentUser,
    service: Annotated[ReportService, Depends(get_report_service)],
) -> ReportResponse:
    return service.update(report_id, payload, current_user)


@router.delete("/{report_id}", response_model=MessageResponse)
def delete_report(
    report_id: UUID,
    current_user: CurrentUser,
    service: Annotated[ReportService, Depends(get_report_service)],
) -> MessageResponse:
    return service.delete(report_id, current_user)
