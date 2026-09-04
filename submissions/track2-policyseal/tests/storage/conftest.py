from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from policyseal.domain.enums import (
    Channel,
    Classification,
    FileKind,
    Purpose,
    RecipientProfile,
    RevisionStatus,
)
from policyseal.domain.models import (
    DisclosureContext,
    DisclosureRevision,
    DisclosureTask,
    SourceFingerprint,
)
from policyseal.storage.database import Database
from policyseal.storage.repositories import PolicySealRepository


@pytest.fixture
def database(tmp_path: Path) -> Database:
    database = Database.from_url(f"sqlite:///{tmp_path / 'policyseal.db'}")
    database.create_schema()
    return database


@pytest.fixture
def repository(database: Database) -> PolicySealRepository:
    return PolicySealRepository(database.session_factory)


@pytest.fixture
def task() -> DisclosureTask:
    return DisclosureTask(
        id="task-001",
        requester_id="requester-001",
        file_kind=FileKind.XLSX,
        source=SourceFingerprint.from_bytes(b"synthetic source"),
        source_storage_id="0123456789abcdef0123456789abcdef.xlsx",
        created_at=datetime(2026, 8, 2, tzinfo=UTC),
    )


@pytest.fixture
def context() -> DisclosureContext:
    return DisclosureContext(
        recipient=RecipientProfile.EXTERNAL_FINANCIAL_AUDITOR,
        organization="audit-partner.example",
        recipient_id="auditor@audit-partner.example",
        purpose=Purpose.ANNUAL_FINANCIAL_AUDIT,
        channel=Channel.SECURE_FILE_EXCHANGE,
        classification=Classification.CONFIDENTIAL,
        policy_version="1.0.0",
    )


@pytest.fixture
def revision(task: DisclosureTask, context: DisclosureContext) -> DisclosureRevision:
    return DisclosureRevision(
        id="revision-001",
        task_id=task.id,
        revision_number=1,
        requester_id=task.requester_id,
        context=context,
        status=RevisionStatus.DRAFT,
        source_sha256=task.source.sha256,
        policy_sha256="a" * 64,
        created_at=datetime(2026, 8, 2, 0, 1, tzinfo=UTC),
    )
