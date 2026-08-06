# System Architecture

## High-Level Architecture

```text
+---------------------------------------------------------------------+
|                              GRADIO UI                              |
|   +-----------------------+       +-----------------------------+   |
|   |                       |       |                             |   |
|   |      Chat Window      |       |      Privacy Dashboard      |   |
|   |      (2/3 width)      |       |         (1/3 width)         |   |
|   |                       |       |                             |   |
|   +-----------------------+       +-----------------------------+   |
+---------------------------------------------------------------------+
                                  |
                                  v
+---------------------------------------------------------------------+
|                    ORCHESTRATION / ROUTING LAYER                    |
|                                                                     |
|   +-------------------------------------------------------------+   |
|   |           BunkerOrchestrator - DSPy intent router           |   |
|   |            (routes each turn to RAG or the Agent;           |   |
|   |               LM router + heuristic fallback)               |   |
|   +-------------------------------------------------------------+   |
+---------------------------------------------------------------------+
                 |                                 |
                 v                                 v
|    +-------------------------+       +-------------------------+    |
|    |         RAG PATH        |       |        AGENT PATH       |    |
|    |-------------------------|       |-------------------------|    |
|    |    BunkerMultiHopRAG    |       |      DspyReActAgent     |    |
|    |    (DSPy) ChromaDB +    |       |  (dspy.ReAct) plan_task |    |
|    |     ROCm embeddings,    |       |   planner + Permission  |    |
|    |   grounded [pid] cites  |       |    Controller gating    |    |
|    +-------------------------+       +-------------------------+    |
                 |                                 |
                 v                                 v
+---------------------------------------------------------------------+
|                            SERVICES LAYER                           |
|                                                                     |
|   +-------------------------------------------------------------+   |
|   |        DSPy Tool Wrappers - 9 gated tools (live path)       |   |
|   |       RAG - ChromaDB (telemetry off) + ROCm embeddings      |   |
|   |        Memory - SQLite SessionStore + ContextManager        |   |
|   |       Audit - JSONL log of every inference & tool call      |   |
|   |     DataFlow Monitor - real-time local/external tracker     |   |
|   |                                                             |   |
|   |   dspy_runtime.BUNKER_LM - process-wide DSPy LM (audited)   |   |
|   +-------------------------------------------------------------+   |
+---------------------------------------------------------------------+
                                  |
                                  v
+---------------------------------------------------------------------+
|                           INFERENCE LAYER                           |
|                                                                     |
|   +---------------+    +-----------------+    +-----------------+   |
|   |  vLLM (ROCm)  |    | Secondary Local |    | Radeon Cloud API|   |
|   |   (Primary)   |    |    (Fallback)   |    | (Bonus Fallback)|   |
|   +---------------+    +-----------------+    +-----------------+   |
|                                                                     |
|                  Optional: Ollama backend (config)                  |
|      Quantizer is an offline dev utility - not in runtime chain     |
+---------------------------------------------------------------------+
                                  |
                                  v
+---------------------------------------------------------------------+
|                            HARDWARE LAYER                           |
|                   AMD Radeon GPU (MI300X / RX7900)                  |
+---------------------------------------------------------------------+
```

## Agent Runtime Loop (ReAct)

```text
                 +--------------------------+
                 |      Gradio UI           |
                 |  Chat + Privacy Dashboard|
                 +------------+-------------+
                              | user turn
                              v
                 +--------------------------+
                 |   BunkerOrchestrator     |
                 |  DSPy intent router +    |
                 |  heuristic fallback      |
                 +------------+-------------+
                              | route
              +---------------+----------------+
              |                                |
              v                                v
    +---------------------+         +---------------------+
    |      RAG PATH       |         |      AGENT PATH     |
    |  BunkerMultiHopRAG  |         |  DspyReActAgent     |
    |  ChromaDB + ROCm    |         |  plan_task planner  |
    |  embeddings         |         +----------+----------+
    |  grounded [pid]     |                    |
    +---------------------+                    v
                                  +--------------------------+
                                  |   dspy.ReAct loop        |
                                  |   Thought -> Action ->   |
                                  |   Observation            |
                                  +------------+-------------+
                                               | tool action
                                               v
                                  +--------------------------+
                                  | PermissionController.gate|
                                  |  (dangerous tools ask    |
                                  |   the user in the UI)    |
                                  +------------+-------------+
                                               v
                                  +--------------------------+
                                  |  Gated DSPy tool wrapper |
                                  |  file / email / calendar |
                                  |  / web / RAG / memory    |
                                  +------------+-------------+
                                               | observation
                                               v
                                  +--------------------------+
                                  | AuditLogger + DataFlow   |
                                  | Monitor (100% local)     |
                                  +------------+-------------+
                                               |
                            loop until Final Answer
                                               v
                                  +--------------------------+
                                  |     Final Answer -> UI   |
                                  +--------------------------+
```

