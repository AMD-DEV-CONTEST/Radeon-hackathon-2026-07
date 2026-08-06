# E-Sentinel Local Deployment on AMD Radeon / ROCm

> Date: 2026-08-03
> Purpose: The "AMD GPU Deployment" section of the AMD AI DevMaster Hackathon Track 2 submission
> Status: Both the AMD Radeon GPU Cloud API path (Qwen3.6-35B-A3B) and the local vLLM path (Qwen3-8B) were verified. Their results are reported separately.

---

## 1. Environment Status (Verified)

### 1.1 Hardware and Software Stack

| Item | Value |
|---|---|
| GPU | AMD Radeon gfx1100 (**Radeon PRO W7900D**, DID `0x744b`, 48GB VRAM, 96 Compute Units) |
| ROCm | **7.2.1** (HIP SDK `7.2.53211`, see `benchmarks/amd/environment.txt`) |
| CPU | AMD EPYC 9334 32-Core × 2 (128 threads) |
| Memory | 503 GB |
| Inference | Free AMD Radeon GPU Cloud API (OpenAI-compatible, verified) + vLLM local deployment (working) |

### 1.2 Verified Inference Path (Free API)

E-Sentinel calls **Qwen3.6-35B-A3B** on AMD Radeon GPU Cloud via `callLLM` in `llm-provider.ts`:

```bash
curl https://developer.amd.com.cn/radeon/api/v1/chat/completions \
  -H "Authorization: Bearer <AMD_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "model":"Qwen3.6-35B-A3B",
    "messages":[{"role":"user","content":"Inspect this customer-service conversation for quality risks."}],
    "chat_template_kwargs":{"enable_thinking":false}
  }'
```

**Key configuration**: The free AMD API enables the chain-of-thought by default (content is empty; the answer is in reasoning). E-Sentinel disables thinking with `chat_template_kwargs.enable_thinking=false` so that `content` is returned normally (quality inspection needs the JSON conclusion directly and does not require the chain-of-thought).

**Verification**: `amd-provider.integration.test.ts` (actually calls the AMD API and returns non-empty content) plus an ablation evaluation passing 20 real quality inspection cases.

---

## 2. Verified vLLM Local Deployment (Track 2 "Local Deployment")

### 2.1 Model Selection

External research confirms: **Qwen3.6-35B-A3B has 35B total parameters (3B activated per token)**, with BF16 weights of roughly 70GB, which **does not fit in a 48GB gfx1100**. Therefore, the local deployment uses **Qwen3-8B** (or 14B), which fits in 48GB in FP16.

| Model | Total params | FP16 VRAM | 48GB gfx1100 |
|---|---|---|---|
| Qwen3-8B | 8B | ~16GB | ✅ Fits |
| Qwen3-14B | 14B | ~28GB | ✅ Fits |
| Qwen3.6-35B-A3B | 35B | ~70GB | ❌ Does not fit (use the free API) |

**Architecture decision**: The local core uses Qwen3-8B/14B (which fit in 48GB), with the 35B API retained as an optional enhancement/control — honestly stated: "All core agent functionality can run independently and locally on AMD Radeon; the 35B API is an optional enhancement, not a system dependency."

### 2.2 Installation (ROCm build of vLLM, the correct method)

> ⚠️ Note: The default `pip install vllm` from PyPI installs the **CUDA build** (including nvidia-* dependencies), which **cannot run** on an AMD gfx1100. You must use the ROCm build.

```bash
# On the AMD instance (gfx1100 + ROCm 7.2.1, Python 3.12)
python3 -m venv /opt/vllm-env
source /opt/vllm-env/bin/activate
pip install --upgrade pip

# ROCm build of vLLM: must use uv (pip will prefer the PyPI default source and install the CUDA build, which cannot run on AMD)
pip install uv
UV_HTTP_TIMEOUT=600 uv pip install "vllm==0.26.0+rocm723" --extra-index-url https://wheels.vllm.ai/rocm/
# Official guide: https://docs.vllm.ai/en/latest/getting_started/installation/gpu.html

# Verify
python -c "import torch; print(torch.cuda.is_available())"   # should be True
python -c "import vllm; print(vllm.__version__)"              # should contain rocm
```

### 2.3 Starting the vLLM Service (Qwen3-8B)

