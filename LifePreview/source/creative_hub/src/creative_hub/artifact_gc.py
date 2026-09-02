"""Lineage-aware mark/sweep for committed artifact objects."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from shared_contracts import RetentionClass

from .artifact_publication import (
    ArtifactMetrics,
    ArtifactPublicationError,
    ArtifactRecord,
    ArtifactStatus,
    ContentAddressedArtifactStore,
    PostgresArtifactRepository,
)
from .db.models import (
    ArtifactLineageEdgeRecord,
    ArtifactProtectionRootRecord,
    ArtifactProtectionVersionRecord,
    ArtifactRecordRow,
)
from .lineage import ArtifactLineageGraph


PROTECTION_KINDS = frozenset(
    {
        "selected",
        "canonical",
        "open_review_evidence",
        "open_qc_evidence",
        "replay_manifest",
    }
)


@dataclass(frozen=True, slots=True)
class ProtectionSnapshot:
    project_id: UUID
    version: int
    roots: frozenset[UUID]


class ArtifactProtectionRegistry:
    """Versioned GC roots with an atomic pre-tombstone guard."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._roots: dict[tuple[UUID, str], frozenset[UUID]] = {}
        self._versions: dict[UUID, int] = {}

    def replace(
        self,
        *,
        project_id: UUID,
        kind: str,
        artifact_ids: Iterable[UUID],
    ) -> int:
        if kind not in PROTECTION_KINDS:
            raise ValueError("unknown artifact protection kind")
        with self._lock:
            self._roots[(project_id, kind)] = frozenset(artifact_ids)
            version = self._versions.get(project_id, 0) + 1
            self._versions[project_id] = version
            return version

    def snapshot(self, *, project_id: UUID) -> ProtectionSnapshot:
        with self._lock:
            roots: set[UUID] = set()
            for (scope, _kind), artifact_ids in self._roots.items():
                if scope == project_id:
                    roots.update(artifact_ids)
            return ProtectionSnapshot(
                project_id=project_id,
                version=self._versions.get(project_id, 0),
                roots=frozenset(roots),
            )

    def run_if_current_and_unprotected(
        self,
        *,
        project_id: UUID,
        expected_version: int,
        artifact_id: UUID,
        action: Callable[[], ArtifactRecord | None],
    ) -> ArtifactRecord | None:
        """Run ``action`` while protection updates are excluded."""

        with self._lock:
            if self._versions.get(project_id, 0) != expected_version:
                return None
            if any(
                artifact_id in artifact_ids
                for (scope, _kind), artifact_ids in self._roots.items()
                if scope == project_id
            ):
                return None
            return action()


