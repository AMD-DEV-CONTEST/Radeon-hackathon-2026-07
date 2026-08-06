from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .knowledge_index_service import KnowledgeIndexOverview, KnowledgeIndexService
from .knowledge_service import KnowledgeDocumentSummary, KnowledgeService
from .knowledge_task_query import KnowledgeTaskQueryService, KnowledgeTaskSummary
from .paddle_ocr_service import PaddleOcrDeploymentService, PaddleOcrState, PaddleOcrStatus


class KnowledgeWorkspaceDocumentsState(StrEnum):
    READY = "ready"
    EMPTY = "empty"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class KnowledgeWorkspaceDocument:
    document_id: str
    title: str
    source_format: str
    content_state: str
    imported_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class KnowledgeWorkspaceDocuments:
    state: KnowledgeWorkspaceDocumentsState
    items: tuple[KnowledgeWorkspaceDocument, ...]


@dataclass(frozen=True)
class KnowledgeWorkspaceStatus:
    tasks: KnowledgeTaskSummary
    ocr: PaddleOcrStatus
    indexes: KnowledgeIndexOverview | None

    @property
    def has_active_work(self) -> bool:
        return self.tasks.has_active_work or bool(
            self.indexes is not None and self.indexes.active_task_id
        )


@dataclass(frozen=True)
class KnowledgeWorkspaceSnapshot:
    documents: tuple[KnowledgeDocumentSummary, ...]
    tasks: KnowledgeTaskSummary
    ocr: PaddleOcrStatus
    indexes: KnowledgeIndexOverview | None
    documents_available: bool = True

    @property
    def has_active_work(self) -> bool:
        return self.tasks.has_active_work or bool(
            self.indexes is not None and self.indexes.active_task_id
        )


class KnowledgeWorkspaceService:
    """Serve independent, background-safe Workspace presentation projections."""

    def __init__(
        self,
        *,
        knowledge_service: KnowledgeService | None,
        task_query: KnowledgeTaskQueryService,
        index_service: KnowledgeIndexService | None,
        ocr_deployment: PaddleOcrDeploymentService | None,
    ) -> None:
        self._knowledge = knowledge_service
        self._tasks = task_query
        self._indexes = index_service
        self._ocr = ocr_deployment

    def load_documents(
        self,
        *,
        library_id: str = "global",
    ) -> KnowledgeWorkspaceDocuments:
        try:
            summaries = tuple(
                self._knowledge.list_documents(library_id=library_id)
                if self._knowledge is not None
                else ()
            )
        except Exception:
            return KnowledgeWorkspaceDocuments(
                state=KnowledgeWorkspaceDocumentsState.UNAVAILABLE,
                items=(),
            )
        documents = tuple(_workspace_document(summary) for summary in summaries)
        return KnowledgeWorkspaceDocuments(
            state=(
                KnowledgeWorkspaceDocumentsState.READY
                if documents
                else KnowledgeWorkspaceDocumentsState.EMPTY
            ),
            items=documents,
        )

    def load_status(
        self,
        *,
        library_id: str = "global",
    ) -> KnowledgeWorkspaceStatus:
        try:
            tasks = self._tasks.summary(library_id=library_id)
        except Exception:
            tasks = KnowledgeTaskSummary(0, 0, 0)
        try:
            if self._ocr is None:
                ocr = PaddleOcrStatus(PaddleOcrState.NOT_INSTALLED, "service_unavailable")
            else:
                status_reader = getattr(self._ocr, "status_snapshot", None)
                if status_reader is None:
                    status_reader = self._ocr.status
                ocr = status_reader()
                if ocr.state is PaddleOcrState.CHECKING:
                    ocr = self._ocr.verify_active()
        except Exception:
            ocr = PaddleOcrStatus(PaddleOcrState.REPAIR_REQUIRED, "status_unavailable")
        try:
            indexes = (
                self._indexes.status(library_id=library_id)
                if self._indexes is not None
                else None
            )
        except Exception:
            indexes = None
        return KnowledgeWorkspaceStatus(
            tasks=tasks,
            ocr=ocr,
            indexes=indexes,
        )

    def snapshot(self, *, library_id: str = "global") -> KnowledgeWorkspaceSnapshot:
        """Compatibility aggregate for non-UI callers.

        The Workspace UI intentionally calls ``load_documents`` and ``load_status``
        independently so optional status work cannot withhold the document viewport.
        """

        documents = self.load_documents(library_id=library_id)
        status = self.load_status(library_id=library_id)
        return KnowledgeWorkspaceSnapshot(
            documents=tuple(
                KnowledgeDocumentSummary(
                    document_id=document.document_id,
                    title=document.title,
                    source_format=document.source_format,
                    content_state=document.content_state,
                    imported_at=document.imported_at,
                    updated_at=document.updated_at,
                )
                for document in documents.items
            ),
            tasks=status.tasks,
            ocr=status.ocr,
            indexes=status.indexes,
            documents_available=(
                documents.state is not KnowledgeWorkspaceDocumentsState.UNAVAILABLE
            ),
        )


def _workspace_document(summary: KnowledgeDocumentSummary) -> KnowledgeWorkspaceDocument:
    return KnowledgeWorkspaceDocument(
        document_id=summary.document_id,
        title=summary.title,
        source_format=summary.source_format,
        content_state=summary.content_state,
        imported_at=summary.imported_at,
        updated_at=summary.updated_at,
    )


__all__ = [
    "KnowledgeWorkspaceDocument",
    "KnowledgeWorkspaceDocuments",
    "KnowledgeWorkspaceDocumentsState",
    "KnowledgeWorkspaceService",
    "KnowledgeWorkspaceSnapshot",
    "KnowledgeWorkspaceStatus",
]
