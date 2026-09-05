from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Callable

from sqlalchemy.orm import sessionmaker

from .knowledge_vector_store import (
    KnowledgeVectorGenerationState,
    KnowledgeVectorStoreError,
    LanceKnowledgeVectorStore,
)
from .storage.models import KnowledgeVectorGenerationRow
from .storage.repositories.knowledge import KnowledgeRepository

_DEFAULT_STALE_STAGING_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class KnowledgeStorageCleanupResult:
    metadata_scanned: int
    healthy_metadata: int
    missing_metadata_deleted: int
    corrupt_metadata_deleted: int
    metadata_retained: int
    orphan_generations_quarantined: int
    stale_staging_quarantined: int
    trash_deleted: int
    trash_remaining: int


class KnowledgeStorageMaintenance:
    """Reconcile SQLite vector readiness with app-owned derived vector bytes."""

    def __init__(
        self,
        session_factory: sessionmaker,
        *,
        vector_store: LanceKnowledgeVectorStore,
        stale_staging_seconds: float = _DEFAULT_STALE_STAGING_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not math.isfinite(stale_staging_seconds) or stale_staging_seconds < 0:
            raise ValueError("stale_staging_seconds must be finite and non-negative")
        self._session_factory = session_factory
        self._vector_store = vector_store
        self._stale_staging_seconds = stale_staging_seconds
        self._clock = clock
        self._repository = KnowledgeRepository()

    def cleanup(self) -> KnowledgeStorageCleanupResult:
        """Remove only projections whose vector ownership can be proven locally."""

        with self._vector_store.lifecycle():
            rows = self._list_metadata()
            healthy = 0
            missing_deleted = 0
            corrupt_deleted = 0
            retained = 0

            for row in rows:
                state = self._inspect(row)
                if state is KnowledgeVectorGenerationState.USABLE:
                    healthy += 1
                    continue
                if state in {
                    KnowledgeVectorGenerationState.MISSING,
                    KnowledgeVectorGenerationState.UNSAFE,
                }:
                    self._delete_metadata(row.id)
                    if state is KnowledgeVectorGenerationState.MISSING:
                        missing_deleted += 1
                    else:
                        corrupt_deleted += 1
                    continue

                try:
                    self._vector_store.quarantine_generation(
                        row.relative_path,
                        expected_generation_id=row.id,
                    )
                except KnowledgeVectorStoreError:
                    retained += 1
                    continue
                self._delete_metadata(row.id)
                corrupt_deleted += 1

            referenced_paths = {
                row.relative_path
                for row in self._list_metadata()
                if row.relative_path == f"indexes/{row.id}"
            }
            orphan_count = 0
            for relative_path in self._vector_store.list_definite_generation_paths():
                if relative_path in referenced_paths:
                    continue
                generation_id = relative_path.removeprefix("indexes/")
                try:
                    self._vector_store.quarantine_generation(
                        relative_path,
                        expected_generation_id=generation_id,
                    )
                except KnowledgeVectorStoreError:
                    continue
                orphan_count += 1

            stale_tokens = self._vector_store.quarantine_stale_vector_staging(
                stale_before=self._clock() - self._stale_staging_seconds
            )
            trash_deleted = 0
            for token in self._vector_store.list_quarantined():
                if self._vector_store.delete_quarantined(token):
                    trash_deleted += 1
            trash_remaining = len(self._vector_store.list_quarantined())

            return KnowledgeStorageCleanupResult(
                metadata_scanned=len(rows),
                healthy_metadata=healthy,
                missing_metadata_deleted=missing_deleted,
                corrupt_metadata_deleted=corrupt_deleted,
                metadata_retained=retained,
                orphan_generations_quarantined=orphan_count,
                stale_staging_quarantined=len(stale_tokens),
                trash_deleted=trash_deleted,
                trash_remaining=trash_remaining,
            )

    def _list_metadata(self) -> list[KnowledgeVectorGenerationRow]:
        with self._session_factory() as session:
            return self._repository.list_all_vector_generations(session)

    def _delete_metadata(self, generation_id: str) -> None:
        with self._session_factory() as session:
            self._repository.delete_vector_generation(session, generation_id)
            session.commit()

    def _inspect(
        self,
        row: KnowledgeVectorGenerationRow,
    ) -> KnowledgeVectorGenerationState:
        if row.distance_metric != "cosine":
            return KnowledgeVectorGenerationState.CORRUPT
        return self._vector_store.inspect_generation(
            row.relative_path,
            expected_generation_id=row.id,
            expected_corpus_fingerprint=row.corpus_fingerprint,
            expected_profile_fingerprint=row.profile_fingerprint,
            expected_count=row.unit_count,
            expected_dimensions=row.dimensions,
        )
