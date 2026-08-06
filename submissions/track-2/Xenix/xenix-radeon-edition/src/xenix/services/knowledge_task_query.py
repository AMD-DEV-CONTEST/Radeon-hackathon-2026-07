from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import sessionmaker
from sqlmodel import select

from .storage.models import (
    KnowledgeDerivationRow,
    KnowledgeDocumentRow,
    KnowledgeImportRow,
    KnowledgeIndexTaskRow,
)


@dataclass(frozen=True)
class KnowledgeTaskItem:
    reference: str
    kind: str
    target: str
    status: str
    phase: str
    trigger: str
    updated_at: datetime
    error_code: str | None
    owner: str
    owner_id: str
    import_id: str | None
    error_summary: str | None = None
    index_kinds: tuple[str, ...] = ()
    can_cancel: bool = False
    can_retry: bool = False
    can_view_log: bool = False
    can_view_details: bool = True


@dataclass(frozen=True)
class KnowledgeTaskSummary:
    active_count: int
    attention_count: int
    recent_count: int

    @property
    def has_active_work(self) -> bool:
        return self.active_count > 0


class KnowledgeTaskQueryService:
    """Read-only presentation feed over existing Knowledge task authorities."""

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def list_tasks(
        self,
        *,
        library_id: str = "global",
        limit: int = 200,
    ) -> list[KnowledgeTaskItem]:
        bounded_limit = max(1, min(int(limit), 500))
        with self._session_factory() as session:
            imports = list(
                session.exec(
                    select(KnowledgeImportRow)
                    .where(KnowledgeImportRow.library_id == library_id)
                    .order_by(KnowledgeImportRow.updated_at.desc())
                    .limit(bounded_limit)
                )
            )
            derivations = list(
                session.exec(
                    select(KnowledgeDerivationRow)
                    .join(
                        KnowledgeDocumentRow,
                        KnowledgeDocumentRow.id == KnowledgeDerivationRow.document_id,
                    )
                    .where(KnowledgeDocumentRow.library_id == library_id)
                    .order_by(KnowledgeDerivationRow.updated_at.desc())
                    .limit(bounded_limit)
                )
            )
            document_ids = tuple({row.document_id for row in derivations})
            documents = (
                {
                    str(row[0]): str(row[1])
                    for row in session.exec(
                        select(KnowledgeDocumentRow.id, KnowledgeDocumentRow.title).where(
                            KnowledgeDocumentRow.id.in_(document_ids)
                        )
                    )
                }
                if document_ids
                else {}
            )
            indexes = list(
                session.exec(
                    select(KnowledgeIndexTaskRow)
                    .where(KnowledgeIndexTaskRow.library_id == library_id)
                    .order_by(KnowledgeIndexTaskRow.updated_at.desc())
                    .limit(bounded_limit)
                )
            )

        derivations_by_import: dict[str, list[KnowledgeDerivationRow]] = {}
        derivations_by_generation: dict[tuple[str, str], list[KnowledgeDerivationRow]] = {}
        for row in derivations:
            if row.import_id:
                derivations_by_import.setdefault(row.import_id, []).append(row)
            derivations_by_generation.setdefault(
                (row.document_id, row.canonical_generation_id), []
            ).append(row)

        items: list[KnowledgeTaskItem] = []
        folded_derivation_ids: set[str] = set()
        for row in imports:
            attempts = sorted(
                derivations_by_import.get(row.id, ()),
                key=lambda item: (item.attempt_number, item.updated_at),
            )
            latest = attempts[-1] if attempts else None
            prior_success = any(item.status == "succeeded" for item in attempts[:-1])
            if latest is not None and not prior_success:
                folded_derivation_ids.update(item.id for item in attempts)
            status = row.status
            phase = row.phase
            error_code = row.error_code
            derivation_retryable = False
            if latest is not None and not prior_success and row.status in {
                "canonical_ready",
                "retrieval_ready",
                "reused",
            }:
                status = latest.status
                phase = latest.phase
                error_code = latest.error_code
                derivation_retryable = latest.retryable
            items.append(
                KnowledgeTaskItem(
                    reference=f"import:{row.id}",
                    kind="import",
                    target=row.original_file_name,
                    status=status,
                    phase=phase,
                    trigger="user",
                    updated_at=max(
                        row.updated_at,
                        latest.updated_at if latest is not None and not prior_success else row.updated_at,
                    ),
                    error_code=error_code,
                    owner="derivation" if derivation_retryable else "import",
                    owner_id=latest.id if derivation_retryable and latest is not None else row.id,
                    import_id=row.id,
                    can_cancel=row.status in {"queued", "running"},
                    can_retry=bool(row.retryable or derivation_retryable),
                    can_view_log=True,
                )
            )

        for attempts in derivations_by_generation.values():
            latest = max(attempts, key=lambda item: (item.attempt_number, item.updated_at))
            if latest.id in folded_derivation_ids:
                continue
            items.append(
                KnowledgeTaskItem(
                    reference=f"derivation:{latest.id}",
                    kind="content_preparation",
                    target=documents.get(latest.document_id, "Knowledge document"),
                    status=latest.status,
                    phase=latest.phase,
                    trigger="compatibility" if latest.attempt_number > 1 else "system",
                    updated_at=latest.updated_at,
                    error_code=latest.error_code,
                    owner="derivation",
                    owner_id=latest.id,
                    import_id=latest.import_id,
                    can_retry=bool(latest.retryable and latest.import_id),
                    can_view_log=False,
                )
            )

        for row in indexes:
            items.append(
                KnowledgeTaskItem(
                    reference=f"index:{row.id}",
                    kind="index_build",
                    target=_index_target(tuple(row.index_kinds_payload)),
                    status=row.status,
                    phase=row.phase,
                    trigger=row.trigger,
                    updated_at=row.updated_at,
                    error_code=row.error_code,
                    owner="index",
                    owner_id=row.id,
                    import_id=None,
                    error_summary=row.error_summary,
                    index_kinds=tuple(row.index_kinds_payload),
                    can_retry=row.status == "failed",
                    can_view_log=False,
                )
            )
        items.sort(key=lambda item: (item.updated_at, item.reference), reverse=True)
        return items[:bounded_limit]

    def summary(self, *, library_id: str = "global") -> KnowledgeTaskSummary:
        items = self.list_tasks(library_id=library_id, limit=200)
        return KnowledgeTaskSummary(
            active_count=sum(item.status in {"pending", "queued", "running"} for item in items),
            attention_count=sum(item.status in {"failed", "needs_attention"} for item in items),
            recent_count=len(items),
        )


def _index_target(kinds: tuple[str, ...]) -> str:
    labels = {"keyword": "Keyword index", "text_vector": "Text vector index"}
    return " + ".join(labels.get(kind, kind) for kind in kinds) or "Knowledge indexes"


__all__ = ["KnowledgeTaskItem", "KnowledgeTaskQueryService", "KnowledgeTaskSummary"]
