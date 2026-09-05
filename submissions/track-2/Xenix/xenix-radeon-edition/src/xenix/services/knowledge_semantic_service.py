from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

from sqlalchemy.orm import sessionmaker

from .embedding_service import (
    EmbeddingProfile,
    EmbeddingService,
    EmbeddingValidationError,
)
from .knowledge_service import (
    KnowledgeSemanticCandidates,
    KnowledgeSemanticIntegrityError,
    KnowledgeSemanticUnavailable,
)
from .knowledge_projection import (
    CORPUS_FINGERPRINT_SCHEMA,
    KnowledgeProjectionIdentity,
    KnowledgeProjectionSnapshot,
)
from .knowledge_storage_maintenance import (
    KnowledgeStorageCleanupResult,
    KnowledgeStorageMaintenance,
)
from .knowledge_vector_store import (
    KnowledgeVectorRecord,
    KnowledgeVectorStoreError,
    LanceKnowledgeVectorStore,
)
from .storage.models import KnowledgeVectorGenerationRow, generate_id
from .storage.repositories.knowledge import KnowledgeRepository

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class KnowledgeSemanticIndexState:
    configured: bool
    profile_fingerprint: str | None
    corpus_fingerprint: str
    unit_count: int
    generation_id: str | None

    @property
    def ready(self) -> bool:
        return self.generation_id is not None


