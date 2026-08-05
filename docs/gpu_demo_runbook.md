# GPU Demo Runbook

Live-demo runbook for the InventoryDoc Agent management-report generation (GPU inference layer).

## Prerequisites

- AMD Radeon GPU + ROCm 6.x environment
- Python 3.10+, with `pip install -r requirements.txt`
- An OpenAI-compatible LLM inference service (llama.cpp or vLLM)

## 0. Confirm AMD GPU Status

```bash
rocm-smi
```

Expected output: GPU model, VRAM, temperature, etc.

> **Note**: In the ROCm / PyTorch ecosystem some device names may show as `cuda`. This is the HIP-compatible naming and does **not** mean an NVIDIA GPU. On-site evidence is `rocm-smi`, the local LLM service logs, the benchmark JSON, and the report-generation metadata.

## 1. Start the LLM Inference Service

### Option A: llama.cpp (recommended)

```bash
# Make sure llama.cpp is compiled with ROCm/HIP support
./llama.cpp/build/bin/llama-server \
  -m ./qwen-model/qwen2.5-7b-instruct-q4_k_m.gguf \
  --host 0.0.0.0 --port 8000 -ngl 99 -a qwen2.5
```

### Option B: vLLM

```bash
vllm serve meta-llama/Llama-3.1-8B-Instruct \
  --host 0.0.0.0 --port 8000 \
  --dtype float16
```

## 2. Health Check

```bash
python3 scripts/benchmark_llm.py
```

Expected output:

- model list
- inference reachable/success
- latency (seconds)
- chars/sec

If it fails, check:

- is the LLM service running?
- is the port correct (default 8000)?
- is `LLM_BASE_URL` overridden?

## 3. Run the Full Workflow

```bash
python3 run_full_workflow.py
```

Expected output:

- all 10 workflow steps `success`
- quality checks 7/7 passed
- core metrics: system stock 21144, net variance -971, variance rate 4.6%, net variance amount -989,900.97 CNY

## 4. Generate the Management Report (real GPU inference)

```bash
python3 scripts/generate_report.py
```

If the LLM is unreachable, an error is shown. Fallback then:

```bash
python3 scripts/generate_report.py --mock
# or
python3 scripts/generate_report.py --demo
```

## 5. Evidence to Show on the Recording

| Step | What to show | Command / Action |
|---|---|---|
| GPU status | `rocm-smi` output (model, VRAM) | `rocm-smi` |
| Service status | LLM service startup log | `rocm-smi` |
| Model list | model name returned by `/v1/models` | `python3 scripts/benchmark_llm.py` |
| Inference metrics | latency, chars/sec, estimated tokens/sec | benchmark output of `scripts/benchmark_llm.py` |
| Report metadata | mode, model, base_url, elapsed, start time | `data/output/report_generation_metadata.json` |
| Workflow metadata | run_id, quality gate, material-pack manifest | `_metadata` of `data/output/analysis_result.json` |

## 6. Environment Variable Reference

| Variable | Default | Description |
|---|---|---|
| `LLM_BASE_URL` | `http://localhost:8000/v1` | LLM API base URL |
| `LLM_MODEL` | `meta-llama/Llama-3.1-8B-Instruct` | model name |
| `LLM_STREAMING` | `true` | stream output or not |

## 7. Fallback Strategy

| Scenario | Handling |
|---|---|
| LLM service not started | use `--mock` or `--demo` |
| Port conflict | start on another port, set `LLM_BASE_URL` |
| Not enough GPU VRAM | use a smaller model or lower quantization (e.g., Q4_K_M) |

## 8. Quick Flow (for demo)

```bash
# 0. Confirm GPU
rocm-smi

# 1. Start service (new terminal)
./llama.cpp/build/bin/llama-server -m qwen-model/qwen2.5-7b-instruct-q4_k_m.gguf --host 0.0.0.0 --port 8000 -ngl 99

# 2. Benchmark (model list + inference metrics)
python3 scripts/benchmark_llm.py

# 3. Full workflow (10 steps + quality gate + adjustment pack)
python3 run_full_workflow.py

# 4. Inspect workflow metadata
python3 -c "import json; d=json.load(open('data/output/analysis_result.json')); print(json.dumps(d['_metadata']['quality_gate'], indent=2))"

# 5. Management report (Demo / Mock / Real)
python3 scripts/generate_report.py --demo
python3 scripts/generate_report.py --mock
python3 scripts/generate_report.py

# 6. Inspect report-generation metadata
cat data/output/report_generation_metadata.json
```
