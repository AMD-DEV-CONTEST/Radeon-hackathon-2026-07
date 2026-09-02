"""Resume business service layer."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from api.candidate.repository import CandidateRepository
from api.common.schema import MessageResponse, PaginatedResponse
from api.resume.repository import ResumeRepository
from api.resume.schema import ResumeCreate, ResumeResponse, ResumeUpdate
from models.user import User
from models.resume import Resume
from core.exceptions import NotFoundError


class ResumeService:
    def __init__(self, db: Session) -> None:
        self.repository = ResumeRepository(db)
        self.candidate_repository = CandidateRepository(db)

    def create(self, payload: ResumeCreate, current_user: User) -> ResumeResponse:
        candidate = self.candidate_repository.get_by_id_for_user(
            payload.candidate_id,
            current_user.id,
        )
        if candidate is None:
            raise NotFoundError("Candidate not found")

        resume = self.repository.create(
            candidate_id=payload.candidate_id,
            file_name=payload.file_name,
            file_path=payload.file_path,
            file_type=payload.file_type,
            file_size=payload.file_size,
            status=payload.status,
            raw_text=payload.raw_text,
            parsed_data=payload.parsed_data,
        )
        return ResumeResponse.model_validate(resume)

    def list(
        self,
        current_user: User,
        *,
        skip: int,
        limit: int,
        candidate_id: UUID | None = None,
    ) -> PaginatedResponse[ResumeResponse]:
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
        )
        return PaginatedResponse[ResumeResponse](
            items=[ResumeResponse.model_validate(item) for item in items],
            total=total,
            skip=skip,
            limit=limit,
        )

    def get(self, resume_id: UUID, current_user: User) -> ResumeResponse:
        resume = self._get_owned_or_404(resume_id, current_user.id)
        return ResumeResponse.model_validate(resume)

    def update(
        self,
        resume_id: UUID,
        payload: ResumeUpdate,
        current_user: User,
    ) -> ResumeResponse:
        resume = self._get_owned_or_404(resume_id, current_user.id)
        updated = self.repository.update(
            resume,
            file_name=payload.file_name,
            file_path=payload.file_path,
            file_type=payload.file_type,
            file_size=payload.file_size,
            status=payload.status,
            raw_text=payload.raw_text,
            parsed_data=payload.parsed_data,
            fields_set=payload.model_fields_set,
        )
        return ResumeResponse.model_validate(updated)

    def delete(self, resume_id: UUID, current_user: User) -> MessageResponse:
        resume = self._get_owned_or_404(resume_id, current_user.id)
        self.repository.delete(resume)
        return MessageResponse(message="Resume deleted")

    def _get_owned_or_404(self, resume_id: UUID, user_id: UUID) -> Resume:
        resume = self.repository.get_by_id_for_user(resume_id, user_id)
        if resume is None:
            raise NotFoundError("Resume not found")
        return resume
