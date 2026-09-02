from pathlib import Path

import pytest

from app.config import Settings
from app.rag.indexer import ProjectIndex
from app.rag.manifest import ContentChunk, ParsedDocument
from app.rag.qa_service import NO_EVIDENCE_MSG, QAService
from app.rag.retriever import Retriever


def _settings(tmp_path: Path) -> Settings:
    return Settings(vector_db_root=tmp_path / "vectors")


def _document() -> ParsedDocument:
    return ParsedDocument(
        relative_path="source/plan.md", format="md",
        chunks=[ContentChunk(content="项目代号是云翼，后端使用 FastAPI。", relative_path="source/plan.md", chunk_index=0)],
    )


def test_index_rejects_path_traversal_project_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="project_id"):
        ProjectIndex("../../outside", _settings(tmp_path), mock_embed_dim=16)


def test_unrelated_question_is_refused(tmp_path: Path) -> None:
    index = ProjectIndex("demo-project", _settings(tmp_path), mock_embed_dim=32)
    index.index([_document()])
    result = QAService(Retriever(index)).ask("项目办公室地址在哪里？")
    assert result.is_refused is True
    assert result.answer == NO_EVIDENCE_MSG


def test_unchanged_document_does_not_reembed(tmp_path: Path) -> None:
    class CountingEmbedder:
        dim = 4
        def __init__(self): self.calls = 0
        def embed(self, texts):
            import numpy as np
            self.calls += 1
            return np.ones((len(texts), self.dim), dtype=np.float32)

    embedder = CountingEmbedder()
    index = ProjectIndex("demo-project", _settings(tmp_path), embedder=embedder)
    index.index([_document()])
    index.index([_document()])
    assert embedder.calls == 1
