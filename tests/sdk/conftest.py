from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cortex.core.article import (
    ArticleType,
    MemoryArticle,
    Provenance,
    Scope,
)
from cortex.node.query import QueryResult


def _prov(producer_agent: str = "did:org:alpha#agent-1",
          producer_org: str = "did:org:alpha") -> Provenance:
    return Provenance(
        producer_agent=producer_agent,
        producer_org=producer_org,
        run_id=str(uuid4()),
        timestamp=datetime.now(UTC),
    )


def make_article(
    *,
    content: str = "Phishing campaign targeting F1 garages detected.",
    payload: dict | None = None,
    scope: Scope = Scope.PUBLIC,
    type_: ArticleType = ArticleType.FINDING,
    cites: list[str] | None = None,
) -> MemoryArticle:
    return MemoryArticle(
        id=str(uuid4()),
        schema_version="1.0",
        type=type_,
        content=content,
        payload=payload or {},
        embedding=None,
        embedding_model=None,
        provenance=_prov(),
        scope=scope,
        agent_signature=b"sig-alpha",
        org_signature=None,
        cites=cites or [],
        trust_score=None,
        trust_expiration=None,
    )


def make_query_result(score: float = 0.8, trust: float = 0.7) -> QueryResult:
    art = make_article()
    return QueryResult(
        article=art,
        article_id=art.id,
        hybrid_score=score,
        trust_score=trust,
        provenance_summary={"producer_org": "did:org:alpha"},
    )


def make_fake_node(*, publish_id: str = "art-id-1") -> MagicMock:
    node = MagicMock(name="CortexNode")
    node.agent_did = "did:org:alpha#agent-1"
    node.org_did = "did:org:alpha"
    node.publish = MagicMock(return_value=publish_id)
    node.query = MagicMock(return_value=[make_query_result()])
    node.derive = MagicMock(return_value="derived-id-1")
    return node


@pytest.fixture
def fake_node() -> MagicMock:
    return make_fake_node()
