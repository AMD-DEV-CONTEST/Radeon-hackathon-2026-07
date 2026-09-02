# OpenAlpha Sentinel

## Project Report for Track 2: Private AI Agent Development and Local Deployment

| Field | Value |
|---|---|
| Team | Coreline Systems Limited |
| Team members | Zeng Baocheng (曾宝成), `csaizbc`, project lead; Yang Jinhao (杨锦皓), `yangjinhao06-droid`, ROCm validation and review |
| Application | OpenAlpha Sentinel |
| Track | Track 2 - Private AI Agent Development and Local Deployment |
| Source repository | https://github.com/coreline-systems/AMD-AI-DevMaster-Hackathon |
| Demo video | [Public 3:39.9 demo](https://github.com/csaizbc/Radeon-hackathon-2026-07/blob/demo-video/OpenAlpha-Sentinel-Demo.en.1080p.mp4) |
| Report version | Submission candidate |

> Submission note: the report distinguishes saved Radeon evidence from results that were not measured in the current evidence set.

## 1. Executive Summary

OpenAlpha Sentinel is a local-first research agent that continuously discovers publicly available open-source quantitative strategy material, converts it into traceable research cards, stores it in a local retrieval system, and answers questions with links back to the original evidence.

The project addresses a practical research problem: strategy descriptions are scattered across code repositories and feeds, terminology is inconsistent, and reported backtest results often omit costs, dates, assumptions, or reproducibility details. OpenAlpha Sentinel does not rank strategies by promised returns and does not trade. It helps a researcher answer narrower, verifiable questions:

- What strategies have been collected?
- Where did each strategy come from, and which source revision was analyzed?
- What rules, markets, time frames, costs, and risks did the author disclose?
- Which relevant facts are unknown or unsupported by the available source?
- What changed when a tracked source was updated?

The local MVP provides a browser workbench and local API for demo data, GitHub discovery, RSS ingestion, strategy-card exploration, source-aware question answering, jobs, and watch rules. The final inference path runs on an AMD Radeon GPU through ROCm and a local `llama.cpp` server. Evidence from clean runtime commit `8f9aad7a206287b2158f0fccb7a70c4a7373aa87` verifies the model hash, a fixed ROCm `llama-bench` snapshot, 35 passing Radeon-host tests, cited CLI and loopback HTTP `200` requests, and one controlled restart trace. A separate clean-load trace at commit `25129cdd853a4fe5a258386350d933339b381028` verifies `37/37` layers on `ROCm0`. The public 3:39.9 final video adds two real cited responses labeled `llama.cpp-rocm` and 96 same-request ROCm SMI activity samples. GPU-backed structured extraction quality, comparable CPU/Radeon optimization, labeled quality results, active peak VRAM, and the optional 24-hour soak remain explicit unmeasured or not-run items.

## 2. Problem and Target Users

### 2.1 Problem

Open-source strategy research is abundant but difficult to monitor and compare reliably:

1. Relevant material is distributed across GitHub repositories, README files, source code, and RSS/Atom feeds.
2. The same strategy family may use different names and incomplete metadata.
3. Backtest claims may omit transaction costs, slippage, benchmark selection, or the test period.
4. A link alone does not preserve the exact revision that supported a conclusion.
5. Sending private research interests and notes to a hosted model is undesirable for many researchers.

### 2.2 Target Users

The primary users are individual quantitative researchers, financial-engineering students, and small research teams that need a repeatable way to monitor public strategy material while keeping their queries, watch lists, notes, and model inference local.

### 2.3 Product Boundary

OpenAlpha Sentinel is a research and education tool. It is not an investment adviser, a return predictor, a broker integration, or an automated trading system. Metrics shown in a card are identified as source-author claims unless the system has separately verified them. Missing evidence is reported as `unknown`; it is not filled in by the model.

## 3. User Experience

The browser workbench is organized around six connected views:

- **Overview** summarizes the local knowledge base, source activity, watch rules, and recent jobs.
- **Strategy Cards** expose normalized strategy attributes, source identity, revision, license information, disclosed evaluation details, risk flags, and evidence.
- **Agent Chat** retrieves relevant cards and answers with source citations rather than unsupported strategy facts.
- **Sources** shows where the indexed material originated.
- **Jobs** shows ingestion activity and failures.
- **Watch Rules** captures recurring research interests for scheduled collection.

A typical workflow is:

1. Seed the deterministic demo corpus or discover a public GitHub repository / ingest an RSS feed.
2. Normalize and deduplicate the retrieved material.
3. create or update a versioned strategy card with evidence linked to the source.
4. Index the content in the local retrieval layer.
5. Ask a natural-language question, inspect the cited cards, and narrow the result through follow-up questions.
6. Save the research criteria as a watch rule and keep the service running for recurring collection.

## 4. System Architecture

```text
Local Browser Workbench
  Overview | Cards | Chat | Sources | Jobs | Watch Rules
                         |
                         v
Local Python API and Agent Orchestrator
  bounded workflow | typed tools | local conversation context | job records
             |                                  |
             v                                  v
Source Adapters                         Local AI Runtime
  GitHub | RSS/Atom | demo snapshot      llama.cpp HTTP API
  fetch | normalize | hash | dedupe       LLM | embeddings
             |                                  |
             +----------------+-----------------+
                              v
Local Data Plane
  SQLite metadata | strategy cards | source evidence | FTS/vector index
  watch rules | jobs | conversation state
```

The source adapters perform network I/O only to collect public source material. Planning, extraction, retrieval, memory, and answer generation are designed to execute locally. The model boundary is provider-based so the local development backend can be replaced by the Radeon `llama.cpp` endpoint without changing the ingestion or retrieval contracts.

## 5. Core Agent Capabilities

Track 2 requires at least two of five core capabilities. OpenAlpha Sentinel is designed to demonstrate all five, with current status stated explicitly below.

| Track capability | OpenAlpha Sentinel implementation | Current status |
|---|---|---|
| Local RAG | Local strategy cards and evidence are indexed and retrieved for source-aware answers. | Verified locally and in separate Radeon CLI and loopback HTTP transcripts with `llama.cpp-rocm` responses and commit-pinned original-line citations; independent load evidence verifies `37/37` layers on `ROCm0` |
| Tool use | The agent uses explicit operations for demo seeding, GitHub discovery, RSS ingestion, retrieval, chat, and watch-rule creation. | Available in the local MVP |
| Multi-step planning | Collection follows a bounded sequence: discover, fetch, normalize, deduplicate, extract, index, and report. | Deterministic workflow available; richer model-assisted planning remains an extension |
| Local multi-turn memory | Conversation context and confirmed research criteria remain within the local application. | Implemented in SQLite and covered by offline integration tests |
| Permission and privacy controls | Source collection is separated from local inference; the application provides domain grants, offline mode, audit records, and memory deletion. | Implemented and covered by offline API tests |

## 6. Data and Evidence Model

Each candidate is represented as a `StrategyCard`. Important fields include:

- identity: card ID, title, card version, and content hash;
- provenance: source type, canonical URL, author or repository, revision/commit, and collection time;
- license: detected SPDX identifier or an explicit unknown/conflict state;
- strategy description: market, asset class, time frame, family, entry/exit logic, indicators, and parameters;
- data and evaluation disclosures: required data, backtest period, costs, slippage, benchmark, and author-reported metrics;
- risk evidence: possible look-ahead bias, survivorship bias, leakage, overfitting, missing costs, or inadequate sample disclosure;
- evidence: the source revision and source fragment supporting a card field;
- quality: a research-readiness breakdown based on traceability, licensing, rule completeness, evaluation disclosure, and reproducibility.

Research readiness measures documentation quality, not expected profitability. No historical-return component is used to turn the score into an investment rating.

## 7. Collection, RAG, and Question Answering

### 7.1 Collection

The MVP supports three reproducible input patterns:

- a deterministic local/demo snapshot for offline rehearsal and testing;
- GitHub discovery for public repositories;
- RSS/Atom ingestion for configured public feeds.

Collected content is normalized and hashed before indexing. Source identity is retained so the UI and chat response can point the user back to the original material. A production 24x7 deployment requires the application process to remain active on the target server; watch rules do not make a stopped laptop or process continuously available.

### 7.2 Retrieval

The local-first retrieval design combines SQLite full-text search with a replaceable vector index. The lexical path gives the MVP a deterministic CPU-compatible fallback, while local embeddings can be enabled on the Radeon server. Metadata filters can narrow results by strategy attributes, source, license state, and risk disclosure.

### 7.3 Answering

The answering workflow retrieves candidate cards before generation. Strategy claims in the answer are tied to retrieved evidence. When the corpus does not contain enough support, the expected behavior is to say so instead of inventing a strategy, source, URL, revision, metric, or risk conclusion.

## 8. AMD Radeon and ROCm Integration

### 8.1 Target Runtime

The final deployment uses a local `llama.cpp` HTTP server built with the ROCm/HIP backend. The local application calls this loopback endpoint for structured extraction and question answering. Embeddings are also intended to run locally, with CPU fallback available during development.

### 8.2 Verified Environment

The following facts were verified on Radeon Cloud on July 16-17, 2026:

| Item | Verified value |
|---|---|
| Image | AMD OneClick Base / ROCm 7.2.1 / Python 3.12.3 |
| Operating system | Ubuntu 24.04.4 LTS |
| GPU architecture | `gfx1100` |
| Reported VRAM | approximately 48 GiB (`49,136 MiB` reported by `llama.cpp`) |
| HIP version | `7.2.53211` |
| `llama.cpp` source | `ROCm/llama.cpp` |
| Verified commit | `1b99711a5f2582ec99686eb7958844749c223cf5` |
| Runtime code | Clean deployment of commit `8f9aad7a206287b2158f0fccb7a70c4a7373aa87` |
| Offload validation code | Clean deployment of commit `25129cdd853a4fe5a258386350d933339b381028` |
| Verified result | Model hash, ROCm `llama-bench`, actual `37/37` layer assignment on `ROCm0`, 35 passing host tests, separate cited CLI/HTTP application paths, and a controlled three-process restart trace |

The cloud platform did not expose a reliable commercial GPU model name, so the report uses `gfx1100 + approximately 48 GiB` until that information can be confirmed.

### 8.3 Selected Model

The selected model is `Qwen/Qwen3-8B-GGUF`, file `Qwen3-8B-Q4_K_M.gguf`, licensed under Apache-2.0. The verified SHA-256 is:

```text
d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785
```

The artifact was downloaded from the ModelScope mirror and hash-checked. The configured deployment requests context `8192`, flash attention, and `-ngl 99`; `generated/rocm-offload-validation-20260717T152430Z.txt` independently records `offloaded 37/37 layers to GPU` on `ROCm0`, a 4,455.34 MiB model buffer, and a 1,152.00 MiB KV buffer. Separate OpenAlpha transcripts capture an SSH-wrapped CLI request and a loopback HTTP POST with status `200`; both report `backend=llama.cpp-rocm` and cite the commit-pinned Daily Equity Mean Reversion fixture at original-file lines `8-28`. These artifacts verify actual layer assignment and the cited application transports, but not per-request GPU attribution. Structured LLM-assisted `StrategyCard` extraction still requires a separate saved validation artifact.

### 8.4 Optimization Plan

The optimization work is designed around measurable pipeline throughput rather than an unsupported speed claim:

- select a GGUF quantization that fits the target VRAM with sufficient context;
- trim navigation, templates, and duplicate text before model inference;
- batch extraction and embedding requests;
- cache extraction and embeddings by source revision and content hash;
- limit output length and validate structured output against the card schema;
- overlap network collection and CPU normalization with bounded GPU work queues;
- compare cold-cache and warm-cache results separately.

## 9. Validation and Results

### 9.1 Current Truthful Status

| Validation item | Status |
|---|---|
| Local MVP startup and browser workflow | Complete |
| Demo seed, source collection paths, cards, chat, jobs, and watch-rule workflow | Complete for local MVP rehearsal |
| ROCm/HIP `llama.cpp` build | Complete |
| Radeon device detection | Complete |
| Model artifact download and SHA-256 verification on Radeon Cloud | Complete |
| Radeon-host automated tests | Complete: 35 passed on Python 3.12.3 |
| Separate Radeon CLI and loopback HTTP cited RAG requests | Complete; HTTP status `200`, backend `llama.cpp-rocm`, commit-pinned citation lines `8-28` |
| Application response transport | Complete for the saved CLI and HTTP transcripts |
| Per-request GPU attribution | Not measured in the current evidence set |
| ROCm `llama-bench` with `-ngl 99` | Complete as a configuration-specific snapshot |
| Actual offloaded-layer count | Complete: `37/37` layers on `ROCm0` in the independent clean-load trace |
| Structured extraction through the Radeon endpoint | Not separately validated |
| Final quality evaluation | Not run in the current evidence set |
| Comparable CPU/GPU optimization study | Not run in the current evidence set |
| Controlled process restart and persistence check | Complete for one saved trace |
| Optional 24-hour continuous-run soak test | Not run (optional) |

The saved five-repetition baseline measured `3033.77 +/- 154.27 tok/s` for `pp512` and `93.47 +/- 0.08 tok/s` for `tg256`. These are direct `llama-bench` results, not a CPU/Radeon improvement claim. The mixed application smoke run completed 15 requests with a 4.8424-second mean, 5.5056-second median, 0.00546-second minimum, and 10.1801-second maximum. It combines deterministic and LLM routes and is not a TTFT distribution.

Local verification used Python 3.11.15 and the deterministic heuristic backend:

- `56` automated tests passed with 81% combined statement coverage;
- citation regressions verify commit-pinned GitHub blob URLs and original-file line offsets after front-matter removal;
- demo seeding processed three fixtures and created three source-linked strategy cards without errors;
- a local research question returned three strategy citations; and
- local API, memory, permission, source, worker, and idempotency paths are covered by the saved JUnit report.

Separately, the final Radeon evidence set is tied to clean runtime commit `8f9aad7a206287b2158f0fccb7a70c4a7373aa87`:

- `generated/rocm-benchmark-20260717T051324Z.txt` captures Ubuntu 24.04.4, Python 3.12.3, HIP 7.2, `gfx1100`, the model and runtime hashes, and the final fixed benchmark snapshot;
- `generated/rocm-test-run-20260717T050554Z.txt` and `generated/rocm-test-results-20260717T050554Z.xml` record 35 passing tests on the Radeon host;
- `generated/rocm-cli-rag-20260717T050851Z.txt` and `generated/rocm-http-rag-20260717T050918Z.txt` separately record real CLI and loopback HTTP `200` requests, `backend=llama.cpp-rocm`, and a commit-pinned citation to original-file lines `8-28`;
- `generated/rocm-restart-trace-20260717T051301Z.txt` records all three PIDs changing across a full stop/start, healthy model/API endpoints, a repeated seed with 0 created and 3 skipped, unchanged protected counts and notifications, `integrity_check=ok`, and 0 foreign-key violations; and
- `generated/rocm-llama-runtime-20260717T051305Z.log` records the process command, model load/listen messages, request timings, and one capture-time GPU-wide snapshot at 63% use and `6,642,937,856` bytes used.

Separately, `generated/rocm-offload-validation-20260717T152430Z.txt` is tied to clean commit `25129cdd853a4fe5a258386350d933339b381028` and records the actual `37/37` layer assignment on `ROCm0`.

The GPU-wide snapshot is not an active peak trace and is not process- or model-resident VRAM. Actual layer assignment is established only by the separate verbose load trace.

### 9.2 Final Benchmark Table

The comparable CPU/Radeon optimization matrix was not run in the current evidence set. Any future comparison must use the same model hash, quantization, prompt version, context budget, and document set for each row.

| Configuration | TTFT P50 / P95 | Decode tokens/s | Embedding docs/s | Cold docs/min | Warm docs/min | Peak VRAM | Failure rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| CPU baseline | Not measured | Not measured | Not measured | Not measured | Not measured | N/A | Not measured |
| Radeon baseline | Not measured | `93.47 +/- 0.08` | Not measured | Not measured | Not measured | Not measured | Not measured |
| Radeon optimized | Not measured | Not separately measured | Not measured | Not measured | Not measured | Not measured | Not measured |

Verified baseline snapshot, reported separately because the full comparable table is incomplete:

| Measurement | Result |
|---|---:|
| `llama-bench pp512`, ROCm, `ngl=99`, 5 repetitions | `3033.77 +/- 154.27 tok/s` |
| `llama-bench tg256`, ROCm, `ngl=99`, 5 repetitions | `93.47 +/- 0.08 tok/s` |
| Mixed application smoke requests | `15/15` completed |
| Mixed application-request mean / median | `4.8424 s / 5.5056 s` |
| Mixed application-request min / max | `0.00546 s / 10.1801 s` |
| GPU-wide capture-time snapshot | 63% GPU use and `6,642,937,856` bytes used; not process- or model-attributed, and active peak was not measured |

Primary optimization result:

```text
Cold-cache throughput improvement: Not measured in the current evidence set
Quality change: Not measured in the current evidence set
Benchmark command / report artifact: ./scripts/benchmark_rocm.sh / generated/rocm-benchmark-20260717T051324Z.txt
```

### 9.3 Final Quality and Reliability Table

| Metric | Result |
|---|---:|
| Required-field correct value or correct `unknown` rate | Not measured in the current evidence set |
| Key categorical-field Macro-F1 | Not measured in the current evidence set |
| License deterministic-field accuracy | Not measured in the current evidence set |
| Citation support rate | Not measured in the current evidence set |
| Resolvable commit-pinned citations with correct original-file lines | Verified for the saved CLI and HTTP examples only; no labeled aggregate rate was measured |
| Repeated seed result | 0 new cards and 3 skipped revisions after restart; protected core counts and notifications unchanged |
| Optional 24-hour soak test | Not run (optional) |
| Process restart/resume without duplicate cards or alerts | Complete for one controlled trace: all three PIDs changed, health passed, integrity `ok`, and 0 foreign-key violations |

## 10. Reproducibility

The source repository is intended to include:

- pinned Python dependencies and configuration examples;
- a deterministic demo corpus that does not depend on live network availability;
- one-command local startup and explicit test commands;
- scripts and documentation for the Radeon `llama.cpp` build and model service;
- fixed benchmark and evaluation manifests;
- model, component, and data-license attribution;
- generated runtime data and model weights excluded from Git.

The final reviewer path should cover installation, demo seeding, local startup, source ingestion, cited Q&A, tests, and the Radeon benchmark without relying on a hosted AI API.

## 11. Innovation and Application Value

OpenAlpha Sentinel is deliberately narrower than a general chatbot. Its differentiating value is the combination of:

1. continuous monitoring rather than one-time question answering;
2. normalized strategy research cards rather than an unstructured link list;
3. source revision and evidence as first-class data;
4. explicit unknowns and disclosure gaps rather than confident completion;
5. a local Radeon inference path that keeps research interests and conversation state private;
6. research-readiness scoring that measures evidence quality, not promised returns.

## 12. Limitations and Next Steps

The MVP does not search the entire internet, execute third-party repositories, run backtests, connect to broker accounts, or recommend trades. GitHub and RSS coverage depends on configured queries and feeds. Continuous collection requires a long-running service on the target machine. PDF/OCR, semantic near-duplicate detection, local reranking, and sandboxed reproducibility checks are future extensions.

The remaining measurement gaps are GPU-backed structured extraction quality, comparable CPU/Radeon optimization and labeled quality benchmarks, TTFT percentiles, and active peak-VRAM tracing; the engineering-strength 24-hour soak test remains optional. Model transfer, hash verification, the configuration-specific ROCm `llama-bench` snapshot, actual `37/37` layer assignment, Radeon-host tests, separate cited CLI/HTTP request evidence, a controlled restart/persistence trace, and the public final product/Radeon video are complete. None of the saved evidence is presented as a measured performance improvement, active peak-memory result, or 24x7 proof.

## 13. Team Contributions

| Member | GitHub ID | Contribution |
|---|---|---|
| Zeng Baocheng (曾宝成), 1154375864@qq.com | [`csaizbc`](https://github.com/csaizbc) | Project lead; application design and implementation; disposable Radeon deployment; benchmarking and evidence; submission engineering |
| Yang Jinhao (杨锦皓), yangjinhao06@gmail.com | [`yangjinhao06-droid`](https://github.com/yangjinhao06-droid) | ROCm validation research; test-evidence documentation; review |

## 14. Deliverables

- Source code and open-source license
- Reproducible project README
- This project report, exported to PDF
- 3-5 minute Radeon demonstration video
- English submission slides (selected supplemental material)
- Benchmark and quality-evaluation results; optional 24-hour stability report if completed
- Third-party component, model, and data-source attribution
- Track 2 pull request to the official hackathon repository
