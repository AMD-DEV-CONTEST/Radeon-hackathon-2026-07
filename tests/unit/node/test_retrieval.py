from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np

from cortex.node.query import QueryResult, retrieve


class FakeIndex:
    def __init__(self, vecs: dict[str, np.ndarray]) -> None:
        self.vecs = vecs

    def search(self, q: np.ndarray, top_k: int) -> list[tuple[str, float]]:
        sims = [(k, float(np.dot(q, v) / (np.linalg.norm(q) * np.linalg.norm(v)))) for k, v in self.vecs.items()]
        sims.sort(key=lambda x: -x[1])
        return sims[:top_k]


class FakeStore:
    def __init__(self, articles: dict[str, SimpleNamespace]) -> None:
        self.articles = articles

    def get(self, art_id: str):
        return self.articles.get(art_id)


class FakeEmbedder:
    def embed_one(self, text: str) -> np.ndarray:
        rng = np.random.default_rng(abs(hash(text)) % (2**32))
        v = rng.normal(size=384).astype(np.float32)
        return v / np.linalg.norm(v)


def make_article(art_id: str, scope: str, trust: float, content: str = "x", art_type: str = "finding"):
    return SimpleNamespace(
        id=art_id, type=art_type, content=content, payload={}, scope=scope,
        agent_signature=b"\x01", org_signature=None, cites=[],
        provenance=SimpleNamespace(
            producer_agent="did:percq:agent:a",
            producer_org="did:percq:org:soc-alpha",
            computation_ref=None, source_data_hash=None,
            source_data_schema=None, run_id="r",
            timestamp=datetime(2026, 7, 18, tzinfo=UTC),
        ),
        trust_score=trust,
    )


def test_retrieval_applies_scope_trust_and_hybrid() -> None:
    a_pub = make_article("a1", "public", 0.9, "alpha")
    a_priv = make_article("a2", "private", 0.95, "beta")
    a_low = make_article("a3", "public", 0.1, "gamma")
    a_partner = make_article("a4", "partner:did:percq:org:soc-alpha", 0.8, "delta")
    articles = {a.id: a for a in [a_pub, a_priv, a_low, a_partner]}
    store = FakeStore(articles)
    index = FakeIndex({a.id: FakeEmbedder().embed_one(a.content) for a in articles.values()})
    emb = FakeEmbedder()
    results = retrieve(
        store=store, vector_index=index, embedder=emb,
        query_text="alpha",
        topic_filter=[], scope_filter=["public", "private"],
        top_k=5, min_trust=0.3, deadline_ms=200,
    )
    ids = [r.article_id for r in results]
    assert "a3" not in ids
    assert "a4" not in ids
    assert "a1" in ids
    assert isinstance(results[0], QueryResult)
    assert all(isinstance(r.hybrid_score, float) for r in results)
