"""Report business service layer."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from api.common.schema import MessageResponse, PaginatedResponse
from api.interview.repository import InterviewRepository
from api.report.repository import ReportRepository
from api.report.schema import ReportCreate, ReportResponse, ReportUpdate
from models.enums import InterviewStatus
from models.user import User
from models.report import Report
from core.exceptions import (
    BadRequestError,
    ConflictError,
    NotFoundError,
)


class ReportService:
    def __init__(self, db: Session) -> None:
        self.repository = ReportRepository(db)
        self.interview_repository = InterviewRepository(db)

    def create(self, payload: ReportCreate, current_user: User) -> ReportResponse:
        interview = self.interview_repository.get_by_id_for_user(
            payload.interview_id,
            current_user.id,
        )
        if interview is None:
            raise NotFoundError("Interview not found")

        interview_status = (
            interview.status
            if isinstance(interview.status, InterviewStatus)
            else InterviewStatus(str(interview.status))
        )
        if interview_status not in {InterviewStatus.COMPLETED, InterviewStatus.LIVE}:
            raise BadRequestError("Reports can only be created for live or completed interviews")

        existing = self.repository.get_by_interview_id(payload.interview_id)
        if existing is not None:
            raise ConflictError("Report already exists for this interview")

        report = self.repository.create(
            interview_id=payload.interview_id,
            overall_score=payload.overall_score,
            recommendation=payload.recommendation,
            performance_confidence=payload.performance_confidence,
            summary=payload.summary,
            executive_note=payload.executive_note,
            competency_matrix=payload.competency_matrix,
            pulse_series=payload.pulse_series,
            export_path=payload.export_path,
        )
        return ReportResponse.model_validate(report)

    def list(
        self,
        current_user: User,
        *,
        skip: int,
        limit: int,
        interview_id: UUID | None = None,
    ) -> PaginatedResponse[ReportResponse]:
        if interview_id is not None:
            interview = self.interview_repository.get_by_id_for_user(
                interview_id,
                current_user.id,
            )
            if interview is None:
                raise NotFoundError("Interview not found")

        items, total = self.repository.list_for_user(
            current_user.id,
            skip=skip,
            limit=limit,
            interview_id=interview_id,
        )
        return PaginatedResponse[ReportResponse](
            items=[ReportResponse.model_validate(item) for item in items],
            total=total,
            skip=skip,
            limit=limit,
        )

    def get(self, report_id: UUID, current_user: User) -> ReportResponse:
        report = self._get_owned_or_404(report_id, current_user.id)
        return ReportResponse.model_validate(report)

    def get_by_interview(
        self,
        interview_id: UUID,
        current_user: User,
    ) -> ReportResponse:
        interview = self.interview_repository.get_by_id_for_user(
            interview_id,
            current_user.id,
        )
        if interview is None:
            raise NotFoundError("Interview not found")

        report = self.repository.get_by_interview_id_for_user(interview_id, current_user.id)
        if report is None:
            raise NotFoundError("Report not found")
        return ReportResponse.model_validate(report)

    def update(
        self,
        report_id: UUID,
        payload: ReportUpdate,
        current_user: User,
    ) -> ReportResponse:
        report = self._get_owned_or_404(report_id, current_user.id)
        updated = self.repository.update(
            report,
            overall_score=payload.overall_score,
            recommendation=payload.recommendation,
            performance_confidence=payload.performance_confidence,
            summary=payload.summary,
            executive_note=payload.executive_note,
            competency_matrix=payload.competency_matrix,
            pulse_series=payload.pulse_series,
            export_path=payload.export_path,
            fields_set=payload.model_fields_set,
        )
        return ReportResponse.model_validate(updated)

    def delete(self, report_id: UUID, current_user: User) -> MessageResponse:
        report = self._get_owned_or_404(report_id, current_user.id)
        self.repository.delete(report)
        return MessageResponse(message="Report deleted")

    def _get_owned_or_404(self, report_id: UUID, user_id: UUID) -> Report:
        report = self.repository.get_by_id_for_user(report_id, user_id)
        if report is None:
            raise NotFoundError("Report not found")
        return report
