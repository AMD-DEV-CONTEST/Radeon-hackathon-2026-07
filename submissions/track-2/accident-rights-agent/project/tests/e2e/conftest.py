from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from app.demo.golden_case import seed_golden_case
from app.rag.corpus import LegalCorpusStore, load_manifest
from app.rag.embeddings import HashEmbeddingProvider
from app.rag.index import LegalVectorIndex
from app.services.case_service import CaseService
from app.services.report_service import ReportService
from app.services.workflow_service import WorkflowService


@dataclass
class E2ERuntime:
    root: Path
    cases: CaseService
    workflows: WorkflowService
    reports: ReportService
    case_id: str


def create_e2e_runtime(root: Path) -> E2ERuntime:
    cases = CaseService(root / "cases")
    case_id = seed_golden_case(cases.workspace)
    documents, chunks = load_manifest("data/laws/source_manifest.json")
    legal_corpus_path = root / "legal.sqlite3"
    LegalCorpusStore(legal_corpus_path).replace(documents, chunks)
    index = LegalVectorIndex(root / "qdrant", HashEmbeddingProvider(dimension=384))
    index.rebuild(chunks)
    index.close()
    workflows = WorkflowService(
        cases,
        checkpoint_path=root / "checkpoints.sqlite3",
        legal_corpus_path=legal_corpus_path,
        qdrant_path=root / "qdrant",
    )
    return E2ERuntime(
        root=root,
        cases=cases,
        workflows=workflows,
        reports=ReportService(cases, root / "reports"),
        case_id=case_id,
    )


@pytest.fixture
def e2e_runtime(tmp_path) -> E2ERuntime:
    return create_e2e_runtime(tmp_path)
