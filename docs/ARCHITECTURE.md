# Agent Architecture Diagram (Agent Architecture Diagram)

> Includes: model/inference layer, orchestration layer, tool layer, memory layer (short-term/long-term), data layer (RAG), observation & evaluation, security boundary

---

## Part 1: System Architecture Overview

```mermaid
flowchart TB
    U["User natural language query"] --> S1["Step1: understand<br/>TriggerFlow chunk<br/>stateless context passing"]
    S1 --> PLAN["Step2: plan<br/>TriggerFlow chunk<br/>R1 node"]
    PLAN --> VAL["Step3: validate<br/>host deterministic validation<br/>blocked after 3 failures"]
    VAL -->|pass| FETCH["Step4: fetch<br/>hybrid retrieval + Query rewriting<br/>workspace_retrieve"]
    VAL -->|retry_plan signal| PLAN
    VAL -->|blocked signal| FIN["finalize<br/>terminal node"]
    FETCH --> Q1{"Retrieval quality check<br/>≥ 2 items?"}
    Q1 -->|insufficient retry_plan| PLAN
    Q1 -->|insufficient blocked| FIN
    Q1 -->|pass| ANS["Step5: answer_and_check<br/>R2 node + quality check"]
    ANS --> Q2{"Answer quality check"}
    Q2 -->|retry_answer signal| ANS
    Q2 -->|pass/exhausted| FIN
    FIN --> RESP["Natural language response output"]

    subgraph Inference Layer
        LLM["vLLM on ROCm<br/>Qwen3-8B (main model)"]
        REASON["vLLM on ROCm<br/>DeepSeek-R1-Distill-Qwen-7B<br/>(reasoning enhancement, port 8002)"]
        EMB["BGE-M3 Embedding<br/>local deployment"]
    end

    subgraph Vector Index Layer
        FAISS["FAISS Index<br/>IndexFlatIP / IVFFlat / HNSW"]
        BM25["BM25 Index<br/>jieba tokenization + BM25Okapi"]
        RERANK["Cross-Encoder<br/>BAAI/bge-reranker-base"]
        QRW["Query Rewriter<br/>LLM ambiguous query expansion"]
    end

    subgraph Workspace Persistence Layer
        WS["Record: inputs/observations/decisions/outputs<br/>File: downloads/artifacts/reports"]
    end

    subgraph Layered Memory
        M1["Session short-term memory<br/>context_window + memo"]
        M2["Task workspace task memory<br/>evidence + stage results"]
        M3["Namespace long-term memory<br/>embedding cosine recall"]
    end

    subgraph Tool Layer
        T1["file_tools<br/>file read/write"]
        T2["doc_tools<br/>document analysis"]
        T3["data_query<br/>business data query"]
    end

    subgraph Security Layer
        SEC["directory whitelist + scope filtering + audit log"]
    end

    subgraph Observation & Evaluation
        OBS["perf benchmark + task quality evaluation + GPU evidence"]
    end

    LLM --> S1
    LLM --> INT
    LLM --> SUM
    EMB --> FAISS
    EMB --> M3
    FAISS --> RAG
    RAG -.-> WS
    DATA -.-> WS
    FETCH -.-> WS
    S1 -.-> M1
    FETCH -.-> M2
    SUM -.-> M3
    FETCH -.-> T1
    FETCH -.-> T2
    FETCH -.-> T3
    SEC -.-> WS
    SEC -.-> T1
    OUT -.-> OBS
    FETCH -.-> OBS
```

---

## Part 2: RAG Data Pipeline Architecture

