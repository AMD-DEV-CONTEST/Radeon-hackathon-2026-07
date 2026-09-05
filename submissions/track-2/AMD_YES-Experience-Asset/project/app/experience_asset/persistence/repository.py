"""SQLite repository with immutable complete snapshots and optimistic writes."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from app.experience_asset.discovery_fingerprint import (
    DISCOVERY_LEASE_SECONDS,
    MAX_DISCOVERY_ATTEMPTS,
    compute_discovery_fingerprint,
    is_retryable,
)
from app.experience_asset.domain.enums import (
    DiscoveryFailureClass,
    DiscoveryOutcome,
    RelationLifecycle,
)
from app.experience_asset.domain.m2 import CriticalMomentMapV1
from app.experience_asset.domain.m3 import DecisionEvidenceLedgerV1
from app.experience_asset.domain.m4 import InsightBoundaryMapV1
from app.experience_asset.domain.models import (
    AgentRunStateV1,
    ExperienceAssetV1,
    PolicyDecision,
    TerminalResultV1,
)
from app.experience_asset.domain.relation import (
    ConfirmedAssetRelationV1,
    DiscoveryAttemptV1,
    DiscoveryFingerprintV1,
    KnowledgeCardReadinessRecordV1,
    NodeProvenanceV1,
    RelationCandidateDecisionV1,
    RelationCandidateV1,
    RoleGraphEdgeV1,
    RoleGraphNodeV1,
    RoleGraphProjectionV1,
    compute_projection_hash,
)
from app.experience_asset.inference.models import (
    M2SemanticRoleProposal,
    M3LedgerProposal,
    M4MapProposal,
    ModelMetadata,
)
from app.experience_asset.role_graph import (
    build_role_graph_projection,
    summary_index_document,
)

MIGRATION_VERSION = 10

# Placeholders left where a deleted asset's text used to be. Non-empty because
# the contract requires non-empty text, and explicit because a blanked field
# that merely looked empty would read as a candidate that never had a summary.
_REDACTED_TITLE = "[已删除资产]"
_REDACTED_SUMMARY = "该资产已被删除。其内容不再保留。标识与哈希保留供审计。"


class PersistenceError(RuntimeError):
    """Base persistence failure."""


class AssetNotFoundError(PersistenceError):
    """Requested asset has no durable record."""


class StorageConflictError(PersistenceError):
    """The caller tried to append from a stale current-version pointer."""


class WorkflowEffectInProgressError(PersistenceError):
    """A replay encountered an effect whose completion is unknown."""


class SQLiteAssetRepository:
    """Owns SQLite access; callers exchange validated domain objects only."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        migration_dir = Path(__file__).parent / "migrations"
        initial = migration_dir / "0001_initial.sql"
        with closing(self._connect()) as connection:
            connection.executescript(initial.read_text(encoding="utf-8"))
            # Older databases predate the checksum column; add it before use.
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(schema_migrations)")
            }
            if "checksum" not in columns:
                connection.execute("ALTER TABLE schema_migrations ADD COLUMN checksum TEXT")
            connection.execute(
                """
                INSERT OR IGNORE INTO schema_migrations(version, applied_at, checksum)
                VALUES (?, ?, ?)
                """,
                (
                    1,
                    datetime.now(UTC).isoformat(),
                    hashlib.sha256(initial.read_text(encoding="utf-8").encode("utf-8")).hexdigest(),
                ),
            )
            for migration in sorted(migration_dir.glob("[0-9][0-9][0-9][0-9]_*.sql")):
                version = int(migration.name.split("_", maxsplit=1)[0])
                if version == 1:
                    continue
                body = migration.read_text(encoding="utf-8")
                checksum = hashlib.sha256(body.encode("utf-8")).hexdigest()
                applied = connection.execute(
                    "SELECT checksum FROM schema_migrations WHERE version = ?",
                    (version,),
                ).fetchone()
                if applied is not None:
                    keys = applied.keys()
                    recorded = applied["checksum"] if "checksum" in keys else None
                    if recorded is not None and recorded != checksum:
                        # A version number alone cannot tell a rewritten
                        # migration from the one that ran. Skipping silently
                        # leaves the database missing constraints the code
                        # assumes are enforced, and nothing reports it — the
                        # schema and the contract disagree with no symptom.
                        raise StorageConflictError(
                            f"migration {version:04d} has changed since it was "
                            "applied to this database. Recreate the database, or "
                            "add a forward-repair migration; the recorded schema "
                            "no longer matches the one the code expects."
                        )
                    continue
                connection.executescript(body)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at, checksum) "
                    "VALUES (?, ?, ?)",
                    (version, datetime.now(UTC).isoformat(), checksum),
                )
            connection.commit()

    def ping(self) -> bool:
        try:
            with closing(self._connect()) as connection:
                connection.execute("SELECT 1").fetchone()
        except sqlite3.Error:
            return False
        return True

    @staticmethod
    def _snapshot_json(snapshot: ExperienceAssetV1) -> str:
        return snapshot.model_dump_json()

    @classmethod
    def _snapshot_hash(cls, snapshot: ExperienceAssetV1) -> str:
        return hashlib.sha256(cls._snapshot_json(snapshot).encode("utf-8")).hexdigest()

    def create(self, snapshot: ExperienceAssetV1) -> None:
        if snapshot.lineage.parent_version_id is not None:
            raise StorageConflictError("initial version cannot have a parent")
        payload = self._snapshot_json(snapshot)
        content_hash = self._snapshot_hash(snapshot)
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO assets(
                        asset_id, lifecycle, current_version_id, created_at, updated_at
                    ) VALUES (?, ?, NULL, ?, ?)
                    """,
                    (
                        str(snapshot.asset_id),
                        snapshot.lifecycle.value,
                        snapshot.created_at.isoformat(),
                        snapshot.updated_at.isoformat(),
                    ),
                )
                self._insert_version(connection, snapshot, payload, content_hash)
                connection.execute(
                    """
                    UPDATE assets
                    SET current_version_id = ?, updated_at = ?, lifecycle = ?
                    WHERE asset_id = ?
                    """,
                    (
                        str(snapshot.version_id),
                        snapshot.updated_at.isoformat(),
                        snapshot.lifecycle.value,
                        str(snapshot.asset_id),
                    ),
                )
                connection.commit()
        except sqlite3.IntegrityError as exc:
            raise StorageConflictError("asset or version already exists") from exc
        except sqlite3.Error as exc:
            raise PersistenceError("failed to create canonical asset") from exc

    def append(
        self,
        snapshot: ExperienceAssetV1,
        *,
        expected_current_version_id: UUID,
    ) -> None:
        if snapshot.lineage.parent_version_id != expected_current_version_id:
            raise StorageConflictError("snapshot parent does not match expected current version")
        payload = self._snapshot_json(snapshot)
        content_hash = self._snapshot_hash(snapshot)
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT current_version_id FROM assets WHERE asset_id = ?",
                    (str(snapshot.asset_id),),
                ).fetchone()
                if row is None:
                    raise AssetNotFoundError(str(snapshot.asset_id))
                if row["current_version_id"] != str(expected_current_version_id):
                    raise StorageConflictError("current version changed; reload before saving")
                self._insert_version(connection, snapshot, payload, content_hash)
                updated = connection.execute(
                    """
                    UPDATE assets
                    SET current_version_id = ?, updated_at = ?, lifecycle = ?
                    WHERE asset_id = ? AND current_version_id = ?
                    """,
                    (
                        str(snapshot.version_id),
                        snapshot.updated_at.isoformat(),
                        snapshot.lifecycle.value,
                        str(snapshot.asset_id),
                        str(expected_current_version_id),
                    ),
                )
                if updated.rowcount != 1:
                    raise StorageConflictError("current version changed during save")
                connection.commit()
        except (AssetNotFoundError, StorageConflictError):
            raise
        except sqlite3.IntegrityError as exc:
            raise StorageConflictError("version already exists or has invalid lineage") from exc
        except sqlite3.Error as exc:
            raise PersistenceError("failed to append canonical version") from exc

    @staticmethod
    def _insert_version(
        connection: sqlite3.Connection,
        snapshot: ExperienceAssetV1,
        payload: str,
        content_hash: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO asset_versions(
                version_id, asset_id, parent_version_id, schema_version,
                change_kind, change_reason, created_at, content_json, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(snapshot.version_id),
                str(snapshot.asset_id),
                (
                    str(snapshot.lineage.parent_version_id)
                    if snapshot.lineage.parent_version_id
                    else None
                ),
                snapshot.schema_version,
                snapshot.lineage.change_kind,
                snapshot.lineage.change_reason,
                snapshot.lineage.created_at.isoformat(),
                payload,
                content_hash,
            ),
        )

    def get_current(self, asset_id: UUID) -> ExperienceAssetV1:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT v.content_json
                FROM assets a
                JOIN asset_versions v ON v.version_id = a.current_version_id
                WHERE a.asset_id = ?
                """,
                (str(asset_id),),
            ).fetchone()
        if row is None:
            raise AssetNotFoundError(str(asset_id))
        return ExperienceAssetV1.model_validate_json(row["content_json"])

    def get_version(self, version_id: UUID) -> ExperienceAssetV1:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT content_json FROM asset_versions WHERE version_id = ?",
                (str(version_id),),
            ).fetchone()
        if row is None:
            raise AssetNotFoundError(str(version_id))
        return ExperienceAssetV1.model_validate_json(row["content_json"])

    def list_version_ids(self, asset_id: UUID) -> list[UUID]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT version_id FROM asset_versions
                WHERE asset_id = ? ORDER BY created_at, rowid
                """,
                (str(asset_id),),
            ).fetchall()
        return [UUID(row["version_id"]) for row in rows]

    def activate_projection(self, projection: RoleGraphProjectionV1) -> None:
        """Persist a complete role graph and make it eligible as the final write."""

        from app.experience_asset.domain.enums import ProjectionLifecycle
        from app.experience_asset.persistence.relation_ledger import (
            ProjectionHashMismatchError,
            StaleBindingError,
        )

        if projection.lifecycle is not ProjectionLifecycle.ACTIVE:
            raise StaleBindingError("only a complete ACTIVE projection can be activated")
        recomputed = compute_projection_hash(
            asset_id=projection.asset_id,
            version_id=projection.version_id,
            knowledge_card_hash=projection.knowledge_card_hash,
            projection_schema_version=projection.projection_schema_version,
            nodes=projection.nodes,
            edges=projection.edges,
            provenance=projection.provenance,
        )
        if recomputed != projection.projection_hash:
            raise ProjectionHashMismatchError("projection content does not match its hash")

        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                binding = connection.execute(
                    """SELECT v.content_hash, v.content_json,
                              m.content_json AS m4_content_json,
                              r.content_json AS readiness_content_json
                    FROM knowledge_card_readiness r
                    JOIN assets a ON a.asset_id=r.asset_id
                    JOIN asset_versions v ON v.asset_id=r.asset_id AND v.version_id=r.version_id
                    JOIN m4_current mc ON mc.asset_id=r.asset_id
                    JOIN m4_artifacts m ON m.asset_id=mc.asset_id
                                       AND m.artifact_id=mc.artifact_id
                    WHERE r.asset_id=? AND r.version_id=? AND r.knowledge_card_hash=?
                      AND r.lifecycle='ACTIVE' AND a.current_version_id=r.version_id
                      AND mc.artifact_id=r.m4_artifact_id""",
                    (
                        str(projection.asset_id),
                        str(projection.version_id),
                        projection.knowledge_card_hash,
                    ),
                ).fetchone()
                if binding is None or binding["content_hash"] != projection.knowledge_card_hash:
                    raise StaleBindingError(
                        "projection does not bind the active ready canonical card"
                    )
                asset = ExperienceAssetV1.model_validate_json(binding["content_json"])
                m4_artifact = InsightBoundaryMapV1.model_validate_json(
                    binding["m4_content_json"]
                )
                readiness = KnowledgeCardReadinessRecordV1.model_validate_json(
                    binding["readiness_content_json"]
                )
                expected = build_role_graph_projection(
                    asset=asset,
                    m4_artifact=m4_artifact,
                    readiness=readiness,
                    created_at=projection.created_at,
                )
                if (
                    expected.projection_id != projection.projection_id
                    or expected.projection_hash != projection.projection_hash
                ):
                    raise ProjectionHashMismatchError(
                        "projection does not match the readiness-bound canonical records"
                    )

                existing = connection.execute(
                    "SELECT lifecycle, projection_hash FROM role_graph_projections "
                    "WHERE projection_id=?",
                    (str(projection.projection_id),),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["lifecycle"] == "ACTIVE"
                        and existing["projection_hash"] == projection.projection_hash
                    ):
                        stored = self._load_projection(
                            connection, str(projection.projection_id)
                        )
                        indexed = connection.execute(
                            "SELECT count(*) FROM relation_summary_fts "
                            "WHERE projection_id=?",
                            (str(projection.projection_id),),
                        ).fetchone()[0]
                        if stored.projection_hash != projection.projection_hash or indexed != 1:
                            raise ProjectionHashMismatchError(
                                "active projection is incomplete or its index row drifted"
                            )
                        connection.rollback()
                        return
                    raise StaleBindingError("projection identity already names different state")

                connection.execute(
                    """INSERT INTO role_graph_projections(
                        projection_id, asset_id, version_id, knowledge_card_hash,
                        projection_schema_version, projection_hash, lifecycle, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'BUILDING', ?)""",
                    (
                        str(projection.projection_id),
                        str(projection.asset_id),
                        str(projection.version_id),
                        projection.knowledge_card_hash,
                        projection.projection_schema_version,
                        projection.projection_hash,
                        projection.created_at.isoformat(),
                    ),
                )
                connection.executemany(
                    """INSERT INTO role_graph_nodes(
                        projection_id, node_id, root_kind, canonical_record_id,
                        is_root, role, display_order, summary_text, summary_text_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            str(projection.projection_id),
                            node.node_id,
                            node.root_kind.value,
                            str(node.canonical_record_id),
                            int(node.is_root),
                            node.role.value if node.role else None,
                            node.display_order,
                            node.summary_text,
                            node.summary_text_hash,
                        )
                        for node in projection.nodes
                    ],
                )
                connection.executemany(
                    """INSERT INTO role_graph_edges(
                        projection_id, edge_id, edge_type, root_node_id,
                        member_node_id, canonical_record_id
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            str(projection.projection_id),
                            edge.edge_id,
                            edge.edge_type.value,
                            edge.root_node_id,
                            edge.member_node_id,
                            str(edge.canonical_record_id),
                        )
                        for edge in projection.edges
                    ],
                )
                connection.executemany(
                    """INSERT INTO role_graph_node_provenance(
                        projection_id, node_id, statement_ids_json,
                        evidence_refs_json, source_refs_json, span_refs_json
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            str(projection.projection_id),
                            entry.node_id,
                            json.dumps([str(value) for value in entry.statement_ids]),
                            json.dumps(entry.evidence_refs),
                            json.dumps(entry.source_refs),
                            json.dumps(entry.span_refs),
                        )
                        for entry in projection.provenance
                    ],
                )
                title, summary, tokens, roles = summary_index_document(projection, asset)
                connection.execute(
                    """INSERT INTO relation_summary_fts(
                        projection_id, asset_id, asset_title, summary_text,
                        lexical_tokens, role_signature
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        str(projection.projection_id),
                        str(projection.asset_id),
                        title,
                        summary,
                        tokens,
                        roles,
                    ),
                )
                updated = connection.execute(
                    "UPDATE role_graph_projections SET lifecycle='ACTIVE' "
                    "WHERE projection_id=? AND lifecycle='BUILDING'",
                    (str(projection.projection_id),),
                )
                if updated.rowcount != 1:
                    raise StorageConflictError("projection activation lost its BUILDING row")
                connection.commit()
        except (StaleBindingError, ProjectionHashMismatchError, StorageConflictError):
            raise
        except sqlite3.IntegrityError as exc:
            raise StorageConflictError("projection conflicts with durable ledger state") from exc
        except sqlite3.Error as exc:
            raise PersistenceError("failed to activate role-graph projection") from exc

    def invalidate_projection(self, projection_id: UUID, *, reason: str) -> None:
        """Invalidate eligibility and remove the FTS row in one transaction."""

        from app.experience_asset.persistence.relation_ledger import StaleBindingError

        if not reason.strip():
            raise ValueError("projection invalidation requires a reason")
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """UPDATE role_graph_projections
                SET lifecycle='INVALIDATED', invalidated_at=?, invalidation_reason=?
                WHERE projection_id=? AND lifecycle='ACTIVE'""",
                (datetime.now(UTC).isoformat(), reason, str(projection_id)),
            )
            if updated.rowcount != 1:
                raise StaleBindingError("projection is missing or no longer active")
            connection.commit()

    def list_eligible_projections(
        self, *, current_asset_id: UUID
    ) -> list[RoleGraphProjectionV1]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT p.projection_id
                FROM role_graph_projections p
                JOIN assets a ON a.asset_id=p.asset_id
                JOIN knowledge_card_readiness r
                  ON r.asset_id=p.asset_id AND r.version_id=p.version_id
                 AND r.knowledge_card_hash=p.knowledge_card_hash
                WHERE p.lifecycle='ACTIVE' AND r.lifecycle='ACTIVE'
                  AND a.current_version_id=p.version_id AND a.asset_id<>?
                  AND a.lifecycle NOT IN ('DELETION_PENDING', 'DELETED')
                ORDER BY p.projection_hash, p.projection_id""",
                (str(current_asset_id),),
            ).fetchall()
            return [self._load_projection(connection, row["projection_id"]) for row in rows]

    def search_active_projection_summaries(
        self, *, tokens: tuple[str, ...], current_asset_id: UUID, top_k: int
    ) -> list[dict[str, object]]:
        """Return positive BM25 rows with deterministic tie-breaking."""

        if not tokens:
            return []
        match_query = " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT f.projection_id, f.asset_id,
                           bm25(relation_summary_fts, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0) AS score
                FROM relation_summary_fts f
                JOIN role_graph_projections p ON p.projection_id=f.projection_id
                JOIN knowledge_card_readiness r
                  ON r.asset_id=p.asset_id AND r.version_id=p.version_id
                 AND r.knowledge_card_hash=p.knowledge_card_hash
                JOIN assets a ON a.asset_id=p.asset_id
                WHERE lexical_tokens MATCH ? AND p.lifecycle='ACTIVE'
                  AND r.lifecycle='ACTIVE' AND a.current_version_id=p.version_id
                  AND p.asset_id<>?
                  AND a.lifecycle NOT IN ('DELETION_PENDING', 'DELETED')
                ORDER BY score ASC, f.projection_id ASC
                LIMIT ?""",
                (match_query, str(current_asset_id), top_k),
            ).fetchall()
        return [
            {
                "projection_id": UUID(row["projection_id"]),
                "asset_id": UUID(row["asset_id"]),
                "bm25_score": float(row["score"]),
            }
            for row in rows
        ]

    # -- retrieval-phase trace (tickets 03, 04, 08) -----------------------

    def record_retrieval_event(self, asset_id: UUID, event: dict) -> int:
        """Append one event to the asset's retrieval-phase trace.

        The sequence is assigned here, inside the transaction that writes the
        row. Letting a caller pass one would let two operations on the same
        asset claim the same position, and the checker's whole premise is that
        the order is real — readiness before any cross-asset search, a
        confirmation before any detail read.
        """
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT max(sequence) AS top FROM retrieval_phase_events WHERE asset_id=?",
                    (str(asset_id),),
                ).fetchone()
                sequence = 0 if row is None or row["top"] is None else int(row["top"]) + 1
                connection.execute(
                    """INSERT INTO retrieval_phase_events(
                        event_id, asset_id, sequence, event_type, payload_json, occurred_at
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid4()),
                        str(asset_id),
                        sequence,
                        event["event_type"],
                        json.dumps({**event, "sequence": sequence}, sort_keys=True),
                        datetime.now(UTC).isoformat(),
                    ),
                )
                connection.commit()
                return sequence
        except sqlite3.Error as exc:
            raise PersistenceError("failed to record a retrieval-phase event") from exc

    def read_retrieval_trace(self, asset_id: UUID) -> dict:
        """The asset's trace in the frozen document shape.

        Returned even when empty, with `events: []`. The checker rejects an empty
        list, which is correct for an artifact submitted as evidence — but a read
        that raised instead would make "this asset has done nothing yet"
        indistinguishable from a storage fault.
        """
        from app.experience_asset.observability.retrieval_phase import (
            RETRIEVAL_TRACE_SCHEMA_VERSION,
        )

        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT payload_json FROM retrieval_phase_events
                WHERE asset_id=? ORDER BY sequence""",
                (str(asset_id),),
            ).fetchall()
        return {
            "schema_version": RETRIEVAL_TRACE_SCHEMA_VERSION,
            "asset_id": str(asset_id),
            "events": [json.loads(row["payload_json"]) for row in rows],
        }

    # -- readiness (ticket 03) --------------------------------------------

    def record_readiness(
        self, readiness: KnowledgeCardReadinessRecordV1
    ) -> KnowledgeCardReadinessRecordV1:
        """Persist one explicit acceptance, bound to an exact version and hash.

        The bindings are rechecked inside the transaction rather than before it.
        Checking first would leave a window in which the asset moves on, and the
        row would then grant readiness for a version the user never accepted —
        which fails silently, because everything downstream simply reads it as
        granted.
        """
        from app.experience_asset.persistence.relation_ledger import StaleBindingError

        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                binding = connection.execute(
                    """SELECT v.content_hash, m.artifact_id AS current_m4_artifact_id
                    FROM assets a
                    JOIN asset_versions v
                      ON v.asset_id=a.asset_id AND v.version_id=a.current_version_id
                    LEFT JOIN m4_current m ON m.asset_id=a.asset_id
                    WHERE a.asset_id=? AND a.current_version_id=?""",
                    (str(readiness.asset_id), str(readiness.version_id)),
                ).fetchone()
                if binding is None:
                    raise StaleBindingError(
                        "the named version is not this asset's current version"
                    )
                if binding["current_m4_artifact_id"] != str(readiness.m4_artifact_id):
                    raise StaleBindingError(
                        "the named M4 artifact is not this asset's current map"
                    )
                if binding["content_hash"] != readiness.knowledge_card_hash:
                    raise StaleBindingError(
                        "the card hash does not match the stored version; the card "
                        "changed after the user read it"
                    )
                existing = connection.execute(
                    """SELECT content_json, version_id, knowledge_card_hash
                    FROM knowledge_card_readiness
                    WHERE asset_id=? AND lifecycle='ACTIVE'""",
                    (str(readiness.asset_id),),
                ).fetchone()
                if existing is not None:
                    # Repeat acceptance of the same version is idempotent, and
                    # the stored record wins: a second click must not mint a new
                    # readiness identity, because relations already name the
                    # first one.
                    if (
                        existing["version_id"] == str(readiness.version_id)
                        and existing["knowledge_card_hash"] == readiness.knowledge_card_hash
                    ):
                        connection.commit()
                        return KnowledgeCardReadinessRecordV1.model_validate_json(
                            existing["content_json"]
                        )
                    raise StaleBindingError(
                        "another version of this card is already accepted; it has to be "
                        "retired before a different version can become ready"
                    )
                connection.execute(
                    """INSERT INTO knowledge_card_readiness(
                        readiness_id, asset_id, version_id, m4_artifact_id,
                        knowledge_card_hash, milestone_state, explicit_user_acceptance,
                        content_json, lifecycle, accepted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, 'ACTIVE', ?)""",
                    (
                        str(readiness.readiness_id),
                        str(readiness.asset_id),
                        str(readiness.version_id),
                        str(readiness.m4_artifact_id),
                        readiness.knowledge_card_hash,
                        readiness.milestone_state.value,
                        readiness.model_dump_json(),
                        readiness.accepted_at.isoformat(),
                    ),
                )
                connection.commit()
                return readiness
        except StaleBindingError:
            raise
        except sqlite3.IntegrityError as exc:
            raise StorageConflictError(
                "this exact readiness binding is already on record"
            ) from exc
        except sqlite3.Error as exc:
            raise PersistenceError("failed to record readiness") from exc

    def read_active_readiness(
        self, asset_id: UUID
    ) -> KnowledgeCardReadinessRecordV1 | None:
        """The active readiness record, or None when the card is not ready.

        Bound to the asset's *current* version on read as well as on write: a
        record left active over a superseded version would keep answering "ready"
        for content the user has since replaced.
        """
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT r.content_json FROM knowledge_card_readiness r
                JOIN assets a ON a.asset_id=r.asset_id
                WHERE r.asset_id=? AND r.lifecycle='ACTIVE'
                  AND a.current_version_id=r.version_id""",
                (str(asset_id),),
            ).fetchone()
        if row is None:
            return None
        return KnowledgeCardReadinessRecordV1.model_validate_json(row["content_json"])

    # -- discovery attempts and fingerprints (ticket 06) ------------------

    def reserve_attempt(
        self,
        attempt: DiscoveryAttemptV1,
        *,
        fingerprint: DiscoveryFingerprintV1,
        lease_seconds: int = DISCOVERY_LEASE_SECONDS,
    ) -> DiscoveryAttemptV1:
        """Reserve one attempt for a fingerprint, durably, before inference runs.

        The attempt number and lease are assigned here rather than trusted from
        the caller: two concurrent callers would both compute the same next
        number from the same read, and the second insert would fail on the
        uniqueness constraint with no way to tell a real conflict from a race.
        """
        from app.experience_asset.persistence.relation_ledger import (
            LedgerConflictError,
            ReservationHeldError,
        )

        if attempt.outcome is not DiscoveryOutcome.RUNNING:
            raise LedgerConflictError("a reservation must be RUNNING")
        if lease_seconds < 0:
            raise ValueError("lease seconds cannot be negative")
        digest = compute_discovery_fingerprint(fingerprint)
        if digest != attempt.discovery_fingerprint:
            raise LedgerConflictError(
                "attempt fingerprint does not match the supplied canonical inputs"
            )
        now = datetime.now(UTC)
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._record_fingerprint_inputs(connection, digest, fingerprint, now)
                rows = connection.execute(
                    """SELECT attempt_number, outcome, failure_class, lease_expires_at
                    FROM relation_discovery_attempts
                    WHERE discovery_fingerprint=?
                    ORDER BY attempt_number""",
                    (digest,),
                ).fetchall()
                for row in rows:
                    if row["outcome"] in {
                        DiscoveryOutcome.CANDIDATE.value,
                        DiscoveryOutcome.NO_MATCH.value,
                    }:
                        # Reserving over a settled semantic answer would spend a
                        # model call re-deciding a question whose inputs have not
                        # changed, and produce a second answer for one logical
                        # search.
                        raise LedgerConflictError(
                            "this fingerprint already has a settled semantic result; "
                            "read it instead of reserving another attempt"
                        )
                    if row["outcome"] == DiscoveryOutcome.RUNNING.value:
                        expires = datetime.fromisoformat(str(row["lease_expires_at"]))
                        if expires > now:
                            raise ReservationHeldError(
                                "another caller holds an un-expired reservation "
                                "for this fingerprint"
                            )
                        raise LedgerConflictError(
                            "an expired reservation is still open; recover it before "
                            "reserving again"
                        )
                    if row["outcome"] == DiscoveryOutcome.TECHNICAL_FAILURE.value:
                        failure = DiscoveryFailureClass(str(row["failure_class"]))
                        if not is_retryable(failure):
                            raise LedgerConflictError(
                                f"{failure.value} is deterministic for these inputs; "
                                "a retry under the same fingerprint cannot succeed"
                            )
                attempt_number = len(rows) + 1
                if attempt_number > MAX_DISCOVERY_ATTEMPTS:
                    raise LedgerConflictError(
                        f"retry budget of {MAX_DISCOVERY_ATTEMPTS} attempts is exhausted "
                        "for this fingerprint"
                    )
                reserved = attempt.model_copy(
                    update={
                        "attempt_number": attempt_number,
                        "started_at": now,
                        "lease_expires_at": now + timedelta(seconds=lease_seconds),
                        "finished_at": None,
                        "elapsed_ms": None,
                    }
                )
                connection.execute(
                    """INSERT INTO relation_discovery_attempts(
                        attempt_id, run_id, asset_id, discovery_fingerprint,
                        current_projection_id, eligible_set_hash, attempt_number,
                        outcome, failure_class, candidate_id, lease_expires_at,
                        started_at, finished_at, elapsed_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, NULL, NULL)""",
                    (
                        str(reserved.attempt_id),
                        str(reserved.run_id),
                        str(reserved.asset_id),
                        digest,
                        str(reserved.current_projection_id),
                        reserved.eligible_set_hash,
                        reserved.attempt_number,
                        reserved.outcome.value,
                        reserved.lease_expires_at.isoformat(),
                        reserved.started_at.isoformat(),
                    ),
                )
                connection.commit()
                return reserved
        except (LedgerConflictError, ReservationHeldError):
            raise
        except sqlite3.IntegrityError as exc:
            raise ReservationHeldError(
                "a concurrent caller reserved this fingerprint first"
            ) from exc
        except sqlite3.Error as exc:
            raise PersistenceError("failed to reserve a discovery attempt") from exc

    def settle_attempt(
        self,
        attempt: DiscoveryAttemptV1,
        *,
        candidate: RelationCandidateV1 | None = None,
    ) -> None:
        """Record the terminal outcome of a reserved attempt with its candidate.

        Both writes commit together. Split apart, a crash between them leaves a
        CANDIDATE attempt pointing at a candidate that does not exist, or an
        orphan candidate with no successful attempt, and neither is detectable
        afterwards without comparing the two tables against each other.
        """
        from app.experience_asset.persistence.relation_ledger import LedgerConflictError

        if attempt.outcome is DiscoveryOutcome.RUNNING:
            raise LedgerConflictError("settling requires a terminal outcome")
        if (attempt.outcome is DiscoveryOutcome.CANDIDATE) != (candidate is not None):
            raise LedgerConflictError(
                "a CANDIDATE outcome settles with its candidate, and only a "
                "CANDIDATE outcome may carry one"
            )
        if candidate is not None and (
            candidate.candidate_id != attempt.candidate_id
            or candidate.discovery_fingerprint != attempt.discovery_fingerprint
            or candidate.current_projection_id != attempt.current_projection_id
        ):
            raise LedgerConflictError(
                "the candidate does not bind the exact attempt that produced it"
            )
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                reserved = connection.execute(
                    """SELECT outcome, started_at FROM relation_discovery_attempts
                    WHERE attempt_id=? AND discovery_fingerprint=?""",
                    (str(attempt.attempt_id), attempt.discovery_fingerprint),
                ).fetchone()
                if reserved is None:
                    raise LedgerConflictError("no reservation exists for this attempt")
                if reserved["outcome"] != DiscoveryOutcome.RUNNING.value:
                    raise LedgerConflictError("this attempt is already settled")
                if attempt.outcome in {
                    DiscoveryOutcome.CANDIDATE,
                    DiscoveryOutcome.NO_MATCH,
                }:
                    settled = connection.execute(
                        """SELECT 1 FROM relation_discovery_attempts
                        WHERE discovery_fingerprint=? AND outcome IN ('CANDIDATE','NO_MATCH')
                          AND attempt_id<>?""",
                        (attempt.discovery_fingerprint, str(attempt.attempt_id)),
                    ).fetchone()
                    if settled is not None:
                        raise LedgerConflictError(
                            "this fingerprint already carries a semantic result"
                        )
                if candidate is not None:
                    connection.execute(
                        """INSERT INTO relation_candidates(
                            candidate_id, discovery_fingerprint, current_asset_id,
                            current_projection_id, related_asset_id,
                            historical_projection_id, relation_type,
                            validation_contract_version, lifecycle, content_json,
                            created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            str(candidate.candidate_id),
                            candidate.discovery_fingerprint,
                            str(candidate.current_asset_id),
                            str(candidate.current_projection_id),
                            str(candidate.related_asset_id),
                            str(candidate.historical_projection_id),
                            candidate.relation_type.value,
                            candidate.validation_contract_version,
                            candidate.lifecycle.value,
                            candidate.model_dump_json(),
                            candidate.created_at.isoformat(),
                        ),
                    )
                started = datetime.fromisoformat(str(reserved["started_at"]))
                finished = attempt.finished_at or datetime.now(UTC)
                elapsed = attempt.elapsed_ms
                if elapsed is None:
                    elapsed = max(0, round((finished - started).total_seconds() * 1000))
                updated = connection.execute(
                    """UPDATE relation_discovery_attempts
                    SET outcome=?, failure_class=?, candidate_id=?, lease_expires_at=NULL,
                        finished_at=?, elapsed_ms=?
                    WHERE attempt_id=? AND outcome='RUNNING'""",
                    (
                        attempt.outcome.value,
                        attempt.failure_class.value if attempt.failure_class else None,
                        str(attempt.candidate_id) if attempt.candidate_id else None,
                        finished.isoformat(),
                        elapsed,
                        str(attempt.attempt_id),
                    ),
                )
                if updated.rowcount != 1:
                    raise LedgerConflictError("the reservation changed during settlement")
                connection.commit()
        except LedgerConflictError:
            raise
        except sqlite3.IntegrityError as exc:
            raise LedgerConflictError("the settled attempt violates a ledger binding") from exc
        except sqlite3.Error as exc:
            raise PersistenceError("failed to settle a discovery attempt") from exc

    def read_settled_result(self, discovery_fingerprint: str) -> DiscoveryAttemptV1 | None:
        """Return the cached semantic result for a fingerprint, if any.

        Technical failures are deliberately not returned. They are auditable
        events carrying no semantic claim, and serving one as an answer would let
        a five-minute outage permanently erase a relation that may well exist.
        """
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT * FROM relation_discovery_attempts
                WHERE discovery_fingerprint=? AND outcome IN ('CANDIDATE','NO_MATCH')
                ORDER BY attempt_number LIMIT 1""",
                (discovery_fingerprint,),
            ).fetchone()
        return self._load_attempt(row) if row else None

    def list_attempts(self, discovery_fingerprint: str) -> list[DiscoveryAttemptV1]:
        """Every attempt for one fingerprint, including retained failures."""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT * FROM relation_discovery_attempts
                WHERE discovery_fingerprint=? ORDER BY attempt_number""",
                (discovery_fingerprint,),
            ).fetchall()
        return [self._load_attempt(row) for row in rows]

    # -- decisions and confirmed relations (ticket 07) --------------------

    def decide_candidate(
        self,
        decision: RelationCandidateDecisionV1,
        *,
        confirmed_relation: ConfirmedAssetRelationV1 | None,
    ) -> RelationCandidateDecisionV1:
        """Record one decision and, on CONFIRM, create the relation atomically.

        Every binding is rechecked inside this transaction rather than before
        it. A mismatch is refused, never resolved against whatever is current:
        a mismatch means the caller is acting on state that no longer exists,
        and resolving it silently would grant access based on a decision the
        user made about different content.
        """
        from app.experience_asset.persistence.relation_ledger import (
            DecisionAlreadySettledError,
            StaleBindingError,
        )

        if (decision.user_action == "CONFIRM") != (confirmed_relation is not None):
            raise StaleBindingError(
                "a CONFIRM settles with its relation, and only a CONFIRM carries one"
            )
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                candidate_row = connection.execute(
                    """SELECT content_json, current_projection_id, related_asset_id,
                              historical_projection_id, relation_type,
                              discovery_fingerprint, lifecycle
                    FROM relation_candidates WHERE candidate_id=?""",
                    (str(decision.candidate_id),),
                ).fetchone()
                if candidate_row is None:
                    raise StaleBindingError("no such candidate")
                if candidate_row["related_asset_id"] != str(decision.related_asset_id):
                    raise StaleBindingError(
                        "the decision names a different related asset than the candidate"
                    )
                readiness = connection.execute(
                    """SELECT version_id, knowledge_card_hash
                    FROM knowledge_card_readiness
                    WHERE asset_id=? AND lifecycle='ACTIVE'""",
                    (str(decision.current_asset_id),),
                ).fetchone()
                if readiness is None:
                    raise StaleBindingError("the current card is not ready")
                if (
                    readiness["version_id"] != str(decision.current_version_id)
                    or readiness["knowledge_card_hash"]
                    != decision.current_knowledge_card_hash
                ):
                    raise StaleBindingError(
                        "the decision was made against a card version or hash that is "
                        "no longer the active ready one"
                    )
                settled = connection.execute(
                    """SELECT * FROM relation_candidate_decisions WHERE candidate_id=?""",
                    (str(decision.candidate_id),),
                ).fetchone()
                if settled is not None:
                    # Repeating a decision is idempotent; the opposite one is
                    # refused rather than overwriting, so the trail records what
                    # the user actually decided and when.
                    if settled["user_action"] == decision.user_action:
                        connection.commit()
                        return self._load_decision(settled)
                    raise DecisionAlreadySettledError(
                        f"this candidate was already {settled['user_action']}D; a "
                        "second, opposite decision would erase what the user chose"
                    )
                connection.execute(
                    """INSERT INTO relation_candidate_decisions(
                        decision_id, candidate_id, current_asset_id, current_version_id,
                        current_knowledge_card_hash, current_projection_id,
                        related_asset_id, user_action, decided_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(decision.decision_id),
                        str(decision.candidate_id),
                        str(decision.current_asset_id),
                        str(decision.current_version_id),
                        decision.current_knowledge_card_hash,
                        candidate_row["current_projection_id"],
                        str(decision.related_asset_id),
                        decision.user_action,
                        decision.decided_at.isoformat(),
                    ),
                )
                if confirmed_relation is not None:
                    if (
                        confirmed_relation.source_candidate_id != decision.candidate_id
                        or str(confirmed_relation.relation_type.value)
                        != candidate_row["relation_type"]
                        or str(confirmed_relation.historical_projection_id)
                        != candidate_row["historical_projection_id"]
                    ):
                        raise StaleBindingError(
                            "the relation does not inherit the candidate's identity"
                        )
                    connection.execute(
                        """INSERT INTO confirmed_asset_relations(
                            relation_id, source_candidate_id, source_discovery_fingerprint,
                            confirming_decision_id, confirming_user_action, relation_type,
                            current_asset_id, current_version_id, current_projection_id,
                            current_knowledge_card_hash, related_asset_id,
                            related_version_id, historical_projection_id,
                            lifecycle, confirmed_at
                        ) VALUES (?, ?, ?, ?, 'CONFIRM', ?, ?, ?, ?, ?, ?, ?, ?,
                                  'CONFIRMED', ?)""",
                        (
                            str(confirmed_relation.relation_id),
                            str(confirmed_relation.source_candidate_id),
                            candidate_row["discovery_fingerprint"],
                            str(decision.decision_id),
                            confirmed_relation.relation_type.value,
                            str(confirmed_relation.current_asset_id),
                            str(confirmed_relation.current_version_id),
                            candidate_row["current_projection_id"],
                            confirmed_relation.current_knowledge_card_hash,
                            str(confirmed_relation.related_asset_id),
                            str(confirmed_relation.related_version_id),
                            str(confirmed_relation.historical_projection_id),
                            confirmed_relation.confirmed_at.isoformat(),
                        ),
                    )
                # The column and the blob move together. This table carries
                # both, and updating one alone leaves a row whose JSON contradicts
                # its own lifecycle — the reader would then get a different answer
                # depending on which the query happened to select.
                settled_lifecycle = (
                    RelationLifecycle.CONFIRMED
                    if confirmed_relation is not None
                    else RelationLifecycle.DECLINED
                )
                # `model_copy` does not validate, so the enum member goes in
                # rather than its value: a bare string round-trips through the
                # model and serializes as one, which is a different JSON shape
                # from every other lifecycle field on the record.
                candidate = RelationCandidateV1.model_validate_json(
                    candidate_row["content_json"]
                ).model_copy(update={"lifecycle": settled_lifecycle})
                connection.execute(
                    """UPDATE relation_candidates SET lifecycle=?, content_json=?
                    WHERE candidate_id=?""",
                    (
                        settled_lifecycle.value,
                        candidate.model_dump_json(),
                        str(decision.candidate_id),
                    ),
                )
                connection.commit()
                return decision
        except (StaleBindingError, DecisionAlreadySettledError):
            raise
        except sqlite3.IntegrityError as exc:
            raise StaleBindingError(
                "the decision or relation violates a ledger binding"
            ) from exc
        except sqlite3.Error as exc:
            raise PersistenceError("failed to record the decision") from exc

    def read_decision(self, candidate_id: UUID) -> RelationCandidateDecisionV1 | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM relation_candidate_decisions WHERE candidate_id=?",
                (str(candidate_id),),
            ).fetchone()
        return self._load_decision(row) if row else None

    @staticmethod
    def _load_decision(row: sqlite3.Row) -> RelationCandidateDecisionV1:
        """Rebuilt from columns, because ticket 01 stored the fields, not a blob.

        A blob would let the row and the JSON inside it disagree, and the FKs
        that bind a decision to its candidate can only constrain columns.
        """
        return RelationCandidateDecisionV1(
            decision_id=UUID(row["decision_id"]),
            candidate_id=UUID(row["candidate_id"]),
            current_asset_id=UUID(row["current_asset_id"]),
            current_version_id=UUID(row["current_version_id"]),
            current_knowledge_card_hash=row["current_knowledge_card_hash"],
            related_asset_id=UUID(row["related_asset_id"]),
            user_action=row["user_action"],
            decided_at=datetime.fromisoformat(str(row["decided_at"])),
        )

    @staticmethod
    def _load_relation(row: sqlite3.Row) -> ConfirmedAssetRelationV1:
        return ConfirmedAssetRelationV1(
            relation_id=UUID(row["relation_id"]),
            source_candidate_id=UUID(row["source_candidate_id"]),
            relation_type=row["relation_type"],
            current_asset_id=UUID(row["current_asset_id"]),
            current_version_id=UUID(row["current_version_id"]),
            current_projection_id=UUID(row["current_projection_id"]),
            current_knowledge_card_hash=row["current_knowledge_card_hash"],
            related_asset_id=UUID(row["related_asset_id"]),
            related_version_id=UUID(row["related_version_id"]),
            historical_projection_id=UUID(row["historical_projection_id"]),
            lifecycle=row["lifecycle"],
            confirmed_at=datetime.fromisoformat(str(row["confirmed_at"])),
            invalidated_at=(
                datetime.fromisoformat(str(row["invalidated_at"]))
                if row["invalidated_at"]
                else None
            ),
            invalidation_reason=row["invalidation_reason"],
        )

    def list_confirmed_relations(
        self, asset_id: UUID
    ) -> list[ConfirmedAssetRelationV1]:
        """Active confirmations for one asset, re-read rather than cached.

        Authorization re-projects from here at every policy evaluation. A value
        cached in run state would let a long-running session keep using a
        relation that has since been invalidated.
        """
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT r.* FROM confirmed_asset_relations r
                JOIN assets a ON a.asset_id=r.current_asset_id
                WHERE r.current_asset_id=? AND r.lifecycle='CONFIRMED'
                  AND a.current_version_id=r.current_version_id
                  AND a.lifecycle NOT IN ('DELETION_PENDING', 'DELETED')
                ORDER BY r.confirmed_at, r.rowid""",
                (str(asset_id),),
            ).fetchall()
        return [self._load_relation(row) for row in rows]

    def read_confirmed_relation(
        self, relation_id: UUID
    ) -> ConfirmedAssetRelationV1 | None:
        """Ticket 09: bound to the current version, like readiness already was.

        A confirmation names the version and hash it was made against. Reading
        it back without checking that binding is still current lets the
        permission outlive the card: readiness withdraws on a new version while
        the relation list keeps answering, and the two then disagree about
        whether the card is usable. Authorization re-projects from here, so the
        binding has to be enforced here rather than in the caller.
        """
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT r.* FROM confirmed_asset_relations r
                JOIN assets a ON a.asset_id=r.current_asset_id
                WHERE r.relation_id=? AND r.lifecycle='CONFIRMED'
                  AND a.current_version_id=r.current_version_id
                  AND a.lifecycle NOT IN ('DELETION_PENDING', 'DELETED')""",
                (str(relation_id),),
            ).fetchone()
        return self._load_relation(row) if row else None

    def read_relation_record(
        self, relation_id: UUID
    ) -> ConfirmedAssetRelationV1 | None:
        """The row as stored, whatever its lifecycle — for audit, not access.

        Kept separate from `read_confirmed_relation` so that reconstructing what
        happened can never be done with the same call that authorizes a read.
        """
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM confirmed_asset_relations WHERE relation_id=?",
                (str(relation_id),),
            ).fetchone()
        return self._load_relation(row) if row else None

    def read_projection(self, projection_id: UUID) -> RoleGraphProjectionV1:
        """Read one projection regardless of lifecycle.

        Retired projections stay readable: a mapping validated under an older
        role contract is still the explanation of a decision the user made, even
        though it is no longer comparable against the current contract.
        """
        with closing(self._connect()) as connection:
            return self._load_projection(connection, str(projection_id))

    def read_candidate(self, candidate_id: UUID) -> RelationCandidateV1 | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT content_json FROM relation_candidates WHERE candidate_id=?",
                (str(candidate_id),),
            ).fetchone()
        if row is None:
            return None
        return RelationCandidateV1.model_validate_json(row["content_json"])

    def invalidate_for_asset_change(
        self,
        asset_id: UUID,
        *,
        reason: str,
        readiness_lifecycle: str | None = "INVALIDATED",
        projection_lifecycle: str | None = "INVALIDATED",
        candidate_lifecycle: str | None = "INVALIDATED",
        relation_lifecycle: str | None = "INVALIDATED",
        match_current_side: bool = True,
        match_related_side: bool = False,
        redact_copied_content: bool = False,
    ) -> dict[str, int]:
        """Revoke everything derived from an asset that changed, in one write.

        Each artifact's target state is supplied by ticket 09's matrix rather
        than decided here: the repository knows how to move a row atomically,
        not what a privacy narrowing means. `None` means the artifact is left
        alone, which is different from moving it to a default.

        One transaction, because the projection lifecycle change and the index
        row removal must not be separable — a crash between them leaves an index
        row granting comparability for canonical state that no longer exists.
        The FTS deletion rides the projection trigger for the same reason.

        Attempts and decisions are never touched. They are the record of what
        happened, and a reviewer needs an invalidated relation to stay
        distinguishable from one that never existed.
        """
        if not reason.strip():
            raise ValueError("invalidation requires a reason")
        if not (match_current_side or match_related_side):
            raise ValueError("invalidation must walk at least one side of the ledger")

        now = datetime.now(UTC).isoformat()
        asset = str(asset_id)
        moved = dict(
            readiness_invalidated=0,
            projections_invalidated=0,
            candidates_moved=0,
            relations_moved=0,
        )
        # Which columns name this asset. A candidate is the subject of one asset
        # and a reference from the other, and the two roles are affected
        # differently by the same change.
        sides = [
            column
            for column, wanted in (
                ("current_asset_id", match_current_side),
                ("related_asset_id", match_related_side),
            )
            if wanted
        ]
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                if readiness_lifecycle is not None:
                    moved["readiness_invalidated"] = connection.execute(
                        """UPDATE knowledge_card_readiness
                        SET lifecycle=?, invalidated_at=?, invalidation_reason=?
                        WHERE asset_id=? AND lifecycle='ACTIVE'""",
                        (readiness_lifecycle, now, reason, asset),
                    ).rowcount
                if projection_lifecycle is not None:
                    moved["projections_invalidated"] = connection.execute(
                        """UPDATE role_graph_projections
                        SET lifecycle=?, invalidated_at=?, invalidation_reason=?
                        WHERE asset_id=? AND lifecycle IN ('BUILDING', 'ACTIVE')""",
                        (projection_lifecycle, now, reason, asset),
                    ).rowcount
                if candidate_lifecycle is not None:
                    moved["candidates_moved"] = self._move_candidates(
                        connection,
                        asset=asset,
                        sides=sides,
                        lifecycle=candidate_lifecycle,
                        redact=redact_copied_content,
                    )
                if relation_lifecycle is not None:
                    for column in sides:
                        moved["relations_moved"] += connection.execute(
                            f"""UPDATE confirmed_asset_relations
                            SET lifecycle=?, invalidated_at=?, invalidation_reason=?
                            WHERE {column}=? AND lifecycle='CONFIRMED'""",
                            (relation_lifecycle, now, reason, asset),
                        ).rowcount
                connection.commit()
        except sqlite3.Error as exc:
            raise PersistenceError("failed to invalidate state for a changed asset") from exc
        return moved

    @staticmethod
    def _move_candidates(
        connection: sqlite3.Connection,
        *,
        asset: str,
        sides: list[str],
        lifecycle: str,
        redact: bool,
    ) -> int:
        """Move candidate lifecycle in the column and in the stored snapshot.

        The candidate keeps its state in both a column and `content_json`.
        Updating only the column leaves the snapshot claiming the old state, and
        the snapshot is what every read reconstructs the candidate from — so the
        row would report `INVALIDATED` to SQL and `PROPOSED` to the product.
        """
        moved = 0
        for column in sides:
            rows = connection.execute(
                f"""SELECT candidate_id, content_json FROM relation_candidates
                WHERE {column}=? AND lifecycle NOT IN ('STALE', 'INVALIDATED')""",
                (asset,),
            ).fetchall()
            for row in rows:
                snapshot = json.loads(row["content_json"])
                snapshot["lifecycle"] = lifecycle
                if redact:
                    # The candidate carries a title and summary describing the
                    # other asset. Keeping them after that asset is deleted
                    # would recreate, inside the audit trail, exactly the copy
                    # the deletion was meant to remove. Identifiers and hashes
                    # are what make the record auditable and are not content.
                    snapshot["title"] = _REDACTED_TITLE
                    snapshot["summary"] = _REDACTED_SUMMARY
                    # Node mappings stay: they are node identifiers, which are
                    # what makes the mapping auditable, not the text the
                    # deletion was meant to remove.
                moved += connection.execute(
                    """UPDATE relation_candidates SET lifecycle=?, content_json=?
                    WHERE candidate_id=?""",
                    (
                        lifecycle,
                        json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                        row["candidate_id"],
                    ),
                ).rowcount
        return moved

    def read_latest_attempt(self, asset_id: UUID) -> DiscoveryAttemptV1 | None:
        """The most recent settled attempt for an asset, whatever its outcome.

        Includes technical failures: the status read has to be able to say the
        last search stopped, which is a different thing from saying nothing was
        found. Only the *cache* refuses to serve a failure as an answer.
        """
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT * FROM relation_discovery_attempts
                WHERE asset_id=? AND outcome<>'RUNNING'
                ORDER BY finished_at DESC, rowid DESC LIMIT 1""",
                (str(asset_id),),
            ).fetchone()
        return self._load_attempt(row) if row else None

    def read_fingerprint_inputs(
        self, discovery_fingerprint: str
    ) -> DiscoveryFingerprintV1 | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM discovery_fingerprint_records WHERE discovery_fingerprint=?",
                (discovery_fingerprint,),
            ).fetchone()
        if row is None:
            return None
        return DiscoveryFingerprintV1(
            fingerprint_schema_version=row["fingerprint_schema_version"],
            current_asset_id=UUID(row["current_asset_id"]),
            current_version_id=UUID(row["current_version_id"]),
            current_knowledge_card_hash=row["current_knowledge_card_hash"],
            current_projection_hash=row["current_projection_hash"],
            eligible_projection_hashes=json.loads(row["eligible_projection_hashes_json"]),
            model_identity=row["model_identity"],
            model_revision=row["model_revision"],
            prompt_version=row["prompt_version"],
            role_contract_version=row["role_contract_version"],
            validation_contract_version=row["validation_contract_version"],
            discovery_intent_version=row["discovery_intent_version"],
            inference_parameters_hash=row["inference_parameters_hash"],
            prefilter_config_version=row["prefilter_config_version"],
        )

    def recover_expired_reservations(self) -> int:
        """Settle reservations whose lease expired, as retryable failures.

        Never as successful: the process holding the lease never reported an
        outcome, so treating it as one would publish a candidate nobody
        validated.

        Recorded as `LEASE_EXPIRED`, which ticket 01 added for exactly this.
        Before it existed this wrote `MODEL_TIMED_OUT`, which said the model was
        asked and did not answer — a claim nothing here can support, and one
        that sends an investigator to the inference server when the fault is in
        process lifecycle.
        """
        now = datetime.now(UTC)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """SELECT attempt_id, started_at FROM relation_discovery_attempts
                WHERE outcome='RUNNING' AND lease_expires_at<=?""",
                (now.isoformat(),),
            ).fetchall()
            for row in rows:
                started = datetime.fromisoformat(str(row["started_at"]))
                connection.execute(
                    """UPDATE relation_discovery_attempts
                    SET outcome='TECHNICAL_FAILURE', failure_class=?,
                        lease_expires_at=NULL, finished_at=?, elapsed_ms=?
                    WHERE attempt_id=? AND outcome='RUNNING'""",
                    (
                        DiscoveryFailureClass.LEASE_EXPIRED.value,
                        now.isoformat(),
                        max(0, round((now - started).total_seconds() * 1000)),
                        row["attempt_id"],
                    ),
                )
            connection.commit()
        return len(rows)

    @staticmethod
    def _record_fingerprint_inputs(
        connection: sqlite3.Connection,
        digest: str,
        fingerprint: DiscoveryFingerprintV1,
        now: datetime,
    ) -> None:
        """Persist the canonical inputs beside the digest, once per fingerprint."""
        from app.experience_asset.persistence.relation_ledger import LedgerConflictError

        existing = connection.execute(
            """SELECT eligible_projection_hashes_json, model_identity, model_revision
            FROM discovery_fingerprint_records WHERE discovery_fingerprint=?""",
            (digest,),
        ).fetchone()
        if existing is not None:
            # Same digest, different inputs means canonicalization is broken.
            # Silently keeping the first set would leave every cached answer
            # attributable to inputs that did not produce it.
            if (
                json.loads(existing["eligible_projection_hashes_json"])
                != fingerprint.eligible_projection_hashes
                or existing["model_identity"] != fingerprint.model_identity
                or existing["model_revision"] != fingerprint.model_revision
            ):
                raise LedgerConflictError(
                    "this fingerprint digest is already on record with different inputs"
                )
            return
        connection.execute(
            """INSERT INTO discovery_fingerprint_records(
                discovery_fingerprint, fingerprint_schema_version, current_asset_id,
                current_version_id, current_knowledge_card_hash, current_projection_hash,
                eligible_projection_hashes_json, model_identity, model_revision,
                prompt_version, role_contract_version, validation_contract_version,
                discovery_intent_version, inference_parameters_hash,
                prefilter_config_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                digest,
                fingerprint.fingerprint_schema_version,
                str(fingerprint.current_asset_id),
                str(fingerprint.current_version_id),
                fingerprint.current_knowledge_card_hash,
                fingerprint.current_projection_hash,
                json.dumps(fingerprint.eligible_projection_hashes),
                fingerprint.model_identity,
                fingerprint.model_revision,
                fingerprint.prompt_version,
                fingerprint.role_contract_version,
                fingerprint.validation_contract_version,
                fingerprint.discovery_intent_version,
                fingerprint.inference_parameters_hash,
                fingerprint.prefilter_config_version,
                now.isoformat(),
            ),
        )

    @staticmethod
    def _load_attempt(row: sqlite3.Row) -> DiscoveryAttemptV1:
        return DiscoveryAttemptV1(
            attempt_id=UUID(row["attempt_id"]),
            run_id=UUID(row["run_id"]),
            asset_id=UUID(row["asset_id"]),
            discovery_fingerprint=row["discovery_fingerprint"],
            current_projection_id=UUID(row["current_projection_id"]),
            eligible_set_hash=row["eligible_set_hash"],
            attempt_number=int(row["attempt_number"]),
            outcome=DiscoveryOutcome(row["outcome"]),
            failure_class=(
                DiscoveryFailureClass(row["failure_class"]) if row["failure_class"] else None
            ),
            candidate_id=UUID(row["candidate_id"]) if row["candidate_id"] else None,
            lease_expires_at=(
                datetime.fromisoformat(str(row["lease_expires_at"]))
                if row["lease_expires_at"]
                else None
            ),
            started_at=datetime.fromisoformat(str(row["started_at"])),
            finished_at=(
                datetime.fromisoformat(str(row["finished_at"])) if row["finished_at"] else None
            ),
            elapsed_ms=int(row["elapsed_ms"]) if row["elapsed_ms"] is not None else None,
        )

    @staticmethod
    def _load_projection(
        connection: sqlite3.Connection, projection_id: str
    ) -> RoleGraphProjectionV1:
        parent = connection.execute(
            "SELECT * FROM role_graph_projections WHERE projection_id=?",
            (projection_id,),
        ).fetchone()
        if parent is None:
            raise AssetNotFoundError(f"projection {projection_id}")
        nodes = [
            RoleGraphNodeV1.model_validate(dict(row))
            for row in connection.execute(
                "SELECT * FROM role_graph_nodes WHERE projection_id=? ORDER BY display_order",
                (projection_id,),
            ).fetchall()
        ]
        edges = [
            RoleGraphEdgeV1.model_validate(dict(row))
            for row in connection.execute(
                "SELECT * FROM role_graph_edges WHERE projection_id=? ORDER BY edge_id",
                (projection_id,),
            ).fetchall()
        ]
        provenance = [
            NodeProvenanceV1(
                projection_id=UUID(row["projection_id"]),
                node_id=row["node_id"],
                statement_ids=json.loads(row["statement_ids_json"]),
                evidence_refs=json.loads(row["evidence_refs_json"]),
                source_refs=json.loads(row["source_refs_json"]),
                span_refs=json.loads(row["span_refs_json"]),
            )
            for row in connection.execute(
                "SELECT * FROM role_graph_node_provenance "
                "WHERE projection_id=? ORDER BY node_id",
                (projection_id,),
            ).fetchall()
        ]
        return RoleGraphProjectionV1(
            projection_id=UUID(parent["projection_id"]),
            asset_id=UUID(parent["asset_id"]),
            version_id=UUID(parent["version_id"]),
            knowledge_card_hash=parent["knowledge_card_hash"],
            projection_schema_version=parent["projection_schema_version"],
            projection_hash=parent["projection_hash"],
            lifecycle=parent["lifecycle"],
            nodes=nodes,
            edges=edges,
            provenance=provenance,
            created_at=parent["created_at"],
            invalidated_at=parent["invalidated_at"],
            invalidation_reason=parent["invalidation_reason"],
        )

    def append_m2(
        self,
        artifact: CriticalMomentMapV1,
        *,
        expected_current_artifact_id: UUID | None,
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT artifact_id FROM m2_current WHERE asset_id = ?",
                (str(artifact.asset_id),),
            ).fetchone()
            actual = UUID(row["artifact_id"]) if row else None
            if actual != expected_current_artifact_id:
                raise StorageConflictError("current M2 changed; reload before saving")
            try:
                connection.execute(
                    """INSERT INTO m2_artifacts(
                        artifact_id, asset_id, parent_artifact_id, base_m1_version_id,
                        content_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        str(artifact.artifact_id),
                        str(artifact.asset_id),
                        str(actual) if actual else None,
                        str(artifact.base_m1_version_id),
                        artifact.model_dump_json(),
                        artifact.created_at.isoformat(),
                    ),
                )
                connection.execute(
                    """INSERT INTO m2_current(asset_id, artifact_id) VALUES (?, ?)
                    ON CONFLICT(asset_id) DO UPDATE SET artifact_id = excluded.artifact_id""",
                    (str(artifact.asset_id), str(artifact.artifact_id)),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise StorageConflictError("M2 artifact already exists") from exc

    def append_canonical_and_m2(
        self,
        snapshot: ExperienceAssetV1,
        artifact: CriticalMomentMapV1,
        *,
        expected_current_version_id: UUID,
        expected_current_artifact_id: UUID | None,
        m3_successor: DecisionEvidenceLedgerV1 | None = None,
    ) -> None:
        """CAS and append both immutable M2 and canonical projections atomically."""
        if snapshot.lineage.parent_version_id != expected_current_version_id:
            raise StorageConflictError("snapshot parent does not match expected current version")
        if artifact.asset_id != snapshot.asset_id:
            raise StorageConflictError("canonical and M2 asset identities differ")
        if m3_successor is not None and m3_successor.asset_id != snapshot.asset_id:
            raise StorageConflictError("canonical and M3 successor asset identities differ")
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                asset_row = connection.execute(
                    "SELECT current_version_id FROM assets WHERE asset_id = ?",
                    (str(snapshot.asset_id),),
                ).fetchone()
                if asset_row is None:
                    raise AssetNotFoundError(str(snapshot.asset_id))
                if asset_row["current_version_id"] != str(expected_current_version_id):
                    raise StorageConflictError("current version changed; reload before saving")
                m2_row = connection.execute(
                    "SELECT artifact_id FROM m2_current WHERE asset_id = ?",
                    (str(snapshot.asset_id),),
                ).fetchone()
                actual_m2 = UUID(m2_row["artifact_id"]) if m2_row else None
                if actual_m2 != expected_current_artifact_id:
                    raise StorageConflictError("current M2 changed; reload before saving")
                connection.execute(
                    """INSERT INTO m2_artifacts(
                        artifact_id, asset_id, parent_artifact_id, base_m1_version_id,
                        content_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        str(artifact.artifact_id),
                        str(artifact.asset_id),
                        str(actual_m2) if actual_m2 else None,
                        str(artifact.base_m1_version_id),
                        artifact.model_dump_json(),
                        artifact.created_at.isoformat(),
                    ),
                )
                m3_row = connection.execute(
                    """SELECT a.content_json FROM m3_current c
                    JOIN m3_artifacts a ON a.artifact_id=c.artifact_id
                    WHERE c.asset_id=?""",
                    (str(snapshot.asset_id),),
                ).fetchone()
                ledger = (
                    DecisionEvidenceLedgerV1.model_validate_json(m3_row["content_json"])
                    if m3_row is not None
                    else None
                )
                if (ledger is None) != (m3_successor is None):
                    raise StorageConflictError("M3 successor does not match current M3")
                if m3_successor is not None:
                    if ledger is None or m3_successor.artifact_id == ledger.artifact_id:
                        raise StorageConflictError("M3 successor identity is not a new child")
                    binds_transition = (
                        m3_successor.invalidated_by_m2_artifact_id == artifact.artifact_id
                        and m3_successor.invalidated_by_canonical_version_id == snapshot.version_id
                    ) or (
                        m3_successor.base_m2_artifact_id == artifact.artifact_id
                        and m3_successor.base_canonical_version_id == snapshot.version_id
                    )
                    if not binds_transition:
                        raise StorageConflictError(
                            "M3 successor does not bind the exact M2 transition"
                        )
                self._insert_version(
                    connection,
                    snapshot,
                    self._snapshot_json(snapshot),
                    self._snapshot_hash(snapshot),
                )
                if m3_successor is not None:
                    connection.execute(
                        "INSERT INTO m3_artifacts VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            str(m3_successor.artifact_id),
                            str(m3_successor.asset_id),
                            str(ledger.artifact_id),
                            str(m3_successor.base_m2_artifact_id),
                            str(m3_successor.base_canonical_version_id),
                            m3_successor.model_dump_json(),
                            m3_successor.created_at.isoformat(),
                        ),
                    )
                    updated_m3 = connection.execute(
                        "UPDATE m3_current SET artifact_id=? WHERE asset_id=? AND artifact_id=?",
                        (
                            str(m3_successor.artifact_id),
                            str(snapshot.asset_id),
                            str(ledger.artifact_id),
                        ),
                    )
                    if updated_m3.rowcount != 1:
                        raise StorageConflictError("current M3 changed during M2 save")
                connection.execute(
                    """INSERT INTO m2_current(asset_id, artifact_id) VALUES (?, ?)
                    ON CONFLICT(asset_id) DO UPDATE SET artifact_id = excluded.artifact_id""",
                    (str(snapshot.asset_id), str(artifact.artifact_id)),
                )
                updated = connection.execute(
                    """UPDATE assets SET current_version_id = ?, updated_at = ?, lifecycle = ?
                    WHERE asset_id = ? AND current_version_id = ?""",
                    (
                        str(snapshot.version_id),
                        snapshot.updated_at.isoformat(),
                        snapshot.lifecycle.value,
                        str(snapshot.asset_id),
                        str(expected_current_version_id),
                    ),
                )
                if updated.rowcount != 1:
                    raise StorageConflictError("current version changed during save")
                connection.commit()
        except (AssetNotFoundError, StorageConflictError):
            raise
        except sqlite3.IntegrityError as exc:
            raise StorageConflictError("canonical or M2 version already exists") from exc
        except sqlite3.Error as exc:
            raise PersistenceError("failed to append canonical and M2 versions") from exc

    def get_current_m2(self, asset_id: UUID) -> CriticalMomentMapV1:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT a.content_json FROM m2_current c
                JOIN m2_artifacts a ON a.artifact_id = c.artifact_id
                WHERE c.asset_id = ?""",
                (str(asset_id),),
            ).fetchone()
        if row is None:
            raise AssetNotFoundError(f"M2 artifact for {asset_id}")
        return CriticalMomentMapV1.model_validate_json(row["content_json"])

    def get_m2_artifact(self, artifact_id: UUID) -> CriticalMomentMapV1:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT content_json FROM m2_artifacts WHERE artifact_id = ?",
                (str(artifact_id),),
            ).fetchone()
        if row is None:
            raise AssetNotFoundError(str(artifact_id))
        return CriticalMomentMapV1.model_validate_json(row["content_json"])

    def list_m2_artifact_ids(self, asset_id: UUID) -> list[UUID]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT artifact_id FROM m2_artifacts WHERE asset_id = ? ORDER BY rowid",
                (str(asset_id),),
            ).fetchall()
        return [UUID(row["artifact_id"]) for row in rows]

    def get_current_m3(self, asset_id: UUID) -> DecisionEvidenceLedgerV1:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT a.content_json FROM m3_current c
                JOIN m3_artifacts a ON a.artifact_id = c.artifact_id
                WHERE c.asset_id = ?""",
                (str(asset_id),),
            ).fetchone()
        if row is None:
            raise AssetNotFoundError(f"M3 artifact for {asset_id}")
        return DecisionEvidenceLedgerV1.model_validate_json(row["content_json"])

    def get_m3_artifact(self, artifact_id: UUID) -> DecisionEvidenceLedgerV1:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT content_json FROM m3_artifacts WHERE artifact_id = ?",
                (str(artifact_id),),
            ).fetchone()
        if row is None:
            raise AssetNotFoundError(str(artifact_id))
        return DecisionEvidenceLedgerV1.model_validate_json(row["content_json"])

    def list_m3_artifact_ids(self, asset_id: UUID) -> list[UUID]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT artifact_id FROM m3_artifacts WHERE asset_id = ? ORDER BY rowid",
                (str(asset_id),),
            ).fetchall()
        return [UUID(row["artifact_id"]) for row in rows]

    def append_canonical_and_m3(
        self,
        snapshot: ExperienceAssetV1,
        artifact: DecisionEvidenceLedgerV1,
        *,
        expected_current_version_id: UUID,
        expected_current_artifact_id: UUID | None,
        expected_m2_artifact_id: UUID,
        graph_run_id: UUID | None = None,
    ) -> None:
        """Atomically CAS canonical, accepted M2 identity, and immutable M3 history."""
        if snapshot.lineage.parent_version_id != expected_current_version_id:
            raise StorageConflictError("snapshot parent does not match expected current version")
        if snapshot.asset_id != artifact.asset_id:
            raise StorageConflictError("canonical and M3 asset identities differ")
        if artifact.base_m2_artifact_id != expected_m2_artifact_id:
            raise StorageConflictError("M3 base does not match expected M2")
        if artifact.base_canonical_version_id != expected_current_version_id:
            raise StorageConflictError("M3 base does not match expected canonical version")
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                asset = connection.execute(
                    "SELECT current_version_id FROM assets WHERE asset_id = ?",
                    (str(snapshot.asset_id),),
                ).fetchone()
                m2 = connection.execute(
                    "SELECT artifact_id FROM m2_current WHERE asset_id = ?",
                    (str(snapshot.asset_id),),
                ).fetchone()
                m3 = connection.execute(
                    "SELECT artifact_id FROM m3_current WHERE asset_id = ?",
                    (str(snapshot.asset_id),),
                ).fetchone()
                actual_m3 = UUID(m3["artifact_id"]) if m3 else None
                if asset is None or asset["current_version_id"] != str(expected_current_version_id):
                    raise StorageConflictError("current canonical version changed")
                if m2 is None or m2["artifact_id"] != str(expected_m2_artifact_id):
                    raise StorageConflictError("current M2 changed")
                if actual_m3 != expected_current_artifact_id:
                    raise StorageConflictError("current M3 changed")
                connection.execute(
                    """INSERT INTO m3_artifacts VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(artifact.artifact_id),
                        str(artifact.asset_id),
                        str(actual_m3) if actual_m3 else None,
                        str(artifact.base_m2_artifact_id),
                        str(artifact.base_canonical_version_id),
                        artifact.model_dump_json(),
                        artifact.created_at.isoformat(),
                    ),
                )
                self._insert_version(
                    connection,
                    snapshot,
                    self._snapshot_json(snapshot),
                    self._snapshot_hash(snapshot),
                )
                if graph_run_id is not None:
                    if artifact.generated_by_run_id != graph_run_id:
                        raise StorageConflictError("M3 graph commit run identity mismatch")
                    existing_commit = connection.execute(
                        """SELECT artifact_id, canonical_version_id
                        FROM m3_run_commits WHERE run_id=?""",
                        (str(graph_run_id),),
                    ).fetchone()
                    identities = (str(artifact.artifact_id), str(snapshot.version_id))
                    if existing_commit is not None:
                        if tuple(existing_commit) != identities:
                            raise StorageConflictError("M3 run commit identity changed")
                    else:
                        connection.execute(
                            "INSERT INTO m3_run_commits VALUES (?, ?, ?, ?)",
                            (str(graph_run_id), *identities, datetime.now(UTC).isoformat()),
                        )
                updated_m3 = connection.execute(
                    """INSERT INTO m3_current VALUES (?, ?) ON CONFLICT(asset_id)
                    DO UPDATE SET artifact_id = excluded.artifact_id
                    WHERE m3_current.artifact_id = ?"""
                    if actual_m3
                    else "INSERT INTO m3_current VALUES (?, ?)",
                    (
                        (str(snapshot.asset_id), str(artifact.artifact_id), str(actual_m3))
                        if actual_m3
                        else (str(snapshot.asset_id), str(artifact.artifact_id))
                    ),
                )
                if updated_m3.rowcount != 1:
                    raise StorageConflictError("current M3 changed during save")
                updated = connection.execute(
                    """UPDATE assets SET current_version_id=?, updated_at=?, lifecycle=?
                    WHERE asset_id=? AND current_version_id=?""",
                    (
                        str(snapshot.version_id),
                        snapshot.updated_at.isoformat(),
                        snapshot.lifecycle.value,
                        str(snapshot.asset_id),
                        str(expected_current_version_id),
                    ),
                )
                if updated.rowcount != 1:
                    raise StorageConflictError("current canonical version changed during save")
                connection.commit()
        except (AssetNotFoundError, StorageConflictError):
            raise
        except sqlite3.IntegrityError as exc:
            raise StorageConflictError("canonical or M3 artifact already exists") from exc
        except sqlite3.Error as exc:
            raise PersistenceError("failed to append canonical and M3") from exc

    def save_m3_proposal(
        self,
        run_id: UUID,
        attempt: int,
        proposal: M3LedgerProposal,
        proposal_hash: str,
        metadata: ModelMetadata,
    ) -> None:
        metadata_values = (
            metadata.server_kind,
            metadata.server_base_url,
            metadata.model_id,
            metadata.response_id,
            metadata.prompt_tokens,
            metadata.completion_tokens,
            metadata.elapsed_ms,
            metadata.received_at.isoformat(),
        )
        with closing(self._connect()) as connection:
            existing = connection.execute(
                """SELECT proposal_hash, content_json, server_kind, server_base_url,
                model_id, response_id, prompt_tokens, completion_tokens, elapsed_ms,
                received_at FROM m3_model_proposals
                WHERE run_id=? AND attempt=?""",
                (str(run_id), attempt),
            ).fetchone()
            requested = (proposal_hash, proposal.model_dump_json(), *metadata_values)
            if existing:
                if tuple(existing) != requested:
                    raise StorageConflictError("M3 proposal differs for this run")
                return
            connection.execute(
                """INSERT INTO m3_model_proposals(
                    run_id, attempt, proposal_hash, content_json, created_at,
                    server_kind, server_base_url, model_id, response_id,
                    prompt_tokens, completion_tokens, elapsed_ms, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(run_id),
                    attempt,
                    proposal_hash,
                    proposal.model_dump_json(),
                    datetime.now(UTC).isoformat(),
                    *metadata_values,
                ),
            )
            connection.commit()

    def get_m3_proposal(self, run_id: UUID, attempt: int) -> tuple[M3LedgerProposal, str]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT proposal_hash, content_json FROM m3_model_proposals
                WHERE run_id=? AND attempt=?""",
                (str(run_id), attempt),
            ).fetchone()
        if row is None:
            raise AssetNotFoundError(f"M3 proposal for {run_id}")
        return M3LedgerProposal.model_validate_json(row["content_json"]), row["proposal_hash"]

    def get_m3_proposal_metadata(self, run_id: UUID, attempt: int) -> ModelMetadata:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT server_kind, server_base_url, model_id, response_id,
                prompt_tokens, completion_tokens, elapsed_ms, received_at
                FROM m3_model_proposals WHERE run_id=? AND attempt=?""",
                (str(run_id), attempt),
            ).fetchone()
        if row is None:
            raise AssetNotFoundError(f"M3 proposal metadata for {run_id}")
        return ModelMetadata.model_validate(dict(row))

    def save_m3_policy_decision(
        self,
        *,
        run_id: UUID,
        proposal_attempt: int,
        decision: PolicyDecision,
    ) -> None:
        """Persist a sanitized Runtime decision separately from graph cursor state."""

        requested = (
            str(run_id),
            proposal_attempt,
            str(decision.proposal_id),
            decision.model_dump_json(),
            decision.decided_at.isoformat(),
        )
        with closing(self._connect()) as connection:
            existing = connection.execute(
                """SELECT run_id, proposal_attempt, proposal_id, content_json, created_at
                FROM m3_policy_decisions WHERE decision_id=?""",
                (str(decision.decision_id),),
            ).fetchone()
            if existing:
                if tuple(existing) != requested:
                    raise StorageConflictError("M3 policy decision identity differs")
                return
            connection.execute(
                """INSERT INTO m3_policy_decisions(
                    decision_id, run_id, proposal_attempt, proposal_id, content_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (str(decision.decision_id), *requested),
            )
            connection.commit()

    def get_m3_policy_decision(
        self,
        *,
        run_id: UUID,
        proposal_attempt: int,
        proposal_id: UUID,
    ) -> PolicyDecision | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT content_json FROM m3_policy_decisions
                WHERE run_id=? AND proposal_attempt=? AND proposal_id=?""",
                (str(run_id), proposal_attempt, str(proposal_id)),
            ).fetchone()
        return PolicyDecision.model_validate_json(row["content_json"]) if row else None

    def list_m3_policy_decisions(self, run_id: UUID) -> list[PolicyDecision]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT content_json FROM m3_policy_decisions
                WHERE run_id=? ORDER BY proposal_attempt, created_at, rowid""",
                (str(run_id),),
            ).fetchall()
        return [PolicyDecision.model_validate_json(row["content_json"]) for row in rows]

    def get_m3_run_commit(
        self, run_id: UUID
    ) -> tuple[DecisionEvidenceLedgerV1, ExperienceAssetV1] | None:
        """Load the immutable artifact and canonical projection committed by this run."""
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT a.content_json AS artifact_json, v.content_json AS snapshot_json
                FROM m3_run_commits c
                JOIN m3_artifacts a ON a.artifact_id=c.artifact_id
                JOIN asset_versions v ON v.version_id=c.canonical_version_id
                WHERE c.run_id=?""",
                (str(run_id),),
            ).fetchone()
        if row is None:
            return None
        return (
            DecisionEvidenceLedgerV1.model_validate_json(row["artifact_json"]),
            ExperienceAssetV1.model_validate_json(row["snapshot_json"]),
        )

    def configure_m3_run(
        self, run_id: UUID, *, regenerate: bool, expected_invalidated_artifact_id: UUID | None
    ) -> None:
        with closing(self._connect()) as connection:
            updated = connection.execute(
                """UPDATE workflow_run_contexts
                SET m3_regenerate=?, expected_invalidated_m3_artifact_id=? WHERE run_id=?""",
                (
                    int(regenerate),
                    str(expected_invalidated_artifact_id)
                    if expected_invalidated_artifact_id
                    else None,
                    str(run_id),
                ),
            )
            if updated.rowcount != 1:
                raise AssetNotFoundError(f"workflow run: {run_id}")
            connection.commit()

    def update_m3_run_outcome(
        self, run_id: UUID, *, repairs: int, replans: int, finding_codes: list[str]
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """UPDATE runs SET structured_repair_count=?, replan_count=?, finding_codes_json=?
                WHERE run_id=?""",
                (repairs, replans, json.dumps(finding_codes), str(run_id)),
            )
            connection.commit()

    def get_latest_m3_run(
        self, asset_id: UUID, *, failed_only: bool = False
    ) -> dict[str, object] | None:
        where = (
            "AND terminal_state IS NOT NULL AND terminal_state != 'SUCCEEDED'"
            if failed_only
            else ""
        )
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"""SELECT r.run_id, r.terminal_state, r.retryable,
                r.safe_user_message, r.recovery_action, r.model_call_count,
                r.structured_repair_count, r.replan_count, r.finding_codes_json,
                r.finished_at, c.base_m2_artifact_id, c.m3_regenerate,
                c.expected_invalidated_m3_artifact_id
                FROM runs r
                JOIN workflow_run_contexts c ON c.run_id=r.run_id
                WHERE r.asset_id=? AND r.workflow_version=? {where}
                ORDER BY r.started_at DESC, r.rowid DESC LIMIT 1""",
                (str(asset_id), "experience-asset/e4-m3/v1"),
            ).fetchone()
        return dict(row) if row else None

    def get_m3_run_outcome(self, run_id: UUID) -> dict[str, object] | None:
        """Return terminal and bounded M3 counters/findings from exactly one run."""
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT run_id, terminal_state, safe_user_message, recovery_action,
                model_call_count, structured_repair_count, replan_count,
                finding_codes_json, finished_at
                FROM runs WHERE run_id=? AND workflow_version=? AND terminal_state IS NOT NULL""",
                (str(run_id), "experience-asset/e4-m3/v1"),
            ).fetchone()
        return dict(row) if row else None

    def get_version_content_hash(self, version_id: UUID) -> str:
        """Return the hash stored with the version, not one recomputed at read time.

        A recomputed hash would agree with the stored one only while the
        serializer is byte-stable, so a serializer change would silently move
        every card hash a readiness record and a relation are bound to.
        """
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT content_hash FROM asset_versions WHERE version_id = ?",
                (str(version_id),),
            ).fetchone()
        if row is None:
            raise AssetNotFoundError(f"version {version_id}")
        return str(row["content_hash"])

    def get_current_m4(self, asset_id: UUID) -> InsightBoundaryMapV1:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT a.content_json FROM m4_current c
                JOIN m4_artifacts a ON a.artifact_id = c.artifact_id
                WHERE c.asset_id = ?""",
                (str(asset_id),),
            ).fetchone()
        if row is None:
            raise AssetNotFoundError(f"M4 artifact for {asset_id}")
        return InsightBoundaryMapV1.model_validate_json(row["content_json"])

    def get_m4_artifact(self, artifact_id: UUID) -> InsightBoundaryMapV1:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT content_json FROM m4_artifacts WHERE artifact_id = ?",
                (str(artifact_id),),
            ).fetchone()
        if row is None:
            raise AssetNotFoundError(str(artifact_id))
        return InsightBoundaryMapV1.model_validate_json(row["content_json"])

    def list_m4_artifact_ids(self, asset_id: UUID) -> list[UUID]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT artifact_id FROM m4_artifacts WHERE asset_id = ? ORDER BY rowid",
                (str(asset_id),),
            ).fetchall()
        return [UUID(row["artifact_id"]) for row in rows]

    def append_canonical_and_m4(
        self,
        snapshot: ExperienceAssetV1,
        artifact: InsightBoundaryMapV1,
        *,
        expected_current_version_id: UUID,
        expected_current_artifact_id: UUID | None,
        expected_m3_artifact_id: UUID,
        graph_run_id: UUID | None = None,
    ) -> None:
        """Atomically CAS canonical, accepted M3 identity, and immutable M4 history."""
        if snapshot.lineage.parent_version_id != expected_current_version_id:
            raise StorageConflictError("snapshot parent does not match expected current version")
        if snapshot.asset_id != artifact.asset_id:
            raise StorageConflictError("canonical and M4 asset identities differ")
        if artifact.base_m3_artifact_id != expected_m3_artifact_id:
            raise StorageConflictError("M4 base does not match expected M3")
        if artifact.base_canonical_version_id != expected_current_version_id:
            raise StorageConflictError("M4 base does not match expected canonical version")
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                asset = connection.execute(
                    "SELECT current_version_id FROM assets WHERE asset_id = ?",
                    (str(snapshot.asset_id),),
                ).fetchone()
                m3 = connection.execute(
                    "SELECT artifact_id FROM m3_current WHERE asset_id = ?",
                    (str(snapshot.asset_id),),
                ).fetchone()
                m4 = connection.execute(
                    "SELECT artifact_id FROM m4_current WHERE asset_id = ?",
                    (str(snapshot.asset_id),),
                ).fetchone()
                actual_m4 = UUID(m4["artifact_id"]) if m4 else None
                if asset is None or asset["current_version_id"] != str(expected_current_version_id):
                    raise StorageConflictError("current canonical version changed")
                if m3 is None or m3["artifact_id"] != str(expected_m3_artifact_id):
                    raise StorageConflictError("current M3 changed")
                if actual_m4 != expected_current_artifact_id:
                    raise StorageConflictError("current M4 changed")
                connection.execute(
                    """INSERT INTO m4_artifacts VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(artifact.artifact_id),
                        str(artifact.asset_id),
                        str(actual_m4) if actual_m4 else None,
                        str(artifact.base_m3_artifact_id),
                        str(artifact.base_canonical_version_id),
                        artifact.model_dump_json(),
                        artifact.created_at.isoformat(),
                    ),
                )
                self._insert_version(
                    connection,
                    snapshot,
                    self._snapshot_json(snapshot),
                    self._snapshot_hash(snapshot),
                )
                if graph_run_id is not None:
                    if artifact.generated_by_run_id != graph_run_id:
                        raise StorageConflictError("M4 graph commit run identity mismatch")
                    existing_commit = connection.execute(
                        """SELECT artifact_id, canonical_version_id
                        FROM m4_run_commits WHERE run_id=?""",
                        (str(graph_run_id),),
                    ).fetchone()
                    identities = (str(artifact.artifact_id), str(snapshot.version_id))
                    if existing_commit is not None:
                        if tuple(existing_commit) != identities:
                            raise StorageConflictError("M4 run commit identity changed")
                    else:
                        connection.execute(
                            "INSERT INTO m4_run_commits VALUES (?, ?, ?, ?)",
                            (str(graph_run_id), *identities, datetime.now(UTC).isoformat()),
                        )
                updated_m4 = connection.execute(
                    """INSERT INTO m4_current VALUES (?, ?) ON CONFLICT(asset_id)
                    DO UPDATE SET artifact_id = excluded.artifact_id
                    WHERE m4_current.artifact_id = ?"""
                    if actual_m4
                    else "INSERT INTO m4_current VALUES (?, ?)",
                    (
                        (str(snapshot.asset_id), str(artifact.artifact_id), str(actual_m4))
                        if actual_m4
                        else (str(snapshot.asset_id), str(artifact.artifact_id))
                    ),
                )
                if updated_m4.rowcount != 1:
                    raise StorageConflictError("current M4 changed during save")
                updated = connection.execute(
                    """UPDATE assets SET current_version_id=?, updated_at=?, lifecycle=?
                    WHERE asset_id=? AND current_version_id=?""",
                    (
                        str(snapshot.version_id),
                        snapshot.updated_at.isoformat(),
                        snapshot.lifecycle.value,
                        str(snapshot.asset_id),
                        str(expected_current_version_id),
                    ),
                )
                if updated.rowcount != 1:
                    raise StorageConflictError("current canonical version changed during save")
                connection.commit()
        except (AssetNotFoundError, StorageConflictError):
            raise
        except sqlite3.IntegrityError as exc:
            raise StorageConflictError("canonical or M4 artifact already exists") from exc
        except sqlite3.Error as exc:
            raise PersistenceError("failed to append canonical and M4") from exc

    def append_canonical_and_m4_successor(
        self,
        snapshot: ExperienceAssetV1,
        successor: InsightBoundaryMapV1,
        *,
        expected_current_version_id: UUID,
        expected_current_artifact_id: UUID,
        expected_m3_artifact_id: UUID,
    ) -> None:
        """Persist the M4 successor of one exact M3 transition, atomically.

        Separate from ``append_canonical_and_m4`` because an invalidated
        successor keeps the base it was built from and names the correction that
        retired it, so it cannot satisfy the create/edit rule that the base is
        the current canonical version.
        """
        if snapshot.lineage.parent_version_id != expected_current_version_id:
            raise StorageConflictError("snapshot parent does not match expected current version")
        if snapshot.asset_id != successor.asset_id:
            raise StorageConflictError("canonical and M4 successor asset identities differ")
        binds_transition = (
            successor.invalidated_by_m3_artifact_id == expected_m3_artifact_id
            and successor.invalidated_by_canonical_version_id == snapshot.version_id
        ) or (
            successor.base_m3_artifact_id == expected_m3_artifact_id
            and successor.base_canonical_version_id == snapshot.version_id
        )
        if not binds_transition:
            raise StorageConflictError("M4 successor does not bind the exact M3 transition")
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                asset = connection.execute(
                    "SELECT current_version_id FROM assets WHERE asset_id = ?",
                    (str(snapshot.asset_id),),
                ).fetchone()
                m3 = connection.execute(
                    "SELECT artifact_id FROM m3_current WHERE asset_id = ?",
                    (str(snapshot.asset_id),),
                ).fetchone()
                m4 = connection.execute(
                    "SELECT artifact_id FROM m4_current WHERE asset_id = ?",
                    (str(snapshot.asset_id),),
                ).fetchone()
                if asset is None or asset["current_version_id"] != str(expected_current_version_id):
                    raise StorageConflictError("current canonical version changed")
                if m3 is None or m3["artifact_id"] != str(expected_m3_artifact_id):
                    raise StorageConflictError("current M3 changed")
                if m4 is None or m4["artifact_id"] != str(expected_current_artifact_id):
                    raise StorageConflictError("current M4 changed")
                if successor.artifact_id == UUID(m4["artifact_id"]):
                    raise StorageConflictError("M4 successor identity is not a new child")
                connection.execute(
                    """INSERT INTO m4_artifacts VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(successor.artifact_id),
                        str(successor.asset_id),
                        str(expected_current_artifact_id),
                        str(successor.base_m3_artifact_id),
                        str(successor.base_canonical_version_id),
                        successor.model_dump_json(),
                        successor.created_at.isoformat(),
                    ),
                )
                self._insert_version(
                    connection,
                    snapshot,
                    self._snapshot_json(snapshot),
                    self._snapshot_hash(snapshot),
                )
                updated_m4 = connection.execute(
                    """UPDATE m4_current SET artifact_id=? WHERE asset_id=? AND artifact_id=?""",
                    (
                        str(successor.artifact_id),
                        str(snapshot.asset_id),
                        str(expected_current_artifact_id),
                    ),
                )
                if updated_m4.rowcount != 1:
                    raise StorageConflictError("current M4 changed during save")
                updated = connection.execute(
                    """UPDATE assets SET current_version_id=?, updated_at=?, lifecycle=?
                    WHERE asset_id=? AND current_version_id=?""",
                    (
                        str(snapshot.version_id),
                        snapshot.updated_at.isoformat(),
                        snapshot.lifecycle.value,
                        str(snapshot.asset_id),
                        str(expected_current_version_id),
                    ),
                )
                if updated.rowcount != 1:
                    raise StorageConflictError("current canonical version changed during save")
                connection.commit()
        except (AssetNotFoundError, StorageConflictError):
            raise
        except sqlite3.IntegrityError as exc:
            raise StorageConflictError("canonical or M4 successor already exists") from exc
        except sqlite3.Error as exc:
            raise PersistenceError("failed to append canonical and M4 successor") from exc

    def save_m4_proposal(
        self,
        run_id: UUID,
        attempt: int,
        proposal: M4MapProposal,
        proposal_hash: str,
        metadata: ModelMetadata,
    ) -> None:
        metadata_values = (
            metadata.server_kind,
            metadata.server_base_url,
            metadata.model_id,
            metadata.response_id,
            metadata.prompt_tokens,
            metadata.completion_tokens,
            metadata.elapsed_ms,
            metadata.received_at.isoformat(),
        )
        with closing(self._connect()) as connection:
            existing = connection.execute(
                """SELECT proposal_hash, content_json, server_kind, server_base_url,
                model_id, response_id, prompt_tokens, completion_tokens, elapsed_ms,
                received_at FROM m4_model_proposals
                WHERE run_id=? AND attempt=?""",
                (str(run_id), attempt),
            ).fetchone()
            requested = (proposal_hash, proposal.model_dump_json(), *metadata_values)
            if existing:
                if tuple(existing) != requested:
                    raise StorageConflictError("M4 proposal differs for this run")
                return
            connection.execute(
                """INSERT INTO m4_model_proposals(
                    run_id, attempt, proposal_hash, content_json, created_at,
                    server_kind, server_base_url, model_id, response_id,
                    prompt_tokens, completion_tokens, elapsed_ms, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(run_id),
                    attempt,
                    proposal_hash,
                    proposal.model_dump_json(),
                    datetime.now(UTC).isoformat(),
                    *metadata_values,
                ),
            )
            connection.commit()

    def get_m4_proposal(self, run_id: UUID, attempt: int) -> tuple[M4MapProposal, str]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT proposal_hash, content_json FROM m4_model_proposals
                WHERE run_id=? AND attempt=?""",
                (str(run_id), attempt),
            ).fetchone()
        if row is None:
            raise AssetNotFoundError(f"M4 proposal for {run_id}")
        return M4MapProposal.model_validate_json(row["content_json"]), row["proposal_hash"]

    def get_m4_proposal_metadata(self, run_id: UUID, attempt: int) -> ModelMetadata:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT server_kind, server_base_url, model_id, response_id,
                prompt_tokens, completion_tokens, elapsed_ms, received_at
                FROM m4_model_proposals WHERE run_id=? AND attempt=?""",
                (str(run_id), attempt),
            ).fetchone()
        if row is None:
            raise AssetNotFoundError(f"M4 proposal metadata for {run_id}")
        return ModelMetadata.model_validate(dict(row))

    def save_m4_policy_decision(
        self,
        *,
        run_id: UUID,
        proposal_attempt: int,
        decision: PolicyDecision,
    ) -> None:
        """Persist a sanitized Runtime decision separately from graph cursor state."""

        requested = (
            str(run_id),
            proposal_attempt,
            str(decision.proposal_id),
            decision.model_dump_json(),
            decision.decided_at.isoformat(),
        )
        with closing(self._connect()) as connection:
            existing = connection.execute(
                """SELECT run_id, proposal_attempt, proposal_id, content_json, created_at
                FROM m4_policy_decisions WHERE decision_id=?""",
                (str(decision.decision_id),),
            ).fetchone()
            if existing:
                if tuple(existing) != requested:
                    raise StorageConflictError("M4 policy decision identity differs")
                return
            connection.execute(
                """INSERT INTO m4_policy_decisions(
                    decision_id, run_id, proposal_attempt, proposal_id, content_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (str(decision.decision_id), *requested),
            )
            connection.commit()

    def get_m4_policy_decision(
        self,
        *,
        run_id: UUID,
        proposal_attempt: int,
        proposal_id: UUID,
    ) -> PolicyDecision | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT content_json FROM m4_policy_decisions
                WHERE run_id=? AND proposal_attempt=? AND proposal_id=?""",
                (str(run_id), proposal_attempt, str(proposal_id)),
            ).fetchone()
        return PolicyDecision.model_validate_json(row["content_json"]) if row else None

    def list_m4_policy_decisions(self, run_id: UUID) -> list[PolicyDecision]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT content_json FROM m4_policy_decisions
                WHERE run_id=? ORDER BY proposal_attempt, created_at, rowid""",
                (str(run_id),),
            ).fetchall()
        return [PolicyDecision.model_validate_json(row["content_json"]) for row in rows]

    def get_m4_run_commit(
        self, run_id: UUID
    ) -> tuple[InsightBoundaryMapV1, ExperienceAssetV1] | None:
        """Load the immutable artifact and canonical projection committed by this run."""
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT a.content_json AS artifact_json, v.content_json AS snapshot_json
                FROM m4_run_commits c
                JOIN m4_artifacts a ON a.artifact_id=c.artifact_id
                JOIN asset_versions v ON v.version_id=c.canonical_version_id
                WHERE c.run_id=?""",
                (str(run_id),),
            ).fetchone()
        if row is None:
            return None
        return (
            InsightBoundaryMapV1.model_validate_json(row["artifact_json"]),
            ExperienceAssetV1.model_validate_json(row["snapshot_json"]),
        )

    def configure_m4_run(
        self,
        run_id: UUID,
        *,
        regenerate: bool,
        expected_invalidated_artifact_id: UUID | None,
        base_m3_artifact_id: UUID,
        context_bound: dict[str, object],
    ) -> None:
        with closing(self._connect()) as connection:
            updated = connection.execute(
                """UPDATE workflow_run_contexts
                SET m4_regenerate=?, expected_invalidated_m4_artifact_id=?,
                base_m3_artifact_id=?, m4_context_bound_json=? WHERE run_id=?""",
                (
                    int(regenerate),
                    str(expected_invalidated_artifact_id)
                    if expected_invalidated_artifact_id
                    else None,
                    str(base_m3_artifact_id),
                    json.dumps(context_bound, sort_keys=True),
                    str(run_id),
                ),
            )
            if updated.rowcount != 1:
                raise AssetNotFoundError(f"workflow run: {run_id}")
            connection.commit()

    def update_m4_run_outcome(
        self, run_id: UUID, *, repairs: int, replans: int, finding_codes: list[str]
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """UPDATE runs SET structured_repair_count=?, replan_count=?, finding_codes_json=?
                WHERE run_id=?""",
                (repairs, replans, json.dumps(finding_codes), str(run_id)),
            )
            connection.commit()

    def get_latest_m4_run(
        self, asset_id: UUID, *, failed_only: bool = False
    ) -> dict[str, object] | None:
        where = (
            "AND terminal_state IS NOT NULL AND terminal_state != 'SUCCEEDED'"
            if failed_only
            else ""
        )
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"""SELECT r.run_id, r.terminal_state, r.retryable,
                r.safe_user_message, r.recovery_action, r.model_call_count,
                r.structured_repair_count, r.replan_count, r.finding_codes_json,
                r.started_at, r.finished_at, c.base_m3_artifact_id, c.m4_regenerate,
                c.expected_invalidated_m4_artifact_id, c.m4_context_bound_json
                FROM runs r
                JOIN workflow_run_contexts c ON c.run_id=r.run_id
                WHERE r.asset_id=? AND r.workflow_version=? {where}
                ORDER BY r.started_at DESC, r.rowid DESC LIMIT 1""",
                (str(asset_id), "experience-asset/e5-m4/v1"),
            ).fetchone()
        return dict(row) if row else None

    def get_m4_run_outcome(self, run_id: UUID) -> dict[str, object] | None:
        """Return terminal and bounded M4 counters/findings from exactly one run."""
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT r.run_id, r.asset_id, r.terminal_state, r.retryable,
                r.safe_user_message, r.recovery_action, r.model_call_count,
                r.structured_repair_count, r.replan_count, r.finding_codes_json,
                r.started_at, r.finished_at, c.m4_context_bound_json
                FROM runs r JOIN workflow_run_contexts c ON c.run_id=r.run_id
                WHERE r.run_id=? AND r.workflow_version=?""",
                (str(run_id), "experience-asset/e5-m4/v1"),
            ).fetchone()
        return dict(row) if row else None

    def save_m2_semantic_role_proposal(
        self,
        *,
        run_id: UUID,
        proposal: M2SemanticRoleProposal,
        proposal_hash: str,
        model_id: str,
        server_base_url: str,
        created_at: datetime,
    ) -> None:
        """Persist validated local-model output outside LangGraph checkpoints."""

        payload = proposal.model_dump_json()
        requested = (
            proposal_hash,
            payload,
            model_id,
            server_base_url,
        )
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT proposal_hash, content_json, model_id, server_base_url
                    FROM m2_semantic_role_proposals WHERE run_id = ?
                    """,
                    (str(run_id),),
                ).fetchone()
                if row is not None:
                    existing = (
                        row["proposal_hash"],
                        row["content_json"],
                        row["model_id"],
                        row["server_base_url"],
                    )
                    if existing != requested:
                        raise StorageConflictError(
                            "M2 semantic proposal already differs for this run"
                        )
                    connection.rollback()
                    return
                connection.execute(
                    """
                    INSERT INTO m2_semantic_role_proposals(
                        run_id, proposal_hash, content_json, model_id,
                        server_base_url, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(run_id),
                        proposal_hash,
                        payload,
                        model_id,
                        server_base_url,
                        created_at.isoformat(),
                    ),
                )
                connection.commit()
        except StorageConflictError:
            raise
        except sqlite3.IntegrityError as exc:
            raise StorageConflictError("M2 semantic proposal run does not exist") from exc
        except sqlite3.Error as exc:
            raise PersistenceError("failed to save M2 semantic proposal") from exc

    def get_m2_semantic_role_proposal(
        self,
        run_id: UUID,
    ) -> tuple[M2SemanticRoleProposal, str]:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT proposal_hash, content_json
                    FROM m2_semantic_role_proposals WHERE run_id = ?
                    """,
                    (str(run_id),),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError("failed to load M2 semantic proposal") from exc
        if row is None:
            raise AssetNotFoundError(f"M2 semantic proposal for run: {run_id}")
        return (
            M2SemanticRoleProposal.model_validate_json(row["content_json"]),
            str(row["proposal_hash"]),
        )

    def start_run(
        self,
        *,
        run_id: UUID,
        asset_id: UUID | None,
        command: str,
        model_id: str | None,
        model_config_hash: str | None,
        code_commit: str | None,
        started_at: datetime,
    ) -> None:
        try:
            with closing(self._connect()) as connection:
                connection.execute(
                    """
                    INSERT INTO runs(
                        run_id, asset_id, command, model_id, model_config_hash,
                        code_commit, started_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(run_id),
                        str(asset_id) if asset_id else None,
                        command,
                        model_id,
                        model_config_hash,
                        code_commit,
                        started_at.isoformat(),
                    ),
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise PersistenceError("failed to start run") from exc

    def start_workflow_run(
        self,
        *,
        run_id: UUID,
        asset_id: UUID,
        base_version_id: UUID,
        command_id: UUID,
        command: str,
        user_goal: str,
        allow_current_source_search: bool,
        workflow_version: str,
        topology_hash: str,
        model_id: str,
        model_config_hash: str,
        server_base_url: str,
        code_commit: str | None,
        started_at: datetime,
        base_m2_artifact_id: UUID | None = None,
    ) -> None:
        """Create one private local run context before graph checkpointing starts."""

        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO runs(
                        run_id, asset_id, command, model_id, model_config_hash,
                        code_commit, started_at, workflow_version, topology_hash,
                        base_version_id, command_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(run_id),
                        str(asset_id),
                        command,
                        model_id,
                        model_config_hash,
                        code_commit,
                        started_at.isoformat(),
                        workflow_version,
                        topology_hash,
                        str(base_version_id),
                        str(command_id),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO workflow_run_contexts(
                        run_id, user_goal, allow_current_source_search,
                        server_base_url, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        str(run_id),
                        user_goal,
                        int(allow_current_source_search),
                        server_base_url,
                        started_at.isoformat(),
                    ),
                )
                if base_m2_artifact_id is not None:
                    connection.execute(
                        "UPDATE workflow_run_contexts SET base_m2_artifact_id=? WHERE run_id=?",
                        (str(base_m2_artifact_id), str(run_id)),
                    )
                connection.commit()
        except sqlite3.IntegrityError as exc:
            raise StorageConflictError("workflow run already exists") from exc
        except sqlite3.Error as exc:
            raise PersistenceError("failed to start workflow run") from exc

    def get_workflow_run_context(self, run_id: UUID) -> dict[str, object]:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT r.run_id, r.asset_id, r.base_version_id, r.command_id, r.command,
                           r.workflow_version, r.topology_hash, r.model_id,
                           r.model_config_hash, r.code_commit, r.started_at,
                           c.user_goal, c.allow_current_source_search,
                           c.server_base_url, c.base_m2_artifact_id, c.m3_regenerate,
                           c.expected_invalidated_m3_artifact_id,
                           c.base_m3_artifact_id, c.m4_regenerate,
                           c.expected_invalidated_m4_artifact_id, c.m4_context_bound_json
                    FROM runs r
                    JOIN workflow_run_contexts c ON c.run_id = r.run_id
                    WHERE r.run_id = ?
                    """,
                    (str(run_id),),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError("failed to load workflow run context") from exc
        if row is None:
            raise AssetNotFoundError(f"workflow run: {run_id}")
        return {
            "run_id": row["run_id"],
            "asset_id": row["asset_id"],
            "base_version_id": row["base_version_id"],
            "command_id": row["command_id"],
            "command": row["command"],
            "workflow_version": row["workflow_version"],
            "topology_hash": row["topology_hash"],
            "model_id": row["model_id"],
            "model_config_hash": row["model_config_hash"],
            "server_base_url": row["server_base_url"],
            "code_commit": row["code_commit"],
            "started_at": row["started_at"],
            "user_goal": row["user_goal"],
            "allow_current_source_search": bool(row["allow_current_source_search"]),
            "base_m2_artifact_id": row["base_m2_artifact_id"],
            "m3_regenerate": bool(row["m3_regenerate"]),
            "expected_invalidated_m3_artifact_id": row["expected_invalidated_m3_artifact_id"],
            "base_m3_artifact_id": row["base_m3_artifact_id"],
            "m4_regenerate": bool(row["m4_regenerate"]),
            "expected_invalidated_m4_artifact_id": row["expected_invalidated_m4_artifact_id"],
            "m4_context_bound_json": row["m4_context_bound_json"],
        }

    def list_incomplete_workflow_run_ids(
        self,
        workflow_version: str | None = None,
    ) -> list[UUID]:
        try:
            with closing(self._connect()) as connection:
                if workflow_version is None:
                    rows = connection.execute(
                        """
                        SELECT run_id FROM runs
                        WHERE workflow_version IS NOT NULL
                          AND terminal_state IS NULL
                        ORDER BY started_at, run_id
                        """
                    ).fetchall()
                else:
                    rows = connection.execute(
                        """
                        SELECT run_id FROM runs
                        WHERE workflow_version = ? AND terminal_state IS NULL
                        ORDER BY started_at, run_id
                        """,
                        (workflow_version,),
                    ).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError("failed to list incomplete workflow runs") from exc
        return [UUID(row["run_id"]) for row in rows]

    def finish_run(self, result: TerminalResultV1) -> None:
        try:
            with closing(self._connect()) as connection:
                updated = connection.execute(
                    """
                    UPDATE runs
                    SET finished_at = ?, terminal_state = ?, last_durable_version_id = ?,
                        retryable = ?, safe_user_message = ?, internal_error_class = ?,
                        elapsed_ms = ?, model_call_count = ?, recovery_action = ?
                    WHERE run_id = ? AND terminal_state IS NULL
                    """,
                    (
                        result.finished_at.isoformat(),
                        result.state.value,
                        (
                            str(result.last_durable_version_id)
                            if result.last_durable_version_id
                            else None
                        ),
                        int(result.retryable),
                        result.safe_user_message,
                        result.internal_error_class,
                        result.elapsed_ms,
                        result.model_call_count,
                        result.recovery_action,
                        str(result.run_id),
                    ),
                )
                if updated.rowcount != 1:
                    raise StorageConflictError("run is missing or already terminal")
                connection.commit()
        except StorageConflictError:
            raise
        except sqlite3.Error as exc:
            raise PersistenceError("failed to finish run") from exc

    def finish_run_idempotent(self, result: TerminalResultV1) -> None:
        """Write one terminal result, accepting an exact semantic replay."""

        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT terminal_state, last_durable_version_id, retryable,
                           safe_user_message, internal_error_class,
                           model_call_count, recovery_action
                    FROM runs WHERE run_id = ?
                    """,
                    (str(result.run_id),),
                ).fetchone()
                if row is None:
                    raise AssetNotFoundError(f"run: {result.run_id}")
                if row["terminal_state"] is not None:
                    existing = (
                        row["terminal_state"],
                        row["last_durable_version_id"],
                        bool(row["retryable"]),
                        row["safe_user_message"],
                        row["internal_error_class"],
                        row["model_call_count"],
                        row["recovery_action"],
                    )
                    requested = (
                        result.state.value,
                        (
                            str(result.last_durable_version_id)
                            if result.last_durable_version_id
                            else None
                        ),
                        result.retryable,
                        result.safe_user_message,
                        result.internal_error_class,
                        result.model_call_count,
                        result.recovery_action,
                    )
                    if existing != requested:
                        raise StorageConflictError("run already has a different terminal result")
                    connection.rollback()
                    return
                connection.execute(
                    """
                    UPDATE runs
                    SET finished_at = ?, terminal_state = ?,
                        last_durable_version_id = ?, retryable = ?,
                        safe_user_message = ?, internal_error_class = ?,
                        elapsed_ms = ?, model_call_count = ?, recovery_action = ?
                    WHERE run_id = ? AND terminal_state IS NULL
                    """,
                    (
                        result.finished_at.isoformat(),
                        result.state.value,
                        (
                            str(result.last_durable_version_id)
                            if result.last_durable_version_id
                            else None
                        ),
                        int(result.retryable),
                        result.safe_user_message,
                        result.internal_error_class,
                        result.elapsed_ms,
                        result.model_call_count,
                        result.recovery_action,
                        str(result.run_id),
                    ),
                )
                connection.commit()
        except (AssetNotFoundError, StorageConflictError):
            raise
        except sqlite3.Error as exc:
            raise PersistenceError("failed to finish run idempotently") from exc

    def claim_workflow_effect(
        self,
        *,
        effect_key: str,
        run_id: UUID,
        node_name: str,
        node_attempt: int,
        started_at: datetime,
    ) -> tuple[str, dict[str, object] | None]:
        """Reserve one effect or return its cached update without replaying it."""

        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT status, result_json FROM workflow_effects
                    WHERE effect_key = ?
                    """,
                    (effect_key,),
                ).fetchone()
                if row is not None:
                    connection.rollback()
                    if row["status"] == "COMPLETED":
                        result = json.loads(row["result_json"])
                        if not isinstance(result, dict):
                            raise PersistenceError("workflow effect result is not an object")
                        return "COMPLETED", result
                    raise WorkflowEffectInProgressError(
                        f"workflow effect completion is unknown: {effect_key}"
                    )
                connection.execute(
                    """
                    INSERT INTO workflow_effects(
                        effect_key, run_id, node_name, node_attempt, status,
                        started_at
                    ) VALUES (?, ?, ?, ?, 'STARTED', ?)
                    """,
                    (
                        effect_key,
                        str(run_id),
                        node_name,
                        node_attempt,
                        started_at.isoformat(),
                    ),
                )
                connection.commit()
                return "CLAIMED", None
        except WorkflowEffectInProgressError:
            raise
        except sqlite3.IntegrityError as exc:
            raise StorageConflictError("workflow effect key conflict") from exc
        except sqlite3.Error as exc:
            raise PersistenceError("failed to claim workflow effect") from exc

    def complete_workflow_effect(
        self,
        *,
        effect_key: str,
        result: dict[str, object],
        finished_at: datetime,
    ) -> None:
        payload = json.dumps(result, sort_keys=True, separators=(",", ":"))
        try:
            with closing(self._connect()) as connection:
                updated = connection.execute(
                    """
                    UPDATE workflow_effects
                    SET status = 'COMPLETED', result_json = ?, finished_at = ?
                    WHERE effect_key = ? AND status = 'STARTED'
                    """,
                    (payload, finished_at.isoformat(), effect_key),
                )
                if updated.rowcount != 1:
                    row = connection.execute(
                        """
                        SELECT status, result_json FROM workflow_effects
                        WHERE effect_key = ?
                        """,
                        (effect_key,),
                    ).fetchone()
                    if row is None or row["status"] != "COMPLETED" or row["result_json"] != payload:
                        raise StorageConflictError(
                            "workflow effect cannot be completed consistently"
                        )
                connection.commit()
        except StorageConflictError:
            raise
        except sqlite3.Error as exc:
            raise PersistenceError("failed to complete workflow effect") from exc

    def count_workflow_effects(self, run_id: UUID, node_name: str) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM workflow_effects WHERE run_id=? AND node_name=?",
                (str(run_id), node_name),
            ).fetchone()
        return int(row["count"])

    def record_workflow_trace(
        self,
        *,
        run_id: UUID,
        workflow_version: str,
        topology_hash: str,
        node_name: str,
        node_attempt: int,
        selected_edge: str | None,
        input_refs: list[str],
        output_refs: list[str],
        policy_outcome: str | None,
        tool_execution_status: str | None,
        verification_outcome: str | None,
        terminal_state: str | None,
        finding_codes: list[str],
        started_at: datetime,
        finished_at: datetime,
    ) -> UUID:
        trace_id = UUID(
            hashlib.sha256(f"{run_id}:{node_name}:{node_attempt}".encode()).hexdigest()[:32]
        )
        try:
            with closing(self._connect()) as connection:
                connection.execute(
                    """
                    INSERT INTO workflow_traces(
                        trace_id, run_id, workflow_version, topology_hash,
                        node_name, node_attempt, selected_edge, input_refs_json,
                        output_refs_json, policy_outcome, tool_execution_status,
                        verification_outcome, terminal_state, finding_codes_json,
                        started_at, finished_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, node_name, node_attempt) DO UPDATE SET
                        selected_edge = excluded.selected_edge,
                        output_refs_json = excluded.output_refs_json,
                        policy_outcome = excluded.policy_outcome,
                        tool_execution_status = excluded.tool_execution_status,
                        verification_outcome = excluded.verification_outcome,
                        terminal_state = excluded.terminal_state,
                        finding_codes_json = excluded.finding_codes_json,
                        finished_at = excluded.finished_at
                    """,
                    (
                        str(trace_id),
                        str(run_id),
                        workflow_version,
                        topology_hash,
                        node_name,
                        node_attempt,
                        selected_edge,
                        json.dumps(input_refs, sort_keys=True),
                        json.dumps(output_refs, sort_keys=True),
                        policy_outcome,
                        tool_execution_status,
                        verification_outcome,
                        terminal_state,
                        json.dumps(finding_codes, sort_keys=True),
                        started_at.isoformat(),
                        finished_at.isoformat(),
                    ),
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise PersistenceError("failed to record workflow trace") from exc
        return trace_id

    def bind_workflow_trace_checkpoint(
        self,
        *,
        run_id: UUID,
        node_name: str,
        checkpoint_id: str,
    ) -> None:
        try:
            with closing(self._connect()) as connection:
                connection.execute(
                    """
                    UPDATE workflow_traces SET checkpoint_id = ?
                    WHERE run_id = ? AND node_name = ? AND checkpoint_id IS NULL
                    """,
                    (checkpoint_id, str(run_id), node_name),
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise PersistenceError("failed to bind workflow trace checkpoint") from exc

    def list_workflow_traces(self, run_id: UUID) -> list[dict[str, object]]:
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    """
                    SELECT workflow_version, topology_hash, node_name,
                           node_attempt, selected_edge, input_refs_json,
                           output_refs_json, policy_outcome,
                           tool_execution_status, verification_outcome,
                           checkpoint_id, terminal_state, finding_codes_json,
                           started_at, finished_at
                    FROM workflow_traces
                    WHERE run_id = ?
                    ORDER BY started_at, rowid
                    """,
                    (str(run_id),),
                ).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError("failed to list workflow traces") from exc
        return [
            {
                "workflow_version": row["workflow_version"],
                "topology_hash": row["topology_hash"],
                "node_name": row["node_name"],
                "node_attempt": row["node_attempt"],
                "selected_edge": row["selected_edge"],
                "input_refs": json.loads(row["input_refs_json"]),
                "output_refs": json.loads(row["output_refs_json"]),
                "policy_outcome": row["policy_outcome"],
                "tool_execution_status": row["tool_execution_status"],
                "verification_outcome": row["verification_outcome"],
                "checkpoint_id": row["checkpoint_id"],
                "terminal_state": row["terminal_state"],
                "finding_codes": json.loads(row["finding_codes_json"]),
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
            }
            for row in rows
        ]

    def get_terminal_result(self, run_id: UUID) -> TerminalResultV1 | None:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT run_id, terminal_state, last_durable_version_id,
                           retryable, safe_user_message, internal_error_class,
                           elapsed_ms, model_call_count, recovery_action, finished_at
                    FROM runs
                    WHERE run_id = ?
                    """,
                    (str(run_id),),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError("failed to load terminal run result") from exc
        if row is None:
            raise AssetNotFoundError(f"run: {run_id}")
        if row["terminal_state"] is None:
            return None
        return TerminalResultV1(
            run_id=row["run_id"],
            state=row["terminal_state"],
            last_durable_version_id=row["last_durable_version_id"],
            retryable=bool(row["retryable"]),
            safe_user_message=row["safe_user_message"],
            internal_error_class=row["internal_error_class"],
            elapsed_ms=row["elapsed_ms"],
            model_call_count=row["model_call_count"],
            recovery_action=row["recovery_action"],
            finished_at=row["finished_at"],
        )

    def save_run_checkpoint(
        self,
        state: AgentRunStateV1,
        *,
        sequence: int,
        phase: str,
    ) -> UUID:
        checkpoint_id = UUID(
            hashlib.sha256(f"{state.run_id}:{sequence}:{phase}".encode()).hexdigest()[:32]
        )
        payload = state.model_dump_json()
        state_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        try:
            with closing(self._connect()) as connection:
                connection.execute(
                    """
                    INSERT INTO run_checkpoints(
                        checkpoint_id, run_id, sequence, phase, state_json,
                        state_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(checkpoint_id),
                        str(state.run_id),
                        sequence,
                        phase,
                        payload,
                        state_hash,
                        state.updated_at.isoformat(),
                    ),
                )
                connection.commit()
        except sqlite3.IntegrityError as exc:
            raise StorageConflictError("run checkpoint sequence already exists") from exc
        except sqlite3.Error as exc:
            raise PersistenceError("failed to save run checkpoint") from exc
        return checkpoint_id

    def get_latest_run_checkpoint(self, run_id: UUID) -> AgentRunStateV1:
        return self.get_latest_run_checkpoint_record(run_id)[1]

    def get_latest_run_checkpoint_record(
        self,
        run_id: UUID,
    ) -> tuple[int, AgentRunStateV1]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT sequence, state_json FROM run_checkpoints
                WHERE run_id = ? ORDER BY sequence DESC LIMIT 1
                """,
                (str(run_id),),
            ).fetchone()
        if row is None:
            raise AssetNotFoundError(f"run checkpoint: {run_id}")
        return int(row["sequence"]), AgentRunStateV1.model_validate_json(row["state_json"])

    def get_latest_asset_run_checkpoint(
        self,
        asset_id: UUID,
    ) -> AgentRunStateV1 | None:
        """Return the newest checkpointed Agent run, excluding non-Agent audit rows."""

        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT rc.state_json
                FROM runs r
                JOIN run_checkpoints rc ON rc.run_id = r.run_id
                WHERE r.asset_id = ?
                ORDER BY r.started_at DESC, rc.sequence DESC
                LIMIT 1
                """,
                (str(asset_id),),
            ).fetchone()
        if row is None:
            return None
        return AgentRunStateV1.model_validate_json(row["state_json"])

    def list_run_checkpoint_phases(self, run_id: UUID) -> list[str]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT phase FROM run_checkpoints
                WHERE run_id = ? ORDER BY sequence
                """,
                (str(run_id),),
            ).fetchall()
        return [row["phase"] for row in rows]
