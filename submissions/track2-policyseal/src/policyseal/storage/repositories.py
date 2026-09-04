from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from policyseal.audit.models import AuditEvent, AuditEventType, payload_as_dict
from policyseal.audit.sanitizer import sanitize_payload
from policyseal.domain.enums import (
    Action,
    ApprovalStatus,
    Channel,
    Classification,
    ContentCategory,
    DecisionOrigin,
    FileKind,
    Purpose,
    RecipientProfile,
    RevisionStatus,
)
from policyseal.domain.errors import ImmutableRevisionError, StorageConflictError
from policyseal.domain.models import (
    ApprovalRecord,
    DeletionTombstone,
    DisclosureContext,
    DisclosureRevision,
    DisclosureTask,
    DocumentRegion,
    PolicyDecision,
    RevisionStageEvent,
    SourceFingerprint,
    StoredArtifactRecord,
)
from policyseal.security.pseudonyms import PseudonymCategory, PseudonymRecord
from policyseal.storage.tables import (
    ApprovalTable,
    ArtifactTable,
    AuditEventTable,
    ContextTable,
    CopilotCheckpointTable,
    DecisionTable,
    DeletionTombstoneTable,
    PseudonymMappingTable,
    RegionTable,
    RevisionStageTable,
    RevisionTable,
    TaskTable,
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _context_table(revision_id: str, context: DisclosureContext) -> ContextTable:
    return ContextTable(
        revision_id=revision_id,
        recipient=context.recipient.value,
        organization=context.organization,
        recipient_id=context.recipient_id,
        purpose=context.purpose.value,
        channel=context.channel.value,
        classification=context.classification.value,
        policy_version=context.policy_version,
        context_sha256=context.sha256,
    )


def _region_table(revision_id: str, region: DocumentRegion) -> RegionTable:
    return RegionTable(
        revision_id=revision_id,
        region_id=region.id,
        file_kind=region.file_kind.value,
        location=region.location,
        region_order=region.order,
        text=region.text,
        category=region.category.value,
        owner_id=region.owner_id,
    )


def _decision_table(revision_id: str, decision: PolicyDecision) -> DecisionTable:
    return DecisionTable(
        revision_id=revision_id,
        region_id=decision.region_id,
        category=decision.category.value,
        action=decision.action.value,
        rule_ids=list(decision.rule_ids),
        evidence_ids=list(decision.evidence_ids),
        reason_code=decision.reason_code,
        reason=decision.reason,
        policy_version=decision.policy_version,
        policy_sha256=decision.policy_sha256,
        origin=decision.origin.value,
        transform=decision.transform,
    )


class PolicySealRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    def add_task(self, task: DisclosureTask) -> None:
        try:
            with self._sessions.begin() as session:
                session.add(
                    TaskTable(
                        id=task.id,
                        requester_id=task.requester_id,
                        file_kind=task.file_kind.value,
                        source_sha256=task.source.sha256,
                        source_size_bytes=task.source.size_bytes,
                        source_storage_id=task.source_storage_id,
                        created_at=task.created_at.astimezone(UTC),
                    )
                )
        except IntegrityError as error:
            raise StorageConflictError(
                "task identity or source storage ID already exists"
            ) from error

    def get_task(self, task_id: str) -> DisclosureTask:
        with self._sessions() as session:
            row = session.get(TaskTable, task_id)
            if row is None:
                raise KeyError(task_id)
            return DisclosureTask(
                id=row.id,
                requester_id=row.requester_id,
                file_kind=FileKind(row.file_kind),
                source=SourceFingerprint(
                    sha256=row.source_sha256,
                    size_bytes=row.source_size_bytes,
                ),
                source_storage_id=row.source_storage_id,
                created_at=_as_utc(row.created_at),
            )

    def list_tasks(self) -> tuple[DisclosureTask, ...]:
        with self._sessions() as session:
            rows = session.scalars(select(TaskTable).order_by(TaskTable.created_at, TaskTable.id))
            return tuple(
                DisclosureTask(
                    id=row.id,
                    requester_id=row.requester_id,
                    file_kind=FileKind(row.file_kind),
                    source=SourceFingerprint(row.source_sha256, row.source_size_bytes),
                    source_storage_id=row.source_storage_id,
                    created_at=_as_utc(row.created_at),
                )
                for row in rows
            )

    def add_revision(
        self,
        revision: DisclosureRevision,
        *,
        regions: Iterable[DocumentRegion] = (),
        decisions: Iterable[PolicyDecision] = (),
    ) -> None:
        region_rows = tuple(regions)
        decision_rows = tuple(decisions)
        known_region_ids = {region.id for region in region_rows}
        if any(decision.region_id not in known_region_ids for decision in decision_rows):
            raise StorageConflictError("every decision must reference a persisted region")
        try:
            with self._sessions.begin() as session:
                task = session.get(TaskTable, revision.task_id)
                if task is None:
                    raise StorageConflictError("revision task does not exist")
                if task.source_sha256 != revision.source_sha256:
                    raise StorageConflictError(
                        "revision source hash differs from its immutable task"
                    )
                if task.requester_id != revision.requester_id:
                    raise StorageConflictError("revision requester differs from its task")
                if any(
                    decision.policy_sha256 != revision.policy_sha256
                    or decision.policy_version != revision.context.policy_version
                    for decision in decision_rows
                ):
                    raise StorageConflictError("decision policy binding differs from its revision")

                revision_row = RevisionTable(
                    id=revision.id,
                    task_id=revision.task_id,
                    revision_number=revision.revision_number,
                    requester_id=revision.requester_id,
                    status=revision.status.value,
                    source_sha256=revision.source_sha256,
                    policy_sha256=revision.policy_sha256,
                    output_storage_id=revision.output_storage_id,
                    output_sha256=revision.output_sha256,
                    decision_manifest_sha256=revision.decision_manifest_sha256,
                    created_at=revision.created_at_utc,
                )
                session.add(revision_row)
                session.flush()
                session.add(_context_table(revision.id, revision.context))
                session.add_all(_region_table(revision.id, region) for region in region_rows)
                session.add_all(
                    _decision_table(revision.id, decision) for decision in decision_rows
                )
        except IntegrityError as error:
            raise StorageConflictError(
                "revision bundle violates an immutable constraint"
            ) from error

    def get_revision(self, revision_id: str) -> DisclosureRevision:
        with self._sessions() as session:
            revision = session.get(RevisionTable, revision_id)
            context = session.get(ContextTable, revision_id)
            if revision is None or context is None:
                raise KeyError(revision_id)
            return self._revision(revision, context)

    def transition_revision_status(
        self,
        revision_id: str,
        *,
        expected: RevisionStatus,
        target: RevisionStatus,
    ) -> DisclosureRevision:
        with self._sessions.begin() as session:
            revision = session.get(RevisionTable, revision_id)
            context = session.get(ContextTable, revision_id)
            if revision is None or context is None:
                raise KeyError(revision_id)
            if revision.status != expected.value:
                raise StorageConflictError("revision status changed concurrently")
            revision.status = target.value
            session.flush()
            return self._revision(revision, context)

    def complete_analysis(
        self,
        revision_id: str,
        *,
        status: RevisionStatus,
        regions: Iterable[DocumentRegion],
        decisions: Iterable[PolicyDecision],
        output_storage_id: str | None,
        output_sha256: str | None,
        decision_manifest_sha256: str,
    ) -> DisclosureRevision:
        region_rows = tuple(regions)
        decision_rows = tuple(decisions)
        known_region_ids = {region.id for region in region_rows}
        if any(decision.region_id not in known_region_ids for decision in decision_rows):
            raise StorageConflictError("every decision must reference a persisted region")
        if (output_storage_id is None) != (output_sha256 is None):
            raise StorageConflictError("output storage ID and checksum must be set together")
        try:
            with self._sessions.begin() as session:
                revision = session.get(RevisionTable, revision_id)
                context = session.get(ContextTable, revision_id)
                if revision is None or context is None:
                    raise KeyError(revision_id)
                if revision.status != RevisionStatus.ANALYZING.value:
                    raise StorageConflictError("only an analyzing revision can be completed")
                existing_region = session.scalar(
                    select(RegionTable.id)
                    .where(RegionTable.revision_id == revision_id)
                    .limit(1)
                )
                existing_decision = session.scalar(
                    select(DecisionTable.id)
                    .where(DecisionTable.revision_id == revision_id)
                    .limit(1)
                )
                if existing_region is not None or existing_decision is not None:
                    raise ImmutableRevisionError("analysis results are immutable once persisted")
                if any(
                    decision.policy_sha256 != revision.policy_sha256
                    or decision.policy_version != context.policy_version
                    for decision in decision_rows
                ):
                    raise StorageConflictError("decision policy binding differs from its revision")
                revision.status = status.value
                revision.output_storage_id = output_storage_id
                revision.output_sha256 = output_sha256
                revision.decision_manifest_sha256 = decision_manifest_sha256
                session.add_all(_region_table(revision_id, region) for region in region_rows)
                session.add_all(
                    _decision_table(revision_id, decision) for decision in decision_rows
                )
                session.flush()
                return self._revision(revision, context)
        except IntegrityError as error:
            raise StorageConflictError(
                "analysis result violates an immutable constraint"
            ) from error

    def list_revisions(self, task_id: str) -> tuple[DisclosureRevision, ...]:
        with self._sessions() as session:
            rows = session.execute(
                select(RevisionTable, ContextTable)
                .join(ContextTable, ContextTable.revision_id == RevisionTable.id)
                .where(RevisionTable.task_id == task_id)
                .order_by(RevisionTable.revision_number)
            ).all()
            return tuple(self._revision(revision, context) for revision, context in rows)

    def append_stage_event(
        self,
        revision_id: str,
        *,
        stage: str,
        status: str,
        occurred_at: datetime,
    ) -> RevisionStageEvent:
        try:
            with self._sessions.begin() as session:
                if session.get(RevisionTable, revision_id) is None:
                    raise KeyError(revision_id)
                sequence = (
                    session.scalar(
                        select(func.max(RevisionStageTable.stage_sequence)).where(
                            RevisionStageTable.revision_id == revision_id
                        )
                    )
                    or 0
                ) + 1
                row = RevisionStageTable(
                    revision_id=revision_id,
                    stage_sequence=sequence,
                    stage=stage,
                    status=status,
                    occurred_at=occurred_at.astimezone(UTC),
                )
                session.add(row)
                session.flush()
                return RevisionStageEvent(
                    revision_id,
                    sequence,
                    stage,
                    status,
                    _as_utc(row.occurred_at),
                )
        except IntegrityError as error:
            raise StorageConflictError("revision stage sequence changed concurrently") from error

    def list_stage_events(self, revision_id: str) -> tuple[RevisionStageEvent, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(RevisionStageTable)
                .where(RevisionStageTable.revision_id == revision_id)
                .order_by(RevisionStageTable.stage_sequence)
            ).all()
            return tuple(
                RevisionStageEvent(
                    row.revision_id,
                    row.stage_sequence,
                    row.stage,
                    row.status,
                    _as_utc(row.occurred_at),
                )
                for row in rows
            )

    def add_artifact(self, artifact: StoredArtifactRecord) -> None:
        try:
            with self._sessions.begin() as session:
                if session.get(TaskTable, artifact.task_id) is None:
                    raise KeyError(artifact.task_id)
                if artifact.revision_id is not None:
                    revision = session.get(RevisionTable, artifact.revision_id)
                    if revision is None or revision.task_id != artifact.task_id:
                        raise StorageConflictError("artifact revision does not belong to its task")
                session.add(
                    ArtifactTable(
                        task_id=artifact.task_id,
                        revision_id=artifact.revision_id,
                        namespace=artifact.namespace,
                        storage_id=artifact.storage_id,
                    )
                )
        except IntegrityError as error:
            raise StorageConflictError("artifact storage identity already exists") from error

    def list_artifacts(self, task_id: str) -> tuple[StoredArtifactRecord, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ArtifactTable).where(ArtifactTable.task_id == task_id)
            ).all()
            return tuple(
                StoredArtifactRecord(
                    task_id=row.task_id,
                    revision_id=row.revision_id,
                    namespace=row.namespace,
                    storage_id=row.storage_id,
                )
                for row in rows
            )

    def delete_task_with_tombstone(self, tombstone: DeletionTombstone) -> None:
        try:
            with self._sessions.begin() as session:
                task = session.get(TaskTable, tombstone.task_id)
                if task is None:
                    raise KeyError(tombstone.task_id)
                revision_count = session.scalar(
                    select(func.count(RevisionTable.id)).where(
                        RevisionTable.task_id == tombstone.task_id
                    )
                )
                if (
                    task.source_sha256 != tombstone.source_sha256
                    or revision_count != tombstone.revision_count
                ):
                    raise StorageConflictError("deletion tombstone does not match the task")
                session.add(
                    DeletionTombstoneTable(
                        id=tombstone.id,
                        task_id=tombstone.task_id,
                        revision_count=tombstone.revision_count,
                        source_sha256=tombstone.source_sha256,
                        deletion_fingerprint=tombstone.deletion_fingerprint,
                        actor_hmac=tombstone.actor_hmac,
                        policy_version=tombstone.policy_version,
                        deleted_at=tombstone.deleted_at.astimezone(UTC),
                    )
                )
                session.execute(
                    delete(CopilotCheckpointTable).where(
                        CopilotCheckpointTable.task_id == tombstone.task_id
                    )
                )
                session.delete(task)
        except IntegrityError as error:
            raise StorageConflictError("deletion tombstone identity already exists") from error

    def get_tombstone(self, task_id: str) -> DeletionTombstone:
        with self._sessions() as session:
            row = session.scalar(
                select(DeletionTombstoneTable).where(
                    DeletionTombstoneTable.task_id == task_id
                )
            )
            if row is None:
                raise KeyError(task_id)
            return DeletionTombstone(
                id=row.id,
                task_id=row.task_id,
                revision_count=row.revision_count,
                source_sha256=row.source_sha256,
                deletion_fingerprint=row.deletion_fingerprint,
                actor_hmac=row.actor_hmac,
                policy_version=row.policy_version,
                deleted_at=_as_utc(row.deleted_at),
            )

    def replace_context(self, revision_id: str, context: DisclosureContext) -> None:
        del context
        with self._sessions() as session:
            if session.get(RevisionTable, revision_id) is None:
                raise KeyError(revision_id)
        raise ImmutableRevisionError("a context change must create a new revision")

    def list_regions(self, revision_id: str) -> tuple[DocumentRegion, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(RegionTable)
                .where(RegionTable.revision_id == revision_id)
                .order_by(RegionTable.region_order, RegionTable.id)
            ).all()
            return tuple(
                DocumentRegion(
                    id=row.region_id,
                    file_kind=FileKind(row.file_kind),
                    location=row.location,
                    order=row.region_order,
                    text=row.text,
                    category=ContentCategory(row.category),
                    owner_id=row.owner_id,
                )
                for row in rows
            )

    def list_decisions(self, revision_id: str) -> tuple[PolicyDecision, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(DecisionTable)
                .where(DecisionTable.revision_id == revision_id)
                .order_by(DecisionTable.id)
            ).all()
            return tuple(self._decision(row) for row in rows)

    def add_decisions(
        self,
        revision_id: str,
        decisions: Iterable[PolicyDecision],
    ) -> None:
        pending = tuple(decisions)
        try:
            with self._sessions.begin() as session:
                revision = session.get(RevisionTable, revision_id)
                if revision is None:
                    raise KeyError(revision_id)
                existing = session.scalar(
                    select(DecisionTable.id)
                    .where(DecisionTable.revision_id == revision_id)
                    .limit(1)
                )
                if existing is not None:
                    raise ImmutableRevisionError("revision decisions are append-only")
                for decision in pending:
                    region_exists = session.scalar(
                        select(RegionTable.id)
                        .where(
                            RegionTable.revision_id == revision_id,
                            RegionTable.region_id == decision.region_id,
                        )
                        .limit(1)
                    )
                    if region_exists is None:
                        raise StorageConflictError(
                            "every decision must reference a persisted region"
                        )
                    if (
                        decision.policy_sha256 != revision.policy_sha256
                        or decision.policy_version
                        != session.get(ContextTable, revision_id).policy_version  # type: ignore[union-attr]
                    ):
                        raise StorageConflictError(
                            "decision policy binding differs from its revision"
                        )
                    session.add(_decision_table(revision_id, decision))
        except IntegrityError as error:
            raise StorageConflictError("decision rows violate an immutable constraint") from error

    def append_audit_event(self, event: AuditEvent) -> None:
        try:
            with self._sessions.begin() as session:
                previous = session.scalars(
                    select(AuditEventTable).order_by(AuditEventTable.sequence.desc()).limit(1)
                ).first()
                expected_previous = previous.event_hash if previous is not None else "0" * 64
                if event.previous_hash != expected_previous:
                    raise StorageConflictError("audit event does not extend the stored hash chain")
                session.add(
                    AuditEventTable(
                        event_id=event.event_id,
                        event_type=event.event_type.value,
                        occurred_at=event.occurred_at.astimezone(UTC),
                        actor=event.actor,
                        task_id=event.task_id,
                        revision_id=event.revision_id,
                        policy_sha256=event.policy_sha256,
                        payload=payload_as_dict(event.payload),
                        previous_hash=event.previous_hash,
                        event_hash=event.event_hash,
                    )
                )
        except IntegrityError as error:
            raise StorageConflictError("audit event identity or hash already exists") from error

    def list_audit_events(self, task_id: str | None = None) -> tuple[AuditEvent, ...]:
        with self._sessions() as session:
            statement = select(AuditEventTable).order_by(AuditEventTable.sequence)
            if task_id is not None:
                statement = statement.where(AuditEventTable.task_id == task_id)
            rows = session.scalars(statement).all()
            events: list[AuditEvent] = []
            for row in rows:
                event_type, payload = sanitize_payload(AuditEventType(row.event_type), row.payload)
                events.append(
                    AuditEvent(
                        event_id=row.event_id,
                        event_type=event_type,
                        occurred_at=_as_utc(row.occurred_at),
                        actor=row.actor,
                        task_id=row.task_id,
                        revision_id=row.revision_id,
                        policy_sha256=row.policy_sha256,
                        payload=payload,
                        previous_hash=row.previous_hash,
                        event_hash=row.event_hash,
                    )
                )
            return tuple(events)

    def add_pseudonym_records(
        self,
        task_id: str,
        records: Iterable[PseudonymRecord],
    ) -> None:
        try:
            with self._sessions.begin() as session:
                if session.get(TaskTable, task_id) is None:
                    raise KeyError(task_id)
                session.add_all(
                    PseudonymMappingTable(
                        task_id=task_id,
                        category=record.category.value,
                        value_hmac=record.value_hmac,
                        alias=record.alias,
                        first_seen_order=record.first_seen_order,
                    )
                    for record in records
                )
        except IntegrityError as error:
            raise StorageConflictError("pseudonym mappings are append-only") from error

    def list_pseudonym_records(self, task_id: str) -> tuple[PseudonymRecord, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(PseudonymMappingTable)
                .where(PseudonymMappingTable.task_id == task_id)
                .order_by(
                    PseudonymMappingTable.category,
                    PseudonymMappingTable.first_seen_order,
                )
            ).all()
            return tuple(
                PseudonymRecord(
                    category=PseudonymCategory(row.category),
                    value_hmac=row.value_hmac,
                    alias=row.alias,
                    first_seen_order=row.first_seen_order,
                )
                for row in rows
            )

    def add_approval(self, approval: ApprovalRecord) -> None:
        try:
            with self._sessions.begin() as session:
                revision = session.get(RevisionTable, approval.revision_id)
                context = session.get(ContextTable, approval.revision_id)
                if revision is None or context is None:
                    raise StorageConflictError("approval revision does not exist")
                if (
                    revision.requester_id != approval.requester_id
                    or revision.source_sha256 != approval.source_sha256
                    or context.context_sha256 != approval.context_sha256
                    or revision.policy_sha256 != approval.policy_sha256
                    or revision.output_sha256 != approval.output_sha256
                    or revision.decision_manifest_sha256
                    != approval.decision_manifest_sha256
                ):
                    raise StorageConflictError("approval does not match its immutable revision")
                session.add(
                    ApprovalTable(
                        id=approval.id,
                        revision_id=approval.revision_id,
                        requester_id=approval.requester_id,
                        reviewer_id=approval.reviewer_id,
                        status=approval.status.value,
                        binding_sha256=approval.binding_sha256,
                        source_sha256=approval.source_sha256,
                        context_sha256=approval.context_sha256,
                        policy_sha256=approval.policy_sha256,
                        output_sha256=approval.output_sha256,
                        decision_manifest_sha256=approval.decision_manifest_sha256,
                        expires_at=approval.expires_at.astimezone(UTC),
                        consumed=approval.consumed,
                        reason_code=approval.reason_code,
                        created_at=approval.created_at.astimezone(UTC),
                        reviewed_at=(
                            approval.reviewed_at.astimezone(UTC)
                            if approval.reviewed_at is not None
                            else None
                        ),
                    )
                )
        except IntegrityError as error:
            raise StorageConflictError("approval ID or revision already exists") from error

    def get_approval(self, approval_id: str) -> ApprovalRecord:
        with self._sessions() as session:
            row = session.get(ApprovalTable, approval_id)
            if row is None:
                raise KeyError(approval_id)
            return self._approval(row)

    def get_approval_for_revision(self, revision_id: str) -> ApprovalRecord:
        with self._sessions() as session:
            row = session.scalar(
                select(ApprovalTable).where(ApprovalTable.revision_id == revision_id)
            )
            if row is None:
                raise KeyError(revision_id)
            return self._approval(row)

    def resolve_approval(
        self,
        approval_id: str,
        *,
        reviewer_id: str,
        status: ApprovalStatus,
        reviewed_at: datetime,
        reason_code: str | None,
        expected_revision_status: RevisionStatus,
        target_revision_status: RevisionStatus,
    ) -> ApprovalRecord:
        with self._sessions.begin() as session:
            approval = session.get(ApprovalTable, approval_id)
            if approval is None:
                raise StorageConflictError("approval does not exist")
            revision = session.get(RevisionTable, approval.revision_id)
            if revision is None:
                raise StorageConflictError("approval revision does not exist")
            if (
                approval.status != ApprovalStatus.PENDING.value
                or approval.consumed
                or revision.status != expected_revision_status.value
            ):
                raise StorageConflictError("approval or revision changed concurrently")
            approval.status = status.value
            approval.reviewer_id = reviewer_id
            approval.reviewed_at = reviewed_at.astimezone(UTC)
            approval.reason_code = reason_code
            revision.status = target_revision_status.value
            session.flush()
            return self._approval(approval)

    def consume_approval(self, approval_id: str) -> ApprovalRecord:
        with self._sessions.begin() as session:
            approval = session.get(ApprovalTable, approval_id)
            if approval is None:
                raise StorageConflictError("approval does not exist")
            revision = session.get(RevisionTable, approval.revision_id)
            if (
                approval.status != ApprovalStatus.APPROVED.value
                or approval.consumed
                or revision is None
                or revision.status != RevisionStatus.APPROVED.value
            ):
                raise StorageConflictError("approval is not consumable")
            approval.consumed = True
            session.flush()
            return self._approval(approval)

    @staticmethod
    def _revision(revision: RevisionTable, context: ContextTable) -> DisclosureRevision:
        return DisclosureRevision(
            id=revision.id,
            task_id=revision.task_id,
            revision_number=revision.revision_number,
            requester_id=revision.requester_id,
            context=DisclosureContext(
                recipient=RecipientProfile(context.recipient),
                organization=context.organization,
                recipient_id=context.recipient_id,
                purpose=Purpose(context.purpose),
                channel=Channel(context.channel),
                classification=Classification(context.classification),
                policy_version=context.policy_version,
            ),
            status=RevisionStatus(revision.status),
            source_sha256=revision.source_sha256,
            policy_sha256=revision.policy_sha256,
            output_storage_id=revision.output_storage_id,
            output_sha256=revision.output_sha256,
            decision_manifest_sha256=revision.decision_manifest_sha256,
            created_at=_as_utc(revision.created_at),
        )

    @staticmethod
    def _decision(row: DecisionTable) -> PolicyDecision:
        return PolicyDecision(
            region_id=row.region_id,
            category=ContentCategory(row.category),
            action=Action(row.action),
            rule_ids=tuple(row.rule_ids),
            evidence_ids=tuple(row.evidence_ids),
            reason_code=row.reason_code,
            reason=row.reason,
            policy_version=row.policy_version,
            policy_sha256=row.policy_sha256,
            origin=DecisionOrigin(row.origin),
            transform=row.transform,
        )

    @staticmethod
    def _approval(row: ApprovalTable) -> ApprovalRecord:
        return ApprovalRecord(
            id=row.id,
            revision_id=row.revision_id,
            requester_id=row.requester_id,
            reviewer_id=row.reviewer_id,
            status=ApprovalStatus(row.status),
            binding_sha256=row.binding_sha256,
            source_sha256=row.source_sha256,
            context_sha256=row.context_sha256,
            policy_sha256=row.policy_sha256,
            output_sha256=row.output_sha256,
            decision_manifest_sha256=row.decision_manifest_sha256,
            expires_at=_as_utc(row.expires_at),
            consumed=row.consumed,
            reason_code=row.reason_code,
            created_at=_as_utc(row.created_at),
            reviewed_at=_as_utc(row.reviewed_at) if row.reviewed_at is not None else None,
        )
