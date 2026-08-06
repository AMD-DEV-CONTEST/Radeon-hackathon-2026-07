# Project Specification Document — VEIL

## 1. Application Scenario

Document publishing, disclosure, and regulatory data-sharing are high-stakes activities. Traditional document sanitization systems rely on Named Entity Recognition (NER) or regular expressions to redact direct identifiers like names or social security numbers. However, they miss contextual and correlational leaks:
* **Contextual Leaks**: "The CEO of the electric vehicle company founded in 2003" identifies Elon Musk just as clearly as his name.
* **Correlational Leaks**: Combining disjointed fragments of information across multiple separately-redacted documents (e.g. tenure, city of residence, and minor role descriptions) allows an attacker to intersect records against public databases (like registries or org charts) and uniquely identify individuals.

VEIL takes an offensive, adversarial stance to solve this. It simulates a motivated adversary by running five concurrent LLM attack agents, each leveraging a different attack vector (stylometric patterns, vector-retrieved open-source records, corporate database histories, container layouts, and demographic intersections) to reconstruct identities. 

By analyzing the document through these adversarial eyes, VEIL calculates and applies the minimal set of repairs (generalizations, pseudonymizations, or suppressions) necessary to plug the leaks, ensuring the document remains secure while retaining maximum utility.

---

## 2. Agent Architecture Diagram

```
                              ┌──────────────────────────┐
                              │     Target Document      │
                              └────────────┬─────────────┘
                                           │
                                  [planner.py: plan()]
                                           │
                                           ▼
                              ┌──────────────────────────┐
                              │    Dynamic Execution     │
                              │       Triage Plan        │
                              └────────────┬─────────────┘
                                           │
                                           ▼
                 ┌──────────────────────────────────────────────────┐
                 │          Adversarial Attack Persona Wave         │
                 │         (Concurrent Async Agent Execution)       │
                 │                                                  │
                 │  ┌──────────────┐ ┌─────────────┐ ┌───────────┐  │
                 │  │ Journalist   │ │   Insider   │ │ Stylomet- │  │
                 │  │ (OSINT RAG)  │ │ (Entity DB) │ │  rist     │  │
                 │  └──────┬───────┘ └──────┬──────┘ └─────┬─────┘  │
                 │         │                │              │        │
                 │  ┌──────▼───────┐ ┌──────▼──────┐       │        │
                 │  │Data-Broker   │ │Layout-Forens│       │        │
                 │  │(Demographics)│ │ (Geometry)  │       │        │
                 │  └──────┬───────┘ └──────┬──────┘       │        │
                 └─────────┼────────────────┼──────────────┼────────┘
                           │                │              │
                    [corpus_search]   [entity_ledger]      │
                           │                │              │
                           ▼                ▼              ▼
                 ┌──────────────────────────────────────────────────┐
                 │                  Tool Registry                   │
                 │  (Dense Qdrant Vector + Lexical SQLite FTS RAG)  │
                 └─────────────────────────┬────────────────────────┘
                                           │
                                           ▼
                              ┌──────────────────────────┐
                              │       Adjudicator        │
                              │ (Confidence & De-dupe)   │
                              └────────────┬─────────────┘
                                           │
                                           ▼
                              ┌──────────────────────────┐
                              │      Risk & Utility      │
                              │    Scoring Metrics       │
                              └────────────┬─────────────┘
                                           │
                                           ▼
                              ┌──────────────────────────┐
                              │      Guardian Agent      │
                              │ (Minimal Edit Generator) │
                              └────────────┬─────────────┘
                                           │
                                           ▼
                              ┌──────────────────────────┐
                              │    Apply Redactions      │
                              └────────────┬─────────────┘
                                           │
                                           ▼
                              ┌──────────────────────────┐
                              │     Adversarial Wave     │
                              │       Verification       │
                              │   (Fresh Re-Attack Loop) │
                              └────────────┬─────────────┘
                                           │
                 [No claims reproduced?] ──┼──> [Yes] ──> Resolved
                                           │
                                           └──> [No] ───> Next Iteration
```

---

## 3. Core Capabilities

### 3.1 Local Knowledge Retrieval (RAG)
VEIL uses a hybrid local RAG system implemented in `veil/tools/corpus_search.py`. 
* **Dense Retrieval**: Utilizes a local `bge-small-en-v1.5-local` embedding model and a file-based Qdrant client to fetch semantically relevant public records or company filings.
* **Lexical Retrieval**: Uses a local SQLite FTS5 virtual table to query exact string matches, capturing rare codenames, dates, or ID numbers that embeddings blur.
* **Fusion**: Integrates candidate chunks using Reciprocal Rank Fusion (RRF).