class PostgresArtifactProtectionRegistry:
    """Durable GC roots with atomic protection/lineage/tombstone fencing."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _lock_project(session: Session, project_id: UUID) -> None:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended(:project_id, 0))"
                ),
                {"project_id": str(project_id)},
            )

    @staticmethod
    def _version_row(
        session: Session,
        project_id: UUID,
    ) -> ArtifactProtectionVersionRecord:
        row = session.get(
            ArtifactProtectionVersionRecord,
            project_id,
            with_for_update=True,
        )
        if row is None:
            row = ArtifactProtectionVersionRecord(
                project_id=project_id,
                version=0,
            )
            session.add(row)
            session.flush()
        return row

    def replace(
        self,
        *,
        project_id: UUID,
        kind: str,
        artifact_ids: Iterable[UUID],
    ) -> int:
        if kind not in PROTECTION_KINDS:
            raise ValueError("unknown artifact protection kind")
        roots = frozenset(artifact_ids)
        with self._session_factory() as session, session.begin():
            self._lock_project(session, project_id)
            version = self._version_row(session, project_id)
            if roots:
                observed = set(
                    session.scalars(
                        select(ArtifactRecordRow.id).where(
                            ArtifactRecordRow.project_id == project_id,
                            ArtifactRecordRow.id.in_(roots),
                            ArtifactRecordRow.status == "COMMITTED",
                        )
                    )
                )
                if observed != roots:
                    raise ValueError(
                        "artifact protection roots must be committed "
                        "artifacts in the project"
                    )
            session.execute(
                delete(ArtifactProtectionRootRecord).where(
                    ArtifactProtectionRootRecord.project_id == project_id,
                    ArtifactProtectionRootRecord.kind == kind,
                )
            )
            session.add_all(
                ArtifactProtectionRootRecord(
                    id=uuid4(),
                    project_id=project_id,
                    kind=kind,
                    artifact_id=artifact_id,
                )
                for artifact_id in sorted(roots, key=str)
            )
            version.version += 1
            session.flush()
            return version.version

    def snapshot(self, *, project_id: UUID) -> ProtectionSnapshot:
        with self._session_factory() as session, session.begin():
            self._lock_project(session, project_id)
            version = self._version_row(session, project_id)
            roots = frozenset(
                session.scalars(
                    select(ArtifactProtectionRootRecord.artifact_id).where(
                        ArtifactProtectionRootRecord.project_id == project_id
                    )
                )
            )
            return ProtectionSnapshot(
                project_id=project_id,
                version=version.version,
                roots=roots,
            )

    def tombstone_if_current_and_unprotected(
        self,
        *,
        repository: ArtifactGCRepository,
        project_id: UUID,
        expected_version: int,
        expected_lineage_version: int,
        artifact_id: UUID,
        expected_artifact_version: int,
        now: datetime,
    ) -> ArtifactRecord | None:
        """Perform all GC race checks and the catalog CAS in one transaction."""

        if not isinstance(repository, PostgresArtifactRepository):
            raise TypeError(
                "durable protections require PostgresArtifactRepository"
            )
        with self._session_factory() as session, session.begin():
            self._lock_project(session, project_id)
            version = self._version_row(session, project_id)
            if version.version != expected_version:
                return None
            lineage_version = int(
                session.scalar(
                    select(func.count())
                    .select_from(ArtifactLineageEdgeRecord)
                    .where(
                        ArtifactLineageEdgeRecord.project_id == project_id
                    )
                )
                or 0
            )
            if lineage_version != expected_lineage_version:
                return None
            protected = session.scalar(
                select(ArtifactProtectionRootRecord.id).where(
                    ArtifactProtectionRootRecord.project_id == project_id,
                    ArtifactProtectionRootRecord.artifact_id == artifact_id,
                )
            )
            if protected is not None:
                return None
            return repository._tombstone_in_session(
                session,
                project_id=project_id,
                artifact_id=artifact_id,
                expected_version=expected_artifact_version,
                now=now,
            )


class ArtifactGCRepository(Protocol):
    def list_committed(
        self,
        *,
        project_id: UUID,
    ) -> tuple[ArtifactRecord, ...]: ...

    def list_tombstoned(
        self,
        *,
        project_id: UUID | None = None,
    ) -> tuple[ArtifactRecord, ...]: ...

    def tombstone(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> ArtifactRecord | None: ...

    def committed_digest_references(self, *, content_digest: str) -> int: ...


@dataclass(frozen=True, slots=True)
class SweepCandidate:
    artifact_id: UUID
    state_version: int
    content_digest: str


@dataclass(frozen=True, slots=True)
class SweepPlan:
    project_id: UUID
    protection_version: int
    lineage_version: int
    candidates: tuple[SweepCandidate, ...]
    marked_at: datetime


@dataclass(frozen=True, slots=True)
class SweepResult:
    tombstoned: tuple[UUID, ...]
    deleted_digests: tuple[str, ...]
    retained: tuple[UUID, ...]
    failed: tuple[UUID, ...]


class ArtifactGarbageCollector:
    def __init__(
        self,
        *,
        repository: ArtifactGCRepository,
        lineage: ArtifactLineageGraph,
        protections: ArtifactProtectionRegistry,
        store: ContentAddressedArtifactStore,
        clock: Callable[[], datetime] | None = None,
        metrics: ArtifactMetrics | None = None,
    ) -> None:
        self.repository = repository
        self.lineage = lineage
        self.protections = protections
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))
        self.metrics = metrics

    def mark(self, *, project_id: UUID) -> SweepPlan:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("GC clock must be timezone-aware")
        protection = self.protections.snapshot(project_id=project_id)
        lineage_version = self.lineage.version(project_id=project_id)
        records = self.repository.list_committed(project_id=project_id)

        roots = set(protection.roots)
        roots.update(
            record.artifact_id
            for record in records
            if self._retained_by_policy(record, now)
        )
        marked = self.lineage.ancestors(
            project_id=project_id,
            artifact_ids=roots,
        )
        candidates = tuple(
            SweepCandidate(
                artifact_id=record.artifact_id,
                state_version=record.state_version,
                content_digest=record.content_digest,
            )
            for record in records
            if record.artifact_id not in marked
            and not self._retained_by_policy(record, now)
        )
        return SweepPlan(
            project_id=project_id,
            protection_version=protection.version,
            lineage_version=lineage_version,
            candidates=candidates,
            marked_at=now,
        )

    def sweep(self, plan: SweepPlan) -> SweepResult:
        tombstoned: list[UUID] = []
        deleted: list[str] = []
        retained: list[UUID] = []
        failed: list[UUID] = []
        for candidate in plan.candidates:
            # New lineage can make a formerly unreachable artifact reachable.
            # Conservatively retain and require a fresh mark.
            if (
                self.lineage.version(project_id=plan.project_id)
                != plan.lineage_version
            ):
                retained.append(candidate.artifact_id)
                self._metric("retained")
                continue

            durable_guard = getattr(
                self.protections,
                "tombstone_if_current_and_unprotected",
                None,
            )
            if callable(durable_guard):
                record = durable_guard(
                    repository=self.repository,
                    project_id=plan.project_id,
                    expected_version=plan.protection_version,
                    expected_lineage_version=plan.lineage_version,
                    artifact_id=candidate.artifact_id,
                    expected_artifact_version=candidate.state_version,
                    now=self.clock(),
                )
            else:
                record = self.protections.run_if_current_and_unprotected(
                    project_id=plan.project_id,
                    expected_version=plan.protection_version,
                    artifact_id=candidate.artifact_id,
                    action=lambda candidate=candidate: self.repository.tombstone(
                        project_id=plan.project_id,
                        artifact_id=candidate.artifact_id,
                        expected_version=candidate.state_version,
                        now=self.clock(),
                    ),
                )
            if record is None:
                retained.append(candidate.artifact_id)
                self._metric("retained")
                continue
            tombstoned.append(record.artifact_id)
            if self.repository.committed_digest_references(
                content_digest=record.content_digest
            ):
                # Physical bytes are shared but catalog authorization is not.
                retained.append(record.artifact_id)
                self._metric("retained")
                continue
            try:
                self.store.delete_object(record)
            except (OSError, ArtifactPublicationError):
                failed.append(record.artifact_id)
                self._metric("failed")
            else:
                deleted.append(record.content_digest)
                self._metric("deleted")
        return SweepResult(
            tombstoned=tuple(tombstoned),
            deleted_digests=tuple(deleted),
            retained=tuple(retained),
            failed=tuple(failed),
        )

    def purge_tombstoned(
        self,
        *,
        project_id: UUID | None = None,
    ) -> tuple[str, ...]:
        """Retry physical deletion after a previous crash/failure."""

        deleted: list[str] = []
        for record in self.repository.list_tombstoned(project_id=project_id):
            if self.repository.committed_digest_references(
                content_digest=record.content_digest
            ):
                continue
            try:
                self.store.delete_object(record)
            except (OSError, ArtifactPublicationError):
                self._metric("failed")
            else:
                deleted.append(record.content_digest)
                self._metric("deleted")
        return tuple(deleted)

    @staticmethod
    def _retained_by_policy(record: ArtifactRecord, now: datetime) -> bool:
        if record.retention_class is RetentionClass.CANON:
            return True
        if record.retain_until is None:
            # Missing expiry is fail-closed. A retention repair must make the
            # deletion decision explicit.
            return True
        return record.retain_until > now

    def _metric(self, outcome: str) -> None:
        if self.metrics is not None:
            self.metrics.record_artifact_orphan(
                action="sweep",
                outcome=outcome,
            )
