# Radeon Benchmark Protocol

This directory stores reproducible performance evidence for the AMD AI DevMaster Track 2
submission. Do not add invented or Mac-only performance numbers. Final results must be captured on
the Radeon PRO W7900 host with the production llama.cpp command and exact model configuration.

## Required Evidence

Record:

- GPU model and ROCm version;
- llama.cpp commit and complete launch command;
- model repository, GGUF quantization, multimodal projection, context size, and cache types;
- cold and warm application-shaped runs;
- time to first generated delta;
- time to first final-content delta;
- prompt and decode tokens per second when reported by the server;
- end-to-end model latency;
- valid structured-JSON rate;
- peak VRAM and GPU utilization from ROCm tooling.

## llama-server Benchmark

Run on the Radeon machine while `llama-server` is available at `127.0.0.1:8000`:

```bash
mkdir -p benchmarks/results benchmarks/raw

uv run python scripts/benchmark_llama.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model mradermacher/Qwen3.6-35B-A3B-Fable-5-Distill-i1-GGUF:Q6_K \
  --image data/fixtures/images/portrait_01__clean.jpg \
  --warmups 1 \
  --runs 5 \
  --max-tokens 384 \
  --reasoning-budget 2048 \
  --gpu "AMD Radeon PRO W7900" \
  --rocm-version "$(rocminfo | rg -m1 'Runtime Version' | xargs)" \
  --llama-cpp-commit "$(git -C /workspace/llama.cpp rev-parse HEAD)" \
  --server-command "llama-server; see docs/REPRODUCE.md" \
  --output benchmarks/results/llama_cpp_w7900_optimized.json \
  --markdown-output benchmarks/results/llama_cpp_w7900_optimized.md
```

The JSON stores run-level metrics. The Markdown file is the reviewer-facing summary. Neither file
contains raw model output, chain-of-thought, or the API key.

For a cold-start record, restart `llama-server`, set `--warmups 0 --runs 1`, and write to separate
`*_cold` files. Do not mix cold and warm results in one median.

## GPU Telemetry

In a second terminal, capture GPU activity during the benchmark:

```bash
watch -n 0.5 rocm-smi --showuse --showmemuse --showtemp
```

Record the terminal in the demonstration video. If the installed ROCm version provides `amd-smi`,
it may be used instead; record its version and exact command. The benchmark script deliberately
does not parse vendor CLI output because formats differ across ROCm releases.

## Fair-Comparison Rules

- Use the same model family, workload, prompt, image, output limit, and repetition count.
- Label different formats or quantizations; Q6_K GGUF and FP16/FP8 weights are not equivalent.
- Report batch size 1 because XiangLens is an interactive single-user agent.
- Disclose warmup count, context size, GPU offload, cache types, and reasoning budget.
- Do not attribute a runtime difference to one hardware feature without controlled evidence.
- Prefer a narrow empirical statement over a causal FP8 claim.

## Result Review

Before committing a result:

- replace every `record-on-radeon-host` placeholder;
- confirm the endpoint is localhost, not a development tunnel;
- confirm all measured runs succeeded;
- confirm the structured JSON rate is reported;
- verify no hostname, key, prompt containing personal data, or raw model content leaked;
- link the Markdown result from `docs/SUBMISSION_BRIEF.md` and the slide deck.

`benchmarks/raw/` is for temporary console captures and must remain untracked. Curated JSON and
Markdown summaries under `benchmarks/results/` may be committed after review.

## Reviewed W7900 Capture — 2026-08-05

The committed capture uses the production-shaped Q6_K multimodal request at batch size 1. The
optimized capture includes one warmup followed by five measured runs; the cold reference is one
separate run after restarting the server.

| Metric | Optimized warm capture | Cold reference |
|---|---:|---:|
| Measured runs | 5 | 1 |
| First generated delta, median | 87.09 ms | 825.58 ms |
| First final-content delta, median | 9,960.18 ms | 10,728.70 ms |
| End-to-end model latency, median | 11,919.78 ms | 12,694.04 ms |
| Decode throughput, median | 83.42 tok/s | 83.16 tok/s |
| Valid structured JSON | 100% | 100% |

All six captured runs produced the same final-content SHA-256. See the reviewed
[optimized summary](results/llama_cpp_w7900_optimized.md) and
[cold reference](results/llama_cpp_w7900_cold.md).

These files demonstrate the tuned stack and warm-state behavior; they are not a controlled
llama.cpp-versus-vLLM comparison and do not isolate the gain from a single flag. Peak VRAM and GPU
utilization were not stored in these benchmark files and must be captured separately with ROCm
telemetry during the demonstration video.