```mermaid
flowchart LR
    DOC["Raw documents<br/>PDF/Word/HTML/TXT/MD"] --> PARSE["Multi-format parsing<br/>parser.py<br/>tables→Markdown + image descriptions"]
    PARSE --> CHUNK["Sliding-window chunking<br/>chunker.py<br/>window=512, overlap=100 (20%)<br/>tables/images kept as whole blocks"]
    CHUNK --> SRC["Source data storage<br/>source + title + section_title<br/>written to Workspace Record"]
    SRC --> EMB1["Embedding generation<br/>BGE-M3<br/>1024-dim vectors"]
    EMB1 --> IDX["FAISS index building<br/>indexer.py<br/>IndexFlatIP"]
    CHUNK --> BM25IDX["BM25 index building<br/>bm25_indexer.py<br/>jieba tokenization + BM25Okapi"]
    IDX --> SAVE["Index persistence<br/>faiss.index + id_map.json<br/>+ bm25_index.pkl"]
    BM25IDX --> SAVE

    QUERY["User query"] --> QR{"Query ambiguous?<br/>QueryRewriter"}
    QR -->|yes| REWRITE["LLM rewriting/expansion<br/>supplying context + synonyms"]
    QR -->|no| EMB2["Direct embedding"]
    REWRITE --> EMB2
    EMB2 --> SEARCH["FAISS ANN retrieval<br/>top-K semantic candidates"]
    EMB2 --> BM25S["BM25 retrieval<br/>top-K term-frequency candidates"]
    SEARCH --> FUSE["Hybrid fusion<br/>weighted normalization (FAISS=0.7, BM25=0.3)<br/>deduplication"]
    BM25S --> FUSE
    FUSE --> RERANK["Cross-Encoder reranking<br/>BAAI/bge-reranker-base<br/>top-K → top-N refined ranking"]
    RERANK --> PACK["Workspace packaging<br/>supplementing full chunk_text + source data"]
    PACK --> CTX["ContextPackage<br/>items + diagnostics"]
    CTX --> AGENT["Agent generates answers<br/>ref-attributed sources"]
```

---

## Part 3: Layered Memory Architecture

```mermaid
flowchart TB
    subgraph Session short-term memory
        SW["context_window<br/>recent conversation window"]
        SM["memo<br/>structured summary"]
        SH["analysis handler<br/>judges whether to compress"]
        SR["resize handler<br/>compress key fields"]
        SH --> SR
        SR --> SW
        SR --> SM
    end

    subgraph Task workspace task memory
        TW["Workspace records<br/>observations/decisions"]
        TR["source_ref<br/>evidence citation chain"]
    end

    subgraph Namespace long-term memory
        NW["collection=memory<br/>confirmed preferences"]
        NR["embedding cosine recall<br/>top-K"]
        NG["self-growth candidates<br/>pending rule/skill"]
        NW --> NR
        NG -.->|after confirmation| NW
    end

    USER["User interaction"] --> SW
    SW --> TW
    TW --> NW
    NR -->|recall| CTX["Current context"]
```

---

## Part 4: Module Correspondence

| Architecture layer | Code module | File path | Reference lesson |
|--------|----------|----------|----------|
| Inference layer | vLLM integration (main model Qwen3-8B) | `src/config.py` `make_chat_agent()` | — |
| Inference layer | vLLM integration (reasoning-enhanced DeepSeek-R1-Distill) | `src/config.py` `make_reasoning_agent()` | — |
| Vector index layer | FAISS index management | `src/rag/indexer.py` | Lesson 19 |
| Vector index layer | RAG retrieval entry (hybrid retrieval + reranking) | `src/rag/retriever.py` | Lesson 19 |
| Document parsing layer | Multi-format document parsing (PDF/Word/HTML/TXT/MD) | `src/rag/parser.py` | Lesson 08 |
| Document parsing layer | Sliding-window chunking + source data storage | `src/rag/chunker.py` | Lesson 08 |
| Sparse retrieval layer | BM25 index building and retrieval (jieba tokenization) | `src/rag/bm25_indexer.py` | Lesson 08 |
| Reranking layer | Cross-Encoder precise ranking | `src/rag/reranker.py` | Lesson 08 |
| Query optimization layer | LLM Query rewriting (ambiguous query expansion) | `src/rag/query_rewriter.py` | Custom |
| Orchestration layer | TriggerFlow five-step business flow orchestration | `src/agent/flow.py` | Lesson 25 |
| Orchestration layer | Five-step function library (step1~step5) | `src/agent/pipeline.py` | Lesson 04, Lesson 07 |
| Orchestration layer | Agent main entry | `src/agent/main.py` | — |
| Tool layer | File read/write | `src/tools/file_tools.py` | Lesson 06 |
| Tool layer | Document analysis | `src/tools/doc_tools.py` | — |
| Tool layer | Business data queries | `src/tools/data_query.py` | — |
| Memory layer | Session management | `src/session/handlers.py` + `registry.py` | Lesson 20 |
| Memory layer | Three-layer memory definitions | `src/memory/layers.py` | Lesson 21 |
| Memory layer | Namespace recall | `src/memory/recall.py` | Lesson 21 |
| Memory layer | Self-growth candidates | `src/memory/growth.py` | Lesson 21 |
| Data layer | Document ingestion | `src/workspace/ingest.py` | Lesson 19 |
| Data layer | Packaging retrieval | `src/workspace/retrieve.py` | Lesson 19 |
| Security layer | Permission control | `src/security/permissions.py` | Custom |
| Security layer | Audit log | `src/security/audit.py` | Custom |
| Observation layer | Trace observability (business + framework facts) | `src/observability/trace_log.py` | Lesson 23 |
| Observation layer | Trace view viewer | `scripts/trace_view.py` | Lesson 23 |
| Observation layer | Performance benchmark | `scripts/benchmark.py` | — |
| Observation layer | RAG baseline | `scripts/benchmark_rag.py` | — |
| Evaluation layer | Host-based deterministic checks | `src/eval/checks.py` | Lesson 24 |
| Evaluation layer | Model semantic judge | `src/eval/judge.py` | Lesson 24 |
| Evaluation layer | Evaluation cases and rules | `src/eval/cases.py` + `rules.yaml` | Lesson 24 |
| Evaluation layer | Report & release gate | `src/eval/report.py` | Lesson 24 |
| Evaluation layer | Batch evaluation runner | `scripts/run_eval.py` | Lesson 24 |
| Evaluation layer | Release gate check | `scripts/release_gate.py` | Lesson 24 |
| Service layer | FastAPI web service | `src/api/server.py` | Lesson 25 |
| Service layer | API data models | `src/api/models.py` | Lesson 25 |
| Service layer | IM webhook routing | `src/api/im_router.py` | Lesson 25 |
| Service layer | Frontend chat interface | `static/index.html` + `app.js` + `styles.css` | Lesson 25 |

