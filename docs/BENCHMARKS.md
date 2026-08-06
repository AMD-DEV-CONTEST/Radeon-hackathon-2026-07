# Performance Benchmarks

## Benchmark Configuration
- **Hardware**: AMD MI300X (Data Center) / AMD Radeon RX 7900 XTX (Desktop)
- **Software Stack**: ROCm 6.2, PyTorch 2.3+ROCm, vLLM 0.5.0
- **Model**: Qwen3-30B-A3B (instruct-tuned)
- **Parameters**: `temperature=0.7`, `top_p=0.9`, `prompt_tokens=1024`, `max_tokens=256`

## Time to First Token (TTFT)
*Measured with a 1024-token input prompt. Lower is better.*

| Hardware | Precision | TTFT (ms) | Source |
| :--- | :--- | :--- | :--- |
| RX 7900 XTX | FP16 | OOM | Measured |
| RX 7900 XTX | INT8 | 125 | Sample (reference) |
| RX 7900 XTX | INT4 | 85 | Sample (reference) |
| MI300X | FP16 | 45 | Sample (reference) |
| MI300X | INT8 | 32 | Sample (reference) |

## Generation Throughput
*Tokens per second (tok/s) during active generation.*

| Hardware | Precision | Throughput (tok/s) | Source |
| :--- | :--- | :--- | :--- |
| RX 7900 XTX | FP16 | N/A (OOM) | Measured |
| RX 7900 XTX | INT8 | 35 | Sample (reference) |
| RX 7900 XTX | INT4 | 65 | Sample (reference) |
| MI300X | FP16 | 110 | Sample (reference) |
| MI300X | INT8 | 185 | Sample (reference) |

## VRAM Usage
*Peak VRAM allocation including KV Cache.*

| Precision | Model Weights (GB) | KV Cache (GB, 8k tokens) | Total VRAM (GB) |
| :--- | :--- | :--- | :--- |
| FP16 | 70 | 2.5 | 72.5 |
| INT8 | 35 | 2.5 | 37.5 |
| INT4 | 17.5 | 2.5 | 20.0 |

## RAG Performance
Using `BAAI/bge-large-en-v1.5` (the configured embedding model) via ROCm on RX 7900 XTX:
- **Embedding Time (1000 tokens)**: 12ms (Sample)
- **Vector Search Latency (ChromaDB, 100k vectors)**: 8ms (Sample)
- **End-to-End RAG Overhead**: ~25ms (Sample)

## Comparison: Bunker Local vs Cloud Alternatives

| Metric | Bunker (INT4, Local) | Typical Cloud API |
| :--- | :--- | :--- |
| **Latency (TTFT)** | ~85ms (Sample) | 200 - 500ms |
| **Privacy / Exfiltration** | **Local-first (no data sent by default)** | High Risk (Data leaves network) |
| **Cost per 1M Tokens** | **$0.00** | $0.50 - $15.00 |
| **Offline Capability** | Yes | No |

## How to Reproduce

### Prerequisites
1. AMD GPU with ROCm 6.2+ installed and validated
2. vLLM server running with desired model loaded
3. Python 3.10+ with `requests` package

### Validate ROCm Stack
```bash
python scripts/validate_rocm.py
```
Expected: prints `torch.version.hip`, GPU name, exits 0.

### Run Benchmarks
```bash
# Basic run (uses defaults: model=Qwen/Qwen3-30B-A3B, 3 iterations)
./scripts/benchmark.sh --vllm-url http://localhost:8000

# Full configuration
./scripts/benchmark.sh \
  --model Qwen/Qwen3-30B-A3B \
  --iterations 5 \
  --vllm-url http://localhost:8000 \
  --prompt-tokens 1024 \
  --completion-tokens 256 \
  --temperature 0.7 \
  --top-p 0.9 \
  --output-dir artifacts
```

### Artifact Output
Each run produces a timestamped JSON file in `artifacts/`:
```
artifacts/benchmark_20260806_143022.json
```

The JSON contains:
- `metadata`: run configuration (model, URL, iterations, token counts, sampling params)
- `summary`: computed statistics (mean, median, stdev, min/max for TTFT and throughput)
- `raw_results`: per-iteration measurements
- `rocm_smi`: captured `rocm-smi --showmeminfo vram --showuse --showtemp` output (if available)

### Interpreting Results
- **Sample (reference)** values in tables above are historical reference numbers from prior runs on specific hardware. They are **not** guaranteed to match your hardware.
- **Measured** values come from a JSON artifact produced by this script on your machine.
- Only numbers with a corresponding `artifacts/benchmark_<timestamp>.json` file should be treated as freshly measured.
- Compare your artifact's `summary.ttft.median_ms` and `summary.throughput.median_tok_s` against the tables.

## Benchmark Methodology

### TTFT Measurement
- Uses vLLM streaming completion endpoint (`/v1/completions` with `stream=true`)
- Prompt: ~1024 tokens of repeated benchmark text
- `max_tokens=1` to isolate first-token latency
- Timer starts at request send, stops at first non-empty token chunk received
- Reports median over N iterations

### Throughput Measurement
- Uses vLLM streaming completion endpoint
- Prompt: ~1024 tokens
- `max_tokens=256` (configurable)
- Counts completion tokens from streamed chunks
- Reports tokens/second = total_completion_tokens / wall_time
- Reports median over N iterations

### ROCm Metrics
- Captures `rocm-smi --showmeminfo vram --showuse --showtemp` before benchmark
- Included in JSON artifact for reproducibility

## Notes
- Run with `--iterations 5` or more for stable statistics
- Ensure GPU is in steady state (not thermal throttling) before benchmarking
- Close other GPU workloads during measurement
- Results vary by: ROCm version, vLLM version, model quantization, GPU clock speeds, cooling