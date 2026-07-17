# OpenAlpha Sentinel - System Architecture

| Field | Value |
|---|---|
| Language | English |
| Track | Track 2 - Private AI Agent Development and Local Deployment |
| Team | Coreline Systems Limited |
| Version | Submission candidate |

## 1. Architecture Goals

OpenAlpha Sentinel is designed to:

1. collect configured public open-source strategy material on a recurring schedule;
2. preserve source identity and evidence throughout processing;
3. store cards, retrieval data, jobs, watches, and conversation context locally;
4. answer research questions from retrieved evidence rather than unsupported model memory;
5. run core extraction and generation on one AMD Radeon GPU through ROCm;
6. remain usable as a local MVP before the remote Radeon runtime is available;
7. recover from source failures and process restarts without silently duplicating records.

## 2. System Context

```text
Researcher
   |
   | localhost browser/API
   v
OpenAlpha Sentinel
   |                           |
   | public source collection  | local inference
   v                           v
GitHub / RSS / Atom       llama.cpp on AMD Radeon + ROCm
   |
   | source URLs and revisions
   v
Local SQLite / retrieval index / evidence store
```

Only source collection requires public network access. The intended final model path is a loopback `llama.cpp` endpoint on the Radeon host. Codex may assist development but is not part of the submitted product runtime.

## 3. Container View

```text
┌──────────────────────── Local Web Workbench ────────────────────────┐
│ Overview │ Strategy Cards │ Agent Chat │ Sources │ Jobs │ Watches   │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ local HTTP/JSON
┌───────────────────────────────▼──────────────────────────────────────┐
│ Python Application / API                                              │
│ request validation │ orchestration │ job control │ response shaping   │
└──────────┬────────────────────┬──────────────────────┬─────────────────┘
           │                    │                      │
┌──────────▼─────────┐ ┌────────▼──────────┐ ┌────────▼────────────────┐
│ Source Adapters     │ │ Agent and RAG      │ │ Model Provider          │
│ demo │ GitHub │ RSS │ │ retrieve │ answer  │ │ local dev │ llama.cpp  │
│ normalize │ hash    │ │ compare │ memory   │ │ structured extraction  │
└──────────┬─────────┘ └────────┬──────────┘ └────────┬────────────────┘
           │                    │                      │ loopback
           └────────────────────┼──────────────────────┘
                                v
┌────────────────────────── Local Data Plane ──────────────────────────┐
│ SQLite metadata/cards/evidence/jobs/watches/conversations            │
│ FTS and replaceable vector index │ content-hash cache │ raw metadata  │
└───────────────────────────────────────────────────────────────────────┘
```

## 4. Component Responsibilities

| Component | Responsibility | Trust / execution boundary |
|---|---|---|
| Web workbench | Present corpus state, cards, cited chat, jobs, and watches | Browser talks only to the local application |
| API | Validate requests and expose bounded product operations | Does not expose an arbitrary shell tool |
| Orchestrator | Run finite ingestion and answering workflows; persist job state | Bounded steps and resource limits |
| GitHub adapter | Discover configured public repositories and obtain source metadata/content | Public source data only |
| RSS adapter | Read configured RSS/Atom feeds and normalize entries | Public source data only |
| Demo adapter | Load deterministic fixtures for offline rehearsal and tests | Repository-owned fixtures |
| Normalizer/deduplicator | Canonicalize text, hash content, and prevent exact repeats | CPU/local data operation |
| Strategy-card extractor | Produce schema-constrained research records | Final path uses local Radeon LLM |
| Retrieval layer | Index and rank cards/evidence with lexical and optional vector search | Local database/index |
| Answering layer | Generate answers only after retrieval and attach source references | Final path uses local Radeon LLM |
| Scheduler/watch service | Persist recurring research criteria and enqueue runs | Requires a continuously running process for 24x7 operation |
| Data plane | Preserve cards, evidence, jobs, watches, and local context | Local filesystem/database |

## 5. Ingestion Sequence

```text
User / Scheduler
      |
      v
Create Job -> Discover -> Fetch -> Normalize -> Hash/Deduplicate
                                               |
                                               v
                                    Chunk / Evidence Map
                                               |
                                               v
                                    Extract StrategyCard
                                               |
                                               v
                                    Validate -> Persist -> Index
                                               |
                                               v
                                      Job Result / UI Update
```

The workflow is intended to be idempotent. A source revision and content hash identify already processed material. A failure from one external source should be recorded without corrupting completed local work.

## 6. Question-answering Sequence

```text
Question
   |
   v
Query normalization -> FTS/vector retrieval -> metadata filters
                                             |
                                             v
                                    cards + evidence fragments
                                             |
                                             v
                              local answer generation / fallback
                                             |
                                             v
                         answer + citations + explicit unknowns
```

The generator must not create source URLs, revisions, or evidence locations. Those values come from persisted retrieval records. If retrieved support is insufficient, the answer reports the limitation.