1. A user turn arrives via Gradio.
2. `BunkerOrchestrator` routes it to the RAG path or the Agent path.
3. **Agent path**: `plan_task` decomposes the request, then the `dspy.ReAct` loop cycles Thought → Action → Observation.
4. Each Action goes through `PermissionController.gate()` — safe tools auto-approve, dangerous tools request the user in the UI.
5. The action runs as a gated DSPy tool wrapper; its result (or error) becomes the next Observation.
6. Every inference and tool call is written to the `AuditLogger` and flagged local-only by the `DataFlowMonitor`.
7. The loop repeats until a Final Answer is reached and rendered to the UI.

## Layer Breakdown

### Presentation Layer
The front-end user interface is built using Gradio, with a left/right column split:
1. **Chat Interface** (2/3 width): The primary interaction space for the user to prompt the agent.
2. **Privacy Dashboard** (1/3 width): Displays real-time metrics from the `DataFlowMonitor` and `AuditLogger`, assuring the user of 100% local processing. Refreshes every 2 seconds.
3. **Agent Thoughts**: An accordion showing the agent's reasoning (Thought / Action / Observation) between turns.
4. **Permission Toggles**: Checkboxes for File/Email/Calendar/Web access. Note: these are display-only today — the runtime approval decision happens inside the tool bodies via `PermissionController` (see Agent Layer).

### Orchestration / Routing Layer
- **BunkerOrchestrator** (`src/agent/orchestrator.py`): The single entry point from the UI. Routes each user turn to the **RAG path** (document questions) or the **Agent path** (tool-using requests) using a DSPy `ChainOfThought` intent router with a deterministic keyword-heuristic fallback. It also threads answered turns back into conversation history so follow-ups reference earlier turns without re-running retrieval.

### Agent Layer (DSPy-native)
- **DspyReActAgent** (`src/agent/dspy_agent.py`): The live agent loop, built on `dspy.ReAct`. The hand-written `ReActAgent` (`src/agent/react_loop.py`) is kept intact for A/B comparison but is **not** wired into `main.py`.
- **Task Planner**: A DSPy `plan_task` signature (`src/agent/signatures.py`) decomposes complex requests into steps that feed the ReAct signature. The older hand-written `TaskPlanner` (`src/agent/planner.py`) remains for A/B.
- **PermissionController** (`src/agent/permission_controller.py`): The gatekeeper. Safe tools (`file_read`, `file_search`, `file_list`, `calendar_query`) auto-approve; dangerous tools (`file_write`, `email_draft`, `email_search`, `calendar_create_event`, `web_search`) always require approval via `gate()`, called from inside each tool body so an LM has no prompt-level bypass.

### Services Layer
- **DSPy Tool Wrappers** (`src/tools/dspy_tools.py`): The 9 live tools as permission-gated `dspy.Tool`s — `file_read/write/search/list`, `email_draft/search`, `calendar_query/create_event`, `web_search`. Each wrapper records an audit + data-flow event and calls `PermissionController.gate()` for dangerous tools.
- **MCP-style ToolRegistry** (`src/tools/registry.py`): Retained for metadata/schema-validation and A/B; not instantiated at runtime (the live path uses the DSPy wrappers).
- **RAG**: The DSPy `BunkerMultiHopRAG` (`src/rag/multihop_rag.py`) — multi-hop retrieval over ChromaDB (telemetry disabled) using ROCm GPU embeddings (`BAAI/bge-large-en-v1.5`), producing grounded `[pid]`-cited answers.
- **Memory**: SQLite `SessionStore` (`src/memory/session_store.py`) plus `ContextManager` for token budgeting.
- **AuditLogger**: JSONL event log (`data/audit/audit.jsonl`) recording every inference and tool call.
- **DataFlowMonitor**: Real-time local vs external data tracking backing the privacy dashboard.
- **dspy_runtime.BUNKER_LM** (`src/dspy_runtime.py`): The process-wide DSPy LM bound to the configured backend (`vllm` | `ollama` | `radeon_api`), with caching disabled so every request stays observable.

