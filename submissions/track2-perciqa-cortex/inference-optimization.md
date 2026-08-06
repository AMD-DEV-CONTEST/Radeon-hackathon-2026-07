# Inference Speed Optimization on AMD (ROCm)

> **Perciqa Cortex — AMD AI DevMaster Hackathon 2026, Track 2 (Radeon/ROCm)**
> All numbers below were measured live against the remote ROCm pod during the demo; the console Bench panel renders the same metrics in real time.

---

## 1. Stack

| Layer | Choice |
|---|---|
| GPU | AMD Radeon PRO W7900 (RDNA3, 49 GB VRAM; rocm-smi device `D7070910`) |
| ROCm | HIP 7.2.53211 |
| PyTorch | 2.10.0+git8514f05 (ROCm build) |
| Embedding model | BAAI/bge-small-en-v1.5 (384-dim) |
| Inference model | Perciqa/Aurora-Code-Mini-V1 via vLLM |
| Monitoring | `rocm-smi` sensor backend |

---

## 2. Why GPU embedding is load-bearing here, not decorative

Every publish and every query embeds text on the local node. In the reference SOC fabric that means: when SOC Alpha's agent publishes a finding, the node signs the article, computes its embedding on the Radeon GPU via ROCm, and broadcasts it to peers. When SOC Beta's agent queries the fabric, its node embeds the query and runs semantic retrieval over its local partition. Both steps sit on the hot path, so embedding throughput and latency directly bound how fast findings propagate and how fast queries answer.

On the Radeon the same embedding work that takes ~175 ms of CPU time per article completes in a fraction of that on the Radeon, which is what makes the fabric feel live rather than batchy.

---

## 3. Measured results (live, remote ROCm pod)

Bench sidecar probes Radeon and CPU throughput every 2 s and publishes live metrics to the broker; the console Bench panel renders them. Representative live sample:

| Metric | Radeon (GPU) | CPU | Speedup |
|---|---|---|---|
| Embeddings / second (batch=16) | ~2,060 | ~5.7 | ~360× |
| Queries / second | ~214 | ~2.2 | ~97× |
| P95 query latency | ~4.6 ms | — | — |
| GPU memory utilization | ~93% | — | — |

Batch-mode embedding throughput exceeds **2,000 embeds/sec** on the Radeon, versus single-digit embeds/sec on CPU — over two orders of magnitude faster. Per-embed latency on the GPU lands in the low single-digit milliseconds; the p95 query path (embed query + vector search) completes in ~5 ms.

These are live remote-GPU numbers, not pre-recorded: the bench sidecar runs continuously on the pod and the console shows them updating in real time.

---

## 4. What was done to get there

### 4.1 PyTorch-ROCm embedding on the Radeon
The embedder (`cortex/node/embedder.py`) initializes with backend `auto` → detects ROCm/CUDA and loads the model on `cuda`. A `bge-small` model (384-dim) was chosen deliberately: small enough to fit alongside the inference model on a 49 GB card, strong enough for threat-intel semantics. Batch size 16 with `fallback_on_oom` enabled.

### 4.2 vLLM-served reasoning on the same pod
Aurora Code Mini V1 runs under vLLM on the ROCm pod at `http://localhost:8000/v1` (32,768-token context). The derive step (LLM synthesis of an insight article from retrieved findings) routes through it, so weights and inference stay inside the sovereign GPU boundary. The SSH tunnel keeps the inference path sovereign: model weights, embeddings, and inference never leave the remote GPU.

### 4.3 Bench sidecar for honest, live numbers
`cortex.bench` (`bench/runner.py`) runs four probes every 2 s: embed-Radeon, embed-CPU, query-Radeon, query-CPU. It publishes a metrics envelope to the broker; the console's Bench panel (GPU status card + node performance) consumes them via `/ws/metrics`. It also exposes Prometheus `/metrics` on :9464. This is the same code path that produced the numbers in §3.

### 4.4 Resilience by design
- **OOM fallback:** if the GPU embedder hits an out-of-memory error, it halves the batch size and retries; on repeated failure it falls back to the CPU embedder (`fallback_on_oom`).
- **Embedder health fallback:** the node's health loop detects a wedged GPU embedder and switches to CPU (`node.embed.fallback_cpu` event).
- **Reasoning fallback:** if no inference pod is reachable, agent reasoning degrades to a scripted reasoner — the demo still runs, with a graceful message instead of a hard failure.
- **Vector index fallback:** HNSW index that fails to load after a crash starts fresh and re-indexes rather than aborting startup.

---

## 5. Verifying live

```bash
# ROCm / GPU info
curl https://cortex.perciqa.com/api/rocm-info
# → {"hip_version":"7.2.53211","vram_total_mb":49136.0,
#    "device_name":"D7070910","rocm_active":true,...}

# Model status
curl https://cortex.perciqa.com/api/llm-info
# → {"status":"online","model":"Perciqa/Aurora-Code-Mini-V1",...}

# Models served by vLLM
curl http://localhost:8000/v1/models
```

The console Bench panel at `cortex.perciqa.com` shows the GPU-vs-CPU numbers updating live, with the rocm-smi memory gauge and the p95 latency.
