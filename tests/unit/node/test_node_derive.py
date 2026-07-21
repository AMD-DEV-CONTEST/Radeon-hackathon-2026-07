import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cortex.core.article import ArticleType, MemoryArticle, Provenance
from cortex.node.node import CortexNode
from tests.unit.node.test_node_publish import FakeBroker, make_keys  # noqa: F401


class _StoreSpy:
    def __init__(self, store): self._s = store
    def get(self, art_id): return _row_to_article(self._s.get(art_id))


def _row_to_article(row):
    from cortex.core.article import Provenance
    prov = Provenance(producer_agent="", producer_org="", computation_ref=None,
                      source_data_hash=None, source_data_schema=None, run_id="",
                      timestamp=datetime.fromisoformat(row["created_at"]))
    return MemoryArticle(id=row["id"], type=row["type"], content=row["content"], payload={},
                         embedding=None, embedding_model=None, provenance=prov,
                         scope=row["scope"], agent_signature=b"", org_signature=row["org_sig"],
                         cites=json.loads(row["cites_json"] or "[]"),
                         trust_score=row["trust_score"], trust_expiration=None)


@pytest.mark.asyncio
async def test_derive_creates_edges_and_emits_envelope(cfg: Path, tmp_path: Path) -> None:
    keys = make_keys(tmp_path)
    broker = FakeBroker()
    node = CortexNode(org_did="did:percq:org:soc-alpha", agent_did="did:percq:agent:alpha-bot-1",
                      key_paths=keys, broker_url="ws://localhost:7432", config_path=cfg,
                      embedder_backend_override="cpu")
    node._broker_override = broker
    await node.start()
    cited_ids: list[str] = []
    prov_base = Provenance(producer_agent="did:percq:agent:alpha-bot-1",
                           producer_org="did:percq:org:soc-alpha",
                           computation_ref=None, source_data_hash="h",
                           source_data_schema=None, run_id="r0",
                           timestamp=datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC))
    for i in range(3):
        prov = Provenance(producer_agent="did:percq:agent:alpha-bot-1",
                          producer_org="did:percq:org:soc-alpha",
                          computation_ref=None, source_data_hash="h" if i else None,
                          source_data_schema=None, run_id=f"r{i}",
                          timestamp=datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC))
        base = MemoryArticle(id="", type=ArticleType.FINDING, content=f"finding {i}",
                             payload={}, embedding=None, embedding_model=None,
                             provenance=prov, scope="public", agent_signature=b"",
                             org_signature=None, cites=[], trust_score=None, trust_expiration=None)
        cited_ids.append(node.publish(base))
    new = MemoryArticle(id="", type=ArticleType.INSIGHT, content="correlated insight from three findings",
                       payload={}, embedding=None, embedding_model=None, provenance=prov_base,
                       scope="public", agent_signature=b"", org_signature=None, cites=[],
                       trust_score=None, trust_expiration=None)
    new_id = node.derive(new, cited_ids)
    for cid in cited_ids:
        assert new_id in node.provenance.cited_by(cid)
    await asyncio.sleep(0.05)
    assert any(e["type"] == "derive" for e in broker.published)
    store_adapter = _StoreSpy(node.store)
    trust = node.trust.trust_for(store_adapter.get(new_id),
                                 datetime.now(UTC),
                                 store_adapter, graph_version=node.provenance.graph_version)
    assert trust > 0.0
    await node.stop()
