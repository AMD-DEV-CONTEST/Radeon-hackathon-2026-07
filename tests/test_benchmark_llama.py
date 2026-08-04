from scripts.benchmark_llama import render_markdown, safe_endpoint, summarize_runs


def test_safe_endpoint_removes_credentials_query_and_fragment() -> None:
    assert (
        safe_endpoint("https://user:secret@example.test:8443/v1/?key=secret#fragment")
        == "https://example.test:8443/v1"
    )


def test_summary_uses_successful_runs_and_reports_structured_rate() -> None:
    summary = summarize_runs(
        [
            {
                "success": True,
                "valid_json": True,
                "time_to_first_delta_ms": 100.0,
                "time_to_first_content_ms": 150.0,
                "total_latency_ms": 1000.0,
                "prompt_tokens_per_second": 500.0,
                "decode_tokens_per_second": 40.0,
            },
            {
                "success": True,
                "valid_json": False,
                "time_to_first_delta_ms": 200.0,
                "time_to_first_content_ms": 250.0,
                "total_latency_ms": 2000.0,
                "prompt_tokens_per_second": 700.0,
                "decode_tokens_per_second": 60.0,
            },
            {"success": False, "error": "timeout"},
        ]
    )

    assert summary["successful_runs"] == 2
    assert summary["structured_json_success_rate"] == 0.5
    assert summary["time_to_first_delta_ms"]["median"] == 150.0
    assert summary["decode_tokens_per_second"]["median"] == 50.0


def test_markdown_contains_method_without_model_content() -> None:
    result = {
        "generated_at_utc": "2026-08-04T00:00:00+00:00",
        "endpoint": "http://127.0.0.1:8000/v1",
        "environment": {
            "runtime": "llama.cpp",
            "gpu": "AMD Radeon PRO W7900",
            "rocm_version": "test",
            "llama_cpp_commit": "abc123",
        },
        "workload": {
            "model": "test-model",
            "image": None,
            "temperature": 0.0,
            "max_tokens": 128,
            "reasoning_budget": 512,
        },
        "warmups": 1,
        "summary": {
            "attempted_runs": 3,
            "structured_json_success_rate": 1.0,
            "time_to_first_delta_ms": {"median": 100.0},
            "time_to_first_content_ms": {"median": 120.0},
            "total_latency_ms": {"median": 900.0},
            "prompt_tokens_per_second": {"median": 600.0},
            "decode_tokens_per_second": {"median": 45.0},
        },
    }

    markdown = render_markdown(result)

    assert "45.00 tok/s" in markdown
    assert "Raw model content and chain-of-thought were not written" in markdown
