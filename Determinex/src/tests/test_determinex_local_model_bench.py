"""tests/test_determinex_local_model_bench.py

Ryan: "since timing will be an issue, we should set up clock runs on these
llms in local for response time based on different vram/ram uni on the
system... i dont have the vram to test them all, fyi, so we will put place
holders and others who download can report their findings."

Live-verified on real hardware during development (GTX 1660 Ti, 6GB VRAM):
qwen2.5-coder:14b-instruct-q4_K_M took 113s to generate 2 tokens for a
trivial prompt -- real proof the flat 300s constant this replaces would have
been wrong for this exact machine. These tests mock the network call (no
real Ollama round-trip) so the suite stays fast and deterministic; the real
end-to-end path was exercised manually, not just unit-tested.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import determinex_local_model_bench as bench  # noqa: E402


def _rewire(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bench, "BENCH_CACHE_PATH", tmp_path / "bench_cache.json")
    monkeypatch.setattr(bench, "COMMUNITY_BENCH_DIR", tmp_path / "community")


# ---------------------------------------------------------------------------
# infer_tier
# ---------------------------------------------------------------------------


def test_infer_tier_exact_matches():
    assert bench.infer_tier("qwen2.5-coder:14b-instruct-q4_K_M") == "14b"
    assert bench.infer_tier("qwen2.5-coder:1.5b-instruct") == "1.5b"
    assert bench.infer_tier("llama3:70b") == "70b"


def test_infer_tier_no_size_token_is_unknown():
    assert bench.infer_tier("some-custom-model-name") == "unknown"


def test_infer_tier_nearest_fallback_for_unlisted_size():
    # 20b isn't a listed tier -- should snap to the nearest (14b, per the table)
    assert bench.infer_tier("mystery:20b-q4") == "14b"


# ---------------------------------------------------------------------------
# detect_hardware -- never raises, degrades gracefully
# ---------------------------------------------------------------------------


def test_detect_hardware_never_raises_even_without_nvidia_smi():
    with patch("subprocess.run", side_effect=FileNotFoundError("no nvidia-smi")):
        hw = bench.detect_hardware()
    assert hw.gpu_name == "unknown"
    assert hw.gpu_vram_gb == 0.0
    # RAM/CPU come from psutil, independent of the GPU probe
    assert hw.total_ram_gb >= 0.0


# ---------------------------------------------------------------------------
# bench_model -- mocked network, real caching logic
# ---------------------------------------------------------------------------


def _fake_urlopen_success(eval_count=5):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"eval_count": eval_count}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    return mock_resp


def test_bench_model_success_writes_cache(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    with patch("urllib.request.urlopen", return_value=_fake_urlopen_success()):
        result = bench.bench_model("test-model:7b")

    assert result.error is None
    assert result.source == "measured_local"
    assert result.tokens_generated == 5
    assert bench.BENCH_CACHE_PATH.exists()

    cache = json.loads(bench.BENCH_CACHE_PATH.read_text(encoding="utf-8"))
    assert len(cache) == 1


def test_bench_model_uses_cache_on_second_call(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    with patch("urllib.request.urlopen", return_value=_fake_urlopen_success()) as mock_open:
        bench.bench_model("test-model:7b")
        bench.bench_model("test-model:7b")  # should hit cache, not call urlopen again
    assert mock_open.call_count == 1


def test_bench_model_force_bypasses_cache(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    with patch("urllib.request.urlopen", return_value=_fake_urlopen_success()) as mock_open:
        bench.bench_model("test-model:7b")
        bench.bench_model("test-model:7b", force=True)
    assert mock_open.call_count == 2


def test_bench_model_network_failure_records_error_not_raise(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("no ollama")):
        result = bench.bench_model("test-model:7b")
    assert result.error is not None
    assert "no ollama" in result.error


# ---------------------------------------------------------------------------
# estimate_timeout_seconds -- priority chain: local -> community -> placeholder
# ---------------------------------------------------------------------------


def test_estimate_timeout_from_real_local_measurement(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    with patch("urllib.request.urlopen", return_value=_fake_urlopen_success()):
        with patch.object(bench.time, "monotonic", side_effect=[0.0, 10.0]):
            timeout = bench.estimate_timeout_seconds("test-model:7b")
    # 10s latency * safety factor 6 = 60s, clamped to floor/ceiling (60-900)
    assert timeout == 60


def test_estimate_timeout_falls_back_to_community_when_local_fails(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    bench.COMMUNITY_BENCH_DIR.mkdir(parents=True)
    community_entry = {
        "model": "test-model:7b",
        "hardware_key": "someone-elses-rig",
        "latency_seconds": 15.0,
        "tokens_generated": 5,
        "tokens_per_second": 0.33,
        "hardware": {},
        "measured_at": "2026-01-01T00:00:00+00:00",
        "error": None,
        "source": "community",
    }
    (bench.COMMUNITY_BENCH_DIR / "contrib1.json").write_text(
        json.dumps(community_entry), encoding="utf-8"
    )

    with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("no local ollama")):
        timeout = bench.estimate_timeout_seconds("test-model:7b")
    # 15s * 6 = 90s
    assert timeout == 90


def test_estimate_timeout_falls_back_to_placeholder_when_nothing_measured(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("no ollama anywhere")):
        timeout = bench.estimate_timeout_seconds("qwen2.5-coder:14b-instruct-q4_K_M")
    # placeholder for 14b tier is 20s * safety factor 6 = 120s
    assert timeout == 120


def test_estimate_timeout_never_raises_and_stays_within_bounds(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("no ollama")):
        timeout = bench.estimate_timeout_seconds("llama3:70b")
    assert bench._TIMEOUT_FLOOR <= timeout <= bench._TIMEOUT_CEILING


# ---------------------------------------------------------------------------
# Community submission -- "others who download can report their findings"
# ---------------------------------------------------------------------------


def test_submit_community_bench_writes_a_file(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    with patch("urllib.request.urlopen", return_value=_fake_urlopen_success()):
        path = bench.submit_community_bench("test-model:7b")

    assert path.exists()
    assert path.parent == bench.COMMUNITY_BENCH_DIR
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["source"] == "community"
    assert data["model"] == "test-model:7b"


def test_submit_community_bench_does_not_clobber_prior_submissions(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    with patch("urllib.request.urlopen", return_value=_fake_urlopen_success()):
        path1 = bench.submit_community_bench("test-model:7b")
        path2 = bench.submit_community_bench("test-model:7b")
    assert path1 != path2
    assert path1.exists() and path2.exists()


def test_load_community_benchmarks_skips_malformed_files(tmp_path, monkeypatch):
    _rewire(monkeypatch, tmp_path)
    bench.COMMUNITY_BENCH_DIR.mkdir(parents=True)
    (bench.COMMUNITY_BENCH_DIR / "good.json").write_text(
        json.dumps(
            {
                "model": "m",
                "hardware_key": "hw",
                "latency_seconds": 1.0,
                "tokens_generated": 1,
                "tokens_per_second": 1.0,
                "hardware": {},
                "measured_at": "2026-01-01T00:00:00+00:00",
                "error": None,
            }
        ),
        encoding="utf-8",
    )
    (bench.COMMUNITY_BENCH_DIR / "bad.json").write_text("not valid json{{{", encoding="utf-8")

    results = bench.load_community_benchmarks()
    assert len(results) == 1
    assert results[0].model == "m"
    assert results[0].source == "community"
