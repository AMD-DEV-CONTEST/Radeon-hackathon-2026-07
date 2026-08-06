from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("langchain_core.documents")
pytest.importorskip("langchain_core.retrievers")

from langchain_core.documents import Document

from cortex.sdk.langchain_adapter import CortexRetriever
from tests.sdk.conftest import make_query_result


def test_get_relevant_documents_maps_query_results_to_documents(fake_node: MagicMock):
    fake_node.query.return_value = [
        make_query_result(score=0.9, trust=0.8),
        make_query_result(score=0.7, trust=0.6),
        make_query_result(score=0.5, trust=0.4),
    ]

    retriever = CortexRetriever(
        node=fake_node, top_k=3, min_trust=0.35,
        topics={"soc"}, scopes={"PUBLIC"},
    )

    docs = retriever._get_relevant_documents(
        "phishing in paddock",
        run_manager=MagicMock(),
    )

    assert len(docs) == 3
    for d in docs:
        assert isinstance(d, Document)
        assert d.page_content
        assert "article_id" in d.metadata
        assert "trust" in d.metadata
        assert "org" in d.metadata
        assert "type" in d.metadata


def test_get_relevant_documents_passes_filter_args(fake_node: MagicMock):
    fake_node.query.return_value = []
    retriever = CortexRetriever(
        node=fake_node, top_k=8, min_trust=0.55,
        topics={"t1"}, scopes={"PUBLIC"},
    )
    retriever._get_relevant_documents("q", run_manager=MagicMock())
    kwargs = fake_node.query.call_args.kwargs
    assert kwargs["top_k"] == 8
    assert kwargs["min_trust"] == 0.55


def test_as_tool_returns_named_tool_whose_run_returns_documents(fake_node: MagicMock):
    from langchain_core.tools import Tool

    fake_node.query.return_value = [make_query_result()]
    retriever = CortexRetriever(node=fake_node)
    tool = retriever.as_tool()

    assert isinstance(tool, Tool)
    assert tool.name == "cortex_search"
    assert "Cortex" in tool.description and "memory" in tool.description.lower()

    out = tool._run("phishing paddock", config=None)
    import json
    parsed = json.loads(out)
    assert isinstance(parsed, list) and len(parsed) == 1
    assert parsed[0]["page_content"]
    assert "article_id" in parsed[0]["metadata"]


def test_cortex_publish_tool_runs_publish_finding(fake_node: MagicMock):
    from langchain_core.tools import Tool

    from cortex.sdk.langchain_adapter import CortexPublishTool

    tool = CortexPublishTool(node=fake_node)
    assert isinstance(tool, Tool)
    assert tool.name == "cortex_publish"

    art_id = tool._run(
        content="Phishing link targeting garage-12 ops staff.",
        payload_json='{"priority": "high"}',
        scope="PUBLIC",
    )
    assert art_id == "art-id-1"
    fake_node.publish.assert_called_once()
    article = fake_node.publish.call_args.args[0]
    assert article.content == "Phishing link targeting garage-12 ops staff."
    assert article.payload == {"priority": "high"}


def test_cortex_publish_tool_rejects_oversized_content(fake_node: MagicMock):
    from cortex.sdk.langchain_adapter import CortexPublishTool

    tool = CortexPublishTool(node=fake_node)
    too_long = "x" * 2001
    try:
        tool._run(content=too_long, payload_json="{}", scope="PRIVATE")
    except ValueError as e:
        assert "2000" in str(e)
    else:
        raise AssertionError("expected ValueError for >2000 char content")
    fake_node.publish.assert_not_called()
