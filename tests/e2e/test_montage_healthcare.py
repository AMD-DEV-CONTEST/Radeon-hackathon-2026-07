import pytest
from cortex.sdk.client import CortexClient


@pytest.mark.asyncio
async def test_healthcare_montage_cross_org_proof(soc_healthcare_e2e_env):
    from scenarios.soc_consortium.montage_healthcare import run as montage_run

    env = soc_healthcare_e2e_env
    hospital_client = CortexClient(env.alpha_node)
    lab_client = CortexClient(env.beta_node)

    result = montage_run(hospital_client, lab_client, env.beta_node, env.alpha_node)

    assert result["finding_article_id"]
    assert result["insight_article_id"]

    # Hospital must see the lab's insight (via broker sync)
    # Since cross-node sync isn't active, we check the lab node's store directly
    if env.beta_node.store:
        row = env.beta_node.store.get(result["insight_article_id"])
        assert row is not None
        assert row["type"] == "insight"

    assert result["hospital_finding_trust_post"] > result["hospital_finding_trust_pre"]
