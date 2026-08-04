from __future__ import annotations

import itertools
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI

from policyseal.agent.copilot_graph import ReviewCopilot
from policyseal.agent.retrieval import HybridEvidenceRetriever
from policyseal.agent.tools import ReviewTools
from policyseal.api.app import create_app
from policyseal.api.dependencies import AppServices
from policyseal.application.analysis import AnalysisService
from policyseal.application.approvals import ApprovalService
from policyseal.application.deletion import DeletionService
from policyseal.application.exports import ExportService
from policyseal.application.simulations import SimulationService
from policyseal.documents.base import DocumentAdapter
from policyseal.documents.docx import DocxAdapter
from policyseal.documents.pdf import PdfAdapter
from policyseal.documents.preflight import PreflightService
from policyseal.documents.residual import ResidualScanner
from policyseal.documents.xlsx import XlsxAdapter
from policyseal.domain.enums import FileKind
from policyseal.policy.loader import load_policy_pack
from policyseal.security.fingerprints import KeyedFingerprinter
from policyseal.security.key_store import MasterKeyStore
from policyseal.security.pseudonyms import Pseudonymizer
from policyseal.storage.database import Database
from policyseal.storage.file_store import ControlledFileStore
from policyseal.storage.repositories import PolicySealRepository


@pytest.fixture
def api_services(tmp_path: Path) -> AppServices:
    database = Database.from_url(f"sqlite:///{tmp_path / 'api.db'}")
    database.create_schema()
    repository = PolicySealRepository(database.session_factory)
    file_store = ControlledFileStore(tmp_path / "files")
    key_store = MasterKeyStore(tmp_path / "secrets" / "master.key")
    fingerprinter = KeyedFingerprinter(key_store)
    residual = ResidualScanner(key_store)
    preflight = PreflightService()
    policy_pack = load_policy_pack(Path("policies/v1"))
    adapters: dict[FileKind, DocumentAdapter] = {
        FileKind.XLSX: XlsxAdapter(preflight, residual),
        FileKind.DOCX: DocxAdapter(preflight, residual, Pseudonymizer(key_store)),
        FileKind.PDF: PdfAdapter(preflight, residual),
    }
    ids = itertools.count(1)

    def clock() -> datetime:
        return datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

    analysis = AnalysisService(
        repository,
        file_store,
        policy_pack,
        adapters,
        fingerprinter,
        clock=clock,
        id_factory=lambda prefix: f"{prefix}-{next(ids):04d}",
    )
    approvals = ApprovalService(
        repository,
        clock=clock,
        id_factory=lambda: "approval-api-0001",
    )
    simulations = SimulationService(analysis)
    copilot = ReviewCopilot(
        ReviewTools(
            repository,
            simulations,
            HybridEvidenceRetriever.from_policy_pack(policy_pack),
        ),
        audit_chain=analysis.audit_chain,
        policy_sha256=policy_pack.sha256,
    )
    return AppServices(
        database=database,
        repository=repository,
        analysis=analysis,
        simulations=simulations,
        approvals=approvals,
        exports=ExportService(
            repository,
            file_store,
            approvals,
            template_root=Path("templates"),
        ),
        deletion=DeletionService(
            repository,
            file_store,
            fingerprinter,
            policy_pack,
            analysis.audit_chain,
            clock=clock,
            delete_task_state=copilot.delete_task,
        ),
        copilot=copilot,
    )


@pytest.fixture
def api_app(api_services: AppServices) -> FastAPI:
    return create_app(api_services)
