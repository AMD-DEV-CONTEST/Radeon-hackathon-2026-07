import pytest
from cortex.sdk.client import CortexClient


@pytest.mark.asyncio
async def test_alpha_counts_insight_with_three_sources(soc_e2e_env):
    from scenarios.soc_consortium.seed import seed_articles
    from scenarios.soc_consortium.agent_alpha import run as alpha_run

    seed_articles(soc_e2e_env.alpha_node, soc_e2e_env.beta_node)

    client = CortexClient(soc_e2e_env.alpha_node)
    result = alpha_run(client, queries="T1059.001 APT29 indicators",
                       min_trust=0.0, top_k=5, step="all")

    assert "insight_article_id" in result, str(result)
    assert len(result.get("sources", [])) == 3, result["sources"]

    insight = node_get_article(soc_e2e_env.alpha_node, result["insight_article_id"])
    assert insight is not None
    assert insight.type == "insight"

    # Verify provenance: insight cites 3 sources
    assert len(insight.cites) == 3, insight.cites


def node_get_article(node, article_id: str):
    """Retrieve an article from a node's store."""
    if node.store is None:
        return None
    row = node.store.get(article_id)
    if row is None:
        return None
    from cortex.core.article import ArticleType, MemoryArticle, Provenance
    import json
    from datetime import datetime
    prov = Provenance(
        producer_agent="", producer_org="",
        computation_ref=None, source_data_hash=None,
        source_data_schema=None, run_id="",
        timestamp=datetime.fromisoformat(row["created_at"]),
    )
    return MemoryArticle(
        id=row["id"], type=row["type"], content=row["content"],
        payload=json.loads(row["payload_json"]),
        embedding=None, embedding_model=None,
        provenance=prov, scope=row["scope"],
        agent_signature=row["agent_sig"],
        org_signature=row["org_sig"],
        cites=json.loads(row["cites_json"] or "[]"),
        trust_score=row["trust_score"],
        trust_expiration=None,
    )
