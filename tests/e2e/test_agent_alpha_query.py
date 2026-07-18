import pytest
from cortex.sdk.client import CortexClient


@pytest.mark.asyncio
async def test_alpha_query_returns_findings(soc_e2e_env):
    from scenarios.soc_consortium.seed import seed_articles
    from scenarios.soc_consortium.agent_alpha import run as alpha_run

    seed_articles(soc_e2e_env.alpha_node, soc_e2e_env.beta_node)

    client = CortexClient(soc_e2e_env.alpha_node)

    result = alpha_run(client, queries="T1059.001 APT29 indicators",
                       min_trust=0.0, top_k=5, step="query")

    assert "retrieved" in result
    assert len(result["retrieved"]) >= 1
    assert all("article_id" in r and "content_preview" in r for r in result["retrieved"])
