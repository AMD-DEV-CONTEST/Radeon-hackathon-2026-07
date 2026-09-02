"""Candidate data access layer."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.candidate import Candidate
from models.enums import Recommendation


class CandidateRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        user_id: UUID,
        name: str,
        email: str,
        title: str | None = None,
        level: str | None = None,
        avatar_url: str | None = None,
        target_role: str | None = None,
        years_of_experience: int | None = None,
        skills: list[str] | None = None,
    ) -> Candidate:
        candidate = Candidate(
            user_id=user_id,
            name=name,
            email=email,
            title=title,
            level=level,
            avatar_url=avatar_url,
            target_role=target_role,
            years_of_experience=years_of_experience,
            skills=skills,
        )
        self.db.add(candidate)
        self.db.commit()
        self.db.refresh(candidate)
        return candidate

    def get_by_id(self, candidate_id: UUID) -> Candidate | None:
        return self.db.get(Candidate, candidate_id)

    def get_by_id_for_user(self, candidate_id: UUID, user_id: UUID) -> Candidate | None:
        statement = select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.user_id == user_id,
        )
        return self.db.scalar(statement)

    def get_by_email_for_user(self, email: str, user_id: UUID) -> Candidate | None:
        statement = select(Candidate).where(
            Candidate.email == email,
            Candidate.user_id == user_id,
        )
        return self.db.scalar(statement)

    def list_for_user(
        self,
        user_id: UUID,
        *,
        skip: int,
        limit: int,
    ) -> tuple[list[Candidate], int]:
        filters = [Candidate.user_id == user_id]
        total = self.db.scalar(select(func.count()).select_from(Candidate).where(*filters)) or 0
        statement = (
            select(Candidate)
            .where(*filters)
            .order_by(Candidate.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        items = list(self.db.scalars(statement))
        return items, total

    def update(
        self,
        candidate: Candidate,
        *,
        name: str | None = None,
        email: str | None = None,
        title: str | None = None,
        level: str | None = None,
        avatar_url: str | None = None,
        target_role: str | None = None,
        years_of_experience: int | None = None,
        skills: list[str] | None = None,
        score: float | None = None,
        recommendation: Recommendation | None = None,
        fields_set: set[str] | None = None,
    ) -> Candidate:
        set_fields = fields_set or set()
        if "name" in set_fields and name is not None:
            candidate.name = name
        if "email" in set_fields and email is not None:
            candidate.email = email
        if "title" in set_fields:
            candidate.title = title
        if "level" in set_fields:
            candidate.level = level
        if "avatar_url" in set_fields:
            candidate.avatar_url = avatar_url
        if "target_role" in set_fields:
            candidate.target_role = target_role
        if "years_of_experience" in set_fields:
            candidate.years_of_experience = years_of_experience
        if "skills" in set_fields:
            candidate.skills = skills
        if "score" in set_fields:
            candidate.score = score
        if "recommendation" in set_fields:
            candidate.recommendation = recommendation

        self.db.add(candidate)
        self.db.commit()
        self.db.refresh(candidate)
        return candidate

    def delete(self, candidate: Candidate) -> None:
        self.db.delete(candidate)
        self.db.commit()
