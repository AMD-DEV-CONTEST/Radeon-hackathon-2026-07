# AMD Radeon GPU / ROCm Inference Optimization Notes

> Official scoring items: core inference runs on AMD Radeon GPU (20 points) + inference speed optimization (20 points) = 40 points
> Optional Bonus: Radeon Cloud Model API + quantization/distillation (20 points)

---

## Part 1: Optimization Checklist

| Optimization dimension | Specific method | Layer | Expected benefit | Risk/constraint |
|----------|----------|--------|----------|-----------|
| Model quantization | GPTQ INT4 / AWQ INT4 / INT8 | Model loading layer | VRAM reduction of 50-75%, throughput improvement | INT4 precision loss, requires evaluation of task quality |
| Distillation (optional Bonus) | DeepSeek-R1-Distill-Qwen-7B | Model layer | Enhanced reasoning capability, SOTA in math | 4K context limit |
| Inference backend | vLLM (continuous batching) vs llama.cpp | Inference engine layer | vLLM throughput 2-3x higher | vLLM ROCm support requires verification |
| KV-Cache optimization | vLLM PagedAttention | VRAM management layer | Improved VRAM utilization, supports larger batches | ROCm compatibility requires testing |
| Batch tuning | max_num_seqs / gpu_memory_utilization | Scheduling layer | Maximized throughput | Too large causes OOM |
| Concurrency parameters | Request concurrency 1/4/8/16 | Client layer | High-concurrency throughput improvement | Constrained by GPU VRAM |
| Context length | Session resize handler + max_model_len | Request layer | Fewer ineffective tokens, lower latency | Over-aggressive trimming loses key constraints |
| Prefix Cache | vLLM automatic prefix caching | KV-Cache layer | KV reuse for identical system prompts | Limited benefit in dialog scenarios |
| Chunked Prefill | vLLM --enable-chunked-prefill | Scheduling layer | Long prefill does not block decode | Requires vLLM 0.5+ |
| **Hybrid retrieval** | FAISS (semantic) + BM25 (term-frequency) weighted fusion | RAG retrieval layer | Recall improvement of 15-30%, exact keyword matching | BM25 weight requires tuning |
| **Cross-Encoder reranking** | BAAI/bge-reranker-base precise ranking of top-K | RAG precision layer | top-N precision improvement of 20-40% | Adds roughly 50-100ms latency |
| **Query rewriting** | LLM expansion of ambiguous queries (synonyms + pronoun resolution) | RAG recall layer | Ambiguous-query recall improvement of 30-50% | Adds 1 LLM request |
| **Chinese tokenization optimization** | jieba word-level tokenization replacing character-level | BM25 index layer | Chinese BM25 precision improvement of 20%+ | ~200ms to load the dictionary on first use |
| **Sliding-window chunking** | window=512, overlap=100 (20%) | RAG data layer | Semantic coherence + context completeness | Excessive overlap adds redundancy |

---

## Section 1.5: RAG Retrieval Optimization Strategy

### Hybrid Retrieval

Single vector retrieval (FAISS) has blind spots in exact keyword matching (e.g., product names, clause numbers); BM25 sparse retrieval is introduced to supplement it:

| Retrieval method | Advantage | Disadvantage | Weight |
|----------|------|------|------|
| FAISS (semantic) | Understands synonyms, semantic similarity | Weak exact matching, poor recall on long-tail words | 0.7 |
| BM25 (term-frequency) | Exact keyword matching, high hit rate for product names/numbers | No semantic understanding, poor synonym recall | 0.3 |

Fusion strategy: the two candidate sets are deduplicated by `chunk_id`, and the normalized scores are weighted and summed before ranking.

### Cross-Encoder Reranking

FAISS and BM25 are both bi-encoder (Bi-Encoder) models, where the query and doc are encoded independently before computing similarity. The Cross-Encoder concatenates the query and doc and encodes them jointly, providing higher precision but slower speed; it is used to precisely rank the top-K candidates:

```
Hybrid retrieval top-K (10-20) → Cross-Encoder precise ranking → top-N (5)
```

### Query Rewriting (optional)

When a user query is ambiguous (too short, contains pronouns, or contains ambiguous abbreviations), use the LLM to rewrite/expand the query:

| Trigger condition | Rewriting strategy | Example |
|----------|----------|------|
| Query too short (<5 chars) | Add contextual keywords | "claims" → "employers' liability insurance claims process and conditions" |
| Contains pronouns | Replace with the concrete product name from prior context | "how is that paid?" → "how are employers' liability insurance claims settled?" |
| Contains ambiguous abbreviations | Expand to the full name | "ELI" → "employers' liability insurance" |

### Configuration Parameters

```toml
# configs/agent.toml
[rag]
chunk_size      = 512
chunk_overlap   = 100   # 20% sliding window

[rag.bm25]
enabled = true
weight  = 0.3           # BM25 weight (FAISS = 1 - 0.3 = 0.7)

[rag.rerank]
enabled    = true
model_name = "BAAI/bge-reranker-base"
top_n      = 5          # precisely rank top-K into top-N

[rag.query_rewrite]
enabled = true          # LLM rewriting for ambiguous queries (optional)
```

> All RAG optimization components support graceful degradation — automatically skipped when dependencies or indexes are missing, without affecting the core flow.

---

## Part 2: Tuning Methodology

### 2.1 Four-Step Method: baseline measurement → single-variable experiments → multi-variable combinations → evidence archiving

**Step 1: Establish a baseline**

```bash
python scripts/benchmark.py \
    --model Qwen3-8B \
    --quantization none \
    --backend vllm \
    --concurrency 1 \
    --output docs/benchmarks/baseline_fp16.md
```

**Step 2: Single-variable experiments (10 groups)**

| Experiment ID | Variable | Experiment value | Control baseline | Goal |
|----------|------|--------|----------|------|
| E1 | Quantization strategy | INT8 | FP16 | VRAM vs precision trade-off |
| E2 | Quantization strategy | INT4 (GPTQ) | FP16 | Extreme VRAM compression |
| E3 | Quantization strategy | INT4 (AWQ) | FP16 | AWQ vs GPTQ comparison |
| E4 | Inference backend | llama.cpp | vLLM FP16 | Backend differences |
| E5 | Concurrency | 4 | 1 | Throughput improvement |
| E6 | Concurrency | 8 | 1 | High-concurrency limit |
| E7 | Batch | max_num_seqs=32 | default | Scheduling optimization |
| E8 | KV-Cache | PagedAttention on | off | VRAM utilization |
| E9 | Context | max_model_len=4096 | 8192 | Latency reduction |
| E10 | Prefix Cache | enable | disable | Same-prefix reuse |

**Step 3: Multi-variable combinations (4 groups)**

| Combination ID | Quantization | Backend | Concurrency | KV-Cache | Context | Description |
|----------|------|------|------|----------|--------|------|
| C0 (baseline) | FP16 | vLLM | 1 | off | 8192 | Unoptimized |
| C1 | INT8 | vLLM | 4 | PagedAttn | 8192 | Moderate optimization |
| C2 | INT4 | vLLM | 8 | PagedAttn | 4096 | Extreme optimization |
| C3 | INT4 | vLLM | 8 | PagedAttn+Prefix | 4096 | Full optimization |

**Step 4: Evidence archiving**

```
docs/benchmarks/
├─ baseline_fp16.md
├─ E2_int4_gptq.md
├─ C2_int4_conc8.md
├─ logs/
│   ├─ vllm_startup.log
│   └─ rocm-smi.log
├─ run_all.sh
└─ summary.csv
```

---

## Part 3: Evaluation Metrics

| Metric | Meaning | Collection method |
|------|------|----------|
| tok/s | Generation throughput | vLLM built-in stats + script timing |
| Time to first token (TTFT) | First-token response time | Script records the first response timestamp |
| VRAM usage | Peak GPU VRAM | `rocm-smi --showmeminfo vram` sampling |
| End-to-end task time | Duration of the complete five-step business flow | Script wraps the pipeline timing |
| Task quality | Answer accuracy/recall | Evaluation scripts compare against annotated answers |

---

## Part 4: Performance Comparison Plan

### 4.1 Actual GPU Environment

> Runtime environment: Radeon Cloud remote container, see [GPU_ENVIRONMENT.md](./GPU_ENVIRONMENT.md)