---

## Part 5: Trace Observability & Eval Evaluation Architecture

### 5.1 Trace Architecture (reference Lesson 23)

Trace records the runtime facts of one TriggerFlow execution without judging quality.

```mermaid
flowchart TB
    subgraph Fact Sources
        BIZ["Business-layer facts<br/>written within chunk"]
        FW["Framework-layer facts<br/>EventCenter Hook subscription"]
    end

    BIZ --> TL["TraceLog.log()<br/>unified structure"]
    FW --> TL

    TL --> EV["events.jsonl<br/>ordered event stream"]
    TL --> RUN["run.json<br/>run result"]
    TL --> SUM["summary.json<br/>six views"]

    subgraph Observation Views
        TV["task_view<br/>execution lifecycle"]
        SV["stage_view<br/>chunk execution statistics"]
        OV["operation_view<br/>business artifacts"]
        AV["attempt_view<br/>model request telemetry"]
        RV["retrieval_view<br/>retrieval candidates + packaging"]
        CV["citation_view<br/>citations + sources"]
    end

    SUM --> TV
    SUM --> SV
    SUM --> OV
    SUM --> AV
    SUM --> RV
    SUM --> CV
```

**Design principles**:
- Trace saves facts; Eval judges quality (the collection layer does not write quality scores)
- Business-layer facts are written by the chunk that owns the artifact (e.g., `business.fetch.retrieved` records the candidate count and packaged item count)
- Framework-layer facts are subscribed via a whitelisted Hook (without copying full Prompt/delta/secrets)
- `bounded()` limits strings to 2000 chars, lists to 50 items, and recursion depth to 8 levels

### 5.2 Eval Evaluation Architecture (reference Lesson 24)

Eval performs segmented quality judgments based on runtime facts, supporting host-based deterministic checks + model-based semantic judging.

```mermaid
flowchart LR
    CASES["Evaluation cases<br/>insurance_qa_50.json"] --> RUNNER["run_eval.py<br/>batch runner"]
    RULES["Evaluation rules<br/>rules.yaml"] --> RUNNER

    RUNNER --> AGENT["InsuranceAgent.query()<br/>Agent under test"]
    AGENT --> RESULT["Run result<br/>+ trace_events"]

    RESULT --> HOST["Host checks<br/>checks.py<br/>10 deterministic rules"]
    RESULT --> JUDGE["Model judge<br/>judge.py<br/>7 semantic rules"]

    HOST --> REPORT["eval_results.json"]
    JUDGE --> REPORT

    REPORT --> GATE["release_gate.py<br/>release gate"]
    GATE --> PASS{"Pass?"}
    PASS -->|Yes| SHIP["Releasable"]
    PASS -->|No| FIX["Needs fixing"]
```