### Inference Layer
- **Primary**: vLLM deployed natively on ROCm for maximum throughput.
- **Fallbacks**: A secondary local vLLM model, then the Radeon Cloud API (always 4-bit quantized, bonus fallback). An optional Ollama backend is supported via config.
- **Quantizer** (`src/inference/quantizer.py`): An offline dev utility (AutoGPTQ INT4/INT8) for preparing models — it is **not** part of the runtime fallback chain.

### Hardware Layer
AMD Radeon hardware executing PyTorch operations via ROCm (HIP). Verified via `torch.version.hip`.

## Data Flow
1. User submits a prompt via the **Gradio UI**.
2. **BunkerOrchestrator** routes the turn — DSPy intent router, falling back to a deterministic heuristic — to the **RAG path** or the **Agent path**.
3. **RAG path**: `BunkerMultiHopRAG` runs `num_hops` retrieval hops against the local ChromaDB store, accumulating notes, then grounds a final answer with `[pid]` citations (backtrack-and-retry on grounding violations).
4. **Agent path**: the planner builds a step plan, then the `dspy.ReAct` loop cycles Thought → Action → Observation.
5. Actions invoke **permission-gated DSPy tool wrappers**; dangerous tools are gated by `PermissionController` inside the tool body.
6. Every tool execution is written to the **AuditLogger** and recorded by the **DataFlowMonitor** as local-only.
7. All inference goes through **dspy_runtime.BUNKER_LM** → local vLLM-ROCm (primary), with the `ModelManager` fallback chain (secondary local → Radeon Cloud API) last.
8. Steps repeat until a Final Answer; the turn is threaded back into conversation history for follow-ups.

## Component Interaction Matrix
| Component | Calls | Called By |
| :--- | :--- | :--- |
| BunkerOrchestrator | LM router, BunkerMultiHopRAG, DspyReActAgent | Gradio UI |
| DspyReActAgent | plan_task, permission-gated DSPy tool wrappers | BunkerOrchestrator |
| DSPy tool wrappers | PermissionController.gate, AuditLogger, DataFlowMonitor, tool funcs | dspy.ReAct |
| PermissionController | — (decides inside tool bodies) | tool wrappers |
| BunkerMultiHopRAG | VectorStore.search (ChromaDB), DSPy ChainOfThought modules | BunkerOrchestrator |
| VectorStore | ROCEmbeddings, ChromaDB | BunkerMultiHopRAG |
| dspy_runtime.BUNKER_LM | vLLM / Ollama / Radeon Cloud API | all DSPy modules |
| ModelManager | VLLMServer (primary, secondary), RadeonCloudAPI | startup lifecycle |

## Deployment Architecture
- **Docker**: The entire stack is containerized. A `docker-compose.yml` orchestrates the Gradio app, the vLLM server, and a persistent volume for SQLite/ChromaDB.
- **vLLM Server**: Runs on a dedicated port handling OpenAI-compatible API requests.
- **Gradio / FastAPI**: The main application acts as a client to the vLLM server, ensuring loose coupling.

## Failure Modes and Fallbacks
- **OOM (Out of Memory)**: If the primary vLLM fails to allocate, `ModelManager` shifts to the secondary local model, then to the 4-bit Radeon Cloud API fallback.
- **Tool Failure**: If a tool raises an exception, the traceback is returned to the agent as a string so it can reason about the failure and retry.
- **Agent Degradation**: If the LM returns malformed output, `DspyReActAgent.run` returns a generic fallback response instead of crashing the UI.
- **RAG Grounding Failure**: If the answer keeps citing passages not present in context after `max_backtracks`, `BunkerGroundingError` halts the pipeline instead of returning ungrounded output.
- **Context Length Exceeded**: `ContextManager` truncates the oldest non-system messages dynamically.
