"""Attempt-aware, crash-recoverable artifact publication.

The public contract in this module intentionally separates bytes from
visibility:

1. a fenced operation attempt receives an opaque staging token;
2. bytes are streamed to staging and verified;
3. a PENDING catalog row is registered;
4. bytes are atomically promoted to a content-addressed object; and
5. the row becomes COMMITTED.

Only COMMITTED records are returned by the visibility methods.  A caller may
repeat ``finalize`` after losing a response at any boundary; it either resumes
the pending publication or returns the already committed record.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import BinaryIO, Protocol
from uuid import UUID, uuid4

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from shared_contracts import PersistentArtifactRef, RetentionClass

from .db.models import (
    ArtifactPublicationClaimRecord,
    ArtifactRecordRow,
    OperationAttemptRecord,
)


CHUNK_SIZE = 1024 * 1024
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ROLE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,199}$")
_MIME = re.compile(
    r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/"
    r"[a-z0-9][a-z0-9!#$&^_.+-]{0,126}$"
)
_H3_BATCH_KEY_PREFIX = "h3-batch-v1:"
_H3_BATCH_KEY = re.compile(
    r"^h3-batch-v1:(?P<manifest>[0-9a-f]{64}):"
    r"(?P<count>[0-9]{5}):(?P<ordinal>[0-9]{5})$"
)
_H3_BATCH_MAX_ARTIFACTS = 99_999


class ArtifactPublicationError(RuntimeError):
    """Base class for publication failures safe to map to a generic error."""


class ArtifactUnavailable(ArtifactPublicationError):
    """The requested artifact/token is absent or outside the project scope."""


class StaleArtifactAttempt(ArtifactPublicationError):
    """An attempt lost its fencing race to a newer attempt."""


class ArtifactConflict(ArtifactPublicationError):
    """An idempotency identity was reused for different bytes or metadata."""


class ArtifactVerificationError(ArtifactPublicationError):
    """Staged bytes do not match their declared identity or media type."""


class PublicationCrash(RuntimeError):
    """Test-only crash injected at an explicit durability boundary."""


class ArtifactStatus(StrEnum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    TOMBSTONED = "TOMBSTONED"


@dataclass(frozen=True, slots=True)
class PublicationClaim:
    project_id: UUID
    operation_run_id: UUID
    attempt_id: UUID
    attempt_number: int
    fencing_token: int
    publication_key: str
    staging_token: UUID
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StagedArtifact:
    staging_locator: str
    content_digest: str
    byte_size: int
    mime_type: str


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    artifact_id: UUID
    project_id: UUID
    operation_run_id: UUID
    attempt_id: UUID
    attempt_number: int
    fencing_token: int
    publication_key: str
    staging_token: UUID
    content_digest: str
    byte_size: int
    mime_type: str
    logical_role: str
    retention_class: RetentionClass
    retain_until: datetime | None
    staging_locator: str
    storage_uri: str | None
    status: ArtifactStatus
    state_version: int
    created_at: datetime
    committed_at: datetime | None = None
    tombstoned_at: datetime | None = None

    def persistent_ref(self) -> PersistentArtifactRef:
        if self.status is not ArtifactStatus.COMMITTED or self.storage_uri is None:
            raise ArtifactUnavailable("artifact is not committed")
        return PersistentArtifactRef(
            artifact_id=self.artifact_id,
            project_id=self.project_id,
            content_digest=self.content_digest,
            mime_type=self.mime_type,
            byte_size=self.byte_size,
            logical_role=self.logical_role,
            storage_uri=self.storage_uri,
            produced_by_operation_run_id=self.operation_run_id,
            produced_by_operation_attempt_id=self.attempt_id,
            created_at=self.created_at,
            retention_class=self.retention_class,
        )


@dataclass(frozen=True, slots=True)
class H3ArtifactBatchManifestEntry:
    """Canonical metadata for one ordered H3 batch member."""

    content_digest: str
    byte_size: int
    mime_type: str
    logical_role: str
    retention_class: RetentionClass


@dataclass(frozen=True, slots=True)
class H3ArtifactBatchIdentity:
    """Identity persisted in every H3 batch member's publication key."""

    manifest_digest: str
    count: int
    ordinal: int


@dataclass(frozen=True, slots=True)
class ArtifactBatchTransition:
    """One exact catalog transition in an atomic publication batch."""

    staging_token: UUID
    storage_uri: str
    expected_version: int


class ArtifactMetrics(Protocol):
    def set_artifact_state(self, *, state: str, count: float) -> None: ...

    def record_artifact_orphan(
        self,
        *,
        action: str,
        outcome: str,
    ) -> None: ...


class ArtifactPublicationRepository(Protocol):
    def begin_claim(
        self,
        *,
        project_id: UUID,
        operation_run_id: UUID,
        attempt_id: UUID,
        attempt_number: int,
        fencing_token: int,
        publication_key: str,
        now: datetime,
    ) -> PublicationClaim: ...

    def get_claim(
        self,
        *,
        project_id: UUID,
        staging_token: UUID,
    ) -> PublicationClaim: ...

    def register_pending(
        self,
        *,
        claim: PublicationClaim,
        staged: StagedArtifact,
        logical_role: str,
        retention_class: RetentionClass,
        retain_until: datetime | None,
        now: datetime,
    ) -> ArtifactRecord: ...

    def get_by_token(
        self,
        *,
        project_id: UUID,
        staging_token: UUID,
    ) -> ArtifactRecord: ...

    def commit(
        self,
        *,
        project_id: UUID,
        staging_token: UUID,
        storage_uri: str,
        expected_version: int,
        now: datetime,
    ) -> ArtifactRecord: ...

    def commit_batch(
        self,
        *,
        project_id: UUID,
        transitions: tuple[ArtifactBatchTransition, ...],
        now: datetime,
    ) -> tuple[ArtifactRecord, ...]: ...

    def abort_batch(
        self,
        *,
        project_id: UUID,
        transitions: tuple[ArtifactBatchTransition, ...],
        now: datetime,
    ) -> tuple[ArtifactRecord, ...]: ...

    def get_visible(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
    ) -> ArtifactRecord: ...

    def find_visible_by_digest(
        self,
        *,
        project_id: UUID,
        content_digest: str,
    ) -> tuple[ArtifactRecord, ...]: ...

    def list_pending(
        self,
        *,
        project_id: UUID | None = None,
    ) -> tuple[ArtifactRecord, ...]: ...

    def active_staging_locators(
        self,
        *,
        newer_than: datetime,
    ) -> frozenset[str]: ...

    def state_counts(self) -> dict[ArtifactStatus, int]: ...

    def committed_digest_references(self, *, content_digest: str) -> int: ...


