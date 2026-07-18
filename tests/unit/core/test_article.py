import pytest

from cortex.core.article import AgentDID, ArticleId, OrgDID
from cortex.core.crypto import did_for_agent, did_for_org


def test_type_aliases_are_str():
    assert ArticleId is str
    assert AgentDID is str
    assert OrgDID is str


def test_did_for_org_known_vector():
    assert did_for_org("soc-alpha") == "did:percq:org:soc-alpha"
    assert did_for_org("acme") == "did:percq:org:acme"


def test_did_for_agent_known_vector():
    fixed = "00000000-0000-4000-8000-000000000000"
    assert did_for_agent(fixed) == "did:percq:agent:00000000-0000-4000-8000-000000000000"


def test_did_for_agent_generates_uuid_v4_when_omitted():
    did = did_for_agent()
    assert did.startswith("did:percq:agent:")
    uuid_part = did.removeprefix("did:percq:agent:")
    # RFC 4122 v4: version nibble == 4, variant nibble in {8,9,a,b}
    assert uuid_part[14] == "4"
    assert uuid_part[19] in ("8", "9", "a", "b")


from cortex.core.article import ArticleType, Scope


def test_article_type_members():
    assert ArticleType.FINDING.value == "finding"
    assert ArticleType.INSIGHT.value == "insight"
    assert ArticleType.PRECEDENT.value == "precedent"
    assert ArticleType.PROCEDURE.value == "procedure"
    assert ArticleType.WARNING.value == "warning"


def test_scope_class_constants():
    assert Scope.PRIVATE == "private"
    assert Scope.PUBLIC == "public"
    assert Scope("private") == "private"
    assert Scope("public") == "public"
    assert Scope("private") == Scope("private")


def test_scope_partner_known_vector():
    s = Scope.partner("did:percq:org:soc-alpha")
    assert s == Scope("partner:did:percq:org:soc-alpha")
    assert s.value == "partner:did:percq:org:soc-alpha"


def test_scope_roundtrip_string():
    assert Scope("private").value == "private"
    assert Scope("partner:did:percq:org:acme").value == "partner:did:percq:org:acme"


def test_scope_is_frozen():
    s = Scope("private")
    with pytest.raises(Exception):
        s.value = "public"


from datetime import UTC, datetime

from cortex.core.article import Provenance


def _ts() -> datetime:
    return datetime(2026, 7, 15, 12, 34, 56, 789012, tzinfo=UTC)


def test_provenance_fields():
    p = Provenance(
        producer_agent="did:percq:agent:00000000-0000-4000-8000-000000000000",
        producer_org="did:percq:org:soc-alpha",
        computation_ref="run://42",
        source_data_hash="0123abcd" * 8,
        source_data_schema="sensor.v1",
        run_id="run-1",
        timestamp=_ts(),
    )
    assert p.producer_agent.startswith("did:percq:agent:")
    assert p.producer_org == "did:percq:org:soc-alpha"
    assert p.computation_ref == "run://42"
    assert p.source_data_schema == "sensor.v1"
    assert p.run_id == "run-1"
    assert p.timestamp == _ts()


def test_provenance_optional_fields_default_none():
    p = Provenance(
        producer_agent="did:percq:agent:x",
        producer_org="did:percq:org:y",
        run_id="run-1",
        timestamp=_ts(),
    )
    assert p.computation_ref is None
    assert p.source_data_hash is None
    assert p.source_data_schema is None


def test_provenance_is_frozen():
    p = Provenance(
        producer_agent="a",
        producer_org="o",
        run_id="r",
        timestamp=_ts(),
    )
    with pytest.raises(Exception):
        p.run_id = "other"


from cortex.core.article import MemoryArticle


def _prov() -> Provenance:
    return Provenance(
        producer_agent="did:percq:agent:00000000-0000-4000-8000-000000000000",
        producer_org="did:percq:org:soc-alpha",
        computation_ref=None,
        source_data_hash=None,
        source_data_schema=None,
        run_id="run-1",
        timestamp=_ts(),
    )


def test_memory_article_defaults_and_fields():
    a = MemoryArticle(
        id="0" * 64,
        type=ArticleType.FINDING,
        content="Short finding",
        payload={"k": 1},
        provenance=_prov(),
        scope=Scope.PRIVATE,
        agent_signature=b"\x01",
    )
    assert a.schema_version == "1.0"
    assert a.embedding is None
    assert a.embedding_model is None
    assert a.org_signature is None
    assert a.cites == []
    assert a.trust_score is None
    assert a.trust_expiration is None
    assert a.agent_signature == b"\x01"


def test_memory_article_content_too_long_raises():
    with pytest.raises(ValueError):
        MemoryArticle(
            id="0" * 64,
            type=ArticleType.FINDING,
            content="x" * 2001,
            payload={},
            provenance=_prov(),
            scope=Scope.PUBLIC,
            agent_signature=b"",
        )


def test_memory_article_content_at_cap_passes():
    a = MemoryArticle(
        id="0" * 64,
        type=ArticleType.FINDING,
        content="x" * 2000,
        payload={},
        provenance=_prov(),
        scope=Scope.PUBLIC,
        agent_signature=b"",
    )
    assert len(a.content) == 2000


def test_memory_article_is_frozen():
    a = MemoryArticle(
        id="0" * 64,
        type=ArticleType.FINDING,
        content="x",
        payload={},
        provenance=_prov(),
        scope=Scope.PRIVATE,
        agent_signature=b"",
    )
    with pytest.raises(Exception):
        a.content = "y"