### 3.2 Tool Invocation
Adversarial agents dynamically execute tools via a schema-enforced tool registry (`veil/tools/registry.py`). Registered tools include:
* `corpus_search`: Journalist agent queries public registries for correlation evidence.
* `entity_ledger`: Insider agent inspects accumulated cross-document identity attributes.
* `candidate_set_size`: Data-Broker queries demographics to estimate k-anonymity.

### 3.3 Multi-Step Task Planning
Before running any inference models, the `Planner` ([planner.py](file:///Users/tushar/Desktop/VEIL-hackathon-submission/veil/veil/agents/planner.py)) triages the input document. It decomposes the task by analyzing characteristics in microseconds:
* If input is plain text, it skips the `Layout-Forensicist` agent to save GPU cycles.
* If text length is under 1,200 characters, it skips the `Stylometrist` to avoid noise fingerprinting.
* It dynamically revises the iteration budget: high-risk documents get the full three passes, while low-risk documents terminate immediately.

### 3.4 Local Cross-Document Memory
To prevent an attacker from combining multiple documents to reconstruct an identity, VEIL maintains a persistent `entity_ledger` database ([entity_ledger.py](file:///Users/tushar/Desktop/VEIL-hackathon-submission/veil/veil/tools/entity_ledger.py)). Using deterministic hashing, VEIL maps individuals to content-addressed aliases (e.g. `PERSON_3F9A2C`), consistently tracking their accumulated attributes across distinct sessions.

### 3.5 Permissions & Privacy Controls
VEIL implements role-based access control (RBAC):
* **Auditor**: Full visibility into reasoning chains, evidence citations, and configuration controls.
* **Redactor**: Allowed only to view findings and execute edits; reasoning details are projected out of responses to prevent the tool itself from leaking details.
* **Viewer**: Allowed only to see the final sanitized document and summary risk scores.
* **Egress Guard**: An AsyncHTTPTransport subclass that blocks all outbound socket calls, enforcing local-only execution.

---

## 4. Model Introduction & Local Deployment Plan

### 4.1 Models Used
* **Primary LLM**: `Qwen/Qwen2.5-7B-Instruct-AWQ` (serving via vLLM). It provides state-of-the-art instruction following, supports long contexts, and runs efficiently under 4-bit AWQ quantization.
* **Embedding Model**: `sentence-transformers/bge-small-en-v1.5` (running locally via SentenceTransformers).

### 4.2 Local Deployment Plan
VEIL runs entirely on a single AMD Radeon GPU host environment:
1. **vLLM Inference Server**: Serves the primary model locally on port 8000. It is configured to run on loopback only.
2. **FastAPI Application Server**: Runs on port 7860, exposing the Single-Page Application (SPA) frontend.
3. **Database**: Implements a local file-based SQLite database for persistence (documents, sessions, entity ledgers, audit trails) and a local Qdrant directory for vector storage.
4. **Egress Block**: Hardware egress rules or transport-layer loopback bounds block external network calls, ensuring the data never leaves the host.

---

## 5. Optimization Description for AMD Radeon GPU

VEIL's performance is optimized to exploit the specific strengths of the AMD Radeon + ROCm backend:

### 5.1 Deterministic Prefix KV Cache Reuse
Adversarial audits involve multiple persona queries against the same document. In naive setups, sending separate prompts forces the engine to compute the document's KV cache five times. 
VEIL constructs prompts deterministically: **`[Document Text]`** is placed first as a shared prefix, while the **`[Persona System Instructions]`** are appended at the end. Since the prefixes are byte-identical, vLLM's automatic prefix cache computes the document KV cache *once* and reuses it across all five persona runs. This yields a **9.82x speedup** (0.35s cached vs 3.47s uncached) and a **95% cache hit rate**.

### 5.2 Concurrent Persona Execution
Rather than executing agent runs serially, VEIL utilizes Python's `asyncio.gather` semaphores to dispatch all five agent queries to vLLM concurrently. This saturates the AMD Radeon GPU's compute pipelines, leveraging vLLM's continuous batching scheduler to raise throughput to **`29.57 tokens/second`** during concurrent waves.

### 5.3 Triton-Based AWQ Quantization on ROCm
By loading the model in 4-bit quantized AWQ format using the ROCm-optimized Triton kernels (`VLLM_USE_TRITON_AWQ=1`), VEIL reduces GPU VRAM consumption to only **`5.43 GiB`**, avoiding memory bottlenecks and leaving abundant headroom on consumer AMD Radeon cards (like the RX 7900 XTX) for concurrent application workloads.