class InMemoryArtifactRepository:
    """Thread-safe reference repository with project and fence enforcement."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._claims_by_key: dict[
            tuple[UUID, UUID, str], PublicationClaim
        ] = {}
        self._claims_by_token: dict[tuple[UUID, UUID], PublicationClaim] = {}
        self._current_attempt: dict[
            tuple[UUID, UUID], tuple[int, UUID, int]
        ] = {}
        self._records_by_token: dict[
            tuple[UUID, UUID], ArtifactRecord
        ] = {}
        self._records_by_id: dict[tuple[UUID, UUID], ArtifactRecord] = {}

    @staticmethod
    def _validate_claim(
        *,
        attempt_number: int,
        fencing_token: int,
        publication_key: str,
    ) -> None:
        if attempt_number < 1:
            raise ValueError("attempt_number must be positive")
        if fencing_token < 0:
            raise ValueError("fencing_token must be non-negative")
        if not publication_key or len(publication_key) > 255:
            raise ValueError("publication_key must contain 1-255 characters")

    def begin_claim(
        self,
        *,
        project_id: UUID,
        operation_run_id: UUID,
        attempt_id: UUID,
        attempt_number: int,
        fencing_token: int,
        publication_key: str,
        now: datetime,
    ) -> PublicationClaim:
        self._validate_claim(
            attempt_number=attempt_number,
            fencing_token=fencing_token,
            publication_key=publication_key,
        )
        _require_aware(now, "now")
        attempt_key = (project_id, operation_run_id)
        key = (project_id, attempt_id, publication_key)
        with self._lock:
            current = self._current_attempt.get(attempt_key)
            identity = (fencing_token, attempt_id, attempt_number)
            if current is not None and (
                fencing_token < current[0]
                or (fencing_token == current[0] and identity != current)
            ):
                raise StaleArtifactAttempt("publication attempt is stale")
            if current is None or fencing_token > current[0]:
                self._current_attempt[attempt_key] = identity

            _require_compatible_h3_batch_manifest(
                publication_key,
                (
                    claim.publication_key
                    for claim in self._claims_by_key.values()
                    if claim.project_id == project_id
                    and claim.operation_run_id == operation_run_id
                    and claim.attempt_id == attempt_id
                ),
            )

            replay = self._claims_by_key.get(key)
            if replay is not None:
                expected = (
                    operation_run_id,
                    attempt_id,
                    attempt_number,
                    fencing_token,
                )
                observed = (
                    replay.operation_run_id,
                    replay.attempt_id,
                    replay.attempt_number,
                    replay.fencing_token,
                )
                if expected != observed:
                    raise ArtifactConflict(
                        "publication key was reused by a different attempt"
                    )
                return replay

            claim = PublicationClaim(
                project_id=project_id,
                operation_run_id=operation_run_id,
                attempt_id=attempt_id,
                attempt_number=attempt_number,
                fencing_token=fencing_token,
                publication_key=publication_key,
                staging_token=uuid4(),
                created_at=now,
            )
            self._claims_by_key[key] = claim
            self._claims_by_token[(project_id, claim.staging_token)] = claim
            return claim

    def _assert_current(self, claim: PublicationClaim) -> None:
        current = self._current_attempt.get(
            (claim.project_id, claim.operation_run_id)
        )
        expected = (
            claim.fencing_token,
            claim.attempt_id,
            claim.attempt_number,
        )
        if current != expected:
            raise StaleArtifactAttempt("publication attempt is stale")

    def get_claim(
        self,
        *,
        project_id: UUID,
        staging_token: UUID,
    ) -> PublicationClaim:
        with self._lock:
            claim = self._claims_by_token.get((project_id, staging_token))
            if claim is None:
                # Deliberately identical for missing and wrong-project tokens.
                raise ArtifactUnavailable("artifact publication is unavailable")
            return claim

    def register_pending(
        self,
        *,
        claim: PublicationClaim,
        staged: StagedArtifact,
        logical_role: str,
        retention_class: RetentionClass,
        retain_until: datetime | None,
        now: datetime,
    ) -> ArtifactRecord:
        _validate_staged(staged)
        _validate_role(logical_role)
        _require_aware(now, "now")
        if retain_until is not None:
            _require_aware(retain_until, "retain_until")
        key = (claim.project_id, claim.staging_token)
        with self._lock:
            stored_claim = self._claims_by_token.get(key)
            if stored_claim != claim:
                raise ArtifactUnavailable("artifact publication is unavailable")
            self._assert_current(claim)
            replay = self._records_by_token.get(key)
            if replay is not None:
                expected = (
                    staged.content_digest,
                    staged.byte_size,
                    staged.mime_type,
                    staged.staging_locator,
                    logical_role,
                    retention_class,
                    retain_until,
                )
                observed = (
                    replay.content_digest,
                    replay.byte_size,
                    replay.mime_type,
                    replay.staging_locator,
                    replay.logical_role,
                    replay.retention_class,
                    replay.retain_until,
                )
                if expected != observed:
                    raise ArtifactConflict(
                        "publication metadata changed during retry"
                    )
                return replay

            record = ArtifactRecord(
                artifact_id=uuid4(),
                project_id=claim.project_id,
                operation_run_id=claim.operation_run_id,
                attempt_id=claim.attempt_id,
                attempt_number=claim.attempt_number,
                fencing_token=claim.fencing_token,
                publication_key=claim.publication_key,
                staging_token=claim.staging_token,
                content_digest=staged.content_digest,
                byte_size=staged.byte_size,
                mime_type=staged.mime_type,
                logical_role=logical_role,
                retention_class=retention_class,
                retain_until=retain_until,
                staging_locator=staged.staging_locator,
                storage_uri=None,
                status=ArtifactStatus.PENDING,
                state_version=0,
                created_at=now,
            )
            self._records_by_token[key] = record
            self._records_by_id[(record.project_id, record.artifact_id)] = record
            return record

    def get_by_token(
        self,
        *,
        project_id: UUID,
        staging_token: UUID,
    ) -> ArtifactRecord:
        with self._lock:
            record = self._records_by_token.get((project_id, staging_token))
            if record is None:
                raise ArtifactUnavailable("artifact publication is unavailable")
            return record

    def commit(
        self,
        *,
        project_id: UUID,
        staging_token: UUID,
        storage_uri: str,
        expected_version: int,
        now: datetime,
    ) -> ArtifactRecord:
        _require_aware(now, "now")
        key = (project_id, staging_token)
        with self._lock:
            record = self._records_by_token.get(key)
            if record is None:
                raise ArtifactUnavailable("artifact publication is unavailable")
            if (
                _parse_h3_batch_publication_key(record.publication_key)
                is not None
            ):
                raise ArtifactConflict(
                    "H3 artifact batch members require atomic batch commit"
                )
            if record.status is ArtifactStatus.COMMITTED:
                if record.storage_uri != storage_uri:
                    raise ArtifactConflict("committed storage identity changed")
                return record
            if record.status is ArtifactStatus.TOMBSTONED:
                raise ArtifactUnavailable("artifact publication is unavailable")
            claim = self._claims_by_token[key]
            self._assert_current(claim)
            if record.state_version != expected_version:
                raise ArtifactConflict("artifact state changed during finalize")
            committed = replace(
                record,
                status=ArtifactStatus.COMMITTED,
                storage_uri=storage_uri,
                state_version=record.state_version + 1,
                committed_at=now,
            )
            self._records_by_token[key] = committed
            self._records_by_id[
                (committed.project_id, committed.artifact_id)
            ] = committed
            return committed

    def commit_batch(
        self,
        *,
        project_id: UUID,
        transitions: tuple[ArtifactBatchTransition, ...],
        now: datetime,
    ) -> tuple[ArtifactRecord, ...]:
        transitions = _validate_batch_transitions(transitions)
        _require_aware(now, "now")
        with self._lock:
            records: list[ArtifactRecord] = []
            for transition in transitions:
                key = (project_id, transition.staging_token)
                record = self._records_by_token.get(key)
                if record is None:
                    raise ArtifactUnavailable(
                        "artifact publication batch is unavailable"
                    )
                records.append(record)
            records = list(
                _validate_h3_batch_records(
                    records,
                    require_complete=True,
                )
            )
            transitions_by_token = {
                item.staging_token: item for item in transitions
            }
            transitions = tuple(
                transitions_by_token[record.staging_token]
                for record in records
            )

            statuses = {record.status for record in records}
            if statuses == {ArtifactStatus.COMMITTED}:
                for record, transition in zip(
                    records, transitions, strict=True
                ):
                    if record.storage_uri != transition.storage_uri:
                        raise ArtifactConflict(
                            "committed batch storage identity changed"
                        )
                return tuple(records)
            if statuses != {ArtifactStatus.PENDING}:
                if ArtifactStatus.TOMBSTONED in statuses:
                    raise ArtifactUnavailable(
                        "artifact publication batch is unavailable"
                    )
                raise ArtifactConflict(
                    "artifact publication batch has mixed visibility"
                )

            identities = {
                (
                    record.operation_run_id,
                    record.attempt_id,
                    record.attempt_number,
                    record.fencing_token,
                )
                for record in records
            }
            if len(identities) != 1:
                raise ArtifactConflict(
                    "artifact publication batch crosses attempt identities"
                )
            for record, transition in zip(records, transitions, strict=True):
                claim = self._claims_by_token[
                    (record.project_id, record.staging_token)
                ]
                self._assert_current(claim)
                if record.state_version != transition.expected_version:
                    raise ArtifactConflict(
                        "artifact state changed during batch finalize"
                    )

            committed = tuple(
                replace(
                    record,
                    status=ArtifactStatus.COMMITTED,
                    storage_uri=transition.storage_uri,
                    state_version=record.state_version + 1,
                    committed_at=now,
                )
                for record, transition in zip(
                    records, transitions, strict=True
                )
            )
            for record in committed:
                self._records_by_token[
                    (record.project_id, record.staging_token)
                ] = record
                self._records_by_id[
                    (record.project_id, record.artifact_id)
                ] = record
            return committed

    def abort_batch(
        self,
        *,
        project_id: UUID,
        transitions: tuple[ArtifactBatchTransition, ...],
        now: datetime,
    ) -> tuple[ArtifactRecord, ...]:
        transitions = _validate_batch_transitions(transitions)
        _require_aware(now, "now")
        with self._lock:
            records: list[ArtifactRecord] = []
            for transition in transitions:
                record = self._records_by_token.get(
                    (project_id, transition.staging_token)
                )
                if record is None:
                    raise ArtifactUnavailable(
                        "artifact publication batch is unavailable"
                    )
                records.append(record)

            statuses = {record.status for record in records}
            if ArtifactStatus.PENDING not in statuses:
                for record, transition in zip(
                    records, transitions, strict=True
                ):
                    if record.storage_uri != transition.storage_uri:
                        raise ArtifactConflict(
                            "aborted batch storage identity changed"
                        )
                return tuple(records)
            identities = {
                (
                    record.operation_run_id,
                    record.attempt_id,
                    record.attempt_number,
                    record.fencing_token,
                )
                for record in records
            }
            if len(identities) != 1:
                raise ArtifactConflict(
                    "artifact publication batch crosses attempt identities"
                )
            for record, transition in zip(records, transitions, strict=True):
                if (
                    record.status is ArtifactStatus.PENDING
                    and record.state_version != transition.expected_version
                ):
                    raise ArtifactConflict(
                        "artifact state changed during batch abort"
                    )
                if (
                    record.status is not ArtifactStatus.PENDING
                    and record.storage_uri != transition.storage_uri
                ):
                    raise ArtifactConflict(
                        "aborted batch storage identity changed"
                    )

            tombstoned = tuple(
                replace(
                    record,
                    status=ArtifactStatus.TOMBSTONED,
                    storage_uri=transition.storage_uri,
                    state_version=record.state_version + 1,
                    committed_at=now,
                    tombstoned_at=now,
                )
                for record, transition in zip(
                    records, transitions, strict=True
                )
                if record.status is ArtifactStatus.PENDING
            )
            for record in tombstoned:
                self._records_by_token[
                    (record.project_id, record.staging_token)
                ] = record
                self._records_by_id[
                    (record.project_id, record.artifact_id)
                ] = record
            by_token = {
                record.staging_token: record for record in tombstoned
            }
            return tuple(
                by_token.get(record.staging_token, record)
                for record in records
            )

    def get_visible(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
    ) -> ArtifactRecord:
        with self._lock:
            record = self._records_by_id.get((project_id, artifact_id))
            if record is None or record.status is not ArtifactStatus.COMMITTED:
                raise ArtifactUnavailable("artifact is unavailable")
            return record

    def find_visible_by_digest(
        self,
        *,
        project_id: UUID,
        content_digest: str,
    ) -> tuple[ArtifactRecord, ...]:
        _validate_digest(content_digest)
        with self._lock:
            return tuple(
                record
                for (record_project, _), record in self._records_by_id.items()
                if record_project == project_id
                and record.status is ArtifactStatus.COMMITTED
                and record.content_digest == content_digest
            )

    def list_pending(
        self,
        *,
        project_id: UUID | None = None,
    ) -> tuple[ArtifactRecord, ...]:
        with self._lock:
            return tuple(
                record
                for record in self._records_by_token.values()
                if record.status is ArtifactStatus.PENDING
                and (project_id is None or record.project_id == project_id)
            )

    def active_staging_locators(
        self,
        *,
        newer_than: datetime,
    ) -> frozenset[str]:
        _require_aware(newer_than, "newer_than")
        with self._lock:
            pending = {
                record.staging_locator
                for record in self._records_by_token.values()
                if record.status is ArtifactStatus.PENDING
            }
            recent_claims = {
                _staging_locator(claim.staging_token)
                for claim in self._claims_by_token.values()
                if claim.created_at >= newer_than
            }
            return frozenset(pending | recent_claims)

    def state_counts(self) -> dict[ArtifactStatus, int]:
        result = {status: 0 for status in ArtifactStatus}
        with self._lock:
            for record in self._records_by_id.values():
                result[record.status] += 1
        return result

    # GC-facing methods are kept here so the in-memory implementation exercises
    # the same optimistic checks required of a PostgreSQL adapter.
    def list_committed(
        self,
        *,
        project_id: UUID,
    ) -> tuple[ArtifactRecord, ...]:
        with self._lock:
            return tuple(
                record
                for (scope, _), record in self._records_by_id.items()
                if scope == project_id
                and record.status is ArtifactStatus.COMMITTED
            )

    def list_tombstoned(
        self,
        *,
        project_id: UUID | None = None,
    ) -> tuple[ArtifactRecord, ...]:
        with self._lock:
            return tuple(
                record
                for (scope, _), record in self._records_by_id.items()
                if record.status is ArtifactStatus.TOMBSTONED
                and (project_id is None or scope == project_id)
            )

    def get_any(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
    ) -> ArtifactRecord:
        with self._lock:
            record = self._records_by_id.get((project_id, artifact_id))
            if record is None:
                raise ArtifactUnavailable("artifact is unavailable")
            return record

    def tombstone(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> ArtifactRecord | None:
        _require_aware(now, "now")
        key = (project_id, artifact_id)
        with self._lock:
            record = self._records_by_id.get(key)
            if record is None:
                return None
            if record.status is ArtifactStatus.TOMBSTONED:
                return record
            if (
                record.status is not ArtifactStatus.COMMITTED
                or record.state_version != expected_version
            ):
                return None
            tombstone = replace(
                record,
                status=ArtifactStatus.TOMBSTONED,
                state_version=record.state_version + 1,
                tombstoned_at=now,
            )
            self._records_by_id[key] = tombstone
            self._records_by_token[
                (tombstone.project_id, tombstone.staging_token)
            ] = tombstone
            return tombstone

    def committed_digest_references(self, *, content_digest: str) -> int:
        _validate_digest(content_digest)
        with self._lock:
            return sum(
                record.status is ArtifactStatus.COMMITTED
                and record.content_digest == content_digest
                for record in self._records_by_id.values()
            )

    def artifact_in_project(
        self,
        project_id: UUID,
        artifact_id: UUID,
    ) -> bool:
        with self._lock:
            return (project_id, artifact_id) in self._records_by_id


SessionFactory = Callable[[], Session]


class PostgresArtifactRepository:
    """Transactional production adapter backed by ``orchestration`` tables.

    Each method owns a short transaction. This is intentional: publication
    crosses storage durability boundaries and must survive a process restart
    between any two calls. PostgreSQL advisory locks serialize claims for one
    operation run while row versions provide the final CAS guard.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _lock_operation(
        session: Session,
        *,
        project_id: UUID,
        operation_run_id: UUID,
    ) -> None:
        bind = session.get_bind()
        if bind.dialect.name == "postgresql":
            session.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended(:identity, 0))"
                ),
                {"identity": f"{project_id}:{operation_run_id}"},
            )

    @staticmethod
    def _assert_current_attempt(
        session: Session,
        *,
        project_id: UUID,
        operation_run_id: UUID,
        attempt_id: UUID,
        attempt_number: int,
        fencing_token: int,
    ) -> None:
        # Every caller already owns the per-operation advisory lock. Attempts
        # are immutable append-only facts, so a plain snapshot read is both
        # sufficient for the fence and compatible with the execution role's
        # deliberate lack of UPDATE permission.
        current = session.execute(
            select(
                OperationAttemptRecord.id,
                OperationAttemptRecord.attempt_number,
                OperationAttemptRecord.fencing_token,
            )
            .where(
                OperationAttemptRecord.project_id == project_id,
                OperationAttemptRecord.operation_run_id == operation_run_id,
            )
            .order_by(
                OperationAttemptRecord.fencing_token.desc(),
                OperationAttemptRecord.attempt_number.desc(),
            )
            .limit(1)
        ).one_or_none()
        expected = (attempt_id, attempt_number, fencing_token)
        if current is None or tuple(current) != expected:
            raise StaleArtifactAttempt("publication attempt is stale")

    @staticmethod
    def _claim(row: ArtifactPublicationClaimRecord) -> PublicationClaim:
        return PublicationClaim(
            project_id=row.project_id,
            operation_run_id=row.operation_run_id,
            attempt_id=row.operation_attempt_id,
            attempt_number=row.attempt_number,
            fencing_token=row.fencing_token,
            publication_key=row.publication_key,
            staging_token=row.staging_token,
            created_at=_aware(row.created_at),
        )

    @staticmethod
    def _artifact(row: ArtifactRecordRow) -> ArtifactRecord:
        return ArtifactRecord(
            artifact_id=row.id,
            project_id=row.project_id,
            operation_run_id=row.operation_run_id,
            attempt_id=row.operation_attempt_id,
            attempt_number=row.attempt_number,
            fencing_token=row.fencing_token,
            publication_key=row.publication_key,
            staging_token=row.staging_token,
            content_digest=row.content_digest,
            byte_size=row.byte_size,
            mime_type=row.mime_type,
            logical_role=row.logical_role,
            retention_class=RetentionClass(row.retention_class),
            retain_until=(
                _aware(row.retain_until)
                if row.retain_until is not None
                else None
            ),
            staging_locator=row.staging_locator,
            storage_uri=row.storage_uri,
            status=ArtifactStatus(row.status),
            state_version=row.state_version,
            created_at=_aware(row.created_at),
            committed_at=(
                _aware(row.committed_at)
                if row.committed_at is not None
                else None
            ),
            tombstoned_at=(
                _aware(row.tombstoned_at)
                if row.tombstoned_at is not None
                else None
            ),
        )

    def begin_claim(
        self,
        *,
        project_id: UUID,
        operation_run_id: UUID,
        attempt_id: UUID,
        attempt_number: int,
        fencing_token: int,
        publication_key: str,
        now: datetime,
    ) -> PublicationClaim:
        InMemoryArtifactRepository._validate_claim(
            attempt_number=attempt_number,
            fencing_token=fencing_token,
            publication_key=publication_key,
        )
        _require_aware(now, "now")
        with self._session_factory() as session, session.begin():
            self._lock_operation(
                session,
                project_id=project_id,
                operation_run_id=operation_run_id,
            )
            self._assert_current_attempt(
                session,
                project_id=project_id,
                operation_run_id=operation_run_id,
                attempt_id=attempt_id,
                attempt_number=attempt_number,
                fencing_token=fencing_token,
            )
            existing_publication_keys = session.scalars(
                select(ArtifactPublicationClaimRecord.publication_key).where(
                    ArtifactPublicationClaimRecord.project_id == project_id,
                    ArtifactPublicationClaimRecord.operation_run_id
                    == operation_run_id,
                    ArtifactPublicationClaimRecord.operation_attempt_id
                    == attempt_id,
                )
            ).all()
            _require_compatible_h3_batch_manifest(
                publication_key,
                existing_publication_keys,
            )
            replay = session.scalar(
                select(ArtifactPublicationClaimRecord)
                .where(
                    ArtifactPublicationClaimRecord.project_id == project_id,
                    ArtifactPublicationClaimRecord.operation_attempt_id
                    == attempt_id,
                    ArtifactPublicationClaimRecord.publication_key
                    == publication_key,
                )
                .with_for_update()
            )
            if replay is not None:
                observed = (
                    replay.operation_run_id,
                    replay.attempt_number,
                    replay.fencing_token,
                )
                expected = (
                    operation_run_id,
                    attempt_number,
                    fencing_token,
                )
                if observed != expected:
                    raise ArtifactConflict(
                        "publication key was reused by a different attempt"
                    )
                return self._claim(replay)
            row = ArtifactPublicationClaimRecord(
                id=uuid4(),
                project_id=project_id,
                operation_run_id=operation_run_id,
                operation_attempt_id=attempt_id,
                attempt_number=attempt_number,
                fencing_token=fencing_token,
                publication_key=publication_key,
                staging_token=uuid4(),
                status="OPEN",
                state_version=0,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            return self._claim(row)

    def get_claim(
        self,
        *,
        project_id: UUID,
        staging_token: UUID,
    ) -> PublicationClaim:
        with self._session_factory() as session:
            row = session.scalar(
                select(ArtifactPublicationClaimRecord).where(
                    ArtifactPublicationClaimRecord.project_id == project_id,
                    ArtifactPublicationClaimRecord.staging_token
                    == staging_token,
                )
            )
            if row is None:
                raise ArtifactUnavailable("artifact publication is unavailable")
            return self._claim(row)

    def register_pending(
        self,
        *,
        claim: PublicationClaim,
        staged: StagedArtifact,
        logical_role: str,
        retention_class: RetentionClass,
        retain_until: datetime | None,
        now: datetime,
    ) -> ArtifactRecord:
        _validate_staged(staged)
        _validate_role(logical_role)
        _require_aware(now, "now")
        if retain_until is not None:
            _require_aware(retain_until, "retain_until")
        with self._session_factory() as session, session.begin():
            self._lock_operation(
                session,
                project_id=claim.project_id,
                operation_run_id=claim.operation_run_id,
            )
            claim_row = session.scalar(
                select(ArtifactPublicationClaimRecord)
                .where(
                    ArtifactPublicationClaimRecord.project_id
                    == claim.project_id,
                    ArtifactPublicationClaimRecord.staging_token
                    == claim.staging_token,
                )
                .with_for_update()
            )
            if claim_row is None or self._claim(claim_row) != claim:
                raise ArtifactUnavailable("artifact publication is unavailable")
            self._assert_current_attempt(
                session,
                project_id=claim.project_id,
                operation_run_id=claim.operation_run_id,
                attempt_id=claim.attempt_id,
                attempt_number=claim.attempt_number,
                fencing_token=claim.fencing_token,
            )
            replay = session.scalar(
                select(ArtifactRecordRow)
                .where(
                    ArtifactRecordRow.project_id == claim.project_id,
                    ArtifactRecordRow.staging_token == claim.staging_token,
                )
                .with_for_update()
            )
            if replay is not None:
                expected = (
                    staged.content_digest,
                    staged.byte_size,
                    staged.mime_type,
                    staged.staging_locator,
                    logical_role,
                    retention_class.value,
                    retain_until,
                )
                observed = (
                    replay.content_digest,
                    replay.byte_size,
                    replay.mime_type,
                    replay.staging_locator,
                    replay.logical_role,
                    replay.retention_class,
                    replay.retain_until,
                )
                if expected != observed:
                    raise ArtifactConflict(
                        "publication metadata changed during retry"
                    )
                return self._artifact(replay)
            row = ArtifactRecordRow(
                id=uuid4(),
                project_id=claim.project_id,
                publication_claim_id=claim_row.id,
                operation_run_id=claim.operation_run_id,
                operation_attempt_id=claim.attempt_id,
                attempt_number=claim.attempt_number,
                fencing_token=claim.fencing_token,
                publication_key=claim.publication_key,
                staging_token=claim.staging_token,
                content_digest=staged.content_digest,
                byte_size=staged.byte_size,
                mime_type=staged.mime_type,
                logical_role=logical_role,
                retention_class=retention_class.value,
                retain_until=retain_until,
                staging_locator=staged.staging_locator,
                storage_uri=None,
                status=ArtifactStatus.PENDING.value,
                state_version=0,
                created_at=now,
            )
            session.add(row)
            claim_row.status = "REGISTERED"
            claim_row.state_version += 1
            claim_row.updated_at = now
            session.flush()
            return self._artifact(row)

    def get_by_token(
        self,
        *,
        project_id: UUID,
        staging_token: UUID,
    ) -> ArtifactRecord:
        with self._session_factory() as session:
            row = session.scalar(
                select(ArtifactRecordRow).where(
                    ArtifactRecordRow.project_id == project_id,
                    ArtifactRecordRow.staging_token == staging_token,
                )
            )
            if row is None:
                raise ArtifactUnavailable("artifact publication is unavailable")
            return self._artifact(row)

    def commit(
        self,
        *,
        project_id: UUID,
        staging_token: UUID,
        storage_uri: str,
        expected_version: int,
        now: datetime,
    ) -> ArtifactRecord:
        _require_aware(now, "now")
        with self._session_factory() as session, session.begin():
            operation_run_id = session.scalar(
                select(ArtifactRecordRow.operation_run_id).where(
                    ArtifactRecordRow.project_id == project_id,
                    ArtifactRecordRow.staging_token == staging_token,
                )
            )
            if operation_run_id is None:
                raise ArtifactUnavailable("artifact publication is unavailable")
            self._lock_operation(
                session,
                project_id=project_id,
                operation_run_id=operation_run_id,
            )
            row = session.scalar(
                select(ArtifactRecordRow)
                .where(
                    ArtifactRecordRow.project_id == project_id,
                    ArtifactRecordRow.staging_token == staging_token,
                )
                .with_for_update()
            )
            if row is None:
                raise ArtifactUnavailable("artifact publication is unavailable")
            if row.operation_run_id != operation_run_id:
                raise ArtifactConflict(
                    "artifact operation identity changed during finalize"
                )
            if (
                _parse_h3_batch_publication_key(row.publication_key)
                is not None
            ):
                raise ArtifactConflict(
                    "H3 artifact batch members require atomic batch commit"
                )
            if row.status == ArtifactStatus.COMMITTED.value:
                if row.storage_uri != storage_uri:
                    raise ArtifactConflict("committed storage identity changed")
                return self._artifact(row)
            if row.status == ArtifactStatus.TOMBSTONED.value:
                raise ArtifactUnavailable("artifact publication is unavailable")
            self._assert_current_attempt(
                session,
                project_id=project_id,
                operation_run_id=row.operation_run_id,
                attempt_id=row.operation_attempt_id,
                attempt_number=row.attempt_number,
                fencing_token=row.fencing_token,
            )
            changed = session.execute(
                update(ArtifactRecordRow)
                .where(
                    ArtifactRecordRow.id == row.id,
                    ArtifactRecordRow.project_id == project_id,
                    ArtifactRecordRow.status == ArtifactStatus.PENDING.value,
                    ArtifactRecordRow.state_version == expected_version,
                )
                .values(
                    storage_uri=storage_uri,
                    status=ArtifactStatus.COMMITTED.value,
                    state_version=expected_version + 1,
                    committed_at=now,
                )
            )
            if changed.rowcount != 1:
                raise ArtifactConflict(
                    "artifact state changed during finalize"
                )
            claim = session.scalar(
                select(ArtifactPublicationClaimRecord)
                .where(
                    ArtifactPublicationClaimRecord.id
                    == row.publication_claim_id
                )
                .with_for_update()
            )
            if claim is not None:
                claim.status = "FINALIZED"
                claim.state_version += 1
                claim.updated_at = now
            session.flush()
            session.expire(row)
            session.refresh(row)
            return self._artifact(row)

    def commit_batch(
        self,
        *,
        project_id: UUID,
        transitions: tuple[ArtifactBatchTransition, ...],
        now: datetime,
    ) -> tuple[ArtifactRecord, ...]:
        transitions = _validate_batch_transitions(transitions)
        _require_aware(now, "now")
        tokens = tuple(item.staging_token for item in transitions)
        by_token = {item.staging_token: item for item in transitions}
        with self._session_factory() as session, session.begin():
            operation_run_ids = tuple(
                session.scalars(
                    select(ArtifactRecordRow.operation_run_id)
                    .where(
                        ArtifactRecordRow.project_id == project_id,
                        ArtifactRecordRow.staging_token.in_(tokens),
                    )
                    .distinct()
                )
            )
            if not operation_run_ids:
                raise ArtifactUnavailable(
                    "artifact publication batch is unavailable"
                )
            if len(operation_run_ids) != 1:
                raise ArtifactConflict(
                    "artifact publication batch crosses operation runs"
                )
            operation_run_id = operation_run_ids[0]
            self._lock_operation(
                session,
                project_id=project_id,
                operation_run_id=operation_run_id,
            )
            rows = session.scalars(
                select(ArtifactRecordRow)
                .where(
                    ArtifactRecordRow.project_id == project_id,
                    ArtifactRecordRow.staging_token.in_(tokens),
                )
                .order_by(ArtifactRecordRow.id)
                .with_for_update()
            ).all()
            rows_by_token = {row.staging_token: row for row in rows}
            if set(rows_by_token) != set(tokens):
                raise ArtifactUnavailable(
                    "artifact publication batch is unavailable"
                )
            ordered = tuple(rows_by_token[token] for token in tokens)
            validated = _validate_h3_batch_records(
                tuple(self._artifact(row) for row in ordered),
                require_complete=True,
            )
            ordered = tuple(
                rows_by_token[record.staging_token] for record in validated
            )
            statuses = {row.status for row in ordered}
            if statuses == {ArtifactStatus.COMMITTED.value}:
                for row in ordered:
                    if row.storage_uri != by_token[row.staging_token].storage_uri:
                        raise ArtifactConflict(
                            "committed batch storage identity changed"
                        )
                return tuple(self._artifact(row) for row in ordered)
            if statuses != {ArtifactStatus.PENDING.value}:
                if ArtifactStatus.TOMBSTONED.value in statuses:
                    raise ArtifactUnavailable(
                        "artifact publication batch is unavailable"
                    )
                raise ArtifactConflict(
                    "artifact publication batch has mixed visibility"
                )

            identities = {
                (
                    row.operation_run_id,
                    row.operation_attempt_id,
                    row.attempt_number,
                    row.fencing_token,
                )
                for row in ordered
            }
            if len(identities) != 1:
                raise ArtifactConflict(
                    "artifact publication batch crosses attempt identities"
                )
            (
                locked_run_id,
                attempt_id,
                attempt_number,
                fencing_token,
            ) = next(iter(identities))
            if locked_run_id != operation_run_id:
                raise ArtifactConflict(
                    "artifact publication batch operation identity changed"
                )
            self._assert_current_attempt(
                session,
                project_id=project_id,
                operation_run_id=operation_run_id,
                attempt_id=attempt_id,
                attempt_number=attempt_number,
                fencing_token=fencing_token,
            )
            for row in ordered:
                transition = by_token[row.staging_token]
                if row.state_version != transition.expected_version:
                    raise ArtifactConflict(
                        "artifact state changed during batch finalize"
                    )

            claim_ids = tuple(row.publication_claim_id for row in ordered)
            claims = session.scalars(
                select(ArtifactPublicationClaimRecord)
                .where(ArtifactPublicationClaimRecord.id.in_(claim_ids))
                .with_for_update()
            ).all()
            if {claim.id for claim in claims} != set(claim_ids):
                raise ArtifactUnavailable(
                    "artifact publication batch is unavailable"
                )
            for row in ordered:
                transition = by_token[row.staging_token]
                row.storage_uri = transition.storage_uri
                row.status = ArtifactStatus.COMMITTED.value
                row.state_version += 1
                row.committed_at = now
            for claim in claims:
                claim.status = "FINALIZED"
                claim.state_version += 1
                claim.updated_at = now
            session.flush()
            return tuple(self._artifact(row) for row in ordered)

    def abort_batch(
        self,
        *,
        project_id: UUID,
        transitions: tuple[ArtifactBatchTransition, ...],
        now: datetime,
    ) -> tuple[ArtifactRecord, ...]:
        transitions = _validate_batch_transitions(transitions)
        _require_aware(now, "now")
        tokens = tuple(item.staging_token for item in transitions)
        by_token = {item.staging_token: item for item in transitions}
        with self._session_factory() as session, session.begin():
            operation_run_ids = tuple(
                session.scalars(
                    select(ArtifactRecordRow.operation_run_id)
                    .where(
                        ArtifactRecordRow.project_id == project_id,
                        ArtifactRecordRow.staging_token.in_(tokens),
                    )
                    .distinct()
                )
            )
            if not operation_run_ids:
                raise ArtifactUnavailable(
                    "artifact publication batch is unavailable"
                )
            if len(operation_run_ids) != 1:
                raise ArtifactConflict(
                    "artifact publication batch crosses operation runs"
                )
            operation_run_id = operation_run_ids[0]
            self._lock_operation(
                session,
                project_id=project_id,
                operation_run_id=operation_run_id,
            )
            rows = session.scalars(
                select(ArtifactRecordRow)
                .where(
                    ArtifactRecordRow.project_id == project_id,
                    ArtifactRecordRow.staging_token.in_(tokens),
                )
                .order_by(ArtifactRecordRow.id)
                .with_for_update()
            ).all()
            rows_by_token = {row.staging_token: row for row in rows}
            if set(rows_by_token) != set(tokens):
                raise ArtifactUnavailable(
                    "artifact publication batch is unavailable"
                )
            ordered = tuple(rows_by_token[token] for token in tokens)
            statuses = {row.status for row in ordered}
            if ArtifactStatus.PENDING.value not in statuses:
                for row in ordered:
                    if row.storage_uri != by_token[row.staging_token].storage_uri:
                        raise ArtifactConflict(
                            "aborted batch storage identity changed"
                        )
                return tuple(self._artifact(row) for row in ordered)
            identities = {
                (
                    row.operation_run_id,
                    row.operation_attempt_id,
                    row.attempt_number,
                    row.fencing_token,
                )
                for row in ordered
            }
            if (
                len(identities) != 1
                or next(iter(identities))[0] != operation_run_id
            ):
                raise ArtifactConflict(
                    "artifact publication batch crosses attempt identities"
                )
            for row in ordered:
                transition = by_token[row.staging_token]
                if (
                    row.status == ArtifactStatus.PENDING.value
                    and row.state_version != transition.expected_version
                ):
                    raise ArtifactConflict(
                        "artifact state changed during batch abort"
                    )
                if (
                    row.status != ArtifactStatus.PENDING.value
                    and row.storage_uri != transition.storage_uri
                ):
                    raise ArtifactConflict(
                        "aborted batch storage identity changed"
                    )

            pending = tuple(
                row
                for row in ordered
                if row.status == ArtifactStatus.PENDING.value
            )
            claim_ids = tuple(row.publication_claim_id for row in pending)
            claims = session.scalars(
                select(ArtifactPublicationClaimRecord)
                .where(ArtifactPublicationClaimRecord.id.in_(claim_ids))
                .with_for_update()
            ).all()
            if {claim.id for claim in claims} != set(claim_ids):
                raise ArtifactUnavailable(
                    "artifact publication batch is unavailable"
                )
            for row in pending:
                transition = by_token[row.staging_token]
                row.storage_uri = transition.storage_uri
                row.status = ArtifactStatus.TOMBSTONED.value
                row.state_version += 1
                row.committed_at = now
                row.tombstoned_at = now
            for claim in claims:
                claim.status = "SUPERSEDED"
                claim.state_version += 1
                claim.updated_at = now
            session.flush()
            return tuple(self._artifact(row) for row in ordered)

    def get_visible(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
    ) -> ArtifactRecord:
        with self._session_factory() as session:
            row = session.scalar(
                select(ArtifactRecordRow).where(
                    ArtifactRecordRow.id == artifact_id,
                    ArtifactRecordRow.project_id == project_id,
                    ArtifactRecordRow.status == ArtifactStatus.COMMITTED.value,
                )
            )
            if row is None:
                raise ArtifactUnavailable("artifact is unavailable")
            return self._artifact(row)

    def find_visible_by_digest(
        self,
        *,
        project_id: UUID,
        content_digest: str,
    ) -> tuple[ArtifactRecord, ...]:
        _validate_digest(content_digest)
        with self._session_factory() as session:
            rows = session.scalars(
                select(ArtifactRecordRow)
                .where(
                    ArtifactRecordRow.project_id == project_id,
                    ArtifactRecordRow.content_digest == content_digest,
                    ArtifactRecordRow.status == ArtifactStatus.COMMITTED.value,
                )
                .order_by(ArtifactRecordRow.created_at, ArtifactRecordRow.id)
            ).all()
            return tuple(self._artifact(row) for row in rows)

    def list_pending(
        self,
        *,
        project_id: UUID | None = None,
    ) -> tuple[ArtifactRecord, ...]:
        statement = select(ArtifactRecordRow).where(
            ArtifactRecordRow.status == ArtifactStatus.PENDING.value
        )
        if project_id is not None:
            statement = statement.where(
                ArtifactRecordRow.project_id == project_id
            )
        with self._session_factory() as session:
            rows = session.scalars(
                statement.order_by(
                    ArtifactRecordRow.created_at,
                    ArtifactRecordRow.id,
                )
            ).all()
            return tuple(self._artifact(row) for row in rows)

    def active_staging_locators(
        self,
        *,
        newer_than: datetime,
    ) -> frozenset[str]:
        _require_aware(newer_than, "newer_than")
        with self._session_factory() as session:
            pending = set(
                session.scalars(
                    select(ArtifactRecordRow.staging_locator).where(
                        ArtifactRecordRow.status
                        == ArtifactStatus.PENDING.value
                    )
                )
            )
            recent_tokens = session.scalars(
                select(ArtifactPublicationClaimRecord.staging_token).where(
                    ArtifactPublicationClaimRecord.created_at >= newer_than
                )
            )
            pending.update(_staging_locator(token) for token in recent_tokens)
            return frozenset(pending)

    def state_counts(self) -> dict[ArtifactStatus, int]:
        result = {status: 0 for status in ArtifactStatus}
        with self._session_factory() as session:
            rows = session.execute(
                select(ArtifactRecordRow.status, func.count())
                .group_by(ArtifactRecordRow.status)
            )
            for status, count in rows:
                result[ArtifactStatus(status)] = int(count)
        return result

    def list_committed(
        self,
        *,
        project_id: UUID,
    ) -> tuple[ArtifactRecord, ...]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(ArtifactRecordRow)
                .where(
                    ArtifactRecordRow.project_id == project_id,
                    ArtifactRecordRow.status == ArtifactStatus.COMMITTED.value,
                )
                .order_by(ArtifactRecordRow.created_at, ArtifactRecordRow.id)
            ).all()
            return tuple(self._artifact(row) for row in rows)

    def list_tombstoned(
        self,
        *,
        project_id: UUID | None = None,
    ) -> tuple[ArtifactRecord, ...]:
        statement = select(ArtifactRecordRow).where(
            ArtifactRecordRow.status == ArtifactStatus.TOMBSTONED.value
        )
        if project_id is not None:
            statement = statement.where(
                ArtifactRecordRow.project_id == project_id
            )
        with self._session_factory() as session:
            rows = session.scalars(
                statement.order_by(
                    ArtifactRecordRow.tombstoned_at,
                    ArtifactRecordRow.id,
                )
            ).all()
            return tuple(self._artifact(row) for row in rows)

    def get_any(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
    ) -> ArtifactRecord:
        with self._session_factory() as session:
            row = session.scalar(
                select(ArtifactRecordRow).where(
                    ArtifactRecordRow.id == artifact_id,
                    ArtifactRecordRow.project_id == project_id,
                )
            )
            if row is None:
                raise ArtifactUnavailable("artifact is unavailable")
            return self._artifact(row)

    @classmethod
    def _tombstone_in_session(
        cls,
        session: Session,
        *,
        project_id: UUID,
        artifact_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> ArtifactRecord | None:
        row = session.scalar(
            select(ArtifactRecordRow)
            .where(
                ArtifactRecordRow.id == artifact_id,
                ArtifactRecordRow.project_id == project_id,
            )
            .with_for_update()
        )
        if row is None:
            return None
        if row.status == ArtifactStatus.TOMBSTONED.value:
            # Another sweeper already won the CAS. Returning ``None`` keeps
            # competing collectors from reporting the same tombstone twice.
            return None
        if (
            row.status != ArtifactStatus.COMMITTED.value
            or row.state_version != expected_version
        ):
            return None
        changed = session.execute(
            update(ArtifactRecordRow)
            .where(
                ArtifactRecordRow.id == artifact_id,
                ArtifactRecordRow.project_id == project_id,
                ArtifactRecordRow.status == ArtifactStatus.COMMITTED.value,
                ArtifactRecordRow.state_version == expected_version,
            )
            .values(
                status=ArtifactStatus.TOMBSTONED.value,
                state_version=expected_version + 1,
                tombstoned_at=now,
            )
        )
        if changed.rowcount != 1:
            return None
        session.flush()
        session.expire(row)
        session.refresh(row)
        return cls._artifact(row)

    def tombstone(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> ArtifactRecord | None:
        _require_aware(now, "now")
        with self._session_factory() as session, session.begin():
            return self._tombstone_in_session(
                session,
                project_id=project_id,
                artifact_id=artifact_id,
                expected_version=expected_version,
                now=now,
            )

    def committed_digest_references(self, *, content_digest: str) -> int:
        _validate_digest(content_digest)
        with self._session_factory() as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(ArtifactRecordRow)
                    .where(
                        ArtifactRecordRow.content_digest == content_digest,
                        ArtifactRecordRow.status
                        == ArtifactStatus.COMMITTED.value,
                    )
                )
                or 0
            )

    def artifact_in_project(
        self,
        project_id: UUID,
        artifact_id: UUID,
    ) -> bool:
        with self._session_factory() as session:
            return (
                session.scalar(
                    select(ArtifactRecordRow.id).where(
                        ArtifactRecordRow.id == artifact_id,
                        ArtifactRecordRow.project_id == project_id,
                    )
                )
                is not None
            )


