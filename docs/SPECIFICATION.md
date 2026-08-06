# Project Specification Document (Project Specification Document)

> Track 2: Development & Local Deployment of Private AI Agents
> Platform: AMD Radeon GPU + ROCm | Framework: Agently 4.1.4.1 | Inference backend: vLLM (ROCm)

---

## Part 1: Application Scenarios (Application Scenarios)

### 1.1 User Profile

| Dimension | Description |
|------|------|
| Target users | Insurance business personnel, SME HR, insurance agents |
| Usage frequency | 10-50 queries per day |
| Technical proficiency | Non-technical users interacting through natural language |
| Core needs | Quickly and accurately answer insurance policy questions, reducing training and learning costs |

### 1.2 User Pain Points

1. **Complex policy terms**: Insurance product terms often run to dozens of pages, are dense with jargon, and manual review is extremely inefficient
2. **Multi-document relationships**: Multiple insurance documents are interrelated (e.g., cross-references between exclusion clauses), and manual retrieval makes comprehensive coverage difficult
3. **Long customer wait times**: When customers ask about claims processes, premium calculations, etc., business personnel must consult multiple documents before answering
4. **Cross-session forgetting**: A customer's historical needs and preferences cannot be remembered across sessions, requiring repeated clarification each time

### 1.3 Inputs and Outputs