```bash
vllm serve /workspace/Qwen3-8B \
  --host 0.0.0.0 \
  --port 8000 \
  --dtype float16 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.88 \
  --max-num-seqs 8 \
  --max-num-batched-tokens 4096 \
  --enable-prefix-caching \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
```

**Parameter notes**:
- `--dtype float16`: RDNA has no BF16 tensor cores; float16 is optimal
- `--max-model-len 8192`: customer-service quality inspection inputs are 2-4K plus 500 for output; 8192 is sufficient, do not enable 262K
- `--enable-auto-tool-choice --tool-call-parser hermes`: Qwen tool calling (Hermes parser)
- `--enable-prefix-caching`: reuses prefixes across multi-turn quality inspection, improving speed

### 2.4 Connecting E-Sentinel

vLLM provides an OpenAI-compatible endpoint; E-Sentinel only needs to point `AMD_API_URL` at the local server:

```bash
# .env.local
AMD_API_URL=http://127.0.0.1:8000/v1/chat/completions
AMD_API_KEY=local       # vLLM local deployment does not need a key
AMD_MODEL=/workspace/Qwen3-8B
```

`llm-provider.ts` already supports this (the `ENV_AMD` provider); no code changes are needed.

---

## 3. Inference Speed Optimization (Track 2 "Speed Optimization Notes")

### 3.1 Optimization Checklist with Controlled Benchmarks (AMD Radeon gfx1100 · Qwen3-8B FP16 · 2026-08-04)

> Each optimization has an **on/off controlled experiment** (same prompt, same hardware, stable values taken over multiple rounds) to demonstrate the increment rather than a single-point figure.
> Raw controlled data: `benchmarks/amd/ablation-control.json`.

| Optimization | Problem | Solution | Controlled benchmark (on vs off) |
|---|---|---|---|
| **Disable chain-of-thought** | Default chain-of-thought leaves content empty and doubles tokens | `chat_template_kwargs.enable_thinking=false` | **3.20×**: ON P50 5.01s/200tok → OFF P50 1.57s/22tok (tokens down 91%) |
| **Prefix caching** | Multi-turn quality inspection recomputes prefix KV | `--enable-prefix-caching` | **1.49×**: cold 3.14s → warm 2.11s (same-prefix reuse) |
| **Quantization/model selection** | 35B FP16 does not fit in 48GB | Local Qwen3-8B FP16 (~16GB, VRAM 87%) | Fits and can infer |
| **Context length** | 262K wastes KV cache | `--max-model-len 8192` | Frees VRAM for concurrency |
| **Batch throughput** | Single-request serial processing | Concurrency 1→8 | Aggregate **~170 tokens/s**, 0 failures (throughput stable from concurrency 1→8) |
| **Interactive inspection latency** | — | Concurrency 2 | E2E **P50 4.2s / P95 6.1s** (300 output tokens) |

Raw data: `benchmarks/amd/summary.json` (the reproducible script `bench_local.py` is on the instance) plus `ablation-control.json` (the controlled experiments). Independent per-concurrency-level evidence is in `benchmarks/amd/concurrency-{1,2,4,8}.json` (exported by `scripts/export-amd-concurrency.mjs`, consistent with the same source as summary); the completeness of the evidence package can be checked by running `npm run benchmark:radeon`.

### 3.3 GPTQ W4A16 Quantization (tested on 2026-08-04)

> Positioning: a **validation experiment rather than a guaranteed speedup** — benefits are reported only after the correctness and performance gates pass. See `training/QUANTIZATION-EN.md` for details.

