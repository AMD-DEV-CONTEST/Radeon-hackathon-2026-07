"""Interview business service layer."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from api.candidate.repository import CandidateRepository
from api.common.schema import MessageResponse, PaginatedResponse
from api.interview.repository import InterviewRepository
from api.interview.schema import InterviewCreate, InterviewResponse, InterviewUpdate
from api.resume.repository import ResumeRepository
from models.enums import InterviewStatus
from models.user import User
from models.interview import Interview
from core.exceptions import (
    BadRequestError,
    NotFoundError,
)

ALLOWED_STATUS_TRANSITIONS: dict[InterviewStatus, set[InterviewStatus]] = {
    InterviewStatus.SCHEDULED: {
        InterviewStatus.LIVE,
        InterviewStatus.CANCELLED,
        InterviewStatus.SCHEDULED,
    },
    InterviewStatus.LIVE: {
        InterviewStatus.COMPLETED,
        InterviewStatus.CANCELLED,
        InterviewStatus.LIVE,
    },
    InterviewStatus.COMPLETED: {InterviewStatus.COMPLETED},
    InterviewStatus.CANCELLED: {InterviewStatus.CANCELLED},
}


class InterviewService:
    def __init__(self, db: Session) -> None:
        self.repository = InterviewRepository(db)
        self.candidate_repository = CandidateRepository(db)
        self.resume_repository = ResumeRepository(db)

    def create(self, payload: InterviewCreate, current_user: User) -> InterviewResponse:
        candidate = self.candidate_repository.get_by_id_for_user(
            payload.candidate_id,
            current_user.id,
        )
        if candidate is None:
            raise NotFoundError("Candidate not found")

        if payload.resume_id is not None:
            resume = self.resume_repository.get_by_id_for_user(
                payload.resume_id,
                current_user.id,
            )
            if resume is None:
                raise NotFoundError("Resume not found")
            if resume.candidate_id != payload.candidate_id:
                raise BadRequestError("Resume does not belong to the selected candidate")

        interview = self.repository.create(
            candidate_id=payload.candidate_id,
            user_id=current_user.id,
            resume_id=payload.resume_id,
            role=payload.role,
            status=payload.status,
            complexity=payload.complexity,
            duration_seconds=payload.duration_seconds,
            started_at=payload.started_at,
            ended_at=payload.ended_at,
        )
        return InterviewResponse.model_validate(interview)

    def list(
        self,
        current_user: User,
        *,
        skip: int,
        limit: int,
        candidate_id: UUID | None = None,
        status_filter: InterviewStatus | None = None,
    ) -> PaginatedResponse[InterviewResponse]:
        if candidate_id is not None:
            candidate = self.candidate_repository.get_by_id_for_user(
                candidate_id,
                current_user.id,
            )
            if candidate is None:
                raise NotFoundError("Candidate not found")

        items, total = self.repository.list_for_user(
            current_user.id,
            skip=skip,
            limit=limit,
            candidate_id=candidate_id,
            status_filter=status_filter,
        )
        return PaginatedResponse[InterviewResponse](
            items=[InterviewResponse.model_validate(item) for item in items],
            total=total,
            skip=skip,
            limit=limit,
        )

    def get(self, interview_id: UUID, current_user: User) -> InterviewResponse:
        interview = self._get_owned_or_404(interview_id, current_user.id)
        return InterviewResponse.model_validate(interview)

    def update(
        self,
        interview_id: UUID,
        payload: InterviewUpdate,
        current_user: User,
    ) -> InterviewResponse:
        interview = self._get_owned_or_404(interview_id, current_user.id)
        fields_set = payload.model_fields_set

        if "resume_id" in fields_set and payload.resume_id is not None:
            resume = self.resume_repository.get_by_id_for_user(
                payload.resume_id,
                current_user.id,
            )
            if resume is None:
                raise NotFoundError("Resume not found")
            if resume.candidate_id != interview.candidate_id:
                raise BadRequestError("Resume does not belong to the interview candidate")

        if "status" in fields_set and payload.status is not None:
            current_status = (
                interview.status
                if isinstance(interview.status, InterviewStatus)
                else InterviewStatus(str(interview.status))
            )
            allowed = ALLOWED_STATUS_TRANSITIONS.get(current_status, set())
            if payload.status not in allowed:
                raise BadRequestError(
                    f"Invalid status transition from '{current_status}' "
                    f"to '{payload.status}'"
                )

        started_at = payload.started_at if "started_at" in fields_set else interview.started_at
        ended_at = payload.ended_at if "ended_at" in fields_set else interview.ended_at
        if started_at and ended_at and ended_at < started_at:
            raise BadRequestError("ended_at must be greater than or equal to started_at")

        updated = self.repository.update(
            interview,
            resume_id=payload.resume_id,
            role=payload.role,
            status=payload.status,
            score=payload.score,
            progress=payload.progress,
            complexity=payload.complexity,
            duration_seconds=payload.duration_seconds,
            started_at=payload.started_at,
            ended_at=payload.ended_at,
            fields_set=fields_set,
        )
        return InterviewResponse.model_validate(updated)

    def delete(self, interview_id: UUID, current_user: User) -> MessageResponse:
        interview = self._get_owned_or_404(interview_id, current_user.id)
        self.repository.delete(interview)
        return MessageResponse(message="Interview deleted")

    def _get_owned_or_404(self, interview_id: UUID, user_id: UUID) -> Interview:
        interview = self.repository.get_by_id_for_user(interview_id, user_id)
        if interview is None:
            raise NotFoundError("Interview not found")
        return interview