**Inputs**:
- User natural language questions (e.g., "What is the claims process for employer liability insurance?")
- Insurance product documents (PDF/Word/HTML/TXT/MD, which enter the `downloads/` file area of the Workspace, supporting table and image parsing)
- Historical conversation context (managed by the Session's `context_window` + `memo`)

**Outputs**:
- Accurate document-based answers (with source documents and sections annotated via ref)
- Multi-step task decomposition and execution results (TriggerFlow orchestration)
- Personalized recommendations via cross-session memory (Namespace long-term memory recall)

### 1.4 Usage Boundaries

- Only handles insurance-domain documents and questions; non-insurance questions will be flagged as out of scope
- Document size limits: single file ≤ 10MB, total ≤ 100MB
- Concurrency limit: a single instance supports 10 concurrent sessions
- Language: primarily Chinese, with compatibility for English documents

### 1.5 Privacy and Localization Value

Insurance business involves sensitive customer information and trade secrets. Full local deployment ensures:
- **Data never leaves the enterprise boundary**: all inference, retrieval, and storage are performed locally
- **No cloud dependency**: core inference runs on AMD Radeon GPU + ROCm and does not depend on closed-source remote APIs
- **Auditable traceability**: all file operations and queries are recorded in the audit log

### 1.6 Application Scenario Table

| Scenario | Description | Value | Corresponding capability |
|------|------|------|----------|
| Insurance policy Q&A | Users ask about coverage scope, exclusion clauses, claims conditions | Quick and accurate answers, improved service efficiency | RAG + tool invocation |
| Product comparison analysis | Compare the pros and cons of different insurance products | Helps customers choose suitable products | Multi-step task planning |
| Claims process guidance | Guide users through the claims application steps | Reduces claims consultation costs | Tool invocation + memory |
| Personalized recommendation | Recommend suitable products based on user historical needs | Improves customer satisfaction | Layered long-term memory |

---

## Part 2: Agent Architecture Diagram (Agent Architecture Diagram)

See [ARCHITECTURE.md](./ARCHITECTURE.md) for details.

### Core Architecture Layers

| Layer | Module | Technology choice | Responsibility |
|------|------|----------|------|
| Inference layer | vLLM (ROCm) | Qwen3-8B | Core LLM inference, executed locally (AMD official workshop benchmark model) |
| Embedding layer | BGE-M3 | Local deployment | Vectorization of documents and queries |
| Vector index layer | FAISS + BM25 | faiss-cpu + rank-bm25 | ANN candidate recall (semantic) + term-frequency match recall (exact keywords) |
| Document parsing layer | Multi-format parser | python-docx + BeautifulSoup + pymupdf | PDF/Word/HTML/TXT/MD parsing, tables to Markdown, image descriptions |
| Reranking layer | Cross-Encoder | BAAI/bge-reranker-base | Precise ranking of top-K results, selecting the most relevant top-N |
| Query optimization layer | Query Rewriter | LLM (Qwen3-8B) | LLM rewriting/expansion for ambiguous queries to improve recall |
| Orchestration layer | TriggerFlow | Agently native | Five-step business flow orchestration |
| Tool layer | file_tools / doc_tools / data_query | Custom | File read/write, document analysis, business queries |
| Memory layer | Session / Task / Namespace | Agently | Short-term session + task evidence + long-term preferences |
| Data layer | Workspace | Agently native | Record + File persistence (chunk source data storage) |
| Security layer | permissions / audit | Custom | Directory whitelist + scope filtering + audit |
| Observation layer | benchmark / evaluate | Custom scripts | Performance benchmarks + task quality evaluation |

---

## Part 3: Introduction to Core Capabilities (Introduction to Core Capabilities)

### 3.1 Capability Mapping Table

| Capability | Implementation module | Reference lesson | Competition threshold requirement |
|------|----------|----------|-------------|
| **Local knowledge retrieval (RAG)** | Hybrid retrieval (FAISS semantic + BM25 term-frequency) + Cross-Encoder reranking + Query rewriting + multi-format parsing + Workspace retrieve packaging | Lesson 19 + Lesson 08 + Section 6.6 | One of choose-2-of-5 |
| **Tool invocation** | 4 types of tools (file read/write, document analysis, business data queries, search) | Lesson 06, Lesson 09 | One of choose-2-of-5 |
| **Multi-step task planning** | TriggerFlow five-step orchestration + Step3 reflection validation + failure fallback | Lesson 07, Lesson 09 | One of choose-2-of-5 |
| **Local multi-turn memory** | Session short-term memory + Namespace long-term memory, fully local with no cloud dependency | Lesson 20, Lesson 21 | One of choose-2-of-5 |
| **Permission control & privacy protection** | Session ownership isolation + Workspace scope filtering + directory whitelist + audit log | Lesson 20 + custom | One of choose-2-of-5 |

> The official minimum threshold is to implement at least 2 of the 5 items; this project implements all 5.

### 3.2 Five-Step Business Flow (TriggerFlow orchestration + visible fallback edges)

| Step | TriggerFlow chunk | Business action | Implementation | Fallback edge |
|------|-------------------|----------|----------|--------|
| Step1 | `understand` | Understand natural language | Stateless context passing, Namespace memory recall | — |
| Step2 | `plan` | Generate query method | R1 node structured output routing (rag_query / data_query), supports sub_queries | — |
| Step3 | `validate` | Validate query correctness | Host-based deterministic validation, blocked after 3 failures | `when("retry_plan").to(plan)` |
| Step4 | `fetch` | Fetch query data | Query rewriting → FAISS+BM25 hybrid retrieval → Cross-Encoder reranking → Workspace packaging | `when("retry_plan").to(plan)` |
| Step5 | `answer_and_check` | Generate answer + quality check | R2 generates answer based on evidence + `[[ref:xxx]]` annotation + quality check | `when("retry_answer").to(answer_and_check)` |
| Terminal | `finalize` | Session persistence + memory extraction | Update chat_history + memo persistence + observation collection | `when("blocked").to(finalize)` |

> **P0-1 fix**: the orchestration layer uses the Agently TriggerFlow API (`flow.to()` serial edges + `flow.when()` visible fallback edges),
> and no longer hides `while True` / `for` retry loops inside chunks. Chunks emit signals via `data.async_emit()`,
> and the Flow defines routing via `when(signal).to(chunk)`, achieving graph-visible topological orchestration.

### 3.3 Layered Memory Design

| Memory layer | What it stores | Primary location | Recall method |
|--------|----------|----------|----------|
| Session short-term | Recent conversation, current requirements | context_window + memo | Injected directly into the request |
| Task workspace | Materials, evidence, stage results | Workspace records | retrieve / grep |
| Namespace long-term | Confirmed preferences, cross-task experience | Workspace collection=memory | embedding cosine recall |

### 3.4 Trace Observability (reference Lesson 23)

| Observation level | Object | Main answer |
|----------|------|----------|
| task | One user query execution | Whether it started, completed, or failed |
| stage | The six TriggerFlow chunks | Which responsibility segment executed and how many times |
| operation | Understand, route, validate, retrieve, answer | What each business work delivered |
| attempt | One model request | provider, model, retries, latency, and usage |

Trace records two types of facts: business layer (chunk artifacts) + framework layer (EventCenter Hook), saved as `events.jsonl` + `summary.json`, without judging quality.

### 3.5 Eval Evaluation & Release Gate (reference Lesson 24)

| Evaluation stage | Number of rules | Check method | Examples |
|----------|--------|----------|------|
| retrieval | 4 | host 3 + model 1 | retrieval sufficiency, hybrid retrieval, reranking, relevance |
| citation | 3 | host 3 | citation presence, citation validity, source traceability |
| answer | 4 | host 2 + model 2 | non-empty, no hallucination, accuracy, completeness |
| end_to_end | 1 | model 1 | end-to-end satisfaction |
| session | 2 | host 2 | Session persistence, Trace recording |
| understand | 1 | model 1 | question comprehension relevance |
| fetch | 2 | host 1 + model 1 | query routing, retrieval strategy |

Release gate: pass rate >= 80%, failure rate <= 10%, key stage pass rate >= 80%, evaluation cases >= 10.

### 3.6 Web Service & IM Integration (reference Lesson 25)

| Capability | Implementation | Description |
|------|----------|------|
| Web chat interface | FastAPI + frontend HTML/JS/CSS | Apple HIG style, five-step pipeline real-time progress |
| SSE streaming | POST `/api/chat/stream` | Real-time push of pipeline stages + answers |
| IM integration | Webhook `/api/im/webhook` | WeCom/Feishu/DingTalk three platforms |
| Session management | GET `/api/sessions/{id}/history` | Multi-session history queries |
| Health check | GET `/api/health` | RAG readiness status + model information |

---

## Part 4: Model Introduction & Local Deployment Plan

See [DEPLOYMENT.md](./DEPLOYMENT.md) for details.

### Model Selection

| Model | Purpose | Reason for selection | Quantization strategy |
|------|------|----------|----------|
| Qwen3-8B | Chat LLM | AMD ROCm official benchmark model, thinking/non-thinking switchable, 128K context | GPTQ INT4 / AWQ / INT8 |
| BGE-M3 | Embedding | Multilingual support, 1024 dimensions, suitable for Chinese retrieval | FP16 |
| DeepSeek-R1-Distill-Qwen-7B | Reasoning enhancement | SOTA in mathematical reasoning (MATH 92.8), CoT chain-of-thought | FP16 |

### Deployment Plan

- **Platform**: Radeon Cloud remote container (verified)
- **GPU**: AMD Radeon Graphics (gfx1100, RDNA 3), 48GB VRAM, 96 CU
- **ROCm version**: 6.16.13 (HSA Runtime 1.18)
- **CPU**: 2× AMD EPYC 9334 (64 cores), ~504GB memory
- **Inference framework**: vLLM 0.6.x+ (ROCm build), exposing an OpenAI Compatible API
- **Integration**: Agently set_settings("OpenAICompatible", base_url="http://localhost:8000/v1")
- **Environment evidence**: see [GPU_ENVIRONMENT.md](./GPU_ENVIRONMENT.md)

---

## Part 5: AMD Radeon GPU / ROCm Inference Optimization Notes

See [ROCm_OPTIMIZATION.md](./ROCm_OPTIMIZATION.md) for details.

### Optimization Checklist

| Optimization dimension | Method | Expected benefit |
|----------|------|----------|
| Model quantization | GPTQ INT4 / AWQ INT4 / INT8 | VRAM reduction of 50-75%, throughput improvement |
| Inference backend | vLLM (continuous batching) vs llama.cpp | vLLM throughput 2-3x higher |
| KV-Cache | vLLM PagedAttention | Improved VRAM utilization |
| Batch tuning | max_num_seqs / gpu_memory_utilization | Maximized throughput |
| Context length | Session resize handler + max_model_len | Fewer ineffective tokens |
| Prefix Cache | vLLM automatic prefix caching | KV reuse for identical system prompts |

### Performance Comparison (5 groups, based on 48GB VRAM)

| Group | Quantization | Concurrency | KV-Cache | max_model_len | Expected tok/s |
|------|------|------|----------|---------------|-----------|
| C0 baseline | FP16 | 1 | off | 8192 | ~18 |
| C1 moderate | INT8 | 4 | PagedAttn | 8192 | ~42 |
| C2 extreme | INT4 | 8 | PagedAttn | 4096 | ~59 |
| C3 all-optimized | INT4 | 16 | PagedAttn+Prefix | 4096 | ~62 |
| C4 large-VRAM | FP16 | 16 | PagedAttn+Prefix | 16384 | ~69 |

> Group C4 leverages the 48GB large-VRAM advantage, without quantization but maxing out concurrency and context length, pursuing the highest throughput with no loss of precision.

---

## Part 6: Submission Information

| Item | Content |
|------|------|
| Track | Track 2: Private AI Agents |
| Platform | Radeon Cloud remote container (gfx1100, 48GB VRAM) |
| ROCm | 6.16.13 |
| Framework | Agently 4.1.4.1 |
| Inference backend | vLLM (ROCm build) |
| Vector index | FAISS (faiss-cpu) + BM25 (rank-bm25) |
| Reranking | Cross-Encoder (BAAI/bge-reranker-base) |
| Query optimization | LLM Query Rewriter (optional) |
| Submission method | Fork the designated GitHub repository subdirectory, submit via Pull Request |
| Deadline | 2026-08-06 23:59 (UTC+8) |