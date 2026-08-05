from track2_harness_benchmark import (
    aider_call_produced_generation,
    run_aider,
    sanitize_context_output,
)


def test_aider_transport_failure_is_not_a_generation():
    call = {
        "returncode": 0,
        "usage": {"total_tokens": 0},
        "output": "403 Forbidden",
    }

    assert not aider_call_produced_generation(call, "same", "same")


def test_aider_usage_or_patch_marks_generation():
    token_call = {"usage": {"total_tokens": 12}}
    edit_call = {"usage": {"total_tokens": 0}}

    assert aider_call_produced_generation(token_call, "same", "same")
    assert aider_call_produced_generation(edit_call, "before", "after")


def test_context_sanitizer_removes_aider_terminal_noise():
    rendered = sanitize_context_output(
        "Detected dumb terminal, disabling fancy input and pretty output.\n"
        "Initial repo scan can be slow in larger repos, but only happens once.\n"
        "Scanning repo: 50%|#####     | 10/20\n"
        "Updating repo map: 100 tokens\n\nfoo.py:\n│def f():\n"
    )

    assert rendered == "foo.py:\n│def f():\n"


def test_aider_does_not_run_or_expose_hidden_tests_during_generation(tmp_path, monkeypatch):
    def fail_hidden_test(*args, **kwargs):
        raise AssertionError("hidden tests must only run in the outer final evaluator")

    def fake_call(*args, **kwargs):
        return {
            "returncode": 0,
            "output": "Tokens: 10 sent, 5 received",
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            "duration_ms": 1,
        }

    def fake_git_output(cwd, *args):
        if "--name-only" in args:
            return "solution.py\n"
        return "diff --git a/solution.py b/solution.py\n"

    monkeypatch.setattr("track2_harness_benchmark.hidden_test", fail_hidden_test)
    monkeypatch.setattr("track2_harness_benchmark.run_aider_call", fake_call)
    monkeypatch.setattr("track2_harness_benchmark.git_output", fake_git_output)

    result = run_aider(
        {
            "task_id": "sample",
            "prompt": "Fix the implementation.",
            "solution_files": ["solution.py"],
        },
        tmp_path,
        tmp_path / "prompts",
        base_url="https://example.invalid/v1",
        api_key="secret",
        model="model",
        max_calls=2,
        api_timeout=10,
        transport_retries=0,
    )

    assert result["semantic_calls"] == 2
    assert result["hidden_test_feedback_exposed"] is False
    trajectory = result["_trajectory"]
    assert "hidden tests failed" not in str(trajectory).lower()
