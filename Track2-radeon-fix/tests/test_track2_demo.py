import json

import pytest

from track2_demo import choose_result, public_task, read_gpu_metrics, render_dashboard


def test_public_task_rejects_evaluator_fields():
    with pytest.raises(ValueError, match="evaluator-only"):
        public_task(
            [{"instance_id": "demo", "repo": "org/repo", "FAIL_TO_PASS": ["secret"]}],
            "demo",
        )


def test_choose_result_requires_exact_repeat():
    rows = [{"harness": "qwen-code", "task_id": "demo", "repeat": 1}]
    assert choose_result(rows, harness="qwen-code", task_id="demo", repeat=1) == rows[0]
    with pytest.raises(ValueError, match="found 0"):
        choose_result(rows, harness="qwen-code", task_id="demo", repeat=2)


def test_dashboard_shows_public_evidence_without_hidden_test_ids():
    rendered = render_dashboard(
        task={"instance_id": "demo", "repo": "org/repo", "problem_statement": "Fix it"},
        result={
            "harness": "qwen-code",
            "repeat": 1,
            "model": "small-model",
            "model_turns": 2,
            "wall_time_ms": 1200,
            "usage": {"total_tokens": 99},
            "api_errors": [],
            "trajectory_diagnostics": {
                "tool_calls": 3,
                "edit_tool_calls": 1,
                "tests_after_edit": True,
                "tool_errors": 0,
                "integrity_eligible": True,
            },
        },
        outcome={
            "patch_applied": True,
            "resolution_status": "FULL",
            "fail_to_pass_success": 1,
            "fail_to_pass_total": 1,
            "pass_to_pass_success": 5,
            "pass_to_pass_total": 5,
        },
        patch="diff --git a/a.py b/a.py\n",
        gpu_metrics={"gpu_model": "Radeon", "ttft_ms": 42},
    )
    assert "FAIL_TO_PASS: 1/1" in rendered
    assert "PASS_TO_PASS: 5/5" in rendered
    assert "Radeon" in rendered
    assert "42 ms" in rendered
    assert "secret" not in rendered


def test_read_gpu_metrics_falls_back_without_rocm_smi(monkeypatch):
    def _raise(*args, **kwargs):
        raise FileNotFoundError("rocm-smi not available")

    monkeypatch.setattr("track2_demo.subprocess.run", _raise)
    monkeypatch.setenv("TRACK2_TTFT_P50_MS", "99.5")
    monkeypatch.setenv("TRACK2_DECODE_TOK_S", "27.1")
    monkeypatch.setenv("TRACK2_KV_CACHE", "test-kv")
    metrics = read_gpu_metrics()
    assert metrics["model"] == "Qwen3-14B-BF16"
    assert metrics["kv_cache"] == "test-kv"
    assert metrics["ttft_p50_ms"] == 99.5
    assert metrics["decode_tokens_per_second"] == 27.1


def test_read_gpu_metrics_uses_config_fallback(monkeypatch):
    monkeypatch.setattr("track2_demo.subprocess.run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.delenv("TRACK2_TTFT_P50_MS", raising=False)
    monkeypatch.delenv("TRACK2_DECODE_TOK_S", raising=False)
    metrics = read_gpu_metrics()
    assert metrics.get("ttft_p50_ms") == 115.6
    assert metrics.get("decode_tokens_per_second") == 12.41
    assert metrics.get("kv_cache") == "auto"
