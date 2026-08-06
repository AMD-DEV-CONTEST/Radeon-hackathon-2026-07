import json

from autopilot.model_compare import compare, evaluate_model, load_dataset, write_comparison

ENTRY_OURS = {"label": "gemma-4-ft (ours)", "model": "m-ft", "base_url": "http://x", "finetuned": True}
ENTRY_BASE = {"label": "gemma-4-base", "model": "m-base", "base_url": "http://y", "finetuned": False}


def _bench_fn(cfg, base_url):
    tps = 400.0 if base_url == "http://x" else 380.0
    return {"config": cfg, "hardware": {}, "metrics": {"tokens_per_s": tps, "ttft_ms": 120.0, "itl_ms": 10.0},
            "energy": {"joules": 100.0, "joules_per_token": 0.5, "mean_power_w": 200.0}, "ts": "t"}


def _complete_fn(base_url, model, prompt, max_tokens):
    return f"response from {model}"


def _judge_fn(prompt, response):
    # "ours" always scores higher, deterministic on the model name embedded in the response
    return {"score": 90.0 if "m-ft" in response else 70.0, "reason": "stub"}


def test_load_dataset_samples_across_file(tmp_path):
    ds_path = tmp_path / "ds.jsonl"
    ds_path.write_text("\n".join(json.dumps({"prompt": f"p{i}", "class": "x", "max_tokens": 10}) for i in range(20)))
    rows = load_dataset(str(ds_path), sample_size=5)
    assert len(rows) == 5


def test_evaluate_model_combines_speed_and_quality():
    result = evaluate_model(ENTRY_OURS, [{"prompt": "p1", "class": "patent", "max_tokens": 10}],
                            bench_fn=_bench_fn, complete_fn=_complete_fn, judge_fn=_judge_fn)
    assert result["label"] == "gemma-4-ft (ours)"
    assert result["finetuned"] is True
    assert result["tokens_per_s"] == 400.0
    assert result["quality_score"] == 90.0
    assert result["quality_by_class"] == {"patent": 90.0}


def test_evaluate_model_surfaces_bench_error():
    def failing_bench(cfg, base_url):
        return {"error": "bench failed"}
    result = evaluate_model(ENTRY_OURS, [{"prompt": "p1", "max_tokens": 10}], bench_fn=failing_bench)
    assert result["error"] == "bench failed"
    assert "quality_score" not in result


def test_compare_ranks_finetuned_model_first_on_quality(tmp_path):
    ds_path = tmp_path / "ds.jsonl"
    ds_path.write_text(json.dumps({"prompt": "p1", "class": "patent", "max_tokens": 10}))
    state = compare([ENTRY_OURS, ENTRY_BASE], dataset_path=str(ds_path), sample_size=1,
                    bench_fn=_bench_fn, complete_fn=_complete_fn, judge_fn=_judge_fn)
    by_label = {m["label"]: m for m in state["models"]}
    assert by_label["gemma-4-ft (ours)"]["quality_score"] > by_label["gemma-4-base"]["quality_score"]
    assert "objective" in state


def test_write_comparison_writes_json(tmp_path):
    state = {"generated_ts": "t", "objective": {}, "models": [{"label": "m", "quality_score": 1}]}
    path = write_comparison(state, directory=str(tmp_path))
    assert path.exists()
    assert json.loads(path.read_text())["models"][0]["label"] == "m"
