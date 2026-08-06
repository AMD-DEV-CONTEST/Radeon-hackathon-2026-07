"""SQLite-backed long-term task and conversation memory."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal

from pydantic import Field
from sqlalchemy import delete, select

from buildguard.reporting.builder import ReportArtifact, ReportDraft
from buildguard.schemas.common import StrictSchema
from buildguard.schemas.vision import InspectionResult, RiskAssessment
from buildguard.storage.database import Database
from buildguard.storage.models import (
    InspectionResultModel,
    MessageModel,
    PerformanceLogModel,
    ReportModel,
    RiskEventModel,
    SecurityAuditLogModel,
    SessionModel,
    TaskModel,
    ToolCallModel,
    VerifiedFactModel,
)
from buildguard.tools.schemas import ToolAuditEntry

LOGGER = logging.getLogger(__name__)


class StoredTask(StrictSchema):
    id: str
    session_id: str
    title: str
    description: str
    status: str
    result: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class LongTermMemory:
    """Persist user-visible state and reusable inspection artifacts."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.database.initialize()

    @staticmethod
    def _task(entity: TaskModel) -> StoredTask:
        return StoredTask(
            id=entity.id,
            session_id=entity.session_id,
            title=entity.title,
            description=entity.description,
            status=entity.status,
            result=entity.plan_json or {},
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    @staticmethod
    def title_from_message(message: str, session_id: str) -> str:
        """Build a compact deterministic title without another LLM call."""
        summary = " ".join(message.split()).strip() or "新对话"
        if len(summary) > 32:
            summary = f"{summary[:31]}…"
        return f"{summary} · {session_id[:6]}"

    def ensure_session(self, session_id: str, title: str | None = None) -> str:
        with self.database.session() as session:
            entity = session.get(SessionModel, session_id)
            if entity is None:
                session.add(
                    SessionModel(
                        id=session_id,
                        title=title or self.title_from_message("", session_id),
                        status="active",
                    )
                )
        return session_id

    def add_message(
        self,
        session_id: str,
        role: Literal["system", "user", "assistant", "tool"],
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self.ensure_session(session_id)
        with self.database.session() as session:
            entity = MessageModel(
                session_id=session_id,
                role=role,
                content=content,
                metadata_json=metadata or {},
            )
            session.add(entity)
            session.flush()
            return entity.id

    def create_task(
        self,
        session_id: str,
        title: str,
        description: str,
        *,
        task_id: str | None = None,
        status: str = "running",
        result: dict[str, Any] | None = None,
    ) -> StoredTask:
        self.ensure_session(session_id)
        with self.database.session() as session:
            entity = TaskModel(
                session_id=session_id,
                title=title,
                description=description,
                status=status,
                plan_json=result or {},
            )
            if task_id is not None:
                entity.id = task_id
            session.add(entity)
            session.flush()
            return self._task(entity)

    def update_task(
        self,
        task_id: str,
        *,
        status: str,
        result: dict[str, Any],
    ) -> StoredTask:
        with self.database.session() as session:
            entity = session.get(TaskModel, task_id)
            if entity is None:
                raise KeyError(f"Task not found: {task_id}")
            entity.status = status
            entity.plan_json = result
            session.flush()
            session.refresh(entity)
            return self._task(entity)

    def get_task(self, task_id: str) -> StoredTask | None:
        with self.database.session() as session:
            entity = session.get(TaskModel, task_id)
            return self._task(entity) if entity is not None else None

    def list_tasks(
        self,
        *,
        session_id: str | None = None,
        risk: str | None = None,
        limit: int = 100,
    ) -> list[StoredTask]:
        if not 1 <= limit <= 1000:
            raise ValueError("Task limit must be within 1..1000")
        with self.database.session() as session:
            statement = select(TaskModel)
            if session_id is not None:
                statement = statement.where(TaskModel.session_id == session_id)
            entities = session.scalars(
                statement.order_by(TaskModel.created_at.desc()).limit(limit)
            ).all()
            tasks = [self._task(entity) for entity in entities]
        if risk is not None:
            tasks = [task for task in tasks if task.result.get("max_risk") == risk]
        return tasks

    def previous_completed(
        self,
        session_id: str,
        *,
        excluding_task_id: str | None = None,
    ) -> StoredTask | None:
        tasks = self.list_tasks(session_id=session_id, limit=100)
        return next(
            (
                task
                for task in tasks
                if task.status == "completed"
                and task.id != excluding_task_id
                and task.result.get("inspections")
            ),
            None,
        )

    def save_inspection(
        self,
        session_id: str,
        inspection: InspectionResult,
        risks: list[RiskAssessment],
    ) -> str:
        self.ensure_session(session_id)
        with self.database.session() as session:
            entity = InspectionResultModel(
                session_id=session_id,
                source_path=str(inspection.source_path.resolve()),
                detections_json=[item.model_dump(mode="json") for item in inspection.detections],
                risks_json=[item.model_dump(mode="json") for item in risks],
                model_name=inspection.model_name,
                processing_ms=inspection.processing_ms,
                success=inspection.success,
                error=inspection.error,
            )
            session.add(entity)
            session.flush()
            return entity.id

    def find_inspection(
        self,
        session_id: str,
        source_path: str,
    ) -> tuple[InspectionResult, list[RiskAssessment]] | None:
        with self.database.session() as session:
            entity = session.scalar(
                select(InspectionResultModel)
                .where(
                    InspectionResultModel.session_id == session_id,
                    InspectionResultModel.source_path == source_path,
                    InspectionResultModel.success.is_(True),
                )
                .order_by(InspectionResultModel.created_at.desc())
            )
            if entity is None:
                return None
            inspection = InspectionResult.model_validate(
                {
                    "id": entity.id,
                    "created_at": entity.created_at,
                    "source_path": entity.source_path,
                    "detections": entity.detections_json,
                    "risks": entity.risks_json,
                    "model_name": entity.model_name,
                    "processing_ms": entity.processing_ms,
                    "success": entity.success,
                    "error": entity.error,
                }
            )
            return inspection, [RiskAssessment.model_validate(item) for item in entity.risks_json]

    def count_detection_occurrences(
        self,
        session_id: str,
        label: str,
        *,
        limit: int = 1000,
    ) -> int:
        """Count prior persisted detections for recurrence-aware risk scoring."""
        normalized = label.casefold()
        with self.database.session() as session:
            entities = session.scalars(
                select(InspectionResultModel)
                .where(InspectionResultModel.session_id == session_id)
                .order_by(InspectionResultModel.created_at.desc())
                .limit(limit)
            ).all()
        return sum(
            1
            for entity in entities
            for detection in entity.detections_json
            if str(detection.get("label", "")).casefold() == normalized
        )

    def save_risk_event(
        self,
        session_id: str,
        *,
        event_type: str,
        severity: str,
        description: str,
        evidence_paths: list[str],
    ) -> str:
        self.ensure_session(session_id)
        with self.database.session() as session:
            entity = RiskEventModel(
                session_id=session_id,
                event_type=event_type,
                severity=severity,
                description=description,
                evidence_json=evidence_paths,
                acknowledged=False,
            )
            session.add(entity)
            session.flush()
            return entity.id

    def save_report(self, draft: ReportDraft, artifact: ReportArtifact) -> str:
        with self.database.session() as session:
            entity = ReportModel(
                session_id=draft.request.session_id,
                title=draft.request.title,
                report_type=draft.request.report_type,
                output_path=str(artifact.markdown_path),
                summary=draft.summary,
            )
            session.add(entity)
            session.flush()
            return entity.id

    def list_reports(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.database.session() as session:
            entities = session.scalars(
                select(ReportModel).order_by(ReportModel.created_at.desc()).limit(limit)
            ).all()
            return [
                {
                    "id": item.id,
                    "session_id": item.session_id,
                    "title": item.title,
                    "report_type": item.report_type,
                    "output_path": item.output_path,
                    "summary": item.summary,
                    "created_at": item.created_at.isoformat(),
                }
                for item in entities
            ]

    def list_messages(self, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.database.session() as session:
            entities = session.scalars(
                select(MessageModel)
                .where(MessageModel.session_id == session_id)
                .order_by(MessageModel.created_at.asc())
                .limit(limit)
            ).all()
            return [
                {
                    "id": item.id,
                    "role": item.role,
                    "content": item.content,
                    "metadata": item.metadata_json,
                    "created_at": item.created_at.isoformat(),
                }
                for item in entities
            ]

    def list_sessions(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.database.session() as session:
            entities = session.scalars(
                select(SessionModel).order_by(SessionModel.updated_at.desc()).limit(limit)
            ).all()
            legacy_ids = [
                item.id for item in entities if item.title == "BuildGuard session"
            ]
            first_messages: dict[str, str] = {}
            if legacy_ids:
                messages = session.scalars(
                    select(MessageModel)
                    .where(
                        MessageModel.session_id.in_(legacy_ids),
                        MessageModel.role == "user",
                    )
                    .order_by(MessageModel.created_at.asc())
                ).all()
                for message in messages:
                    first_messages.setdefault(message.session_id, message.content)
            return [
                {
                    "id": item.id,
                    "title": (
                        self.title_from_message(
                            first_messages.get(item.id, ""),
                            item.id,
                        )
                        if item.title == "BuildGuard session"
                        else item.title
                    ),
                    "status": item.status,
                    "metadata": item.metadata_json,
                    "created_at": item.created_at.isoformat(),
                    "updated_at": item.updated_at.isoformat(),
                }
                for item in entities
            ]

    def add_verified_fact(
        self,
        session_id: str,
        *,
        subject: str,
        predicate: str,
        object_text: str,
        source_kind: str,
        source_id: str,
        checksum: str | None = None,
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        self.ensure_session(session_id)
        with self.database.session() as session:
            entity = VerifiedFactModel(
                session_id=session_id,
                subject=subject,
                predicate=predicate,
                object_text=object_text,
                source_kind=source_kind,
                source_id=source_id,
                checksum=checksum,
                confidence=confidence,
                active=True,
            )
            session.add(entity)
            session.flush()
            return self._verified_fact(entity)

    @staticmethod
    def _verified_fact(entity: VerifiedFactModel) -> dict[str, Any]:
        return {
            "id": entity.id,
            "session_id": entity.session_id,
            "subject": entity.subject,
            "predicate": entity.predicate,
            "object": entity.object_text,
            "source_kind": entity.source_kind,
            "source_id": entity.source_id,
            "checksum": entity.checksum,
            "confidence": entity.confidence,
            "active": entity.active,
            "created_at": entity.created_at.isoformat(),
        }

    def list_verified_facts(
        self,
        session_id: str,
        *,
        active_only: bool = True,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        with self.database.session() as session:
            statement = select(VerifiedFactModel).where(VerifiedFactModel.session_id == session_id)
            if active_only:
                statement = statement.where(VerifiedFactModel.active.is_(True))
            entities = session.scalars(
                statement.order_by(VerifiedFactModel.created_at.desc()).limit(limit)
            ).all()
            return [self._verified_fact(item) for item in entities]

    def deactivate_verified_fact(self, session_id: str, fact_id: str) -> bool:
        with self.database.session() as session:
            entity = session.get(VerifiedFactModel, fact_id)
            if entity is None or entity.session_id != session_id:
                return False
            entity.active = False
            return True

    def clear_session(self, session_id: str) -> dict[str, int]:
        """Delete one bounded session and dependent user data after API confirmation."""
        with self.database.session() as session:

            def deleted_count(statement: Any) -> int:
                result = session.execute(statement)
                return int(getattr(result, "rowcount", 0) or 0)

            task_ids = list(
                session.scalars(
                    select(TaskModel.id).where(TaskModel.session_id == session_id)
                ).all()
            )
            counts: dict[str, int] = {}
            if task_ids:
                counts["tool_calls"] = deleted_count(
                    delete(ToolCallModel).where(ToolCallModel.task_id.in_(task_ids))
                )
            for name, model in (
                ("verified_facts", VerifiedFactModel),
                ("messages", MessageModel),
                ("inspections", InspectionResultModel),
                ("risk_events", RiskEventModel),
                ("reports", ReportModel),
                ("tasks", TaskModel),
            ):
                counts[name] = deleted_count(delete(model).where(model.session_id == session_id))
            counts["sessions"] = deleted_count(
                delete(SessionModel).where(SessionModel.id == session_id)
            )
            return counts

    def record_performance(
        self,
        operation: str,
        duration_ms: float,
        *,
        success: bool = True,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        """Best-effort operational telemetry; logging must not fail the workflow."""
        try:
            with self.database.session() as session:
                session.add(
                    PerformanceLogModel(
                        operation=operation,
                        duration_ms=max(0.0, duration_ms),
                        success=success,
                        metrics_json=metrics or {},
                    )
                )
        except Exception as exc:
            LOGGER.warning("Performance persistence failed: %s", exc)

    def record_tool_call(
        self,
        task_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        result: dict[str, Any] | None,
        success: bool,
        duration_ms: float,
    ) -> str:
        """Persist one schema-validated Agent tool invocation."""
        with self.database.session() as session:
            entity = ToolCallModel(
                task_id=task_id,
                tool_name=tool_name,
                arguments_json=arguments,
                result_json=result,
                success=success,
                duration_ms=max(0.0, duration_ms),
            )
            session.add(entity)
            session.flush()
            return entity.id

    def record_tool_audit(self, entry: ToolAuditEntry) -> str:
        """Mirror the append-only tool audit into queryable SQLite storage."""
        outcome = (
            "success"
            if entry.execution_status == "success"
            else "denied"
            if entry.execution_status in {"denied", "pending_confirmation"}
            else "failure"
        )
        with self.database.session() as session:
            entity = SecurityAuditLogModel(
                actor=entry.actor,
                action=f"tool:{entry.tool_name}",
                resource=f"task:{entry.task_id}",
                outcome=outcome,
                details_json=entry.model_dump(mode="json"),
            )
            session.add(entity)
            session.flush()
            return entity.id