class ContentAddressedArtifactStore:
    """Filesystem storage rooted at one non-symlink directory."""

    def __init__(
        self,
        root: Path | str,
        *,
        chunk_size: int = CHUNK_SIZE,
        max_bytes: int = 50 * 1024 * 1024 * 1024,
    ) -> None:
        requested_root = Path(root).absolute()
        if chunk_size < 1 or max_bytes < 1:
            raise ValueError("artifact storage bounds must be positive")
        self.chunk_size = chunk_size
        self.max_bytes = max_bytes
        requested_root.mkdir(parents=True, exist_ok=True)
        requested_staging = requested_root / ".staging"
        requested_objects_parent = requested_root / "objects"
        requested_objects = requested_objects_parent / "sha256"
        requested_staging.mkdir(parents=True, exist_ok=True)
        requested_objects.mkdir(parents=True, exist_ok=True)
        if (
            _is_link(requested_root)
            or _is_link(requested_staging)
            or _is_link(requested_objects_parent)
            or _is_link(requested_objects)
        ):
            raise ValueError("artifact storage roots must not be links")
        self.root = requested_root.resolve(strict=True)
        self.staging_root = requested_staging.resolve(strict=True)
        self.objects_root = requested_objects.resolve(strict=True)

    def stage_stream(
        self,
        *,
        claim: PublicationClaim,
        stream: BinaryIO | Iterable[bytes],
        mime_type: str,
        expected_digest: str | None = None,
        expected_size: int | None = None,
    ) -> StagedArtifact:
        mime_type = _validate_mime(mime_type)
        if expected_digest is not None:
            _validate_digest(expected_digest)
        if expected_size is not None and expected_size < 1:
            raise ValueError("expected_size must be positive")
        locator = _staging_locator(claim.staging_token)
        path = self.path_for_staging(locator)
        temporary = self.staging_root / (
            f".{claim.staging_token}.{uuid4()}.upload"
        )
        digest = hashlib.sha256()
        size = 0
        prefix = bytearray()
        try:
            with temporary.open("xb", buffering=0) as target:
                for chunk in _iter_stream(stream, self.chunk_size):
                    if not isinstance(chunk, bytes) or not chunk:
                        raise ArtifactVerificationError(
                            "artifact stream returned an invalid chunk"
                        )
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise ArtifactVerificationError(
                            "artifact exceeds the configured size limit"
                        )
                    if len(prefix) < 64:
                        prefix.extend(chunk[: 64 - len(prefix)])
                    digest.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        if size < 1:
            temporary.unlink(missing_ok=True)
            raise ArtifactVerificationError("empty artifacts are not publishable")
        observed_digest = digest.hexdigest()
        try:
            _verify_media(bytes(prefix), mime_type)
            if expected_digest is not None and observed_digest != expected_digest:
                raise ArtifactVerificationError(
                    "artifact digest does not match the expected digest"
                )
            if expected_size is not None and size != expected_size:
                raise ArtifactVerificationError(
                    "artifact size does not match the expected size"
                )
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        staged = StagedArtifact(
            staging_locator=locator,
            content_digest=observed_digest,
            byte_size=size,
            mime_type=mime_type,
        )
        try:
            os.link(temporary, path)
        except FileExistsError:
            # A lost response after staging can safely repeat with the same
            # bytes.  Different bytes never replace the canonical staging
            # object for the token.
            self._verify_file(path, staged)
        except OSError as exc:
            raise ArtifactPublicationError(
                "artifact staging is unavailable"
            ) from exc
        finally:
            temporary.unlink(missing_ok=True)
        return staged

    def path_for_staging(self, locator: str) -> Path:
        if not re.fullmatch(r"\.staging/[0-9a-f-]{36}\.part", locator):
            raise ArtifactUnavailable("staging object is unavailable")
        path = self.root.joinpath(*locator.split("/"))
        if path.parent != self.staging_root:
            raise ArtifactUnavailable("staging object is unavailable")
        return path

    def object_path(self, content_digest: str) -> Path:
        _validate_digest(content_digest)
        return self.objects_root / content_digest[:2] / content_digest

    def storage_uri(self, content_digest: str) -> str:
        _validate_digest(content_digest)
        return f"artifact://sha256/{content_digest}"

    def verify_staging(self, staged: StagedArtifact) -> Path:
        path = self.path_for_staging(staged.staging_locator)
        self._verify_file(path, staged)
        return path

    def promote(self, staged: StagedArtifact) -> Path:
        destination, _created = self._promote_with_status(staged)
        return destination

    def _promote_with_status(
        self,
        staged: StagedArtifact,
    ) -> tuple[Path, bool]:
        source = self.verify_staging(staged)
        destination = self.object_path(staged.content_digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if _is_link(destination.parent):
            raise ArtifactVerificationError(
                "content-addressed object directory is unsafe"
            )
        try:
            os.link(source, destination)
        except FileExistsError:
            self._verify_file(destination, staged)
            created = False
        except OSError as exc:
            # Hard links are the atomic no-overwrite primitive here.  Falling
            # back to replace would allow one writer to overwrite another.
            raise ArtifactPublicationError(
                "artifact promotion is unavailable"
            ) from exc
        else:
            created = True
            self._fsync_directory(destination.parent)
        source.unlink(missing_ok=True)
        self._fsync_directory(self.staging_root)
        return destination, created

    def ensure_promoted(self, staged: StagedArtifact) -> Path:
        destination, _created = self.ensure_promoted_with_status(staged)
        return destination

    def ensure_promoted_with_status(
        self,
        staged: StagedArtifact,
    ) -> tuple[Path, bool]:
        """Promote and report whether this call created the object."""

        destination = self.object_path(staged.content_digest)
        if destination.exists():
            self._verify_file(destination, staged)
            self.path_for_staging(staged.staging_locator).unlink(missing_ok=True)
            return destination, False
        return self._promote_with_status(staged)

    def verify_object(self, staged: StagedArtifact) -> Path:
        destination = self.object_path(staged.content_digest)
        self._verify_file(destination, staged)
        return destination

    def discard_staging(self, staging_locator: str) -> None:
        """Delete exactly one validated staging object, if it still exists."""

        path = self.path_for_staging(staging_locator)
        path.unlink(missing_ok=True)
        self._fsync_directory(self.staging_root)

    def delete_object(self, record: ArtifactRecord) -> bool:
        path = self.object_path(record.content_digest)
        try:
            if not path.exists():
                return False
            expected = StagedArtifact(
                staging_locator=record.staging_locator,
                content_digest=record.content_digest,
                byte_size=record.byte_size,
                mime_type=record.mime_type,
            )
            self._verify_file(path, expected)
            path.unlink()
            self._fsync_directory(path.parent)
            return True
        except FileNotFoundError:
            return False

    def scan_staging(self) -> Iterator[tuple[str, Path]]:
        for pattern in ("*.part", "*.upload"):
            for path in self.staging_root.glob(pattern):
                if path.is_file() and not _is_link(path):
                    yield f".staging/{path.name}", path

    def _verify_file(self, path: Path, staged: StagedArtifact) -> None:
        try:
            metadata = path.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or _is_link(path)
                or metadata.st_size != staged.byte_size
            ):
                raise ArtifactVerificationError(
                    "artifact bytes failed verification"
                )
            digest = hashlib.sha256()
            prefix = bytearray()
            with path.open("rb", buffering=0) as source:
                while chunk := source.read(self.chunk_size):
                    if len(prefix) < 64:
                        prefix.extend(chunk[: 64 - len(prefix)])
                    digest.update(chunk)
            _verify_media(bytes(prefix), staged.mime_type)
            if digest.hexdigest() != staged.content_digest:
                raise ArtifactVerificationError(
                    "artifact bytes failed verification"
                )
        except OSError as exc:
            raise ArtifactVerificationError(
                "artifact bytes failed verification"
            ) from exc

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


