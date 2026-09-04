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
class UIRuntime:
    root: Path
    cases: CaseService
    workflows: WorkflowService
    reports: ReportService
    case_id: str
    thread_id: str
    state: dict
    updates: list[dict]


def build_ui_runtime(root: Path, *, run: bool = True) -> UIRuntime:
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
    updates = list(workflows.run_incremental(case_id)) if run else []
    state = updates[-1]["state"] if updates else {}
    thread_id = updates[-1]["thread_id"] if updates else ""
    return UIRuntime(
        root=root,
        cases=cases,
        workflows=workflows,
        reports=ReportService(cases, root / "reports"),
        case_id=case_id,
        thread_id=thread_id,
        state=state,
        updates=updates,
    )


@pytest.fixture(scope="session")
def golden_ui_runtime(tmp_path_factory) -> UIRuntime:
    return build_ui_runtime(tmp_path_factory.mktemp("golden-ui"))
