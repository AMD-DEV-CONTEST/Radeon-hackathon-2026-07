# Perciqa Cortex — Source Code & Deployment Guide

Full source repository: **https://github.com/perciqa/cortex**

This folder points to the complete source repo and summarizes environment configuration, startup, and dependencies. For the live submission, the repository itself is the authoritative source.

---

## Repository layout

```
cortex/
├── core/          # Data model, crypto (Ed25519), canonical JSON, envelope protocol
├── node/          # Local tenant node: embedder, store, signer, query engine, trust engine
├── broker/        # Federated pub/sub WebSocket server with topic + scope ACL
├── sdk/           # Agent-facing client + LangChain / LlamaIndex adapters
├── bench/         # GPU vs CPU benchmark harness (Prometheus metrics)
└── console/       # FastAPI backend + React SPA web UI
```

---

## Environment

- Python 3.11+
- AMD Radeon GPU with ROCm 6.1+ (recommended), any CUDA GPU, or CPU-only fallback
- ~10 GB disk for models

## Dependencies

```bash
pip install -e ".[dev,cpu]"     # CPU-only fallback
# OR
pip install -e ".[dev,gpu]"     # Requires ROCm/CUDA PyTorch
```

Key runtime deps: PyTorch (ROCm build), transformers, hnswlib, websockets, fastapi, uvicorn, vLLM (for the inference pod).

## Verify installation

```bash
pytest -q tests/    # ~213 tests across unit, integration, and e2e
```

---

## Startup (native)

```bash
# 1. Broker (WebSocket + health on 7432)
python -m cortex.broker --config deploy/config/broker.yaml

# 2. A node per tenant (separate terminals)
python -m cortex.cli start --config deploy/config/alpha.yaml
python -m cortex.cli start --config deploy/config/beta.yaml

# 3. Console UI
python -m cortex.console --broker ws://localhost:7432 --port 8080
# Open http://localhost:8080

# 4. Live LLM reasoning (Aurora Code Mini V1 via vLLM)
VLLM_URL=http://localhost:8000/v1 python -m cortex.cli start --config deploy/config/alpha.yaml
```

## Startup (Docker Compose)

```bash
docker compose up -d broker node-alpha node-beta console
# GPU profile adds the vLLM inference pod + bench sidecars:
COMPOSE_PROFILES=gpu docker compose up -d
```

---

## Key environment overrides

| Variable | Purpose |
|---|---|
| `CORTEX_BROKER_URL` | Broker WebSocket URL |
| `CORTEX_EMBED_BACKEND` | `gpu` / `cpu` / `auto` |
| `VLLM_URL` / `VLLM_MODEL` | Inference endpoint + model (default `perciqa/aurora-code-mini-v1`) |
| `CORTEX_LOG_LEVEL` | `DEBUG` / `INFO` / `WARN` |

---

## AMD / ROCm notes

- **Embedder:** BAAI/bge-small-en-v1.5 on PyTorch-ROCm (AMD Radeon PRO W7900, RDNA3, 49 GB VRAM; rocm-smi device `D7070910`)
- **Measured throughput (live):** ~2,060 embeds/sec on Radeon vs ~5.7 on CPU (~360×), ~214 queries/sec, p95 query latency ~4.6 ms
- **Inference:** Perciqa/Aurora-Code-Mini-V1 served by vLLM on the same ROCm pod
- **Fallback:** embedder auto-halves batch size on OOM and falls back to CPU; reasoning falls back to scripted mode