CrashHook = Callable[[str, ArtifactRecord | StagedArtifact], None]


class ArtifactPublicationService:
    def __init__(
        self,
        *,
        repository: ArtifactPublicationRepository,
        store: ContentAddressedArtifactStore,
        clock: Callable[[], datetime] | None = None,
        metrics: ArtifactMetrics | None = None,
        crash_hook: CrashHook | None = None,
    ) -> None:
        self.repository = repository
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))
        self.metrics = metrics
        self.crash_hook = crash_hook

    def begin(
        self,
        *,
        project_id: UUID,
        operation_run_id: UUID,
        attempt_id: UUID,
        attempt_number: int,
        fencing_token: int,
        publication_key: str,
        now: datetime | None = None,
    ) -> PublicationClaim:
        return self.repository.begin_claim(
            project_id=project_id,
            operation_run_id=operation_run_id,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            fencing_token=fencing_token,
            publication_key=publication_key,
            now=now if now is not None else self.clock(),
        )

    def stage(
        self,
        *,
        claim: PublicationClaim,
        stream: BinaryIO | Iterable[bytes],
        mime_type: str,
        expected_digest: str | None = None,
        expected_size: int | None = None,
    ) -> StagedArtifact:
        # Re-resolve by project and token so a caller cannot forge a dataclass.
        if (
            self.repository.get_claim(
                project_id=claim.project_id,
                staging_token=claim.staging_token,
            )
            != claim
        ):
            raise ArtifactUnavailable("artifact publication is unavailable")
        staged = self.store.stage_stream(
            claim=claim,
            stream=stream,
            mime_type=mime_type,
            expected_digest=expected_digest,
            expected_size=expected_size,
        )
        self._boundary("after_stage", staged)
        self._refresh_metrics(
            staging_count=sum(1 for _ in self.store.scan_staging())
        )
        return staged

    def register(
        self,
        *,
        claim: PublicationClaim,
        staged: StagedArtifact,
        logical_role: str,
        retention_class: RetentionClass,
        retain_until: datetime | None = None,
        now: datetime | None = None,
    ) -> ArtifactRecord:
        self.store.verify_staging(staged)
        record = self.repository.register_pending(
            claim=claim,
            staged=staged,
            logical_role=logical_role,
            retention_class=retention_class,
            retain_until=retain_until,
            now=now if now is not None else self.clock(),
        )
        self._boundary("after_register_pending", record)
        self._refresh_metrics()
        return record

    def finalize(
        self,
        *,
        project_id: UUID,
        staging_token: UUID,
    ) -> ArtifactRecord:
        record = self.repository.get_by_token(
            project_id=project_id,
            staging_token=staging_token,
        )
        if _parse_h3_batch_publication_key(record.publication_key) is not None:
            raise ArtifactConflict(
                "H3 artifact batch members require atomic batch finalize"
            )
        if record.status is ArtifactStatus.COMMITTED:
            return record
        if record.status is not ArtifactStatus.PENDING:
            raise ArtifactUnavailable("artifact publication is unavailable")
        staged = StagedArtifact(
            staging_locator=record.staging_locator,
            content_digest=record.content_digest,
            byte_size=record.byte_size,
            mime_type=record.mime_type,
        )
        self.store.ensure_promoted(staged)
        self._boundary("after_promote", record)
        committed = self.repository.commit(
            project_id=project_id,
            staging_token=staging_token,
            storage_uri=self.store.storage_uri(record.content_digest),
            expected_version=record.state_version,
            now=self.clock(),
        )
        self._boundary("after_commit", committed)
        self._refresh_metrics()
        return committed

    def finalize_batch(
        self,
        *,
        project_id: UUID,
        staging_tokens: tuple[UUID, ...],
    ) -> tuple[ArtifactRecord, ...]:
        tokens = _validate_batch_tokens(staging_tokens)
        records = tuple(
            self.repository.get_by_token(
                project_id=project_id,
                staging_token=token,
            )
            for token in tokens
        )
        records = _validate_h3_batch_records(records, require_complete=True)
        statuses = {record.status for record in records}
        if statuses == {ArtifactStatus.COMMITTED}:
            return records
        if statuses != {ArtifactStatus.PENDING}:
            if ArtifactStatus.TOMBSTONED in statuses:
                raise ArtifactUnavailable(
                    "artifact publication batch is unavailable"
                )
            raise ArtifactConflict(
                "artifact publication batch has mixed visibility"
            )

        transitions: list[ArtifactBatchTransition] = []
        for record in records:
            staged = StagedArtifact(
                staging_locator=record.staging_locator,
                content_digest=record.content_digest,
                byte_size=record.byte_size,
                mime_type=record.mime_type,
            )
            self.store.ensure_promoted(staged)
            # Verify both newly promoted and pre-existing objects before any
            # member becomes visible in the catalog.  Failed commits leave
            # unreferenced CAS objects for a separately fenced, grace-period
            # garbage collector: synchronous reference-count-then-delete
            # races another publisher of the same digest.
            self.store.verify_object(staged)
            transitions.append(
                ArtifactBatchTransition(
                    staging_token=record.staging_token,
                    storage_uri=self.store.storage_uri(
                        record.content_digest
                    ),
                    expected_version=record.state_version,
                )
            )
        committed = self.repository.commit_batch(
            project_id=project_id,
            transitions=tuple(transitions),
            now=self.clock(),
        )
        self._refresh_metrics()
        return committed

    def abort_batch(
        self,
        *,
        project_id: UUID,
        staging_tokens: tuple[UUID, ...],
        allow_incomplete: bool = False,
    ) -> tuple[ArtifactRecord, ...]:
        tokens = _validate_batch_tokens(staging_tokens)
        records = tuple(
            self.repository.get_by_token(
                project_id=project_id,
                staging_token=token,
            )
            for token in tokens
        )
        if not allow_incomplete:
            records = _validate_h3_batch_records(
                records,
                require_complete=True,
            )
        else:
            _validate_h3_batch_records(records, require_complete=False)
        transitions = tuple(
            ArtifactBatchTransition(
                staging_token=record.staging_token,
                storage_uri=self.store.storage_uri(record.content_digest),
                expected_version=record.state_version,
            )
            for record in records
        )
        aborted = self.repository.abort_batch(
            project_id=project_id,
            transitions=transitions,
            now=self.clock(),
        )
        for record in records:
            self.store.discard_staging(record.staging_locator)
        self._refresh_metrics(
            staging_count=sum(1 for _ in self.store.scan_staging())
        )
        return aborted

    def adopt(
        self,
        *,
        project_id: UUID,
        staging_token: UUID,
    ) -> ArtifactRecord:
        try:
            result = self.finalize(
                project_id=project_id,
                staging_token=staging_token,
            )
        except Exception:
            self._record_orphan(action="adopt", outcome="failed")
            raise
        self._record_orphan(action="adopt", outcome="succeeded")
        return result

    def publish(
        self,
        *,
        project_id: UUID,
        operation_run_id: UUID,
        attempt_id: UUID,
        attempt_number: int,
        fencing_token: int,
        publication_key: str,
        stream: BinaryIO | Iterable[bytes],
        mime_type: str,
        logical_role: str,
        retention_class: RetentionClass,
        retain_until: datetime | None = None,
        expected_digest: str | None = None,
        expected_size: int | None = None,
    ) -> ArtifactRecord:
        claim = self.begin(
            project_id=project_id,
            operation_run_id=operation_run_id,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            fencing_token=fencing_token,
            publication_key=publication_key,
        )
        try:
            existing = self.repository.get_by_token(
                project_id=project_id,
                staging_token=claim.staging_token,
            )
        except ArtifactUnavailable:
            existing = None
        if existing is not None:
            return self.finalize(
                project_id=project_id,
                staging_token=claim.staging_token,
            )
        staged = self.stage(
            claim=claim,
            stream=stream,
            mime_type=mime_type,
            expected_digest=expected_digest,
            expected_size=expected_size,
        )
        self.register(
            claim=claim,
            staged=staged,
            logical_role=logical_role,
            retention_class=retention_class,
            retain_until=retain_until,
        )
        return self.finalize(
            project_id=project_id,
            staging_token=claim.staging_token,
        )

    def recover_pending(
        self,
        *,
        project_id: UUID | None = None,
    ) -> tuple[ArtifactRecord, ...]:
        recovered: list[ArtifactRecord] = []
        singles: list[ArtifactRecord] = []
        batches: dict[
            tuple[UUID, UUID, UUID, str, int], list[ArtifactRecord]
        ] = {}
        for record in self.repository.list_pending(project_id=project_id):
            try:
                identity = _parse_h3_batch_publication_key(
                    record.publication_key
                )
            except ArtifactPublicationError:
                self._record_orphan(action="reconcile", outcome="failed")
                continue
            if identity is None:
                singles.append(record)
                continue
            key = (
                record.project_id,
                record.operation_run_id,
                record.attempt_id,
                identity.manifest_digest,
                identity.count,
            )
            batches.setdefault(key, []).append(record)

        for record in singles:
            try:
                recovered.append(
                    self.finalize(
                        project_id=record.project_id,
                        staging_token=record.staging_token,
                    )
                )
            except ArtifactPublicationError:
                self._record_orphan(action="reconcile", outcome="failed")
            else:
                self._record_orphan(action="reconcile", outcome="succeeded")

        for records in batches.values():
            try:
                ordered = _validate_h3_batch_records(
                    records,
                    require_complete=True,
                )
                recovered.extend(
                    self.finalize_batch(
                        project_id=ordered[0].project_id,
                        staging_tokens=tuple(
                            record.staging_token for record in ordered
                        ),
                    )
                )
            except ArtifactPublicationError:
                self._record_orphan(action="reconcile", outcome="failed")
            else:
                self._record_orphan(action="reconcile", outcome="succeeded")
        return tuple(recovered)

    def cleanup_orphan_staging(
        self,
        *,
        older_than: timedelta,
    ) -> tuple[str, ...]:
        if older_than <= timedelta(0):
            raise ValueError("orphan grace period must be positive")
        cutoff = self.clock() - older_than
        active = self.repository.active_staging_locators(newer_than=cutoff)
        deleted: list[str] = []
        for locator, path in self.store.scan_staging():
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
                if locator in active or modified >= cutoff:
                    continue
                path.unlink()
                deleted.append(locator)
                self._record_orphan(action="sweep", outcome="deleted")
            except OSError:
                self._record_orphan(action="sweep", outcome="failed")
        self._refresh_metrics(orphan_count=sum(1 for _ in self.store.scan_staging()))
        return tuple(deleted)

    def _boundary(
        self,
        name: str,
        value: ArtifactRecord | StagedArtifact,
    ) -> None:
        if self.crash_hook is not None:
            self.crash_hook(name, value)

    def _record_orphan(self, *, action: str, outcome: str) -> None:
        if self.metrics is not None:
            self.metrics.record_artifact_orphan(
                action=action,
                outcome=outcome,
            )

    def _refresh_metrics(
        self,
        *,
        staging_count: int | None = None,
        orphan_count: int | None = None,
    ) -> None:
        if self.metrics is None:
            return
        counts = self.repository.state_counts()
        self.metrics.set_artifact_state(
            state="pending",
            count=counts[ArtifactStatus.PENDING],
        )
        self.metrics.set_artifact_state(
            state="published",
            count=counts[ArtifactStatus.COMMITTED],
        )
        self.metrics.set_artifact_state(
            state="tombstoned",
            count=counts[ArtifactStatus.TOMBSTONED],
        )
        if staging_count is not None:
            self.metrics.set_artifact_state(
                state="staging",
                count=staging_count,
            )
        if orphan_count is not None:
            self.metrics.set_artifact_state(
                state="orphan_staging",
                count=orphan_count,
            )