## 7. Core Data Entities

| Entity | Purpose |
|---|---|
| `SourceRecord` | Canonical source identity and collection metadata |
| `ArtifactRevision` | Immutable source version, revision/commit, collection time, and hash |
| `DocumentChunk` | Normalized fragment tied to one artifact revision |
| `StrategyCard` | Versioned normalized strategy research record |
| `Evidence` | Mapping from a card field or answer claim to a stored fragment/source |
| `WatchRule` | Query criteria, source scope, interval, and enabled state |
| `Job` | Ingestion state, counts, errors, retries, and timestamps |
| `ConversationState` | Local multi-turn research context or summary |

## 8. Local API Surface

The workbench consumes a bounded local API. The current frontend contract includes:

```text
GET  /api/dashboard
GET  /api/cards
GET  /api/sources
GET  /api/jobs
GET  /api/notifications
GET  /api/audit
GET  /api/tools
GET  /api/watch-rules
GET  /api/permissions
GET  /api/memory
POST /api/demo/seed
POST /api/discover/github
POST /api/ingest/rss
POST /api/chat
POST /api/watch-rules
POST /api/watch-rules/{rule_id}/run
```

The exact payload schemas are defined by the implementation and tests. Additional bounded endpoints manage offline mode, allowed domains, and local-memory deletion.

## 9. Deployment Modes

### 9.1 Local Development / Rehearsal

- Runs the Python application and browser workbench on localhost.
- Uses deterministic demo data and CPU-compatible lexical retrieval.
- May use a local development model backend where configured.
- Makes no AMD GPU performance claim.

### 9.2 Final Radeon Deployment

- Runs on Ubuntu with ROCm and the pinned `ROCm/llama.cpp` build.
- Loads the verified GGUF model locally.
- Sends extraction and answer requests to the loopback model endpoint.
- Captures reproducibility, request, runtime, utilization, latency, and throughput evidence; actual `37/37` layer assignment is saved, while active peak-VRAM and labeled quality evidence remain release gates.
- Keeps the application process active for recurring collection.

## 10. AMD Radeon / ROCm Boundary

Verified on the Radeon deployment:

- ROCm 7.2.1 environment available;
- `ROCm/llama.cpp` commit `1b99711a5f2582ec99686eb7958844749c223cf5` compiled for `gfx1100`;
- one Radeon device detected;
- approximately `49,136 MiB` VRAM reported;
- Qwen3-8B Q4_K_M hash verified;
- ROCm `llama-bench` recorded `ngl=99` as its GPU-layer configuration;
- clean OpenAlpha runtime commit `8f9aad7a206287b2158f0fccb7a70c4a7373aa87` captured in the manifests;
- clean offload-validation commit `25129cdd853a4fe5a258386350d933339b381028` recorded `37/37` layers on `ROCm0`;
- 35 automated tests passed on the Radeon host with Python 3.12.3;
- separate CLI and loopback HTTP `200` requests returned `backend=llama.cpp-rocm` with a commit-pinned citation to original-file lines `8-28`;
- one controlled stop/start changed all three model/API/worker PIDs and passed both health checks; and
- the post-restart repeated seed created 0 cards and skipped 3 revisions, protected core counts and notifications stayed unchanged, SQLite integrity was `ok`, and foreign-key violations were 0.

Not separately validated or measured in the current evidence set:

- run structured LLM extraction through the local endpoint;
- complete fixed CPU/Radeon/optimized benchmarks;
- capture TTFT percentiles, active peak VRAM, and process/model attribution;
- complete labeled extraction/citation quality evaluation; the final video is recorded and validated, with public publication pending;
- the optional 24-hour soak test was not run and is not claimed as supporting reliability evidence.

## 11. Operability for 24x7 Collection

The watch scheduler is application-level functionality, not a guarantee that a stopped machine continues running. A true 24x7 deployment needs:

- a persistent Radeon server or always-on host;
- a process supervisor or equivalent restart policy;
- persistent database and cache paths;
- observable job failure/retry information;
- a completed 24-hour soak run.

The disposable host uses PID/start-time/log lifecycle management because systemd is offline; systemd units remain available for conventional hosts. One saved trace proves a controlled full stop/start with changed PIDs, healthy endpoints, duplicate-safe reseeding, unchanged notification count, and valid database integrity. It is a short recovery check, not proof of 24x7 operation; the optional 24-hour soak was not run.

## 12. Architecture Decisions

1. Use one bounded orchestrator instead of an open-ended multi-agent swarm.
2. Keep source collection separate from local AI inference.
3. Preserve evidence and revisions as data, rather than asking the model to recreate citations.
4. Keep SQLite/FTS as a deterministic local baseline and make vector retrieval replaceable.
5. Hide model backends behind one provider interface so local development and Radeon deployment share product logic.
6. Do not execute third-party strategy repositories as part of collection.
7. Measure research evidence quality and reproducibility, not expected investment return.
