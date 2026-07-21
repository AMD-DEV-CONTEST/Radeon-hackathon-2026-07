import os
import json
import pytest


@pytest.mark.asyncio
async def test_demo_run_orchestrates(tmp_path):
    from scenarios.soc_consortium.demo_run import run_demo

    state_dir = tmp_path / "state"
    video_dir = tmp_path / "video"
    state_dir.mkdir(parents=True, exist_ok=True)
    video_dir.mkdir(parents=True, exist_ok=True)

    result = await run_demo(state_dir, video_dir, no_record=True)

    assert result["started"]
    assert "broker" in result["started"]
    assert "seed_article_count" in result
    assert result["seed_article_count"] == 10
    assert "alpha_result" in result
    assert "beta_result" in result
    assert result["beta_result"].get("warning_article_id")

    # Verify state file was written
    state_file = state_dir / "demo_state.json"
    assert state_file.exists()
    data = json.loads(state_file.read_text())
    assert data["seed_article_count"] == 10
