from datetime import UTC, datetime
from types import SimpleNamespace

from cortex.node.trust import TrustEngine


def make_article(art_id: str, org: str = "did:percq:org:soc-alpha",
                 ts: datetime | None = None, cites: list[str] | None = None,
                 org_signature: bytes | None = b"\x01",
                 source_data_hash: str | None = "deadbeef"):
    ts = ts or datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    prov = SimpleNamespace(producer_org=org, timestamp=ts, source_data_hash=source_data_hash)
    return SimpleNamespace(
        id=art_id, provenance=prov,
        cites=cites or [], org_signature=org_signature,
        provenance_source_data_hash=source_data_hash,
    )


def test_recency_decay_half_life() -> None:
    e = TrustEngine()
    assert abs(e.recency_decay(90 * 86400) - 0.5) < 1e-6
    assert abs(e.recency_decay(0) - 1.0) < 1e-6


def test_trust_for_known_value() -> None:
    e = TrustEngine(default_org_reputation=0.8,
                    reputation_overrides={"did:percq:org:soc-alpha": 0.9},
                    half_life_days=90, min_trust_default=0.3)
    art = make_article("a1", org="did:percq:org:soc-alpha", ts=datetime(2026, 7, 18, 12, 0, tzinfo=UTC))
    now = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    store = SimpleNamespace(get=lambda _id: None)
    t = e.trust_for(art, now, store)
    assert abs(t - 0.6237) < 1e-3


def test_trust_for_with_cites() -> None:
    e = TrustEngine(default_org_reputation=0.9, half_life_days=90, min_trust_default=0.3)
    base_ts = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    now = base_ts
    cited_articles = {
        "c1": make_article("c1", org="did:percq:org:soc-alpha", ts=base_ts, org_signature=b"\x01", source_data_hash="h"),
        "c2": make_article("c2", org="did:percq:org:soc-alpha", ts=base_ts, org_signature=b"\x01", source_data_hash="h"),
    }

    class StubStore:
        def get(self, _id):
            return cited_articles.get(_id)

    cited_trusts = [e.trust_for(cited_articles[c], now, StubStore()) for c in cited_articles]
    expected_source_trust = sum(cited_trusts) / 2
    deriv = make_article("d1", ts=base_ts, cites=["c1", "c2"])
    t = e.trust_for(deriv, now, StubStore())
    expected_base = 0.9 * 1.0 * 1.1 * 1.05
    expected = max(0.0, min(1.0, 0.6 * expected_base + 0.4 * expected_source_trust))
    assert abs(t - expected) < 1e-3


def test_memoization_and_invalidation() -> None:
    e = TrustEngine(default_org_reputation=0.9, half_life_days=90)
    base_ts = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    now = base_ts
    store = SimpleNamespace(get=lambda _id: None)
    art = make_article("m1", ts=base_ts)
    t0 = e.trust_for(art, now, store, graph_version=0)
    t1 = e.trust_for(art, now, store, graph_version=0)
    assert t0 == t1
    t2 = e.trust_for(art, now, store, graph_version=1)
    assert t2 == t0
    assert ("m1", 1) in e._cache