**Release gate criteria**:

| Gate | Threshold | Description |
|------|------|------|
| Number of evaluation cases | >= 10 | Ensures statistical significance |
| Pass rate | >= 80% | At the end_to_end level |
| Failure rate | <= 10% | End-to-end failure ceiling |
| Key stage pass rate | >= 80% | retrieval + citation + answer |

### 5.3 Web Service Architecture (reference Lesson 25)

```mermaid
flowchart TB
    USER["User browser"] -->|"HTTP/SSE"| API["FastAPI Server<br/>src/api/server.py"]
    WECOM["WeCom"] -->|"Webhook"| IM["IM Router<br/>src/api/im_router.py"]
    FEISHU["Feishu"] -->|"Webhook"| IM
    DINGTALK["DingTalk"] -->|"Webhook"| IM

    API --> AGENT["InsuranceAgent<br/>src/agent/main.py"]
    IM --> AGENT

    AGENT --> FLOW["TriggerFlow<br/>src/agent/flow.py"]
    FLOW --> TRACE["TraceLog<br/>src/observability/trace_log.py"]
    FLOW --> RAG["RAG retrieval<br/>src/rag/retriever.py"]

    subgraph Frontend
        HTML["index.html<br/>chat interface"]
        JS["app.js<br/>SSE streaming"]
        CSS["styles.css<br/>Apple HIG"]
    end

    API --> HTML
    API --> JS
    API --> CSS
```

---

## Part 6: RAG Retrieval Architecture Selection: Custom Approach vs Agently Native Approach