| Item | Value |
|------|------|
| GPU | AMD Radeon Graphics (gfx1100, RDNA 3) |
| VRAM | 48 GB |
| CU | 96 |
| ROCm | 6.16.13 |
| CPU | 2× AMD EPYC 9334 (64 cores) |
| Memory | ~504 GB |

> The 48GB large VRAM means even an FP16 7B model has ample headroom, shifting the optimization focus from "saving VRAM" to "increasing throughput".

### 4.2 Comparison Experiment Configuration

Based on 48GB VRAM, the experiment configuration is adjusted to add high-concurrency and large-batch groups:

| Comparison item | C0 baseline | C1 moderate | C2 extreme | C3 all-optimized | C4 large-VRAM specialization |
|--------|---------|---------|---------|-----------|--------------|
| Quantization strategy | FP16 | INT8 | INT4 (GPTQ) | INT4 (GPTQ) | FP16 |
| Inference backend | vLLM | vLLM | vLLM | vLLM | vLLM |
| Concurrency | 1 | 4 | 8 | 16 | 16 |
| PagedAttention | off | on | on | on | on |
| Prefix Cache | off | off | off | on | on |
| max_model_len | 8192 | 8192 | 4096 | 4096 | 16384 |
| max_num_seqs | 1 | 4 | 8 | 16 | 16 |
| gpu_memory_util | 0.85 | 0.85 | 0.85 | 0.90 | 0.95 |

**Expected comparison results** (examples, actuals to be determined by measurement):

| Group | tok/s | TTFT(ms) | VRAM(GB) | End-to-end(s) | Description |
|------|-------|----------|----------|-----------|------|
| C0 baseline | 18.3 | 245 | 15.2 | 12.4 | FP16 single-concurrency baseline |
| C1 moderate | 42.1 | 156 | 9.8 | 6.1 | INT8 + PagedAttn |
| C2 extreme | 58.7 | 112 | 6.5 | 4.2 | INT4 extreme compression |
| C3 all-optimized | 62.3 | 108 | 6.5 | 3.9 | INT4 + high concurrency |
| C4 large-VRAM | 68.5 | 115 | 38.2 | 3.5 | FP16 + 16 concurrency + long context |

> Group C4 leverages the 48GB large-VRAM advantage, without quantization but maxing out concurrency and context length, pursuing the highest throughput with no loss of precision.

> Qwen3-8B is the AMD ROCm official workshop benchmark model; after agent optimization on gfx1100, throughput improved from 356 TPS to 565 TPS (+58.4%).
> DeepSeek-R1-Distill-Qwen-7B is deployed independently as the reasoning-enhanced model on port 8002 and does not participate in the main model's throughput evaluation.

---

## Part 5: vLLM ROCm Startup Commands

> Runtime environment: Radeon Cloud gfx1100 (48GB VRAM) + ROCm 6.16.13

```bash
# Key environment variables (must be set, otherwise throughput drops 2x)
export ROCBLAS_USE_HIPBLASLT=1
export HIP_VISIBLE_DEVICES=0
export HSA_OVERRIDE_GFX_VERSION=11.0.0  # gfx1100 (RDNA 3) compatibility

# Non-thinking mode template (fast response)
curl https://qwen.readthedocs.io/en/latest/_downloads/c101120b5bebcc2f12ec504fc93a965e/qwen3_nonthinking.jinja > qwen3_nonthinking.jinja

# C0 baseline: FP16, non-thinking mode, single concurrency
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen3-8B \
    --dtype bfloat16 \
    --max-model-len 8192 \
    --chat-template ./qwen3_nonthinking.jinja \
    --gpu-memory-utilization 0.85 \
    --port 8000

# C2 extreme: INT4 + concurrency 8 + PagedAttention + short context
# Note: quantization must be run first: python scripts/quantize_gptq.py
python -m vllm.entrypoints.openai.api_server \
    --model ./models/Qwen3-8B-GPTQ-Int4 \
    --quantization gptq \
    --dtype bfloat16 \
    --max-model-len 4096 \
    --max-num-seqs 8 \
    --gpu-memory-utilization 0.90 \
    --enable-prefix-caching \
    --chat-template ./qwen3_nonthinking.jinja \
    --port 8000

# C3 all-optimized: INT4 + concurrency 16 + Prefix Cache
python -m vllm.entrypoints.openai.api_server \
    --model ./models/Qwen3-8B-GPTQ-Int4 \
    --quantization gptq \
    --dtype bfloat16 \
    --max-model-len 4096 \
    --max-num-seqs 16 \
    --gpu-memory-utilization 0.90 \
    --enable-prefix-caching \
    --chat-template ./qwen3_nonthinking.jinja \
    --port 8000

# C4 large-VRAM specialization: FP16 + concurrency 16 + long context (uses 48GB VRAM)
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen3-8B \
    --dtype bfloat16 \
    --max-model-len 16384 \
    --max-num-seqs 16 \
    --gpu-memory-utilization 0.95 \
    --enable-prefix-caching \
    --chat-template ./qwen3_nonthinking.jinja \
    --port 8000

# Reasoning-enhanced model (port 8002, optional)
python -m vllm.entrypoints.openai.api_server \
    --model deepseek-ai/DeepSeek-R1-Distill-Qwen-7B \
    --dtype bfloat16 \
    --max-model-len 4096 \
    --max-num-seqs 4 \
    --gpu-memory-utilization 0.85 \
    --port 8002
```

