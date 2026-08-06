from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import text
from sqlmodel import Session, select

from ..models import (
    KnowledgeCanonicalGenerationRow,
    KnowledgeDerivationRow,
    KnowledgeDocumentRow,
    KnowledgeImportRow,
    KnowledgeIndexTaskRow,
    KnowledgeUnitRow,
    KnowledgeVectorGenerationRow,
)
from ...knowledge_projection import (
    CORPUS_FINGERPRINT_SCHEMA,
    KnowledgeProjectionIdentity,
    KnowledgeProjectionMetadata,
    KnowledgeProjectionSnapshot,
    KnowledgeProjectionUnit,
    RETRIEVAL_PROJECTION_VERSION,
)


class KnowledgeRepository:
    def create_document(self, session: Session, row: KnowledgeDocumentRow) -> KnowledgeDocumentRow:
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def get_document(self, session: Session, document_id: str) -> KnowledgeDocumentRow | None:
        return session.get(KnowledgeDocumentRow, document_id)

    def get_document_by_source_sha256(
        self,
        session: Session,
        *,
        library_id: str,
        source_sha256: str,
        include_inactive: bool = False,
    ) -> KnowledgeDocumentRow | None:
        statement = select(KnowledgeDocumentRow).where(
            KnowledgeDocumentRow.library_id == library_id,
            KnowledgeDocumentRow.source_sha256 == source_sha256,
        )
        if not include_inactive:
            statement = statement.where(KnowledgeDocumentRow.active.is_(True))
        return session.exec(statement).first()

    def list_documents(
        self,
        session: Session,
        *,
        library_id: str,
    ) -> list[KnowledgeDocumentRow]:
        return list(
            session.exec(
                select(KnowledgeDocumentRow)
                .where(
                    KnowledgeDocumentRow.library_id == library_id,
                    KnowledgeDocumentRow.active.is_(True),
                )
                .order_by(
                    KnowledgeDocumentRow.updated_at.desc(),
                    KnowledgeDocumentRow.title,
                    KnowledgeDocumentRow.id,
                )
            )
        )

    def deactivate_document_membership(
        self,
        session: Session,
        *,
        library_id: str,
        document_id: str,
        updated_at: datetime,
    ) -> bool:
        result = session.execute(
            text(
                "UPDATE knowledge_document "
                "SET active=0, updated_at=:updated_at "
                "WHERE id=:document_id AND library_id=:library_id AND active=1 "
                "AND NOT EXISTS ("
                "SELECT 1 FROM knowledge_import AS i "
                "WHERE (i.document_id=:document_id "
                "OR i.planned_document_id=:document_id) "
                "AND i.status IN ('pending', 'queued', 'running')"
                ") "
                "AND NOT EXISTS ("
                "SELECT 1 FROM knowledge_derivation AS d "
                "WHERE d.document_id=:document_id "
                "AND d.status IN ('pending', 'queued', 'running')"
                ")"
            ),
            {
                "document_id": document_id,
                "library_id": library_id,
                "updated_at": updated_at,
            },
        )
        return int(result.rowcount or 0) == 1

    def document_has_active_work(
        self,
        session: Session,
        *,
        document_id: str,
    ) -> bool:
        row = session.execute(
            text(
                "SELECT EXISTS("
                "SELECT 1 FROM knowledge_import AS i "
                "WHERE (i.document_id=:document_id "
                "OR i.planned_document_id=:document_id) "
                "AND i.status IN ('pending', 'queued', 'running') "
                "UNION ALL "
                "SELECT 1 FROM knowledge_derivation AS d "
                "WHERE d.document_id=:document_id "
                "AND d.status IN ('pending', 'queued', 'running')"
                ")"
            ),
            {"document_id": document_id},
        ).first()
        return bool(row and row[0])

    def replace_units(
        self,
        session: Session,
        *,
        document: KnowledgeDocumentRow,
        units: Sequence[KnowledgeUnitRow],
    ) -> None:
        old_ids = list(
            session.exec(
                select(KnowledgeUnitRow.id).where(KnowledgeUnitRow.document_id == document.id)
            )
        )
        if old_ids:
            for unit_id in old_ids:
                session.execute(
                    text("DELETE FROM knowledge_unit_fts WHERE unit_id=:unit_id"),
                    {"unit_id": unit_id},
                )
            for row in session.exec(
                select(KnowledgeUnitRow).where(KnowledgeUnitRow.document_id == document.id)
            ):
                session.delete(row)
            session.flush()
        for unit in units:
            session.add(unit)
        session.flush()
        for unit in units:
            session.execute(
                text(
                    "INSERT INTO knowledge_unit_fts(unit_id, title, search_text) "
                    "VALUES (:unit_id, :title, :search_text)"
                ),
                {"unit_id": unit.id, "title": document.title, "search_text": unit.search_text},
            )

    def search_unit_ids(
        self,
        session: Session,
        *,
        fts_query: str,
        library_id: str,
        document_ids: Sequence[str],
        limit: int,
    ) -> list[str]:
        sql = (
            "SELECT f.unit_id FROM knowledge_unit_fts AS f "
            "JOIN knowledge_unit AS u ON u.id=f.unit_id "
            "JOIN knowledge_document AS d ON d.id=u.document_id "
            "WHERE knowledge_unit_fts MATCH :query AND d.active=1 "
            "AND d.library_id=:library_id "
            "AND d.retrieval_status='ready' "
            "AND d.retrieval_projection_version=:projection_version "
            "AND u.canonical_generation_id=d.retrieval_generation_id "
        )
        params: dict[str, object] = {
            "query": fts_query,
            "library_id": library_id,
            "limit": limit,
            "projection_version": RETRIEVAL_PROJECTION_VERSION,
        }
        if document_ids:
            placeholders = ", ".join(f":document_{index}" for index in range(len(document_ids)))
            sql += f"AND d.id IN ({placeholders}) "
            params.update({f"document_{index}": value for index, value in enumerate(document_ids)})
        sql += "ORDER BY bm25(knowledge_unit_fts) LIMIT :limit"
        return [str(row[0]) for row in session.execute(text(sql), params)]

    def get_units(self, session: Session, unit_ids: Sequence[str]) -> list[KnowledgeUnitRow]:
        if not unit_ids:
            return []
        rows = list(session.exec(select(KnowledgeUnitRow).where(KnowledgeUnitRow.id.in_(unit_ids))))
        by_id = {row.id: row for row in rows}
        return [by_id[unit_id] for unit_id in unit_ids if unit_id in by_id]

    def get_documents(
        self,
        session: Session,
        document_ids: Sequence[str],
    ) -> dict[str, KnowledgeDocumentRow]:
        if not document_ids:
            return {}
        rows = session.exec(
            select(KnowledgeDocumentRow).where(
                KnowledgeDocumentRow.id.in_(list(dict.fromkeys(document_ids)))
            )
        )
        return {row.id: row for row in rows}

    def list_current_units(
        self,
        session: Session,
        *,
        library_id: str,
    ) -> list[KnowledgeUnitRow]:
        return list(
            session.exec(
                select(KnowledgeUnitRow)
                .join(
                    KnowledgeDocumentRow,
                    KnowledgeDocumentRow.id == KnowledgeUnitRow.document_id,
                )
                .where(
                    KnowledgeDocumentRow.library_id == library_id,
                    KnowledgeDocumentRow.active.is_(True),
                    KnowledgeDocumentRow.retrieval_status == "ready",
                    KnowledgeDocumentRow.retrieval_projection_version
                    == RETRIEVAL_PROJECTION_VERSION,
                    KnowledgeUnitRow.canonical_generation_id
                    == KnowledgeDocumentRow.retrieval_generation_id,
                )
                .order_by(
                    KnowledgeUnitRow.document_id,
                    KnowledgeUnitRow.ordinal,
                    KnowledgeUnitRow.id,
                )
            )
        )

    def list_current_projection_metadata(
        self,
        session: Session,
        *,
        library_id: str,
    ) -> list[KnowledgeProjectionMetadata]:
        rows = session.exec(
            select(
                KnowledgeDocumentRow.id,
                KnowledgeDocumentRow.retrieval_generation_id,
                KnowledgeDocumentRow.retrieval_projection_version,
                KnowledgeDocumentRow.retrieval_content_fingerprint,
                KnowledgeDocumentRow.retrieval_unit_count,
            )
            .where(
                KnowledgeDocumentRow.library_id == library_id,
                KnowledgeDocumentRow.active.is_(True),
                KnowledgeDocumentRow.retrieval_status == "ready",
                KnowledgeDocumentRow.retrieval_projection_version
                == RETRIEVAL_PROJECTION_VERSION,
                KnowledgeDocumentRow.retrieval_generation_id.is_not(None),
                KnowledgeDocumentRow.retrieval_content_fingerprint.is_not(None),
                KnowledgeDocumentRow.retrieval_unit_count > 0,
            )
            .order_by(KnowledgeDocumentRow.id)
        )
        return [
            KnowledgeProjectionMetadata(
                document_id=str(row[0]),
                retrieval_generation_id=str(row[1]),
                projection_version=int(row[2]),
                content_fingerprint=str(row[3]),
                unit_count=int(row[4]),
            )
            for row in rows
        ]

    def current_projection_identity(
        self,
        session: Session,
        *,
        library_id: str,
    ) -> KnowledgeProjectionIdentity:
        return KnowledgeProjectionIdentity(
            tuple(
                self.list_current_projection_metadata(
                    session,
                    library_id=library_id,
                )
            )
        )

    def load_projection_snapshot(
        self,
        session: Session,
        *,
        library_id: str,
    ) -> KnowledgeProjectionSnapshot:
        """Read projection metadata and bodies from one SQLite snapshot/query."""

        rows = session.execute(
            text(
                "SELECT d.id AS document_id, "
                "d.retrieval_generation_id AS retrieval_generation_id, "
                "d.retrieval_projection_version AS projection_version, "
                "d.retrieval_content_fingerprint AS content_fingerprint, "
                "d.retrieval_unit_count AS declared_unit_count, "
                "u.id AS unit_id, u.canonical_generation_id AS unit_generation_id, "
                "u.ordinal AS unit_ordinal, u.text AS unit_text "
                "FROM knowledge_document AS d "
                "LEFT JOIN knowledge_unit AS u ON u.document_id=d.id "
                "AND u.canonical_generation_id=d.retrieval_generation_id "
                "WHERE d.library_id=:library_id AND d.active=1 "
                "AND d.retrieval_status='ready' "
                "AND d.retrieval_projection_version=:projection_version "
                "AND d.retrieval_generation_id IS NOT NULL "
                "AND d.retrieval_content_fingerprint IS NOT NULL "
                "AND d.retrieval_unit_count > 0 "
                "ORDER BY d.id, u.ordinal, u.id"
            ),
            {
                "library_id": library_id,
                "projection_version": RETRIEVAL_PROJECTION_VERSION,
            },
        ).mappings()
        metadata: list[KnowledgeProjectionMetadata] = []
        units: list[KnowledgeProjectionUnit] = []
        seen_documents: set[str] = set()
        for row in rows:
            document_id = str(row["document_id"])
            generation_id = str(row["retrieval_generation_id"])
            if document_id not in seen_documents:
                metadata.append(
                    KnowledgeProjectionMetadata(
                        document_id=document_id,
                        retrieval_generation_id=generation_id,
                        projection_version=int(row["projection_version"]),
                        content_fingerprint=str(row["content_fingerprint"]),
                        unit_count=int(row["declared_unit_count"]),
                    )
                )
                seen_documents.add(document_id)
            if row["unit_id"] is None:
                continue
            units.append(
                KnowledgeProjectionUnit(
                    id=str(row["unit_id"]),
                    document_id=document_id,
                    canonical_generation_id=str(row["unit_generation_id"]),
                    ordinal=int(row["unit_ordinal"]),
                    text=str(row["unit_text"]),
                )
            )
        return KnowledgeProjectionSnapshot(
            identity=KnowledgeProjectionIdentity(tuple(metadata)),
            units=tuple(units),
        )

    def keyword_index_counts(
        self,
        session: Session,
        *,
        library_id: str,
    ) -> tuple[int, int]:
        params = {
            "library_id": library_id,
            "projection_version": RETRIEVAL_PROJECTION_VERSION,
        }
        current = int(
            session.execute(
                text(
                    "SELECT COUNT(*) FROM knowledge_unit AS u "
                    "JOIN knowledge_document AS d ON d.id=u.document_id "
                    "WHERE d.library_id=:library_id AND d.active=1 "
                    "AND d.retrieval_status='ready' "
                    "AND d.retrieval_projection_version=:projection_version "
                    "AND u.canonical_generation_id=d.retrieval_generation_id"
                ),
                params,
            ).scalar_one()
        )
        indexed = int(
            session.execute(
                text(
                    "SELECT COUNT(*) FROM knowledge_unit_fts AS f "
                    "JOIN knowledge_unit AS u ON u.id=f.unit_id "
                    "JOIN knowledge_document AS d ON d.id=u.document_id "
                    "WHERE d.library_id=:library_id AND d.active=1 "
                    "AND d.retrieval_status='ready' "
                    "AND d.retrieval_projection_version=:projection_version "
                    "AND u.canonical_generation_id=d.retrieval_generation_id"
                ),
                params,
            ).scalar_one()
        )
        return current, indexed

    def rebuild_keyword_index(
        self,
        session: Session,
        *,
        library_id: str,
    ) -> int:
        session.execute(
            text(
                "DELETE FROM knowledge_unit_fts WHERE unit_id IN ("
                "SELECT u.id FROM knowledge_unit AS u "
                "JOIN knowledge_document AS d ON d.id=u.document_id "
                "WHERE d.library_id=:library_id)"
            ),
            {"library_id": library_id},
        )
        result = session.execute(
            text(
                "INSERT INTO knowledge_unit_fts(unit_id, title, search_text) "
                "SELECT u.id, d.title, u.search_text "
                "FROM knowledge_unit AS u "
                "JOIN knowledge_document AS d ON d.id=u.document_id "
                "WHERE d.library_id=:library_id AND d.active=1 "
                "AND d.retrieval_status='ready' "
                "AND d.retrieval_projection_version=:projection_version "
                "AND u.canonical_generation_id=d.retrieval_generation_id"
            ),
            {
                "library_id": library_id,
                "projection_version": RETRIEVAL_PROJECTION_VERSION,
            },
        )
        return max(0, int(result.rowcount or 0))

    def list_vector_generations(
        self,
        session: Session,
        *,
        library_id: str,
        profile_fingerprint: str,
        corpus_fingerprint: str,
    ) -> list[KnowledgeVectorGenerationRow]:
        return list(
            session.exec(
                select(KnowledgeVectorGenerationRow)
                .where(
                    KnowledgeVectorGenerationRow.library_id == library_id,
                    KnowledgeVectorGenerationRow.profile_fingerprint
                    == profile_fingerprint,
                    KnowledgeVectorGenerationRow.corpus_fingerprint
                    == corpus_fingerprint,
                    KnowledgeVectorGenerationRow.corpus_fingerprint_schema
                    == CORPUS_FINGERPRINT_SCHEMA,
                )
                .order_by(KnowledgeVectorGenerationRow.created_at.desc())
            )
        )

    def create_vector_generation(
        self,
        session: Session,
        row: KnowledgeVectorGenerationRow,
    ) -> KnowledgeVectorGenerationRow:
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def list_all_vector_generations(
        self,
        session: Session,
    ) -> list[KnowledgeVectorGenerationRow]:
        return list(
            session.exec(
                select(KnowledgeVectorGenerationRow).order_by(
                    KnowledgeVectorGenerationRow.created_at,
                    KnowledgeVectorGenerationRow.id,
                )
            )
        )

    def delete_vector_generation(
        self,
        session: Session,
        generation_id: str,
    ) -> bool:
        row = session.get(KnowledgeVectorGenerationRow, generation_id)
        if row is None:
            return False
        session.delete(row)
        session.flush()
        return True

    def create_index_task(
        self,
        session: Session,
        row: KnowledgeIndexTaskRow,
    ) -> KnowledgeIndexTaskRow:
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def get_index_task(
        self,
        session: Session,
        task_id: str,
    ) -> KnowledgeIndexTaskRow | None:
        return session.get(KnowledgeIndexTaskRow, task_id)

    def save_index_task(
        self,
        session: Session,
        row: KnowledgeIndexTaskRow,
    ) -> KnowledgeIndexTaskRow:
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def list_index_tasks(
        self,
        session: Session,
        *,
        library_id: str | None,
        statuses: Sequence[str] | None = None,
    ) -> list[KnowledgeIndexTaskRow]:
        statement = select(KnowledgeIndexTaskRow)
        if library_id is not None:
            statement = statement.where(
                KnowledgeIndexTaskRow.library_id == library_id
            )
        if statuses:
            statement = statement.where(KnowledgeIndexTaskRow.status.in_(statuses))
        return list(
            session.exec(
                statement.order_by(
                    KnowledgeIndexTaskRow.created_at.desc(),
                    KnowledgeIndexTaskRow.id.desc(),
                )
            )
        )

    def create_import(
        self,
        session: Session,
        row: KnowledgeImportRow,
    ) -> KnowledgeImportRow:
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def get_import(self, session: Session, import_id: str) -> KnowledgeImportRow | None:
        return session.get(KnowledgeImportRow, import_id)

    def list_imports(
        self,
        session: Session,
        *,
        library_id: str,
    ) -> list[KnowledgeImportRow]:
        return list(
            session.exec(
                select(KnowledgeImportRow)
                .where(KnowledgeImportRow.library_id == library_id)
                .order_by(KnowledgeImportRow.created_at.desc())
            )
        )

    def list_imports_by_status(
        self,
        session: Session,
        *,
        statuses: Sequence[str],
    ) -> list[KnowledgeImportRow]:
        normalized = list(dict.fromkeys(str(status) for status in statuses if str(status)))
        if not normalized:
            return []
        return list(
            session.exec(
                select(KnowledgeImportRow)
                .where(KnowledgeImportRow.status.in_(normalized))
                .order_by(KnowledgeImportRow.created_at, KnowledgeImportRow.id)
            )
        )

    def save_import(
        self,
        session: Session,
        row: KnowledgeImportRow,
    ) -> KnowledgeImportRow:
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def create_canonical_generation(
        self,
        session: Session,
        row: KnowledgeCanonicalGenerationRow,
    ) -> KnowledgeCanonicalGenerationRow:
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def get_canonical_generation(
        self,
        session: Session,
        generation_id: str,
    ) -> KnowledgeCanonicalGenerationRow | None:
        return session.get(KnowledgeCanonicalGenerationRow, generation_id)

    def get_current_canonical_generation(
        self,
        session: Session,
        *,
        document_id: str,
    ) -> KnowledgeCanonicalGenerationRow | None:
        document = self.get_document(session, document_id)
        if document is None:
            return None
        return self.get_canonical_generation(session, document.canonical_generation_id)

    def list_canonical_generations(
        self,
        session: Session,
        *,
        document_id: str,
    ) -> list[KnowledgeCanonicalGenerationRow]:
        return list(
            session.exec(
                select(KnowledgeCanonicalGenerationRow)
                .where(KnowledgeCanonicalGenerationRow.document_id == document_id)
                .order_by(KnowledgeCanonicalGenerationRow.created_at.desc())
            )
        )

    def create_derivation(
        self,
        session: Session,
        row: KnowledgeDerivationRow,
    ) -> KnowledgeDerivationRow:
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def get_derivation(
        self,
        session: Session,
        derivation_id: str,
    ) -> KnowledgeDerivationRow | None:
        return session.get(KnowledgeDerivationRow, derivation_id)

    def list_derivations(
        self,
        session: Session,
        *,
        document_id: str,
        canonical_generation_id: str | None = None,
    ) -> list[KnowledgeDerivationRow]:
        statement = select(KnowledgeDerivationRow).where(
            KnowledgeDerivationRow.document_id == document_id
        )
        if canonical_generation_id is not None:
            statement = statement.where(
                KnowledgeDerivationRow.canonical_generation_id
                == canonical_generation_id
            )
        return list(
            session.exec(
                statement.order_by(
                    KnowledgeDerivationRow.created_at.desc(),
                    KnowledgeDerivationRow.id,
                )
            )
        )

    def save_derivation(
        self,
        session: Session,
        row: KnowledgeDerivationRow,
    ) -> KnowledgeDerivationRow:
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def set_document_retrieval_state(
        self,
        session: Session,
        *,
        document: KnowledgeDocumentRow,
        generation_id: str | None,
        status: str,
    ) -> KnowledgeDocumentRow:
        document.retrieval_generation_id = generation_id
        document.retrieval_status = status
        session.add(document)
        session.flush()
        session.refresh(document)
        return document
