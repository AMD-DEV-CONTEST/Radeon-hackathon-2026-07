from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.cases import create_app
from app.rag.corpus import LegalCorpusStore, load_manifest
from app.rag.embeddings import HashEmbeddingProvider
from app.rag.index import LegalVectorIndex


def test_api_exposes_progress_failure_and_resume_state(tmp_path, demo_case, monkeypatch):
    workspace, case_id = demo_case
    documents, chunks = load_manifest("data/laws/source_manifest.json")
    corpus_path = tmp_path / "api-legal.sqlite3"
    qdrant_path = tmp_path / "api-qdrant"
    LegalCorpusStore(corpus_path).replace(documents, chunks)
    index = LegalVectorIndex(
        qdrant_path, HashEmbeddingProvider(dimension=128)
    )
    index.rebuild(chunks)
    index.close()
    monkeypatch.setenv("HASH_EMBEDDING_DIMENSION", "128")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("RERANKER_PROVIDER", "heuristic")

    app = create_app(
        case_root=workspace.root,
        checkpoint_path=tmp_path / "api-checkpoints.sqlite3",
        legal_corpus_path=corpus_path,
        qdrant_path=qdrant_path,
    )
    client = TestClient(app)
    interrupted = client.post(
        f"/cases/{case_id}/workflow",
        params={
            "thread_id": "THREAD-API-RECOVERY",
            "interrupt_after": "evidence_ready",
        },
    )
    assert interrupted.status_code == 200
    status = client.get("/workflows/THREAD-API-RECOVERY")
    assert status.status_code == 200
    assert status.json()["recoverable"] is True
    assert status.json()["current_node"] == "evidence_ready"

    resumed = client.post("/workflows/THREAD-API-RECOVERY/resume")
    assert resumed.status_code == 200
    payload = resumed.json()
    assert payload["current_node"] == "human_approval"
    assert payload["approval_status"] == "pending"
    assert payload["document_status"] == "draft"
