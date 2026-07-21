from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from cortex.core.article import ArticleType, Scope
from cortex.sdk.client import CortexClient


def test_publish_finding_builds_article_and_calls_node_publish(fake_node: MagicMock):
    client = CortexClient(fake_node)

    art_id = client.publish_finding(
        content="Spoofed team-radio email observed in paddock VLAN.",
        payload={"priority": "high", "asset": "garage-12"},
        scope=Scope.PUBLIC,
    )

    assert art_id == "art-id-1"
    fake_node.publish.assert_called_once()
    article = fake_node.publish.call_args.args[0]
    assert article.type == ArticleType.FINDING
    assert article.content == "Spoofed team-radio email observed in paddock VLAN."
    assert article.payload == {"priority": "high", "asset": "garage-12"}
    assert article.scope == Scope.PUBLIC
    assert article.provenance.producer_agent == fake_node.agent_did
    assert article.provenance.producer_org == fake_node.org_did
    assert isinstance(article.provenance.run_id, str) and article.provenance.run_id
    assert isinstance(article.provenance.timestamp, datetime)
    assert article.provenance.timestamp.tzinfo == UTC


def test_publish_finding_defaults_scope_to_private(fake_node: MagicMock):
    client = CortexClient(fake_node)
    client.publish_finding(content="x", payload={})
    article = fake_node.publish.call_args.args[0]
    assert article.scope == Scope.PRIVATE


def test_publish_insight_includes_cites(fake_node: MagicMock):
    from cortex.core.article import ArticleType

    client = CortexClient(fake_node)
    art_id = client.publish_insight(
        content="Correlation of phishing + DNS tunneling suggests APT replay.",
        payload={"confidence": 0.74},
        scope=Scope.PUBLIC,
        cites=["art-source-1", "art-source-2"],
    )

    assert art_id == "art-id-1"
    article = fake_node.publish.call_args.args[0]
    assert article.type == ArticleType.INSIGHT
    assert article.cites == ["art-source-1", "art-source-2"]


def test_publish_warning_procedure_precedent_dispatch_correct_type(fake_node: MagicMock):
    from cortex.core.article import ArticleType

    client = CortexClient(fake_node)
    pairs = [
        (client.publish_warning, ArticleType.WARNING),
        (client.publish_procedure, ArticleType.PROCEDURE),
        (client.publish_precedent, ArticleType.PRECEDENT),
    ]
    for fn, expected_type in pairs:
        fn(content="x", payload={"k": 1}, scope=Scope.PUBLIC)
        article = fake_node.publish.call_args.args[0]
        assert article.type == expected_type


def test_search_passes_filter_args_and_returns_results_unchanged(
    fake_node: MagicMock,
):
    from tests.sdk.conftest import make_query_result

    expected = [make_query_result(score=0.9, trust=0.8),
                make_query_result(score=0.7, trust=0.6)]
    fake_node.query.return_value = expected

    client = CortexClient(fake_node)
    results = client.search(
        query_text="phishing paddock",
        topics={"soc", "email"},
        scopes={"PUBLIC"},
        top_k=7,
        min_trust=0.45,
    )

    assert results is expected
    fake_node.query.assert_called_once()
    kwargs = fake_node.query.call_args.kwargs
    assert kwargs["query_text"] == "phishing paddock"
    assert set(kwargs["topic_filter"]) == {"soc", "email"}
    assert kwargs["scope_filter"] == ["PUBLIC"]
    assert kwargs["top_k"] == 7
    assert kwargs["min_trust"] == 0.45


def test_search_defaults_topics_scopes_to_none(fake_node: MagicMock):
    client = CortexClient(fake_node)
    client.search(query_text="x")
    kwargs = fake_node.query.call_args.kwargs
    assert kwargs["topic_filter"] is None
    assert kwargs["scope_filter"] is None
    assert kwargs["top_k"] == 5
    assert kwargs["min_trust"] == 0.3


def test_search_maps_query_errors(fake_node: MagicMock):
    from cortex.sdk.exceptions import CortexQueryError

    fake_node.query.side_effect = RuntimeError("query connection reset")
    client = CortexClient(fake_node)
    try:
        client.search(query_text="x")
    except CortexQueryError as e:
        assert "query connection reset" in str(e)
    else:
        raise AssertionError("expected CortexQueryError")


def test_compose_insight_calls_derive_with_new_article_and_cites(fake_node: MagicMock):
    from cortex.sdk.client import CortexClient

    client = CortexClient(fake_node)
    new_id = client.compose_insight(
        content="Insight derived from 2 phishing findings.",
        payload={"confidence": 0.81},
        scope=Scope.PUBLIC,
        sources=["art-a", "art-b"],
    )

    assert new_id == "derived-id-1"
    fake_node.derive.assert_called_once()
    call = fake_node.derive.call_args
    article = call.args[0]
    cites = call.args[1]
    assert article.type == ArticleType.INSIGHT
    assert article.content == "Insight derived from 2 phishing findings."
    assert article.payload == {"confidence": 0.81}
    assert article.scope == Scope.PUBLIC
    assert article.provenance.producer_agent == fake_node.agent_did
    assert cites == ["art-a", "art-b"]


def test_compose_insight_maps_errors(fake_node: MagicMock):
    from cortex.sdk.exceptions import CortexSDKError

    fake_node.derive.side_effect = ValueError("derive failed")
    client = CortexClient(fake_node)
    try:
        client.compose_insight(content="x", payload={}, scope=Scope.PRIVATE, sources=[])
    except CortexSDKError:
        pass
    else:
        raise AssertionError("expected CortexSDKError")
