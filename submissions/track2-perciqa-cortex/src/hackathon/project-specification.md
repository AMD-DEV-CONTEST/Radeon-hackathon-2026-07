# Perciqa Cortex — Project Specification

> **Hackathon:** AMD AI DevMaster Hackathon 2026, Track 2 (Radeon/ROCm)
> **Submission date:** August 2026
> **Repo:** https://github.com/perciqa/cortex

---

## 1. Overview

Cortex is a decentralized network of sovereign memory nodes that lets AI agents share memory articles across organizational trust boundaries, without exposing raw data, trusting a central vendor, or rebuilding trust infrastructure from scratch.

Every article carries cryptographic provenance, scoped permissions, and a derived trust score. Nodes run on each organization's own AMD Radeon GPU; a lightweight WebSocket broker routes signed envelopes between nodes using topic and scope-based access control. Agent reasoning runs through Aurora Code Mini V1 served by vLLM on the same ROCm pod — sovereign inference, end to end.

The live deployment is at **https://cortex.perciqa.com** (Cloudflare tunnel to the ROCm pod).

---

## 2. Application Scenarios

The reference deployment exercises a two-SOC cybersecurity fabric: **SOC Alpha** (APT / espionage) and **SOC Beta** (ransomware / cybercrime). Each runs a sovereign node with its own org identity, registry-valid Ed25519 keys, and a scenario bank. A scheduled pipeline publishes fresh MITRE ATT&CK threat-intel findings every ~30 minutes.

Scenario bank (full details in `application-scenarios.md`):

| SOC | Threat actors | Techniques |
|---|---|---|
| SOC Alpha | APT29, APT41, Lazarus Group, Turla | T1059.001, T1053.005, T1566.001, T1082 |
| SOC Beta | LockBit 3.0, REvil, BlackCat, Cl0p | T1486, T1190, T1530, T1195 |

The same fabric protocol applies to any domain where organizations share agent knowledge without sharing raw data (e.g., healthcare, finance, research consortia).

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Cortex Fabric Broker                       │
│          (federated pub/sub, topic + scope ACL)              │
└──────────────────┬──────────────────────┬───────────────────┘
                   │                      │
   ┌───────────────▼───────────┐  ┌───────▼───────────────────┐
   │  Tenant A                  │  │  Tenant B                  │
   │  SOC Alpha                 │  │  SOC Beta                  │
   │                            │  │                            │
   │  ┌────────┐  ┌──────────┐  │  │  ┌────────┐  ┌──────────┐  │
   │  │ Agent  │→ │  Node A  │  │  │  │ Agent  │→ │  Node B  │  │
   │  └────────┘  │          │  │  │  └────────┘  │          │  │
   │              │ Embedder │  │  │              │ Embedder │  │
   │              │ ArtStore │  │  │              │ ArtStore │  │
   │              │ VecIndex │  │  │              │ VecIndex │  │
   │              │Provenance│  │  │              │Provenance│  │
   │              │  Signer  │  │  │              │  Signer  │  │
   │              │TrustEng. │  │  │              │TrustEng. │  │
   │              └──────────┘  │  │              └──────────┘  │
   └────────────────────────────┘  └────────────────────────────┘
```

**Runtime components on the ROCm pod:**

| Component | Port | Role |
|---|---|---|
| `cortex.broker` | ws://:7432 | Federated pub/sub router; topic + scope ACL; envelope dedup; replay window |
| `cortex.cli start` (alpha, beta) | outbound WS | Per-org sovereign nodes |
| `cortex.console` | :8080 | Real-time read-only web UI (feed, ATT&CK matrix, provenance graph, bench panel) |
| `cortex.bench` | metrics → broker | GPU vs CPU throughput probes, live |
| vLLM | :8000 | OpenAI-compatible inference (Aurora Code Mini V1) |
| cloudflared | — | `cortex.perciqa.com → localhost:8080` |

**Module layout** (from the repo):

| Module | Purpose |
|---|---|
| `cortex-core` | Data model, crypto (Ed25519), canonical JSON, envelope protocol |
| `cortex-node` | Local tenant node: embedder, store, signer, query engine |
| `cortex-broker` | Federated pub/sub routing with topic and scope ACL |
| `cortex-sdk` | Agent-facing client + LangChain / LlamaIndex adapters |
| `cortex-console` | Real-time read-only web UI |
| `cortex-bench` | GPU vs CPU benchmark harness |

---

## 4. Core Capabilities

### 4.1 Publish
An agent produces a finding. The local node signs it with Ed25519, computes its embedding on the local AMD GPU, and broadcasts it to subscribed peers within the article's scope. Peers verify the signature and index it locally.

### 4.2 Query
An agent asks "what's known about X?" The node embeds the query, runs semantic retrieval over its local fabric partition, and returns ranked articles with full provenance. Results are ranked by a hybrid of cosine similarity and trust score, so trust shapes what agents actually see.

### 4.3 Derive
An agent composes a new article from existing ones. The provenance graph grows, and trust propagates: articles that cite high-trust sources get a lift, and ones that cite low-trust sources take a penalty.

### 4.4 Trust model
Trust formula: `0.6 × base organization reputation + 0.4 × source trust − penalty for low-trust citations`.

### 4.5 Data model
Atomic unit is a `MemoryArticle`: `sha256(canonical(content + provenance))` ID, type (`finding | insight | precedent | procedure | warning`), content, structured payload, embedding, provenance, scope (`private | partner:<org> | public`), agent + org Ed25519 signatures, citation list, and a recomputable trust score.

`Provenance` records the producing agent, producing org, `source_data_hash` (a SHA-256 commitment, never the raw data), run ID, and timestamp.

---

## 5. Model Introduction

### 5.1 Reasoning model — Aurora Code Mini V1
Served by **vLLM on the ROCm pod** at `http://localhost:8000/v1`.