def _validate_batch_tokens(values: Iterable[UUID]) -> tuple[UUID, ...]:
    tokens = tuple(values)
    if not tokens or not all(isinstance(token, UUID) for token in tokens):
        raise ValueError("artifact publication batch tokens are invalid")
    if len(tokens) != len(set(tokens)):
        raise ArtifactConflict(
            "artifact publication batch contains duplicate tokens"
        )
    return tokens


def _validate_batch_transitions(
    values: Iterable[ArtifactBatchTransition],
) -> tuple[ArtifactBatchTransition, ...]:
    transitions = tuple(values)
    if not transitions or not all(
        isinstance(item, ArtifactBatchTransition)
        and item.expected_version >= 0
        and isinstance(item.storage_uri, str)
        and item.storage_uri.startswith("artifact://")
        for item in transitions
    ):
        raise ValueError("artifact publication batch transitions are invalid")
    _validate_batch_tokens(item.staging_token for item in transitions)
    return transitions


def build_h3_batch_manifest_digest(
    entries: Iterable[H3ArtifactBatchManifestEntry],
) -> str:
    """Return the canonical digest persisted by every H3 batch member."""

    normalized: list[dict[str, object]] = []
    for ordinal, entry in enumerate(tuple(entries)):
        if not isinstance(entry, H3ArtifactBatchManifestEntry):
            raise TypeError("H3 batch manifest entries are invalid")
        _validate_digest(entry.content_digest)
        if entry.byte_size < 1:
            raise ValueError("H3 batch artifact byte size must be positive")
        mime_type = _validate_mime(entry.mime_type)
        logical_role = _validate_role(entry.logical_role)
        retention_class = RetentionClass(entry.retention_class)
        normalized.append(
            {
                "ordinal": ordinal,
                "content_digest": entry.content_digest,
                "byte_size": entry.byte_size,
                "mime_type": mime_type,
                "logical_role": logical_role,
                "retention_class": retention_class.value,
            }
        )
    if not normalized or len(normalized) > _H3_BATCH_MAX_ARTIFACTS:
        raise ValueError("H3 artifact batch size is invalid")
    canonical = json.dumps(
        {
            "schema": "creative-hub.h3-artifact-batch.v1",
            "count": len(normalized),
            "artifacts": normalized,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_h3_batch_publication_key(
    *,
    manifest_digest: str,
    count: int,
    ordinal: int,
) -> str:
    """Encode the schema, manifest, count, and ordinal without new columns."""

    _validate_digest(manifest_digest)
    if not 1 <= count <= _H3_BATCH_MAX_ARTIFACTS:
        raise ValueError("H3 artifact batch count is invalid")
    if not 0 <= ordinal < count:
        raise ValueError("H3 artifact batch ordinal is invalid")
    return (
        f"{_H3_BATCH_KEY_PREFIX}{manifest_digest}:"
        f"{count:05d}:{ordinal:05d}"
    )


def _parse_h3_batch_publication_key(
    publication_key: str,
) -> H3ArtifactBatchIdentity | None:
    match = _H3_BATCH_KEY.fullmatch(publication_key)
    if match is None:
        if publication_key.startswith("h3-batch"):
            raise ArtifactConflict(
                "H3 artifact batch publication identity is invalid"
            )
        return None
    count = int(match.group("count"))
    ordinal = int(match.group("ordinal"))
    if not 1 <= count <= _H3_BATCH_MAX_ARTIFACTS or not 0 <= ordinal < count:
        raise ArtifactConflict(
            "H3 artifact batch publication identity is invalid"
        )
    return H3ArtifactBatchIdentity(
        manifest_digest=match.group("manifest"),
        count=count,
        ordinal=ordinal,
    )


def _require_compatible_h3_batch_manifest(
    publication_key: str,
    existing_publication_keys: Iterable[str],
) -> None:
    """Fence one immutable H3 batch manifest to one operation Attempt."""

    requested = _parse_h3_batch_publication_key(publication_key)
    if requested is None:
        return
    requested_manifest = (requested.manifest_digest, requested.count)
    for existing_key in existing_publication_keys:
        existing = _parse_h3_batch_publication_key(existing_key)
        if existing is None:
            continue
        if (existing.manifest_digest, existing.count) != requested_manifest:
            raise ArtifactConflict(
                "H3 artifact batch manifest changed for this attempt"
            )


def _validate_h3_batch_records(
    values: Iterable[ArtifactRecord],
    *,
    require_complete: bool,
) -> tuple[ArtifactRecord, ...]:
    records = tuple(values)
    if not records:
        raise ArtifactConflict("H3 artifact batch is unavailable")
    identified: list[tuple[H3ArtifactBatchIdentity, ArtifactRecord]] = []
    for record in records:
        identity = _parse_h3_batch_publication_key(record.publication_key)
        if identity is None:
            raise ArtifactConflict(
                "artifact publication batch contains a non-H3 member"
            )
        identified.append((identity, record))
    batch_identities = {
        (
            record.project_id,
            record.operation_run_id,
            record.attempt_id,
            record.attempt_number,
            record.fencing_token,
            identity.manifest_digest,
            identity.count,
        )
        for identity, record in identified
    }
    if len(batch_identities) != 1:
        raise ArtifactConflict("H3 artifact batch identity changed")
    manifest_digest = identified[0][0].manifest_digest
    count = identified[0][0].count
    ordinals = [identity.ordinal for identity, _record in identified]
    if len(ordinals) != len(set(ordinals)):
        raise ArtifactConflict("H3 artifact batch contains duplicate ordinals")
    if require_complete and set(ordinals) != set(range(count)):
        raise ArtifactConflict("H3 artifact batch is incomplete")
    ordered_pairs = tuple(sorted(identified, key=lambda item: item[0].ordinal))
    if require_complete:
        observed_manifest = build_h3_batch_manifest_digest(
            H3ArtifactBatchManifestEntry(
                content_digest=record.content_digest,
                byte_size=record.byte_size,
                mime_type=record.mime_type,
                logical_role=record.logical_role,
                retention_class=record.retention_class,
            )
            for _identity, record in ordered_pairs
        )
        if observed_manifest != manifest_digest:
            raise ArtifactConflict("H3 artifact batch manifest changed")
    return tuple(record for _identity, record in ordered_pairs)


def _staging_locator(staging_token: UUID) -> str:
    return f".staging/{staging_token}.part"


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _aware(value: datetime) -> datetime:
    """Normalize SQLite's timezone-naive round-trip without weakening writes."""

    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value


def _validate_digest(value: str) -> str:
    if not _DIGEST.fullmatch(value):
        raise ValueError("content digest must be lowercase SHA-256")
    return value


def _validate_mime(value: str) -> str:
    normalized = value.strip().lower()
    if not _MIME.fullmatch(normalized):
        raise ValueError("invalid MIME type")
    return normalized


def _validate_role(value: str) -> str:
    if not _ROLE.fullmatch(value):
        raise ValueError("invalid artifact logical role")
    return value


def _validate_staged(value: StagedArtifact) -> None:
    _validate_digest(value.content_digest)
    _validate_mime(value.mime_type)
    if value.byte_size < 1:
        raise ValueError("artifact byte size must be positive")
    if not re.fullmatch(
        r"\.staging/[0-9a-f-]{36}\.part",
        value.staging_locator,
    ):
        raise ValueError("invalid staging locator")


def _iter_stream(
    stream: BinaryIO | Iterable[bytes],
    chunk_size: int,
) -> Iterator[bytes]:
    reader = getattr(stream, "read", None)
    if callable(reader):
        while chunk := reader(chunk_size):
            yield chunk
        return
    yield from stream


def _sniff_media(prefix: bytes) -> str | None:
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if prefix.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP":
        return "image/webp"
    if len(prefix) >= 12 and prefix[4:8] == b"ftyp":
        return "video/mp4"
    if prefix.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if prefix.startswith(b"RIFF") and prefix[8:12] == b"WAVE":
        return "audio/wav"
    if prefix.startswith(b"ID3") or (
        len(prefix) >= 2
        and prefix[0] == 0xFF
        and prefix[1] & 0xE0 == 0xE0
    ):
        return "audio/mpeg"
    stripped = prefix.lstrip()
    if stripped.startswith((b"{", b"[")):
        try:
            stripped.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return "application/json"
    if stripped.lower().startswith(
        (b"<!doctype html", b"<html", b"<script", b"<?xml")
    ):
        return "text/html"
    return None


def _verify_media(prefix: bytes, declared: str) -> None:
    sniffed = _sniff_media(prefix)
    strict = {
        "image/png",
        "image/jpeg",
        "image/webp",
        "video/mp4",
        "video/webm",
        "audio/wav",
        "audio/mpeg",
    }
    if declared in strict and sniffed != declared:
        raise ArtifactVerificationError(
            "artifact media type does not match its bytes"
        )
    if declared == "application/json" and sniffed != declared:
        raise ArtifactVerificationError("artifact is not valid JSON")
    if sniffed == "text/html" and declared != "text/html":
        raise ArtifactVerificationError(
            "active content does not match its declared media type"
        )


def _is_link(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse and attributes & reparse)
