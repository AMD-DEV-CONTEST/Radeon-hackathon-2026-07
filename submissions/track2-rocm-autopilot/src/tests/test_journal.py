import json

from autopilot.journal import Journal


def _run(tokens_per_s, ttft_ms, jpt=0.5):
    return {
        "config": {"model": "m", "precision": "bf16", "max_num_seqs": 64,
                   "enable_prefix_caching": True, "power_cap_w": None, "concurrency": 8},
        "hardware": {"gpu": "test", "vram_gb": 80},
        "metrics": {"tokens_per_s": tokens_per_s, "ttft_ms": ttft_ms, "itl_ms": 10.0},
        "energy": {"joules": 100.0, "joules_per_token": jpt, "mean_power_w": 300.0},
        "ts": "2026-07-25T12:00:00",
    }


def test_leaderboard_ranks_and_zeroes_constraint_violations(tmp_path):
    j = Journal(directory=str(tmp_path))
    j.add_run(_run(100.0, 200.0), "baseline ok", label="human-expert")
    j.add_run(_run(150.0, 900.0), "fast but violates TTFT")  # -> score 0
    j.add_run(_run(120.0, 300.0), "agent improves")

    lb = j.leaderboard()
    assert lb[0]["label"] == "agent-iter-2" and lb[0]["rank"] == 1
    assert lb[-1]["score"] == 0.0  # violator last

    state = json.loads((tmp_path / "state.json").read_text())
    assert state["objective"]["constraint_ttft_ms"] == 500.0
    assert len(state["runs"]) == 3
    assert (tmp_path / "journal.jsonl").read_text().count("\n") == 3