class KnowledgeSemanticService:
    """Build and query immutable vector projections of the current unit corpus.

    SQLite remains the authority for units and published generation metadata.
    LanceDB stores only the replaceable ``unit_id -> vector`` projection.
    """

    def __init__(
        self,
        session_factory: sessionmaker,
        *,
        embedding_service: EmbeddingService,
        vector_store: LanceKnowledgeVectorStore,
    ) -> None:
        self._session_factory = session_factory
        self._embedding_service = embedding_service
        self._vector_store = vector_store
        self._repository = KnowledgeRepository()
        self._storage_maintenance = KnowledgeStorageMaintenance(
            session_factory,
            vector_store=vector_store,
        )
        self._maintenance_pending = True

    def cleanup_storage(self) -> KnowledgeStorageCleanupResult:
        with self._vector_store.lifecycle():
            result = self._storage_maintenance.cleanup()
            self._maintenance_pending = False
            return result

    def is_configured(self) -> bool:
        try:
            return self._embedding_service.freeze() is not None
        except EmbeddingValidationError:
            return False

    def inspect_index(
        self,
        *,
        library_id: str = "global",
    ) -> KnowledgeSemanticIndexState:
        identity = self._current_projection_identity(library_id)
        current_fingerprint = identity.corpus_fingerprint
        unit_count = identity.unit_count
        try:
            operation = self._embedding_service.freeze()
        except EmbeddingValidationError:
            operation = None
        if operation is None:
            return KnowledgeSemanticIndexState(
                configured=False,
                profile_fingerprint=None,
                corpus_fingerprint=current_fingerprint,
                unit_count=unit_count,
                generation_id=None,
            )
        generation = self._usable_generation(
            library_id=library_id,
            profile_fingerprint=operation.profile.profile_fingerprint,
            corpus_fingerprint=current_fingerprint,
            dimensions=None,
            expected_unit_ids=identity.unit_ids,
            expected_unit_count=unit_count,
        )
        return KnowledgeSemanticIndexState(
            configured=True,
            profile_fingerprint=operation.profile.profile_fingerprint,
            corpus_fingerprint=current_fingerprint,
            unit_count=unit_count,
            generation_id=generation.id if generation is not None else None,
        )

    def rebuild_generation(
        self,
        *,
        library_id: str = "global",
        force: bool = True,
    ) -> KnowledgeVectorGenerationRow:
        try:
            return self._rebuild_generation(library_id=library_id, force=force)
        except (KnowledgeSemanticUnavailable, KnowledgeSemanticIntegrityError):
            raise
        except EmbeddingValidationError:
            # Index orchestration is allowed to project the embedding adapter's
            # bounded, content-free failure. Interactive retrieval still exposes
            # only Knowledge-domain availability below.
            raise
        except KnowledgeVectorStoreError as exc:
            raise KnowledgeSemanticUnavailable() from exc
        except Exception as exc:
            raise KnowledgeSemanticIntegrityError() from exc

    def search(
        self,
        query: str,
        *,
        library_id: str,
        limit: int,
    ) -> KnowledgeSemanticCandidates:
        try:
            return self._search(query, library_id=library_id, limit=limit)
        except (KnowledgeSemanticUnavailable, KnowledgeSemanticIntegrityError):
            raise
        except (EmbeddingValidationError, KnowledgeVectorStoreError) as exc:
            raise KnowledgeSemanticUnavailable() from exc
        except Exception as exc:
            raise KnowledgeSemanticIntegrityError() from exc

    def is_current(
        self,
        candidates: KnowledgeSemanticCandidates,
        *,
        library_id: str,
    ) -> bool:
        try:
            operation = self._embedding_service.freeze()
            if operation is None:
                raise KnowledgeSemanticUnavailable()
            return (
                operation.profile.profile_fingerprint
                == candidates.profile_fingerprint
                and self._current_corpus_fingerprint(library_id)
                == candidates.corpus_fingerprint
            )
        except (KnowledgeSemanticUnavailable, KnowledgeSemanticIntegrityError):
            raise
        except (EmbeddingValidationError, KnowledgeVectorStoreError) as exc:
            raise KnowledgeSemanticUnavailable() from exc
        except Exception as exc:
            raise KnowledgeSemanticIntegrityError() from exc

    def _search(
        self,
        query: str,
        *,
        library_id: str,
        limit: int,
    ) -> KnowledgeSemanticCandidates:
        if limit < 1:
            raise KnowledgeSemanticIntegrityError()

        operation = self._embedding_service.freeze()
        if operation is None:
            raise KnowledgeSemanticUnavailable()
        self._run_pending_maintenance()
        identity = self._current_projection_identity(library_id)
        if not identity.unit_ids:
            raise KnowledgeSemanticUnavailable()

        current_fingerprint = identity.corpus_fingerprint
        generation = self._usable_generation(
            library_id=library_id,
            profile_fingerprint=operation.profile.profile_fingerprint,
            corpus_fingerprint=current_fingerprint,
            dimensions=None,
            expected_unit_ids=identity.unit_ids,
            expected_unit_count=identity.unit_count,
        )
        if generation is None:
            raise KnowledgeSemanticUnavailable()

        query_batch = operation.embed_texts([query])
        self._require_profile(query_batch.profile, operation.profile)
        if len(query_batch.vectors) != 1:
            raise KnowledgeSemanticIntegrityError()
        if query_batch.dimensions != generation.dimensions:
            raise KnowledgeSemanticIntegrityError()

        with self._vector_store.lifecycle():
            unit_ids = self._vector_store.search(
                generation.relative_path,
                query_vector=query_batch.vectors[0],
                limit=limit,
            )

            if (
                self._current_projection_identity(library_id) != identity
            ):
                raise KnowledgeSemanticUnavailable()
        return KnowledgeSemanticCandidates(
            unit_ids=tuple(unit_ids),
            corpus_fingerprint=generation.corpus_fingerprint,
            profile_fingerprint=operation.profile.profile_fingerprint,
            generation_id=generation.id,
        )

    def _run_pending_maintenance(self) -> None:
        try:
            with self._vector_store.lifecycle():
                if not self._maintenance_pending:
                    return
                self._storage_maintenance.cleanup()
                self._maintenance_pending = False
        except Exception:
            LOGGER.warning("Knowledge vector maintenance was deferred.")

    def _rebuild_generation(
        self,
        *,
        library_id: str,
        force: bool,
    ) -> KnowledgeVectorGenerationRow:
        operation = self._embedding_service.freeze()
        if operation is None:
            raise KnowledgeSemanticUnavailable()
        self._run_pending_maintenance()
        with self._vector_store.lifecycle():
            snapshot = self._current_projection_snapshot(library_id)
            if not snapshot.units:
                raise KnowledgeSemanticUnavailable()
            identity = snapshot.identity
            profile = operation.profile
            current_fingerprint = identity.corpus_fingerprint
            existing = self._usable_generation(
                library_id=library_id,
                profile_fingerprint=profile.profile_fingerprint,
                corpus_fingerprint=current_fingerprint,
                dimensions=None,
                expected_unit_ids=identity.unit_ids,
                expected_unit_count=identity.unit_count,
            )
            if existing is not None and not force:
                return existing

            document_batch = operation.embed_texts(
                [unit.text for unit in snapshot.units]
            )
            self._require_profile(document_batch.profile, profile)
            if len(document_batch.vectors) != identity.unit_count:
                raise KnowledgeSemanticIntegrityError()
            dimensions = document_batch.dimensions

            generation_id = generate_id()
            relative_path = self._vector_store.write_generation(
                generation_id=generation_id,
                records=[
                    KnowledgeVectorRecord(unit_id=unit.id, vector=vector)
                    for unit, vector in zip(
                        snapshot.units,
                        document_batch.vectors,
                        strict=True,
                    )
                ],
                dimensions=dimensions,
                corpus_fingerprint=current_fingerprint,
                profile_fingerprint=profile.profile_fingerprint,
            )

            published = False
            try:
                current_operation = self._embedding_service.freeze()
                if (
                    current_operation is None
                    or current_operation.profile.profile_fingerprint
                    != profile.profile_fingerprint
                ):
                    raise KnowledgeSemanticUnavailable()

                row = KnowledgeVectorGenerationRow(
                    id=generation_id,
                    library_id=library_id,
                    corpus_fingerprint=current_fingerprint,
                    profile_fingerprint=profile.profile_fingerprint,
                    provider_key=profile.provider_key,
                    model=profile.model,
                    dimensions=dimensions,
                    distance_metric="cosine",
                    relative_path=relative_path,
                    unit_count=identity.unit_count,
                    corpus_fingerprint_schema=CORPUS_FINGERPRINT_SCHEMA,
                )
                with self._session_factory() as session:
                    if (
                        self._repository.current_projection_identity(
                            session,
                            library_id=library_id,
                        )
                        != identity
                    ):
                        raise KnowledgeSemanticUnavailable()
                    self._repository.create_vector_generation(session, row)
                    session.commit()
                    published = True
                    session.refresh(row)
                    return row
            finally:
                if not published:
                    self._vector_store.discard_unpublished_generation(
                        relative_path,
                        expected_generation_id=generation_id,
                    )

    def _usable_generation(
        self,
        *,
        library_id: str,
        profile_fingerprint: str,
        corpus_fingerprint: str,
        dimensions: int | None,
        expected_unit_ids: Sequence[str],
        expected_unit_count: int,
    ) -> KnowledgeVectorGenerationRow | None:
        with self._session_factory() as session:
            generations = self._repository.list_vector_generations(
                session,
                library_id=library_id,
                profile_fingerprint=profile_fingerprint,
                corpus_fingerprint=corpus_fingerprint,
            )
        for generation in generations:
            metadata_matches = (
                generation.distance_metric == "cosine"
                and (dimensions is None or generation.dimensions == dimensions)
                and generation.corpus_fingerprint_schema == CORPUS_FINGERPRINT_SCHEMA
                and generation.unit_count == expected_unit_count
            )
            if not metadata_matches:
                continue
            if self._vector_store.generation_is_usable(
                    generation.relative_path,
                    expected_generation_id=generation.id,
                    expected_corpus_fingerprint=corpus_fingerprint,
                    expected_profile_fingerprint=profile_fingerprint,
                    expected_unit_ids=expected_unit_ids,
                    expected_count=expected_unit_count,
                    expected_dimensions=generation.dimensions,
                ):
                return generation
        return None

    def _current_projection_identity(
        self,
        library_id: str,
    ) -> KnowledgeProjectionIdentity:
        with self._session_factory() as session:
            return self._repository.current_projection_identity(
                session,
                library_id=library_id,
            )

    def _current_corpus_fingerprint(self, library_id: str) -> str:
        return self._current_projection_identity(library_id).corpus_fingerprint

    def _current_projection_snapshot(
        self,
        library_id: str,
    ) -> KnowledgeProjectionSnapshot:
        with self._session_factory() as session:
            return self._repository.load_projection_snapshot(
                session,
                library_id=library_id,
            )

    @staticmethod
    def _require_profile(actual: EmbeddingProfile, expected: EmbeddingProfile) -> None:
        if actual.profile_fingerprint != expected.profile_fingerprint:
            raise KnowledgeSemanticIntegrityError()
