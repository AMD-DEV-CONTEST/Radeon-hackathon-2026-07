"""Repository boundary for database access."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from buildguard.storage.models import (
    Base,
    CameraStatusModel,
    InspectionResultModel,
    MessageModel,
    PerformanceLogModel,
    RagChunkModel,
    RagDocumentModel,
    RealtimeEventModel,
    ReportModel,
    RiskEventModel,
    SecurityAuditLogModel,
    SessionModel,
    TaskModel,
    ToolCallModel,
    UploadedEvidenceModel,
)

ModelT = TypeVar("ModelT", bound=Base)


class Repository(Generic[ModelT]):
    """Typed CRUD operations for one mapped model."""

    def __init__(self, session: Session, model: type[ModelT]) -> None:
        self.session = session
        self.model = model

    def create(self, **values: Any) -> ModelT:
        entity = self.model(**values)
        self.session.add(entity)
        self.session.flush()
        return entity

    def get(self, entity_id: str) -> ModelT | None:
        return self.session.get(self.model, entity_id)

    def list(self, *, offset: int = 0, limit: int = 100) -> Sequence[ModelT]:
        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("offset must be non-negative and limit must be 1..1000")
        return self.session.scalars(select(self.model).offset(offset).limit(limit)).all()

    def update(self, entity_id: str, **values: Any) -> ModelT:
        entity = self.get(entity_id)
        if entity is None:
            raise KeyError(f"{self.model.__name__} not found: {entity_id}")
        for key, value in values.items():
            if key in {"id", "created_at"} or not hasattr(entity, key):
                raise ValueError(f"Field cannot be updated: {key}")
            setattr(entity, key, value)
        self.session.flush()
        return entity

    def delete(self, entity_id: str) -> bool:
        entity = self.get(entity_id)
        if entity is None:
            return False
        self.session.delete(entity)
        self.session.flush()
        return True


class Repositories:
    """Repository collection scoped to one SQLAlchemy transaction."""

    def __init__(self, session: Session) -> None:
        self.sessions = Repository(session, SessionModel)
        self.messages = Repository(session, MessageModel)
        self.tasks = Repository(session, TaskModel)
        self.tool_calls = Repository(session, ToolCallModel)
        self.uploaded_evidence = Repository(session, UploadedEvidenceModel)
        self.inspections = Repository(session, InspectionResultModel)
        self.risk_events = Repository(session, RiskEventModel)
        self.reports = Repository(session, ReportModel)
        self.rag_documents = Repository(session, RagDocumentModel)
        self.rag_chunks = Repository(session, RagChunkModel)
        self.performance = Repository(session, PerformanceLogModel)
        self.audit = Repository(session, SecurityAuditLogModel)
        self.camera_statuses = Repository(session, CameraStatusModel)
        self.realtime_events = Repository(session, RealtimeEventModel)