**Weights**: `JunHowie/Qwen3-8B-GPTQ-Int4` (HF via hf-mirror; ModelScope's `hiruyun/gptq-Qwen3-8B` is in Moore Threads format, and the vLLM ROCm load failure has been recorded). The native W4A16 kernel for gfx1100 is loaded automatically by vLLM (`--enable-auto-tool-choice --tool-call-parser hermes` work normally).

**Version-specific boundary**: This project validates the **RDNA3-specific W4A16 path of vLLM 0.26** executing GPTQ on **gfx1100** (successful load plus end-to-end benchmark). This conclusion **does not generalize** to all AMD GPUs or all vLLM GPTQ configurations — vLLM's general quantization compatibility table still marks GPTQ/AWQ as unsupported on AMD GPUs.

```bash
vllm serve /workspace/hf-models/models--JunHowie--Qwen3-8B-GPTQ-Int4/snapshots/<id> \
  --host 0.0.0.0 --port 8000 --max-model-len 8192 --gpu-memory-utilization 0.88 \
  --max-num-seqs 8 --enable-prefix-caching \
  --enable-auto-tool-choice --tool-call-parser hermes
```

**Quality gate** (human-gold 105): agent (main path) Recall 0.905 (FP16 0.921, −0.016), F1 0.844 (↑), FPR 0.357 (↓), κ 0.481 (↑) → **PASS**; dual Recall 0.254 (FP16 0.508) → significant regression, recorded as-is.

**Performance gate**: model-weight size 16GB→5.7GB (**−64%**), concurrency-1 output tok/s 34→55 (**+62%**), concurrency-8 output tok/s 133→238 (**+79%**), concurrency-1 single-request end-to-end latency (including generation) 5891→2345ms (**−60%**) → **PASS** (both thresholds met: model-weight size down ≥30% and throughput up ≥15%).

> **Benchmark method boundary**: comparison using `scripts/bench-latency.mjs` — no warm-up, one request per concurrency level (single observation), `5891→2345ms` is the **total single-request end-to-end latency rather than first-token latency (TTFT)**, `max_tokens=200` is fixed but the actual number of output tokens is not recorded separately. The relative change is valid in the FP16↔GPTQ comparison using the same script; the absolute values cannot be compared directly with the `vllm bench` random dataset (~175 tok/s).

**Conclusion**: GPTQ W4A16 is viable as an agent deployment optimization (main-path quality maintained plus model-weight size and throughput gains); **this GPTQ weight significantly degrades the tested Dual configuration**, so the Dual path retains FP16.

### 3.2 Benchmark Method (Reproducible)

```bash
vllm bench serve \
  --backend openai-chat \
  --base-url http://127.0.0.1:8000 \
  --model /workspace/Qwen3-8B \
  --dataset-name random \
  --num-prompts 100 \
  --random-input-len 2048 \
  --random-output-len 384 \
  --max-concurrency 8 \
  --metric-percentiles 50,95,99 \
  --save-result --save-detailed \
  --result-dir benchmarks
```

**Metrics**: TTFT, TPOT, ITL, end-to-end latency, concurrent aggregate throughput, P50/P95/P99. The raw JSON is recorded and reproducible.

---

## 4. Reproduction Paths (official "minimum demonstrable MVP")

| Path | Description |
|---|---|
| **① Operations console** | Sign in at `/dashboard` — 27-panel QA operations platform |
| **② One-command reproduction** | `node scripts/evaluate-goldset.mjs --variants dual,agent` (real AMD inference) |
| **③ 3-5 minute video** | Demonstrates AMD inference + ReAct tool calling + ablation data |

---

## 5. Environment Setup Log (one of the three official deliverables)

| Milestone | Status |
|---|---|
| AMD Radeon GPU Cloud instance | ✅ Connected (gfx1100 + ROCm 7.2.1) |
| Free API working | ✅ Verified (Qwen3.6-35B-A3B quality inspection) |
| E-Sentinel integrated with AMD | ✅ `callLLM` goes through AMD; ablation evaluation passed |
| vLLM local deployment | ✅ Installation complete (448 packages) + serve working (Qwen3-8B, VRAM 87%) |
| Tool calling | ✅ Real Hermes parser tool_call trace (`benchmarks/amd/tool-call-trace.json`) |
| Local regression | ✅ 20-case pilot: Severe Recall 1.000 (local 8B), stability recall 1.000/1.000/1.000 |
| Benchmark | ✅ TTFT 73ms / interactive E2E P50 4.2s / batch 170 tokens/s (`benchmarks/amd/summary.json`) |

> Observed during testing (2026-08-04): the instance's default DNS 8.8.8.8 is blocked in mainland China and there is no IPv6 route, causing slow PyPI/HF downloads — switched to Aliyun/Tencent DNS plus an IPv4 preference in gai.conf; direct HF connections are blocked, so models are fetched from the ModelScope CN CDN (50MB/s). Local Qwen3-8B results are reported separately from the cloud 35B (local 20-case recall 1.000, P50 latency 8.5s, faster than the cloud).