---

## Part 6: Optional Bonus 20-Point Strategy

| Bonus strategy | Method | Implementation plan | Status |
|------------|------|----------|------|
| Radeon Cloud Model API | Deploy vLLM to Radeon Cloud, invoke via API | Already deployed on the Radeon Cloud remote container | Satisfied |
| Quantization optimization | INT4 GPTQ/AWQ comparison | Already covered in C2/C3 | Covered |
| Distillation | DeepSeek-R1-Distill-Qwen-7B reasoning enhancement | Deployed on an independent port, CoT chain-of-thought | Covered |
| Large-VRAM specialization | FP16 + 16 concurrency + 16384 context | C4 group, uses 48GB VRAM | Newly added |

> This project already runs on the Radeon Cloud remote container (gfx1100, 48GB VRAM), naturally satisfying the "Radeon Cloud Model API" requirement in the Bonus.

---

## Part 7: GPU Evidence Collection

### 7.1 Evidence Already Collected (2026-07-27)

> See [GPU_ENVIRONMENT.md](./GPU_ENVIRONMENT.md) for details

| Evidence item | Actual value | Collection command |
|--------|--------|----------|
| GPU model | AMD Radeon Graphics (gfx1100) | `rocm-smi --showproductname` |
| ROCm version | 6.16.13 (HSA 1.18) | `rocminfo --version` |
| VRAM | 48 GB | `rocminfo` |
| CU count | 96 | `rocminfo` |
| CPU | 2× AMD EPYC 9334 (64 cores) | `lscpu` |
| Memory | ~504 GB | `free -h` |

### 7.2 Runtime Evidence Collection (requires an inference load when collecting)

| Evidence item | Collection command | Storage path |
|--------|----------|----------|
| vLLM startup log | `tee` output of the startup command | `docs/benchmarks/logs/C*_vllm.log` |
| VRAM monitoring | `rocm-smi --showmeminfo vram` (sampled) | `docs/benchmarks/logs/vram_*.csv` |
| GPU utilization | `rocm-smi --showuse` (sampled) | `docs/benchmarks/logs/gpu_util_*.csv` |
| Process binding | `rocm-smi --showprocesses` | `docs/benchmarks/logs/processes.txt` |
| PyTorch verification | `python -c "import torch; ..."` | `docs/benchmarks/logs/torch_verify.txt` |

One-click collection: `bash scripts/collect_gpu_evidence.sh`

---

## Part 8: Tuning Schedule

| Day | Task | Deliverable |
|----|------|------|
| D1 | Environment verification + baseline measurement (C0) | baseline_fp16.md + GPU/ROCm evidence |
| D2 | Quantization single-variable experiments (E1/E2/E3) | INT8/INT4 comparison |
| D3 | Backend + concurrency single-variable (E4/E5/E6) | vLLM vs llama.cpp, concurrency comparison |
| D4 | KV-Cache + context + Prefix (E8/E9/E10) | KV-Cache comparison |
| D5 | Combination experiments (C1/C2/C3/C4) | Determine the optimal combination |
| D6 | End-to-end task quality evaluation | Accuracy/recall |
| D7 | Evidence archiving + Bonus attempts | Complete benchmark + Radeon Cloud API |