"""Candidate business service layer."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from api.candidate.repository import CandidateRepository
from api.candidate.schema import CandidateCreate, CandidateResponse, CandidateUpdate
from api.common.schema import MessageResponse, PaginatedResponse
from models.user import User
from models.candidate import Candidate
from core.exceptions import (
    ConflictError,
    NotFoundError,
)


class CandidateService:
    def __init__(self, db: Session) -> None:
        self.repository = CandidateRepository(db)

    def create(self, payload: CandidateCreate, current_user: User) -> CandidateResponse:
        existing = self.repository.get_by_email_for_user(payload.email, current_user.id)
        if existing is not None:
            raise ConflictError("Candidate with this email already exists")

        candidate = self.repository.create(
            user_id=current_user.id,
            name=payload.name,
            email=payload.email,
            title=payload.title,
            level=payload.level,
            avatar_url=payload.avatar_url,
            target_role=payload.target_role,
            years_of_experience=payload.years_of_experience,
            skills=payload.skills,
        )
        return CandidateResponse.model_validate(candidate)

    def list(
        self,
        current_user: User,
        *,
        skip: int,
        limit: int,
    ) -> PaginatedResponse[CandidateResponse]:
        items, total = self.repository.list_for_user(
            current_user.id,
            skip=skip,
            limit=limit,
        )
        return PaginatedResponse[CandidateResponse](
            items=[CandidateResponse.model_validate(item) for item in items],
            total=total,
            skip=skip,
            limit=limit,
        )

    def get(self, candidate_id: UUID, current_user: User) -> CandidateResponse:
        candidate = self._get_owned_or_404(candidate_id, current_user.id)
        return CandidateResponse.model_validate(candidate)

    def update(
        self,
        candidate_id: UUID,
        payload: CandidateUpdate,
        current_user: User,
    ) -> CandidateResponse:
        candidate = self._get_owned_or_404(candidate_id, current_user.id)
        fields_set = payload.model_fields_set

        if "email" in fields_set and payload.email is not None:
            existing = self.repository.get_by_email_for_user(payload.email, current_user.id)
            if existing is not None and existing.id != candidate.id:
                raise ConflictError("Candidate with this email already exists")

        updated = self.repository.update(
            candidate,
            name=payload.name,
            email=payload.email,
            title=payload.title,
            level=payload.level,
            avatar_url=payload.avatar_url,
            target_role=payload.target_role,
            years_of_experience=payload.years_of_experience,
            skills=payload.skills,
            score=payload.score,
            recommendation=payload.recommendation,
            fields_set=fields_set,
        )
        return CandidateResponse.model_validate(updated)

    def delete(self, candidate_id: UUID, current_user: User) -> MessageResponse:
        candidate = self._get_owned_or_404(candidate_id, current_user.id)
        self.repository.delete(candidate)
        return MessageResponse(message="Candidate deleted")

    def _get_owned_or_404(self, candidate_id: UUID, user_id: UUID) -> Candidate:
        candidate = self.repository.get_by_id_for_user(candidate_id, user_id)
        if candidate is None:
            raise NotFoundError("Candidate not found")
        return candidate
