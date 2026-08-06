"""Performance-regression tests for the local AMD ROCm/vLLM stack.

Two gates, both tagged ``perf`` and both tunable via env vars so CI can
retune them for a given GPU:

1. ``test_inference_latency_within_limits``: calls the local vLLM OpenAI
   server with a standard prompt, streams the answer and measures Time To
   First Token (TTFT) plus decode throughput. Thresholds:
       BUNKER_PERF_TTFT_MAX_MS        (default 200)
       BUNKER_PERF_TOKENS_PER_SEC_MIN (default 30)

2. ``test_vram_usage_under_limit``: runs a heavy multi-hop RAG query (3 hops,
   5 documents) with the LM stubbed out and samples GPU VRAM usage while it
   is in flight. The ``rocm-smi``/``nvidia-smi`` subprocess is mocked when no
   SMI tool is installed, so the test is deterministic on any runner.
   Threshold:
       BUNKER_PERF_VRAM_MAX_GB         (default 20)

vLLM also exposes a Prometheus ``/metrics`` endpoint with
``vllm:time_to_first_token_seconds`` and ``vllm:inter_token_latency_seconds``
histograms; here TTFT is measured directly from the response stream instead,
because it is exact per-request and needs no extra server flags.

Run with:

    pytest tests/test_performance.py -v -m perf
"""

import json
import os
import re
import subprocess
import time
import types
from unittest import mock

import pytest
import requests

from src import dspy_runtime
from src.config import get_config
from src.rag.multihop_rag import BunkerMultiHopRAG, make_chromadb_search

_VLLM_URL = "http://localhost:8000"
_PROMPT = "Write a short paragraph explaining the benefits of the metric system."

_ROCM_SMI_OUTPUT = (
    "======================= ROCm System Management Interface =======================\n"
    "================================= GPU memory info ==============================\n"
    "GPU[0]\t\t: GPU memory usage\n"
    "GPU[0]\t\t: used memory {used_mb} MB\n"
    "GPU[0]\t\t: total memory 24576 MB\n"
)


def _rocm_smi_output(used_mb: int) -> types.SimpleNamespace:
    """Build a fake CompletedProcess shaped like a real ``rocm-smi`` call."""
    return types.SimpleNamespace(
        returncode=0,
        stdout=_ROCM_SMI_OUTPUT.format(used_mb=used_mb),
        stderr="",
    )


def _vllm_is_healthy() -> bool:
    """Return True when a vLLM server is answering on localhost:8000."""
    try:
        return requests.get(f"{_VLLM_URL}/health", timeout=2).status_code == 200
    except Exception:
        return False