> Review basis: [agently-request/references/knowledge-base.md](https://github.com/AgentEra/Agently-Skills/blob/main/skills/agently-request/references/knowledge-base.md)

### 6.1 Selection Conclusion

This project adopts a **custom retrieval pipeline** (FAISS + BM25 + Cross-Encoder) rather than Agently's native `RecordStore → ContextSource → ContextReader` chain. This is not an ad-hoc decision but a comprehensive trade-off based on ROCm hardware compatibility, competition scoring requirements, and performance controllability.

### 6.2 Reasons for Selection

**Reason one: Chroma is incompatible with this project's ROCm environment**

Agently's native `vector_store_provider="auto"` prefers Chroma, but AMD's official ROCm Infinity Hub shows Chroma supports only MI200/MI100/MI50 + ROCm v5.x [$TRAE_REF](https://www.amd.com/en/developer/resources/infinity-hub/chroma.html). This project's environment is gfx1100 (RX 7900 XTX) + ROCm 6.16.13, where Chroma cannot run and can only fall back to a SQLite vector table, completely losing GPU acceleration. FAISS's HIP backend natively supports AMD GPUs, with an 18x speedup verified on MI250 [$TRAE_REF](https://blog.csdn.net/gitblog_00702/article/details/151504966).

**Reason two: the native approach lacks BM25 hybrid retrieval and Cross-Encoder reranking**

`RecordStore.retrieve(method="auto")` does not support BM25 hybrid retrieval, and `ContextReader` has no built-in Cross-Encoder reranking stage. In the competition scoring, "functional completeness" (40 points) and "technical depth" (30 points) require demonstrating advanced techniques such as hybrid retrieval and reranking. With the native approach, these capabilities still need to be built from scratch and are no simpler than the custom approach.

**Reason three: the custom approach yields 4-5 additional quantifiable demonstration points on the ROCm scoring dimension**

| Scoring element | Custom approach | Native approach |
|---------|---------|---------|
| AMD GPU inference | LLM + **FAISS GPU** + **Cross-Encoder GPU** + **Embedding GPU** | LLM + Embedding GPU |
| Quantization optimization | LLM INT4 + **FAISS FP16** | LLM INT4 |
| Number of tunable parameters | 15+ | 3-4 |
| Quantifiable benchmark comparisons | 5+ groups (CPU vs GPU, Flat vs IVF, FAISS vs BM25, etc.) | 0-1 groups |
| Graceful degradation paths | 3 levels | 1 level |

**Reason four: significant FAISS performance advantage**

Benchmarking shows FAISS has an average query latency of 0.34ms, while ChromaDB is 2.58ms — FAISS is 7.6x faster [$TRAE_REF](https://www.xugj520.cn/en/archives/vector-database-comparison-chromadb-pinecone-faiss.html). On AMD GPUs, the FAISS IVF index is another 18x faster than CPU [$TRAE_REF](https://blog.csdn.net/gitblog_00702/article/details/151504966).

### 6.3 Boundary Mapping Between the Custom and Native Approaches

| Custom component | Corresponding Agently native component | Currently replaced? |
|---------|----------------------|------------|
| `records/*.json` + `FaissIndexer` | `RecordStore` (SQLite + vector index) | Yes — custom FAISS replaces it |
| `BM25Indexer` | No native equivalent | Custom supplement (native does not support BM25) |
| `CrossEncoderReranker` | No native equivalent | Custom supplement (native does not support Cross-Encoder) |
| `retrieve_context()` scope filtering | `ContextReader` + `ContextBudget` | Partial — the custom budget is a global hardcoded value |
| `RAGRetriever` | `ContextSource` + `TaskContext` | Yes — the custom call chain is shorter |

### 6.4 Known Limitations & Future Migration Path

**Known limitations**:
- No `ContextIndex` cache reuse (each `retrieve()` re-executes FAISS + BM25)
- No `Progressive Disclosure` (consumer-bound budgets, staged reads)
- No `Cross-Source` capability (integrating regulation libraries and case libraries in the future requires extension)
- `budget_chars=2000` is globally hardcoded and does not vary by consumer or stage

**Migration path** (planned after the competition):
- Phase 1: Migrate `records/*.json` to `RecordStore`, keeping the FAISS index
- Phase 2: Wrap a `RAGContextSource` adapter and connect it to `TaskContext`
- Phase 3: Use `ContextReader` to replace the budget trimming in `retrieve_context()`
- Estimated migration cost: 12-18 hours

---

## Part 7: Data Flow Description

### 7.1 Document Ingestion Process

```
User uploads document → parser.py multi-format parsing (PDF/Word/HTML/TXT/MD)
                         → extract text + tables (to Markdown) + image descriptions
                         → output ParsedDocument {title, source, sections[]}
                         → chunker.py sliding-window chunking (window=512, overlap=100, 20%)
                         → table/image paragraphs kept as whole blocks; text paragraphs split by sliding window
                         → each chunk carries source, title, section_title, section_type
                         → write_chunks_to_workspace → records/*.json (source data persistence)
                         → BGE-M3 embedding (batch of 32)
                         → FAISS index building + BM25 index building (jieba tokenization)
                         → index persistence (faiss.index + id_map.json + bm25_index.pkl)
```

### 7.2 Query Flow (including topology repair loop + RAG enhancement)

```
User asks → Step1: stateless context passing (P2-C, does not directly modify chat_agent)
         → [outer loop] Step2: R1 intent recognition (rag_query / data_query), supporting sub_queries fan-out (P2-D)
         → [inner loop] Step3: host deterministic validation, blocked after 3 failures (C3)
         → Step4: retrieval flow (R5 Query rewriting + hybrid retrieval + reranking)
           → [R5] Query ambiguous? → LLM rewriting/expansion (supplying context + synonyms)
           → FAISS ANN retrieval (top-K semantic candidates)
           → BM25 retrieval (top-K term-frequency candidates) (if BM25 is available)
           → hybrid fusion: weighted normalized scores (FAISS=0.7, BM25=0.3) + deduplication
           → Cross-Encoder reranking: top-K → top-N refined ranking (if reranker is available)
           → Workspace packaging (P0-A: pass to retrieve_context, supplement full chunk_text + source data)
         → P1 quality check: retrieval ≥ 2 items? if insufficient, fall back to Step2 retry (up to 2 times)
         → Step5: R2 generates answers based on evidence + ref-attributed sources
         → P3 quality check: answer length / citation count / ref markers? if not passed, fix loop (up to 2 times)
         → Session updates conversation history
         → Namespace updates long-term memory (as applicable)
```

### 7.3 Memory Promotion Process

```
Session short-term memory → analysis handler detects the window is too long
                → resize handler compresses it into a memo
                → key facts written to Task workspace (source_ref)
                → confirmed preferences promoted to Namespace (evidence_refs)
                → self-growth candidates generated (pending) → merged after confirmation
```