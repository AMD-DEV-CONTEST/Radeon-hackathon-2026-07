from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from policyseal.application.analysis import AnalysisService
from policyseal.application.approvals import ApprovalService
from policyseal.application.exports import ExportService
from policyseal.application.simulations import SimulationService
from policyseal.documents.docx import DocxAdapter
from policyseal.documents.pdf import PdfAdapter
from policyseal.documents.preflight import PreflightService
from policyseal.documents.residual import ResidualScanner
from policyseal.documents.xlsx import XlsxAdapter
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
from policyseal.policy.loader import load_policy_pack
from policyseal.security.fingerprints import KeyedFingerprinter
from policyseal.security.key_store import MasterKeyStore
from policyseal.security.pseudonyms import Pseudonymizer
from policyseal.storage.database import Database
from policyseal.storage.file_store import ControlledFileStore
from policyseal.storage.repositories import PolicySealRepository


@dataclass(frozen=True)
class Services:
    analysis: AnalysisService
    approvals: ApprovalService
    exports: ExportService
    simulations: SimulationService
    repository: PolicySealRepository
    file_store: ControlledFileStore
    fingerprinter: KeyedFingerprinter


@pytest.fixture
def repository(tmp_path: Path) -> PolicySealRepository:
    database = Database.from_url(f"sqlite:///{tmp_path / 'approvals.db'}")
    database.create_schema()
    return PolicySealRepository(database.session_factory)


@pytest.fixture
def pending_revision(repository: PolicySealRepository) -> DisclosureRevision:
    source = SourceFingerprint.from_bytes(b"synthetic approval source")
    task = DisclosureTask(
        id="task-approval",
        requester_id="requester-1",
        file_kind=FileKind.PDF,
        source=source,
        source_storage_id="abcdefabcdefabcdefabcdefabcdefab.pdf",
        created_at=datetime(2026, 8, 2, tzinfo=UTC),
    )
    context = DisclosureContext(
        recipient=RecipientProfile.CANDIDATE_SUPPLIER,
        organization="candidate-supplier.example",
        recipient_id="contracts@candidate-supplier.example",
        purpose=Purpose.CONTRACT_TERMS_PREVIEW,
        channel=Channel.CORPORATE_EMAIL,
        classification=Classification.CONFIDENTIAL,
        policy_version="1.0.0",
    )
    revision = DisclosureRevision(
        id="revision-approval",
        task_id=task.id,
        revision_number=1,
        requester_id=task.requester_id,
        context=context,
        status=RevisionStatus.AWAITING_APPROVAL,
        source_sha256=source.sha256,
        policy_sha256="a" * 64,
        output_storage_id="11111111111111111111111111111111.docx",
        output_sha256="b" * 64,
        decision_manifest_sha256="c" * 64,
        created_at=datetime(2026, 8, 2, 0, 1, tzinfo=UTC),
    )
    repository.add_task(task)
    repository.add_revision(revision)
    return revision


@pytest.fixture
def blocked_revision(repository: PolicySealRepository) -> DisclosureRevision:
    source = SourceFingerprint.from_bytes(b"synthetic blocked source")
    task = DisclosureTask(
        id="task-blocked",
        requester_id="requester-2",
        file_kind=FileKind.PDF,
        source=source,
        source_storage_id="22222222222222222222222222222222.pdf",
        created_at=datetime(2026, 8, 2, tzinfo=UTC),
    )
    context = DisclosureContext.candidate_supplier_corporate_email()
    revision = DisclosureRevision(
        id="revision-blocked",
        task_id=task.id,
        revision_number=1,
        requester_id=task.requester_id,
        context=context,
        status=RevisionStatus.BLOCKED,
        source_sha256=source.sha256,
        policy_sha256="a" * 64,
        created_at=datetime(2026, 8, 2, 0, 1, tzinfo=UTC),
    )
    repository.add_task(task)
    repository.add_revision(revision)
    return revision


@pytest.fixture
def approval_service(repository: PolicySealRepository) -> ApprovalService:
    return ApprovalService(
        repository,
        clock=lambda: datetime(2026, 8, 2, 1, 0, tzinfo=UTC),
        id_factory=lambda: "approval-001",
    )


@pytest.fixture
def services(tmp_path: Path) -> Services:
    database = Database.from_url(f"sqlite:///{tmp_path / 'app.db'}")
    database.create_schema()
    app_repository = PolicySealRepository(database.session_factory)
    file_store = ControlledFileStore(tmp_path / "files")
    key_store = MasterKeyStore(tmp_path / "secrets" / "master.key")
    fingerprinter = KeyedFingerprinter(key_store)
    residual = ResidualScanner(key_store)
    preflight = PreflightService()
    policy_pack = load_policy_pack(Path("policies/v1"))
    adapters = {
        FileKind.XLSX: XlsxAdapter(preflight, residual),
        FileKind.DOCX: DocxAdapter(preflight, residual, Pseudonymizer(key_store)),
        FileKind.PDF: PdfAdapter(preflight, residual),
    }
    ids = itertools.count(1)

    def clock() -> datetime:
        return datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

    analysis = AnalysisService(
        app_repository,
        file_store,
        policy_pack,
        adapters,
        fingerprinter,
        clock=clock,
        id_factory=lambda prefix: f"{prefix}-{next(ids):04d}",
    )
    approvals = ApprovalService(
        app_repository,
        clock=clock,
        id_factory=lambda: "approval-analysis-001",
    )
    exports = ExportService(
        app_repository,
        file_store,
        approvals,
        template_root=Path("templates"),
    )
    return Services(
        analysis,
        approvals,
        exports,
        SimulationService(analysis),
        app_repository,
        file_store,
        fingerprinter,
    )