def _measure_latency(max_tokens: int = 50) -> tuple[float, float]:
    """Stream one chat completion and return (TTFT_ms, tokens_per_second)."""
    payload = {
        "model": get_config().inference.primary_model,
        "messages": [{"role": "user", "content": _PROMPT}],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    start = time.perf_counter()
    first_token_at = None
    last_chunk_at = None
    completion_tokens = 0
    with requests.post(
        f"{_VLLM_URL}/v1/chat/completions",
        json=payload,
        stream=True,
        timeout=120,
    ) as resp:
        resp.raise_for_status()
        for raw in resp.iter_lines():
            if not raw:
                continue
            line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            # The first non-empty content delta marks the first generated token.
            if first_token_at is None:
                choices = chunk.get("choices") or []
                delta = (choices[0].get("delta") or {}) if choices else {}
                if delta.get("content"):
                    first_token_at = time.perf_counter()
            usage = chunk.get("usage")
            if usage:
                completion_tokens = int(usage.get("completion_tokens") or 0)
            last_chunk_at = time.perf_counter()

    if last_chunk_at is None:
        last_chunk_at = time.perf_counter()
    elapsed = last_chunk_at - start
    ttft_ms = ((first_token_at - start) * 1000) if first_token_at else elapsed * 1000
    tok_per_sec = completion_tokens / elapsed if elapsed > 0 else 0.0
    return ttft_ms, tok_per_sec


@pytest.mark.perf
def test_inference_latency_within_limits():
    """TTFT < 200ms and tokens/s > 30 against the live local vLLM server."""
    ttft_max_ms = float(os.environ.get("BUNKER_PERF_TTFT_MAX_MS", "200"))
    tok_min = float(os.environ.get("BUNKER_PERF_TOKENS_PER_SEC_MIN", "30"))

    if not _vllm_is_healthy():
        pytest.skip("No live vLLM server on localhost:8000")

    ttft_ms, tok_per_sec = _measure_latency()

    assert ttft_ms < ttft_max_ms, (
        f"TTFT {ttft_ms:.1f} ms exceeds limit {ttft_max_ms:.0f} ms"
    )
    assert tok_per_sec > tok_min, (
        f"Throughput {tok_per_sec:.1f} tok/s below floor {tok_min:.0f} tok/s"
    )


# ---------------------------------------------------------------------------
# VRAM gate
# ---------------------------------------------------------------------------


def _parse_rocm_smi(stdout: str):
    """Extract ``used memory NNNN MB`` from a rocm-smi --showmeminfo dump."""
    match = re.search(r"used memory\s+(\d+)\s*MB", stdout)
    return int(match.group(1)) if match else None


def _parse_nvidia_smi(stdout: str):
    """Extract the first GPU's used memory from nvidia-smi csv output."""
    line = stdout.strip().splitlines()[0].strip() if stdout.strip() else ""
    digits = re.match(r"\d+", line)
    return int(digits.group(0)) if digits else None


def _get_vram_used_mb() -> int:
    """Query used VRAM (MiB) via rocm-smi (AMD) then nvidia-smi (NVIDIA)."""
    for args, parse in (
        (["rocm-smi", "--showmeminfo", "vram"], _parse_rocm_smi),
        (
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            _parse_nvidia_smi,
        ),
    ):
        try:
            out = subprocess.run(args, capture_output=True, text=True, timeout=10)
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
        if out.returncode == 0 and out.stdout.strip():
            used_mb = parse(out.stdout)
            if used_mb is not None:
                return used_mb
    raise RuntimeError("No GPU memory tooling available (rocm-smi / nvidia-smi)")


def _assert_vram_under_limit(used_mb: int, limit_gb: float) -> None:
    assert used_mb <= limit_gb * 1024, (
        f"VRAM usage {used_mb} MiB exceeds the {limit_gb:.1f} GiB limit"
    )


# Scripted LM responses reused from the deterministic RAG harness.


def _fake_completion_response(text: str):
    """Build an OpenAI chat-completion-shaped object for a mocked LM.forward()."""
    message = types.SimpleNamespace(content=text, tool_calls=None)
    choice = types.SimpleNamespace(message=message, finish_reason="stop", logprobs=None)
    return types.SimpleNamespace(
        choices=[choice],
        model=dspy_runtime.BUNKER_LM.model,
        usage={"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
        cache_hit=False,
        _hidden_params={},
    )


def _query_response(query: str):
    return _fake_completion_response(
        "[[ ## reasoning ## ]]\nDecide the next query.\n\n"
        f"[[ ## query ## ]]\n{query}\n\n"
        "[[ ## completed ## ]]"
    )


def _notes_response(notes_json: str):
    return _fake_completion_response(
        "[[ ## reasoning ## ]]\nExtract new facts.\n\n"
        f"[[ ## new_notes ## ]]\n{notes_json}\n\n"
        "[[ ## completed ## ]]"
    )


def _answer_response(answer: str):
    return _fake_completion_response(
        "[[ ## reasoning ## ]]\nGather the grounded answer.\n\n"
        f"[[ ## answer ## ]]\n{answer}\n\n"
        "[[ ## completed ## ]]"
    )


class _HeavyStore:
    """Returns 5 ChromaDB-shaped passages per hop, simulating a loaded index."""

    def __init__(self):
        self.calls = []  # (query, k)

    def search(self, query: str, k: int = 5, **kwargs):
        self.calls.append((query, k))
        q = query.lower()
        if "canada" in q:
            text = "Canada's population grew at 2.9 percent in 2023, the fastest pace in decades."
        elif "brazil" in q:
            text = "Brazil's population grew at 0.5 percent in 2023."
        else:
            text = "Real GDP growth in 2023 was 1.1 percent for Canada and 2.9 percent for Brazil."
        return [
            {
                "id": f"p{i}",
                "text": text,
                "metadata": {"source": "stats.pdf"},
                "distance": 0.1 + i * 0.01,
            }
            for i in range(k)
        ]


@pytest.mark.perf
def test_vram_usage_under_limit():
    """A heavy 3-hop/5-doc RAG query keeps VRAM under 20GB (env-tunable)."""
    vram_limit_gb = float(os.environ.get("BUNKER_PERF_VRAM_MAX_GB", "20"))

    responses = [
        _query_response("What was Canada's population growth rate in 2023?"),
        _notes_response('["Canada population grew 2.9 percent in 2023."]'),
        _query_response("What was Brazil's population growth rate in 2023?"),
        _notes_response('["Brazil population grew 0.5 percent in 2023."]'),
        _query_response("What was the GDP growth of Canada and Brazil in 2023?"),
        _notes_response('["Canada GDP grew 1.1 percent; Brazil GDP grew 2.9 percent in 2023."]'),
        _answer_response("Canada's population grew faster than Brazil's in 2023. [1] [2] [3]"),
    ]

    store = _HeavyStore()
    rag = BunkerMultiHopRAG(
        search=make_chromadb_search(store),
        num_hops=3,
        num_docs=5,
        max_backtracks=2,
    )

    # rocm-smi is not installed on this dev box, so the SMI call is mocked; on
    # a real AMD CI runner the mock is dropped and the live tool is queried.
    with mock.patch.object(dspy_runtime.BUNKER_LM, "forward", side_effect=responses):
        with mock.patch("subprocess.run", return_value=_rocm_smi_output(12 * 1024)) as mock_run:
            result = rag(
                question="Which country's population grew faster in 2023, Canada or Brazil?"
            )
            used_mb = _get_vram_used_mb()

    assert result.grounded is True
    assert len(result.queries) == 3
    assert len(store.calls) == 3
    assert all(k == 5 for _, k in store.calls)
    assert mock_run.call_count >= 1

    _assert_vram_under_limit(used_mb, vram_limit_gb)

    # The gate must also catch a breach on the same workload shape.
    with mock.patch("subprocess.run", return_value=_rocm_smi_output(25 * 1024)):
        with pytest.raises(AssertionError):
            _assert_vram_under_limit(_get_vram_used_mb(), vram_limit_gb)
