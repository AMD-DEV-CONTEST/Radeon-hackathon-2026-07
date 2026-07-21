import json
import pytest

from cortex.sdk.client import CortexClient


@pytest.mark.asyncio
async def test_end_to_end_demo_smoke(tmp_path):
    from scenarios.soc_consortium.demo_run import run_demo

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    result = await run_demo(state_dir, tmp_path, no_record=True)

    assert "broker" in result["started"]
    assert result["seed_article_count"] == 10

    # Verify data plane: seed produced 10 articles
    # (alpha insight and beta warning already verified by demo_run internals)
    assert result["alpha_result"].get("insight_article_id")
    assert result["beta_result"].get("warning_article_id")

    # demo_state.json written
    state_file = state_dir / "demo_state.json"
    assert state_file.exists()
    data = json.loads(state_file.read_text())
    assert data["seed_article_count"] == 10
