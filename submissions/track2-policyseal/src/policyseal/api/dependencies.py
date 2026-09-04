from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import Request

from policyseal.agent.classification_graph import SemanticClassificationGraph
from policyseal.agent.copilot_graph import ReviewCopilot
from policyseal.agent.embeddings import FastEmbedTextEncoder
from policyseal.agent.llm_client import LocalVllmClient
from policyseal.agent.retrieval import HybridEvidenceRetriever
from policyseal.agent.tools import ReviewTools
from policyseal.application.analysis import AnalysisService
from policyseal.application.approvals import ApprovalService
from policyseal.application.deletion import DeletionService
from policyseal.application.exports import ExportService
from policyseal.application.simulations import SimulationService
from policyseal.config import Settings
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


@dataclass(frozen=True, slots=True)
class AppServices:
    database: Database
    repository: PolicySealRepository
    analysis: AnalysisService
    simulations: SimulationService
    approvals: ApprovalService
    exports: ExportService
    deletion: DeletionService
    copilot: ReviewCopilot | None = None


def build_services(settings: Settings) -> AppServices:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    database = Database.from_url(settings.database_url)
    database.create_schema()
    repository = PolicySealRepository(database.session_factory)
    file_store = ControlledFileStore(settings.storage_dir)
    key_store = MasterKeyStore(settings.master_key_path)
    fingerprinter = KeyedFingerprinter(key_store)
    residual = ResidualScanner(key_store)
    preflight = PreflightService()
    policy_pack = load_policy_pack(settings.policy_dir / "v1")
    adapters: dict[FileKind, DocumentAdapter] = {
        FileKind.XLSX: XlsxAdapter(preflight, residual),
        FileKind.DOCX: DocxAdapter(preflight, residual, Pseudonymizer(key_store)),
        FileKind.PDF: PdfAdapter(preflight, residual),
    }
    analysis = AnalysisService(
        repository,
        file_store,
        policy_pack,
        adapters,
        fingerprinter,
        semantic_classifier=SemanticClassificationGraph(
            LocalVllmClient(
                settings.llm_base_url,
                settings.llm_model,
                timeout_seconds=settings.llm_timeout_seconds,
                max_tokens=settings.llm_max_tokens,
            ),
            min_confidence=settings.semantic_min_confidence,
            batch_size=settings.semantic_batch_size,
            consistency_passes=settings.semantic_consistency_passes,
        ),
    )
    approvals = ApprovalService(repository)
    exports = ExportService(
        repository,
        file_store,
        approvals,
        template_root=Path("templates"),
    )
    retriever = HybridEvidenceRetriever.from_policy_pack(
        policy_pack,
        encoder=FastEmbedTextEncoder(
            source_model=settings.embedding_model,
            cache_dir=settings.embedding_cache_dir,
            local_files_only=settings.embedding_local_files_only,
        ),
    )
    simulations = SimulationService(analysis)
    copilot = ReviewCopilot(
        ReviewTools(repository, simulations, retriever),
        audit_chain=analysis.audit_chain,
        policy_sha256=policy_pack.sha256,
    )
    return AppServices(
        database=database,
        repository=repository,
        analysis=analysis,
        simulations=simulations,
        approvals=approvals,
        exports=exports,
        deletion=DeletionService(
            repository,
            file_store,
            fingerprinter,
            policy_pack,
            analysis.audit_chain,
            delete_task_state=copilot.delete_task,
        ),
        copilot=copilot,
    )


def get_services(request: Request) -> AppServices:
    services = getattr(request.app.state, "services", None)
    if services is None:
        services = build_services(request.app.state.settings)
        request.app.state.services = services
    return services
