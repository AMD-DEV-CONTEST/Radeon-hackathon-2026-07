from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.orm import sessionmaker
from sqlmodel import Session

from ..exceptions import ValidationError
from .storage.models import utc_now
from .storage.repositories.knowledge import KnowledgeRepository

if TYPE_CHECKING:
    from .knowledge_index_service import KnowledgeIndexService


@dataclass(frozen=True)
class KnowledgeDocumentRemovalReceipt:
    document_id: str
    title: str
    vector_rebuild_task_id: str | None


class KnowledgeDocumentRemovalError(ValidationError):
    pass


class KnowledgeDocumentNotFound(KnowledgeDocumentRemovalError):
    def __init__(self) -> None:
        super().__init__(
            "The Knowledge document was not found.",
            error_code="knowledge_document_not_found",
            retryable=False,
        )


class KnowledgeDocumentBusy(KnowledgeDocumentRemovalError):
    def __init__(self) -> None:
        super().__init__(
            "The Knowledge document is still being imported or prepared.",
            error_code="knowledge_document_busy",
            retryable=True,
        )


class KnowledgeDocumentLifecycleService:
    """Own library-membership lifecycle commands for Knowledge documents."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        index_service: KnowledgeIndexService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._indexes = index_service
        self._repository = KnowledgeRepository()

    def remove_document(
        self,
        document_id: str,
        *,
        library_id: str = "global",
    ) -> KnowledgeDocumentRemovalReceipt:
        normalized_document_id = _required_identity(document_id)
        normalized_library_id = _required_identity(library_id)

        with self._session_factory() as session:
            document = self._repository.get_document(
                session,
                normalized_document_id,
            )
            if (
                document is None
                or document.library_id != normalized_library_id
                or not document.active
            ):
                raise KnowledgeDocumentNotFound()
            title = document.title

            deactivated = self._repository.deactivate_document_membership(
                session,
                library_id=normalized_library_id,
                document_id=normalized_document_id,
                updated_at=utc_now(),
            )
            if not deactivated:
                if self._repository.document_has_active_work(
                    session,
                    document_id=normalized_document_id,
                ):
                    raise KnowledgeDocumentBusy()
                raise KnowledgeDocumentNotFound()
            session.commit()

        rebuild_task_id: str | None = None
        if self._indexes is not None:
            rebuild_task_id = self._indexes.notify_corpus_changed(
                normalized_library_id
            )
        return KnowledgeDocumentRemovalReceipt(
            document_id=normalized_document_id,
            title=title,
            vector_rebuild_task_id=rebuild_task_id,
        )


def _required_identity(value: str) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if not normalized:
        raise KnowledgeDocumentNotFound()
    return normalized


__all__ = [
    "KnowledgeDocumentBusy",
    "KnowledgeDocumentLifecycleService",
    "KnowledgeDocumentNotFound",
    "KnowledgeDocumentRemovalError",
    "KnowledgeDocumentRemovalReceipt",
]
