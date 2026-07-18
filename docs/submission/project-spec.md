# Perciqa Cortex — Project Specification Document

> AMD AI DevMaster Hackathon 2026 — Track 2: Development & Local Deployment of Private AI Agents
> Submission: `"Track 2, Perciqa, Cortex"`

---

## 1. Application Scenarios

### Primary: F1 Cybersecurity SOC Consortium

Multiple Security Operations Centers (SOCs) share threat intelligence via Cortex. SOC Alpha's agent detects a new TTP attributed to threat actor X; SOC Beta's agent queries the fabric for "what's new on X?" and retrieves Alpha's finding with cryptographic provenance — which SOC produced it, what source data was hashed, and when. Neither SOC exposes probe placement, customer data, or analyst identities.

### Secondary: Healthcare R&D Loop

A hospital's clinical agent retrieves findings from a research lab's literature-analysis agent. Patient data never leaves the hospital; research methods never leave the lab. The same fabric protocol routes articles, scoped by `partner:<org_did>`, proving domain generality.

---

## 2. Agent Architecture

```
                     ┌──────────────────────────────────┐
                     │      Cortex Fabric Broker         │
                     │  (WebSocket, topic+scope ACL)     │
                     └──────────┬──────────────┬─────────┘
                                │              │
                ┌───────────────▼──┐  ┌────────▼──────────────┐
                │ Tenant A (SOC ▲) │  │ Tenant B (SOC β)      │
                │                 │  │                        │
                │ ┌───────────┐   │  │  ┌───────────┐         │
                │ │ Agent ▲   │   │  │  │ Agent β   │         │
                │ │(LangChain)│   │  │  │(LlamaIndex)│         │
                │ └─────┬─────┘   │  │  └─────┬─────┘         │
                │       │         │  │        │               │
                │ ┌─────▼──────┐  │  │  ┌─────▼──────┐        │
                │ │ CortexNode │  │  │  │ CortexNode │        │
                │ │ - Embedder │  │  │  │ - Embedder │        │
                │ │ - Store    │  │  │  │ - Store    │        │
                │ │ - Signer   │  │  │  │ - Signer   │        │
                │ │ - Trust    │  │  │  │ - Trust    │        │
                │ └────────────┘  │  │  └────────────┘        │
                └─────────────────┘  └────────────────────────┘
```

### Core Capabilities

| Capability | Description |
|---|---|
| **Publish** | Agent produces a finding → node signs (Ed25519) → embeds on GPU → broadcasts to peers within scope ACL |
| **Query** | Agent asks "what's known about X?" → node embeds query → semantic retrieval over fabric partition → ranked by hybrid (cosine + trust) score |
| **Derive** | Agent composes new article from existing ones → provenance graph extends → trust propagates from cited sources |

---

## 3. Data Model

### MemoryArticle (atomic unit)

| Field | Type | Description |
|---|---|---|
| `id` | sha256 hex | Deterministic from canonical content |
| `type` | enum | finding, insight, precedent, procedure, warning |
| `content` | str (≤2000 chars) | Natural-language summary |
| `payload` | dict | Structured typed data (e.g., CVE record, ATT&CK technique) |
| `embedding` | float32[384] | L2-normalized, computed on local GPU at publish |
| `provenance` | struct | Producer agent DID, org DID, source data hash, timestamp |
| `scope` | str | private, partner:<org_did>, public |
| `agent_signature` | bytes | Ed25519 over canonical fields |
| `trust_score` | float [0,1] | Computed from reputation, recency, citation depth |

### Lifecycle States

```
Drafted → Signed → Indexed → Published → Cited → Archived
```

---

## 4. Model Introduction & Local Deployment Plan

### Embedding Model

| Property | Value |
|---|---|
| **Model** | BAAI/bge-small-en-v1.5 |
| **Parameters** | 33M |
| **Output dimension** | 384 |
| **Deployment** | PyTorch-on-ROCm, loaded locally in-process |
| **GPU path** | ROCm 7.2 via `torch.cuda` (HIP backend) |
| **CPU fallback** | Identical pipeline, same output quality |

### Agent Reasoning Model

| Property | Value |
|---|---|
| **Primary** | Llama-3 8B via vLLM-on-ROCm |
| **Fallback** | Qwen2.5-Coder-14B (Gemma 4 12B alternative) |
| **Integration** | OpenAI-compatible HTTP API from `CortexAgent`'s `ScriptedReasoner` |
| **Deployment** | vLLM server on same GPU pod, `--host 0.0.0.0 --port 8000` |

### Deployment Topology (Hackathon)

```
Single machine (or GPU pod):
├── cortex-broker               :7432
├── cortex-node A (SOC Alpha)   local
├── cortex-node B (SOC Beta)    local
├── cortex-console (FastAPI)    :8080
└── cortex-bench (sidecar)      per node
```

All processes on one machine for demo reliability. Production: one node per customer site on AMD MI300X.

---

## 5. Optimization for Inference Speed on AMD Radeon GPU

### Embedding Pipeline

| Optimization | Benefit |
|---|---|
| **ROCm-native PyTorch** | HIP backend provides zero-copy tensor ops on Radeon |
| **Batch inference** | Batch of 16 processed in ~9.45 ms median (vs 65 ms CPU) |
| **Float16 storage** | Half-precision vectors halve memory without ranking degradation |
| **CUDA graph warmup** | First forward pass triggers kernel compilation; subsequent calls hit compiled kernels |
| **OOM halve-and-retry** | On GPU OOM, batch size halves automatically and persists the effective size |

### Measured Performance (AMD MI300X)

| Metric | Radeon MI300X | CPU (Apple M4 Pro) | Target |
|---|---|---|---|
| Single embed latency (median) | **6.68 ms** | — | ≤30 ms |
| Batch 16 latency (median) | **9.45 ms** | 65.35 ms | ≤80 ms |
| Batch 16 throughput | **1,004 embeds/sec** | 244.8 embeds/sec | ≥350 embeds/sec |
| ROCm/HIP version | **7.2.53211** | N/A | — |

### Vector Search

| Backend | Scenario | Performance |
|---|---|---|
| FAISS-gpu | Radeon available | GPU-accelerated similarity search over 10k+ articles |
| hnswlib (CPU) | CPU fallback | Pure-CPU HNSW, sub-50ms queries over 10k articles |

### Trust Scoring

Trust formula runs on CPU (sub-millisecond per article). The GPU is used for the compute-heavy embedding and retrieval paths, which constitute >95% of the inference workload in the publish/query loop.

---

## 6. AMD Radeon GPU / ROCm Integration Summary

| Function | Model | Radeon path | Status |
|---|---|---|---|
| Article embedding | bge-small-en-v1.5 | PyTorch-on-ROCm | ✅ Verified: 6.68 ms latency |
| Semantic retrieval | FAISS-gpu / hnswlib | FAISS on ROCm | ✅ HNSW fallback tested |
| Agent reasoning | Llama-3 8B / Qwen-2.5 | vLLM-on-ROCm | 🔧 Configurable via API |
| Benchmark display | cortex-bench | Per-node sidecar | ✅ Live metrics in Console |