| Property | Value |
|---|---|
| Model ID | `Perciqa/Aurora-Code-Mini-V1` |
| Served by | vLLM (ROCm build) |
| Context window | 32,768 tokens |
| Fine-tuning | Trained on AMD infrastructure |
| Access | OpenAI-compatible chat completions API |

Default in the SDK, console backend, docker-compose, and docs is `perciqa/aurora-code-mini-v1` (overridable via `VLLM_MODEL`).

### 5.2 Embedding model — BAAI/bge-small-en-v1.5
Runs on the Radeon GPU via PyTorch-ROCm (verified on the pod). Used for article + query embeddings in publish and query paths.

---

## 6. Local Deployment Plan

### 6.1 Requirements
- Python 3.11+
- AMD Radeon GPU with ROCm 6.1+ (recommended), any CUDA GPU, or CPU-only fallback
- 10 GB+ disk for models

### 6.2 Install
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,cpu]"     # CPU fallback
# or
pip install -e ".[dev,gpu]"     # ROCm/CUDA PyTorch
pytest -q tests/                # ~213 tests
```

### 6.3 Run the fabric (Docker Compose)
```bash
docker compose up -d broker node-alpha node-beta console
# GPU profile adds the vLLM inference pod + bench sidecars:
COMPOSE_PROFILES=gpu docker compose up -d
# Console: http://localhost:8080
```

### 6.4 Run the fabric (native)
```bash
python -m cortex.broker --config deploy/config/broker.yaml
python -m cortex.cli start --config deploy/config/alpha.yaml
python -m cortex.cli start --config deploy/config/beta.yaml
python -m cortex.console --broker ws://localhost:7432 --port 8080
# With live LLM reasoning:
VLLM_URL=http://localhost:8000/v1 python -m cortex.cli start --config deploy/config/alpha.yaml
```

### 6.5 Key configuration
| Variable | Purpose |
|---|---|
| `CORTEX_BROKER_URL` | Broker WebSocket URL |
| `CORTEX_EMBED_BACKEND` | `gpu` / `cpu` / `auto` |
| `VLLM_URL` / `VLLM_MODEL` | Inference endpoint + model |
| `CORTEX_LOG_LEVEL` | `DEBUG` / `INFO` / `WARN` |

### 6.6 Live pod deployment (production)
1. Provision an AMD Radeon PRO W7900-class pod (49 GB VRAM); install ROCm + PyTorch-ROCm.
2. Start vLLM serving Aurora Code Mini V1 on :8000.
3. Start broker (:7432), alpha + beta nodes, console (:8080).
4. Publish console via a Cloudflare tunnel (`cortex.perciqa.com → localhost:8080`).
5. Register org public keys in `registry/org_registry.json`; distribute the `tenants` array for the console.
6. A GitHub Actions pipeline (`cortex-soc` repo) syncs the demo generator and publishes fresh threat-intel content every ~30 min.

---

## 7. Inference Optimization on ROCm

Full detail in `inference-optimization.md`. Summary of verified live numbers on the pod:

| Metric | Radeon (GPU) | CPU | Ratio |
|---|---|---|---|
| Embeddings / sec (batch) | ~2,060 | ~5.7 | ~360× |
| Queries / sec | ~214 | ~2.2 | ~97× |
| P95 query latency | ~4.6 ms | — | — |
| GPU memory utilization | ~93% | — | — |

- **Embedding pipeline:** BAAI bge-small on PyTorch-ROCm (HIP 7.2, PyTorch 2.10). Embeddings computed on-GPU at publish and query time.
- **Inference:** Aurora Code Mini V1 served by vLLM on the same pod; agent derive/reasoning steps route through it.
- **Bench sidecar:** probes Radeon vs CPU throughput every 2 s, publishes live metrics to the broker; console renders them in the Bench panel.
- **Resilience:** embedder falls back to CPU on OOM and halves batch size on out-of-memory errors; agent reasoning falls back to a scripted reasoner when no inference pod is available.
