from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("llama_index.core")
from llama_index.core.schema import Document as LIDocument

from cortex.sdk.langchain_adapter import CortexRetriever
from cortex.sdk.llamaindex_adapter import CortexReader
from tests.sdk.conftest import make_query_result


def test_cortex_reader_produces_llamaindex_documents(fake_node: MagicMock):
    fake_node.query.return_value = [make_query_result(), make_query_result()]
    lc_retriever = CortexRetriever(node=fake_node)
    reader = CortexReader.from_retriever(lc_retriever)

    docs = reader.load_data(query="phishing paddock")

    assert len(docs) == 2
    for d in docs:
        assert isinstance(d, LIDocument)
        assert d.text
        assert "article_id" in d.metadata
        assert "trust" in d.metadata
        assert "org" in d.metadata
        assert "type" in d.metadata


def test_cortex_reader_uses_explicit_node_when_no_retriever(fake_node: MagicMock):
    fake_node.query.return_value = []
    reader = CortexReader(node=fake_node, top_k=4, min_trust=0.5,
                          topics={"soc"}, scopes={"PUBLIC"})
    reader.load_data(query="x")
    kwargs = fake_node.query.call_args.kwargs
    assert kwargs["top_k"] == 4
    assert kwargs["min_trust"] == 0.5


def test_vector_store_index_from_cortex_reader(fake_node: MagicMock, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy")
    monkeypatch.setenv("IS_TESTING", "1")
    pytest.importorskip("llama_index.core")
    from llama_index.core import VectorStoreIndex

    fake_node.query.return_value = [make_query_result() for _ in range(3)]
    reader = CortexReader.from_retriever(CortexRetriever(node=fake_node))

    index = VectorStoreIndex.from_documents(reader.load_data(query="phishing"))
    retriever = index.as_retriever(similarity_top_k=2)
    nodes = retriever.retrieve("phishing")
    assert len(nodes) >= 1
    for n in nodes:
        assert n.node.text
