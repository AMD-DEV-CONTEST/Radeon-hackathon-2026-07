# Perciqa Cortex — Source Code

This directory contains the **complete source code** of the Perciqa Cortex repository (portable tree, ~6 MB). The authoritative live repository is https://github.com/perciqa/cortex — this copy is provided so the submission is self-contained.

```
cortex/
├── core/          # Data model, crypto (Ed25519), canonical JSON, envelope protocol
├── node/          # Local tenant node: embedder, store, signer, query engine, trust engine
├── broker/        # Federated pub/sub WebSocket server with topic + scope ACL
├── sdk/           # Agent-facing client + LangChain / LlamaIndex adapters
├── bench/         # GPU vs CPU benchmark harness (Prometheus metrics)
└── console/       # FastAPI backend + React SPA web UI (source + built dist included)
deploy/            # YAML config templates (broker, nodes, registry) + docker-compose
examples/          # Quickstart examples
scripts/           # Utility scripts (ROCm verification, spec generation)
tests/             # ~213 unit, integration, and e2e tests
pyproject.toml     # Package metadata + dependency extras
```

Excluded from this portable copy: `node_modules`, `.venv`, Python/TypeScript build caches, the internal `docs/` (design notes), and the `hackathon/` spec folder (kept at submission root) — none are required to build or run from source.

---

## Environment

- Python 3.11+
- AMD Radeon GPU with ROCm 6.1+ (recommended), any CUDA GPU, or CPU-only fallback
- Node.js 18+ (only if rebuilding the console frontend; the built `dist/` is included)

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
