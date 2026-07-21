from datetime import UTC, datetime

from cortex.core.canonical import canonical_bytes


def test_canonical_insertion_order_invariant():
    a = canonical_bytes({"b": 2, "a": 1, "c": 3})
    b = canonical_bytes({"c": 3, "a": 1, "b": 2})
    assert a == b
    assert a == b'{"a":1,"b":2,"c":3}'


def test_canonical_no_insignificant_whitespace():
    assert canonical_bytes({"a": 1}) == b'{"a":1}'


def test_canonical_datetime_serializes_utc_microseconds_z():
    dt = datetime(2026, 7, 15, 12, 34, 56, 789012, tzinfo=UTC)
    out = canonical_bytes({"t": dt})
    assert out == b'{"t":"2026-07-15T12:34:56.789012Z"}'


def test_canonical_naive_datetime_normalized_to_utc():
    dt = datetime(2026, 7, 15, 12, 34, 56, 789012)
    out = canonical_bytes({"t": dt})
    assert out == b'{"t":"2026-07-15T12:34:56.789012Z"}'


from cortex.core.canonical import compute_article_id, sha256_hex


def test_sha256_hex_known_vector():
    assert (
        sha256_hex(b'{"a":1}')
        == "015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862"
    )


def test_compute_article_id_known_vector():
    canonical = b'{"a":1}'
    assert (
        compute_article_id(canonical)
        == "015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862"
    )
    assert len(compute_article_id(canonical)) == 64


from cortex.core.article import MemoryArticle
from cortex.core.canonical import article_canonical_bytes


def _article_with_extras() -> MemoryArticle:
    from datetime import datetime

    from cortex.core.article import ArticleType, Provenance, Scope
    p = Provenance(
        producer_agent="did:percq:agent:00000000-0000-4000-8000-000000000000",
        producer_org="did:percq:org:soc-alpha",
        computation_ref=None,
        source_data_hash=None,
        source_data_schema=None,
        run_id="run-1",
        timestamp=datetime(2026, 7, 15, 12, 34, 56, 789012, tzinfo=UTC),
    )
    return MemoryArticle(
        id="0" * 64,
        type=ArticleType.FINDING,
        content="hello",
        payload={"k": 1},
        provenance=p,
        scope=Scope.PUBLIC,
        agent_signature=b"\x01\x02",
        embedding=[0.1, 0.2],
        embedding_model="bge-small-en-v1.5",
        org_signature=b"\x03\x04",
        trust_score=0.9,
        trust_expiration=datetime(2026, 7, 16, 0, 0, 0, 0, tzinfo=UTC),
    )


def test_article_canonical_bytes_excludes_embedding_and_trust():
    cb = article_canonical_bytes(_article_with_extras())
    assert b"embedding" not in cb
    assert b"embedding_model" not in cb
    assert b"trust_score" not in cb
    assert b"trust_expiration" not in cb
    assert b"agent_signature" not in cb
    assert b"org_signature" not in cb
    assert b'"id"' not in cb


def test_article_canonical_bytes_includes_signed_fields():
    cb = article_canonical_bytes(_article_with_extras())
    assert b'"content":"hello"' in cb
    assert b'"schema_version":"1.0"' in cb
    assert b'"type":"finding"' in cb
    assert b'"payload":{"k":1}' in cb
    assert b'"scope":"public"' in cb
    assert b'"run_id":"run-1"' in cb




def test_article_id_deterministic_for_identical_content():
    a = _article_with_extras()
    b = _article_with_extras()
    id_a = compute_article_id(article_canonical_bytes(a))
    id_b = compute_article_id(article_canonical_bytes(b))
    assert id_a == id_b
    assert len(id_a) == 64


def test_article_id_changes_when_content_mutates():
    base = _article_with_extras()
    from cortex.core.article import MemoryArticle
    mutated = MemoryArticle(
        id=base.id,
        type=base.type,
        content="hellp",
        payload=dict(base.payload),
        provenance=base.provenance,
        scope=base.scope,
        agent_signature=base.agent_signature,
        embedding=base.embedding,
        embedding_model=base.embedding_model,
        org_signature=base.org_signature,
        cites=list(base.cites),
        trust_score=base.trust_score,
        trust_expiration=base.trust_expiration,
    )
    id_base = compute_article_id(article_canonical_bytes(base))
    id_mut = compute_article_id(article_canonical_bytes(mutated))
    assert id_base != id_mut


def test_article_id_invariant_to_embedding_changes():
    base = _article_with_extras()
    from cortex.core.article import MemoryArticle
    alt = MemoryArticle(
        id=base.id,
        type=base.type,
        content=base.content,
        payload=dict(base.payload),
        provenance=base.provenance,
        scope=base.scope,
        agent_signature=base.agent_signature,
        embedding=[9.0, 9.0],
        embedding_model="other-model",
        org_signature=base.org_signature,
        cites=list(base.cites),
        trust_score=0.1,
    )
    id_base = compute_article_id(article_canonical_bytes(base))
    id_alt = compute_article_id(article_canonical_bytes(alt))
    assert id_base == id_alt
