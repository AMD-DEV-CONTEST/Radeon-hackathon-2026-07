# Running Aegis's inference engine on AMD ROCm

Aegis's entire value proposition depends on inference actually running locally
on an AMD Radeon GPU. This guide covers getting a ROCm-backed vLLM server up.

## 1. Prerequisites

- An AMD Radeon GPU with ROCm support (RDNA2/RDNA3/CDNA — see AMD's ROCm
  compatibility matrix for your exact card).
- ROCm 6.x drivers installed on the host (`rocm-smi` should run without error).
- Docker with the AMD GPU device plugin, or a bare-metal Python environment.

Verify the driver is visible:

```bash
rocm-smi
```

You should see your GPU listed with utilization/VRAM stats. If this fails,
fix the driver install before proceeding — nothing above this layer will work.

## 2. Option A — Docker (recommended, matches docker-compose.yml)

The `vllm` service in the root `docker-compose.yml` already targets ROCm:

```bash
docker compose up vllm
```

This pulls `rocm/vllm:latest` and serves `Qwen/Qwen2.5-14B-Instruct` on port 8001
with the flags documented in `app/inference/client.py`'s docstring:

```
--dtype float16 --gpu-memory-utilization 0.90 --max-num-seqs 32 --enable-prefix-caching
```

- `--dtype float16`: halves VRAM vs. fp32 with negligible quality loss for this task.
- `--gpu-memory-utilization 0.90`: leaves headroom for KV cache growth under
  concurrent multi-agent load without OOMing.
- `--max-num-seqs 32`: caps concurrent sequences so batching stays predictable;
  tune down on cards with less VRAM (e.g. 16 on a 16GB card).
- `--enable-prefix-caching`: since every agent shares a similar system-prompt
  prefix, this meaningfully cuts prefill latency across the multi-agent graph.

## 3. Option B — Bare metal

```bash
pip install vllm --extra-index-url https://download.pytorch.org/whl/rocm6.1
vllm serve Qwen/Qwen2.5-14B-Instruct \
    --host 0.0.0.0 --port 8001 \
    --dtype float16 \
    --gpu-memory-utilization 0.90 \
    --max-num-seqs 32 \
    --enable-prefix-caching
```

## 4. Choosing a model for your VRAM budget

| GPU VRAM | Suggested model | Notes |
|---|---|---|
| 16 GB | Qwen2.5-7B-Instruct | Fits comfortably with room for KV cache headroom |
| 24 GB | Qwen2.5-14B-Instruct (default) | Balances quality and concurrent-agent throughput |
| 48 GB+ | Qwen2.5-32B-Instruct | Higher-quality synthesis; lower max concurrency |

Update `INFERENCE_MODEL` in `.env` to match.

## 5. Embeddings

The RAG/memory pipeline (`app/memory/embeddings.py`) calls the same server's
`/embeddings` endpoint. vLLM can serve an embedding model alongside the chat
model on a second port if you want a dedicated smaller embedding model — point
`INFERENCE_BASE_URL` at whichever process serves `/embeddings` for your setup.

## 6. Verifying it's wired up correctly

```bash
curl http://localhost:8000/api/v1/health | python3 -m json.tool
```

The `inference_engine` component should report `"status": "ok"`. If it
reports `"down"`, check `docker compose logs vllm` first.

## 7. Running the benchmark

```bash
python benchmarks/benchmark_inference.py --concurrency 1 4 8 16
```

Produces `benchmarks/results/<timestamp>.json`, which the frontend's
`/benchmarks` page and the `/api/v1/benchmarks/latest` endpoint read directly.
