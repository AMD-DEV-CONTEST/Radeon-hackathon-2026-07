import pytest
import json
from cortex.sdk.client import CortexClient


@pytest.mark.asyncio
async def test_beta_corroborates_and_warns(soc_e2e_env):
    from scenarios.soc_consortium.seed import seed_articles
    from scenarios.soc_consortium.agent_alpha import run as alpha_run
    from scenarios.soc_consortium.agent_beta import run as beta_run

    seed_articles(soc_e2e_env.alpha_node, soc_e2e_env.beta_node)

    client_alpha = CortexClient(soc_e2e_env.alpha_node)
    alpha_result = alpha_run(client_alpha, step="all")
    assert "insight_article_id" in alpha_result

    # Beta runs on the same node to find Alpha's insight via fabric search
    client_beta = CortexClient(soc_e2e_env.alpha_node)
    beta_result = beta_run(client_beta, soc_e2e_env.alpha_node)

    assert len(beta_result["new_findings"]) == 2, beta_result["new_findings"]
    assert beta_result["warning_article_id"]

    # Verify the warning article exists and cites the insight + new findings
    if soc_e2e_env.alpha_node.store:
        row = soc_e2e_env.alpha_node.store.get(beta_result["warning_article_id"])
        assert row is not None
        cites = json.loads(row["cites_json"] or "[]")
        src_set = set(cites)
        assert beta_result["insight_article_id"] in src_set
        assert set(beta_result["new_findings"]).issubset(src_set)
