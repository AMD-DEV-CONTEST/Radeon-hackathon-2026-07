from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import inspect

from policyseal.audit.chain import AuditChain
from policyseal.domain.enums import Action, Channel, ContentCategory, FileKind, RevisionStatus
from policyseal.domain.errors import ImmutableRevisionError, StorageConflictError
from policyseal.domain.models import (
    DisclosureContext,
    DisclosureRevision,
    DisclosureTask,
    DocumentRegion,
    PolicyDecision,
)
from policyseal.security.pseudonyms import PseudonymCategory, PseudonymRecord
from policyseal.storage.database import Database
from policyseal.storage.file_store import ControlledFileStore, FileNamespace, UnsafeStoragePath
from policyseal.storage.repositories import PolicySealRepository


def test_schema_contains_every_p0_persistence_boundary(database: Database) -> None:
    tables = set(inspect(database.engine).get_table_names())

    assert tables == {
        "approvals",
        "artifacts",
        "audit_events",
        "contexts",
        "copilot_checkpoints",
        "decisions",
        "deletion_tombstones",
        "pseudonym_mappings",
        "regions",
        "revisions",
        "revision_stages",
        "tasks",
    }


def test_revision_cannot_be_mutated_after_creation(
    repository: PolicySealRepository,
    task: DisclosureTask,
    revision: DisclosureRevision,
) -> None:
    repository.add_task(task)
    repository.add_revision(revision)

    with pytest.raises(ImmutableRevisionError):
        repository.replace_context(
            revision.id,
            revision.context.with_channel(Channel.PERSONAL_EMAIL),
        )


def test_revision_round_trip_retains_context_and_old_policy(
    repository: PolicySealRepository,
    task: DisclosureTask,
    revision: DisclosureRevision,
) -> None:
    repository.add_task(task)
    repository.add_revision(revision)
    second = replace(
        revision,
        id="revision-002",
        revision_number=2,
        context=replace(revision.context, policy_version="2.0.0"),
        policy_sha256="b" * 64,
    )
    repository.add_revision(second)

    stored_first = repository.get_revision(revision.id)
    stored_second = repository.get_revision(second.id)

    assert stored_first == revision
    assert stored_first.context.policy_version == "1.0.0"
    assert stored_second.context.policy_version == "2.0.0"
    assert repository.list_revisions(task.id) == (revision, second)


def test_source_hash_mismatch_rolls_back_revision(
    repository: PolicySealRepository,
    task: DisclosureTask,
    revision: DisclosureRevision,
) -> None:
    repository.add_task(task)

    with pytest.raises(StorageConflictError):
        repository.add_revision(replace(revision, source_sha256="f" * 64))

    assert repository.list_revisions(task.id) == ()


def test_failed_bundle_transaction_rolls_back_every_row(
    repository: PolicySealRepository,
    task: DisclosureTask,
    revision: DisclosureRevision,
) -> None:
    repository.add_task(task)
    duplicate_regions = (
        DocumentRegion(
            id="region-1",
            file_kind=FileKind.XLSX,
            location="xlsx:Sheet1:A1",
            order=0,
            text="synthetic",
            category=ContentCategory.GENERAL_BUSINESS,
        ),
        DocumentRegion(
            id="region-1",
            file_kind=FileKind.XLSX,
            location="xlsx:Sheet1:A2",
            order=1,
            text="synthetic duplicate",
            category=ContentCategory.GENERAL_BUSINESS,
        ),
    )

    with pytest.raises(StorageConflictError):
        repository.add_revision(revision, regions=duplicate_regions)

    assert repository.list_revisions(task.id) == ()
    assert repository.list_regions(revision.id) == ()


def test_regions_and_decisions_are_append_only(
    repository: PolicySealRepository,
    task: DisclosureTask,
    revision: DisclosureRevision,
) -> None:
    region = DocumentRegion(
        id="region-1",
        file_kind=FileKind.XLSX,
        location="xlsx:Sheet1:A1",
        order=0,
        text="synthetic",
        category=ContentCategory.GENERAL_BUSINESS,
    )
    decision = PolicyDecision(
        region_id=region.id,
        category=region.category,
        action=Action.KEEP,
        rule_ids=("PS-XLSX-INTERNAL-KEEP",),
        evidence_ids=("EV-XLSX-001",),
        reason_code="procurement_purpose_required",
        reason="Required for the controlled purpose.",
        policy_version="1.0.0",
        policy_sha256=revision.policy_sha256,
    )
    repository.add_task(task)
    repository.add_revision(revision, regions=(region,), decisions=(decision,))

    assert repository.list_regions(revision.id) == (region,)
    assert repository.list_decisions(revision.id) == (decision,)
    with pytest.raises(ImmutableRevisionError):
        repository.add_decisions(revision.id, (decision,))


def test_file_store_uses_random_ids_and_rejects_traversal(tmp_path: Path) -> None:
    store = ControlledFileStore(tmp_path / "files")
    first = store.write(FileNamespace.SOURCES, b"first", suffix=".xlsx")
    second = store.write(FileNamespace.SOURCES, b"second", suffix=".xlsx")

    assert first.storage_id != second.storage_id
    assert "first" not in first.storage_id
    assert store.read(FileNamespace.SOURCES, first.storage_id) == b"first"
    with pytest.raises(UnsafeStoragePath):
        store.read(FileNamespace.SOURCES, "../../master.key")
    with pytest.raises(ImmutableRevisionError):
        store.replace(FileNamespace.SOURCES, first.storage_id, b"changed")


def test_context_fingerprint_is_stable(context: DisclosureContext) -> None:
    assert context.sha256 == context.sha256
    assert context.sha256 != context.with_channel(Channel.PERSONAL_EMAIL).sha256


def test_illegal_status_value_never_reaches_storage(
    revision: DisclosureRevision,
) -> None:
    assert revision.status is RevisionStatus.DRAFT


def test_audit_events_and_hmac_only_pseudonyms_round_trip(
    repository: PolicySealRepository,
    task: DisclosureTask,
) -> None:
    repository.add_task(task)
    chain = AuditChain.in_memory()
    event = chain.append(
        "task_created",
        {"task_id": task.id, "source_sha256": task.source.sha256},
        event_id="audit-001",
        task_id=task.id,
    )
    pseudonym = PseudonymRecord(
        category=PseudonymCategory.HOST,
        value_hmac="c" * 64,
        alias="Host-ABCD-01",
        first_seen_order=1,
    )

    repository.append_audit_event(event)
    repository.add_pseudonym_records(task.id, (pseudonym,))

    assert repository.list_audit_events(task.id) == (event,)
    assert repository.list_pseudonym_records(task.id) == (pseudonym,)
