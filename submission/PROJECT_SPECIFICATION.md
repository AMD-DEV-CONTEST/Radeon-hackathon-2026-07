# KinetAios — Local-First Multi-Engine AI Agent Dashboard

**Track 2: Development & Local Deployment of Private AI Agents**

---

## 1. Application Scenarios

### 1.1 Problem Statement

Existing AI agent tools fall into two camps, both with fundamental limitations:

1. **Thin chat wrappers** (most "AI desktop apps") — forward messages to an API, stream tokens back. No real tool access, no file system, no memory beyond the context window. They are glorified API clients.

2. **CLI launchers** — spawn `claude` or `codex` as subprocesses and pipe output. Users must install those CLIs, pay for their subscriptions, and accept vendor lock-in. No customization, no extensibility.

**KinetAios is the third path: a from-scratch ReAct agent engine that runs entirely on your desktop, with 12 built-in tools, cross-session long-term memory, file snapshot rollback, and support for any LLM provider — no account, no relay server.**

### 1.2 Target Users

| User | Scenario |
|------|----------|
| **Software engineers** | Code audit, bug investigation, multi-file refactoring, git operations — agent reads, writes, and edits files with automatic snapshot rollback |
| **Data analysts** | Excel/CSV ingestion, cross-source analysis, ECharts HTML report generation — all via natural language |
| **IoT / Hardware developers** | Serial communication, BLE, Modbus, sensor lookup, oscilloscope diagnostics — 17 domain plugins for embedded workflows |
| **Privacy-conscious users** | All data stays local (SQLite), API key encrypted with OS-native DPAPI/Keychain, zero telemetry |
| **Multi-model researchers** | Run Direct (ReAct), Claude Code, and Codex engines side-by-side from one window with cross-engine memory |

### 1.3 Key Differentiators

| Capability | KinetAios | Claude Desktop | Cursor | Cherry Studio | ChatGPT Desktop |
|---|---|---|---|---|---|
| Self-built ReAct engine (not a wrapper) | ✅ | — | — | — | — |
| 12 built-in local tools (shell/file/grep/git/web) | ✅ | — | — | — | — |
| File write auto-snapshot + one-click rollback | ✅ | — | — | — | — |
| Cross-session long-term memory (SQLite + FTS5 + embedding) | ✅ | — | — | — | — |
| Three engines in one window (Direct / Claude Code / Codex) | ✅ | — | — | — | — |
| Plan·Execute·Verify·Judge 4-layer engine (DirectV2) | ✅ | — | — | — | — |
| Sub-agent dispatch (parallel exploration) | ✅ | — | — | — | — |
| Ollama native support (local/offline inference) | ✅ | — | — | ✅ | — |
| MCP client + server (bidirectional) | ✅ | ✅ | — | — | — |
| Plugin system (tools / slash commands / panels) | ✅ | — | — | — | — |
| Three-tier sandbox + SSRF protection | ✅ | — | — | — | — |
| Open source (GPL v3) | ✅ | — | — | — | ✅ |

---

## 2. Agent Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                      Renderer (Vanilla TS + HTML/CSS)             │
│                                                                   │
│  Dashboard · Chat UI · Sidebar · Context Inspector                │
│  Memory Graph (SVG) · Files Pane · Plugin Panels · Town View      │
│                                                                   │
│           contextIsolation: true, nodeIntegration: false          │
└───────────────────────────┬──────────────────────────────────────┘
                            │  contextBridge (typed KinetAPI)
┌───────────────────────────┴──────────────────────────────────────┐
│                    Preload (narrow security boundary)             │
└───────────────────────────┬──────────────────────────────────────┘
                            │  IPC
┌───────────────────────────┴──────────────────────────────────────┐
│                    Main Process (Node.js / Electron)              │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    Engine Layer                              │ │
│  │                                                              │ │
│  │  ┌──────────┐  ┌──────────────┐  ┌────────────────────┐     │ │
│  │  │ Direct   │  │ DirectV2     │  │ ClaudeCode         │     │ │
│  │  │ (ReAct)  │  │ (Plan·Verify)│  │ Codex              │     │ │
│  │  │          │  │              │  │ (CLI subprocess)   │     │ │
│  │  └────┬─────┘  └──────┬───────┘  └─────────┬──────────┘     │ │
│  │       │               │                     │                │ │
│  │       └───────────────┴─────────────────────┘                │ │
│  │                       │                                      │ │
│  │              ┌────────▼─────────┐                            │ │
│  │              │  AgentLoop       │                            │ │
│  │              │  (shared core)   │                            │ │
│  │              └────────┬─────────┘                            │ │
│  └───────────────────────┼─────────────────────────────────────┘ │
│                          │                                        │
│  ┌───────────────────────▼─────────────────────────────────────┐ │
│  │              Provider Layer (SSE Streaming)                  │ │
│  │                                                              │ │
│  │  ┌──────────────────┐  ┌──────────────┐  ┌───────────────┐  │ │
│  │  │ OpenAI-compat    │  │ Anthropic    │  │ Ollama Native │  │ │
│  │  │ (GLM/DeepSeek/   │  │ (Claude,     │  │ (/api/chat,   │  │ │
│  │  │ Qwen/OpenAI)     │  │ cache_ctrl)  │  │ 32K context)  │  │ │
│  │  └──────────────────┘  └──────────────┘  └───────────────┘  │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                   Tool Layer (12 built-in)                   │ │
│  │                                                              │ │
│  │  shell · read_file · write_file · edit_file                  │ │
│  │  grep · glob · git_diff · web_fetch · web_search             │ │
│  │  recall_memory · dispatch_agent · flight_plan                │ │
│  │                                                              │ │
│  │  + 17 Plugin Suites (office/IoT/hardware/nestjs/...)        │ │
│  │  + MCP Client/Server (bidirectional, auto-discovery)        │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  ┌────────────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ SQLite + FTS5      │  │ Settings     │  │ Memory Engine    │  │
│  │ (history, turns,   │  │ (safeStorage │  │ (extract/dedup/  │  │
│  │  memories, embed,  │  │  encrypted)  │  │  embed/inject)   │  │
│  │  triples)          │  │              │  │                  │  │
│  └────────────────────┘  └──────────────┘  └──────────────────┘  │
└───────────────────────────────────────────────────────────────────┘
```

### 2.1 DirectV2 Engine — Plan · Execute · Verify · Judge

The flagship engine implements a 4-layer architecture (not just a faster ReAct loop):

```
┌─────────┐     ┌───────────┐     ┌──────────┐     ┌───────┐
│ Planner │ ──► │ Executor  │ ──► │ Verifier │ ──► │ Judge │
│         │     │ (ReAct)   │     │          │     │       │
└─────────┘     └───────────┘     └──────────┘     └───────┘
     ▲                                                 │
     └────────── Goal not met? Replan (max 2x) ───────┘
```

- **Planner**: First turn explores the codebase and outputs a structured JSON plan (no tool execution).
- **Executor**: Each plan step runs as an independent ReAct loop with full tool access.
- **Verifier**: After each step, runs validation commands (e.g. `npx tsc --noEmit`, tests, lint). Auto-retries up to 3× on failure.
- **Judge**: Independent LLM call verifies whether the goal is truly achieved (doesn't trust the model's self-reported "done").
- **Replan**: If Judge rejects → re-plans from scratch (max 2 replans).
- **Auto-degradation**: Simple tasks skip planning, falling back to single-turn ReAct + autoVerify.

### 2.2 Memory System — Three-Tier Deduplication

```
New fact extracted from conversation
         │
         ▼
┌─ Tier 1: Exact match ──────────────┐
│ String equality check (fast)        │ → discard if duplicate
└─────────────────────────────────────┘
         │ (not found)
         ▼
┌─ Tier 2: Fuzzy match (Jaccard) ────┐
│ Token similarity ≥ 0.65             │ → discard if duplicate
└─────────────────────────────────────┘
         │ (not found)
         ▼
┌─ Tier 3: Semantic (embedding) ─────┐
│ Cosine similarity ≥ 0.85            │ → discard if duplicate
│ (Float32Array vectors in SQLite)    │
└─────────────────────────────────────┘
         │ (unique)
         ▼
    Store fact + embedding + triple
```

Memory recall uses **hybrid retrieval**: FTS5 full-text search + embedding cosine similarity top-K, with automatic fallback to FTS5 when embeddings are unavailable.

### 2.3 Context Management — Triple Safety Net

| Mechanism | Trigger | Action |
|-----------|---------|--------|
| **Reactive Trim** | API returns context-too-long error | Halve token budget, trim history from head, retry current turn once |
| **History Compaction** | History exceeds budget | LLM summarizes early turns into a compact message; tail turns preserved intact |
| **Orphan Cleanup** | After any trim | Remove tool results whose calling assistant message was trimmed away (prevents invalid API calls) |

---

## 3. Introduction to Core Capabilities

### 3.1 Three Switchable Engines

| Engine | Description | Use Case |
|--------|-------------|----------|
| **Direct (Kaios)** | Built-in ReAct loop with tool-level concurrency | General tasks, code editing, data analysis |
| **DirectV2 (Kaios v2)** | Plan → Execute → Verify → Judge 4-layer architecture | Complex multi-step tasks requiring validation |
| **Claude Code** | Spawns `claude -p --output-format stream-json`, NDJSON parsing, `--resume` session continuation | Leverages Claude's coding strengths |
| **Codex** | Spawns `codex exec --json`, JSONL parsing, `resume` continuation | Leverages OpenAI Codex capabilities |

Engines are switchable per conversation. Switching clears cross-engine context (a Claude session ID is meaningless to Codex). **Cross-engine memory persists** — user facts learned in one engine are available in all others.

### 3.2 Twelve Built-in Tools

| Tool | Description |
|------|-------------|
| `shell` | Execute arbitrary shell commands (user confirmation + sandbox enforcement) |
| `read_file` | Read file contents (UTF-8) |
| `write_file` | Write file (auto-snapshot before write) |
| `edit_file` | Precise string replacement (old_string → new_string) |
| `grep` | Recursive content search (regex, auto-excludes node_modules/.git) |
| `glob` | List files by glob pattern |
| `git_diff` | View git working tree changes (read-only) |
| `web_fetch` | Fetch URL content (SSRF-protected, Jina Reader fallback) |
| `web_search` | Multi-engine search (Bing → DuckDuckGo fallback) |
| `recall_memory` | Search long-term memory (FTS5 + embedding hybrid retrieval) |
| `dispatch_agent` | Dispatch read-only sub-agent with independent context |
| `flight_plan` | (Plugin-injected; additional tools from enabled plugins) |

### 3.3 Plugin System (v2.2)

17 built-in plugin suites spanning multiple domains:

- **Office Suite**: Excel read/write/convert, PDF extraction, OCR, Word operations, CSV analysis (18 tools)
- **IoT/Hardware**: Arduino compile/upload, serial communication, BLE scan/connect, Modbus RTU/TCP, sensor lookup, oscilloscope diagnostics, GPIO reading
- **Development**: NestJS module generator, PlatformIO compile/upload, OTA firmware tools
- **Creative**: Brainstorm (Excalidraw whiteboard), math practice
- **Domain-specific**: Low-altitude airspace check, flight planning, MQTT pub/sub

Plugins inject tools, slash commands, hooks, and full-screen panels. **Per-need injection** (keyword matching) saves ~60% tokens compared to injecting all tools every turn.

### 3.4 MCP Bidirectional Integration

- **MCP Client**: Auto-discovers system-configured MCP services (`~/.claude.json`, `~/.codex/config.toml`, Claude Desktop config). Stdio transport with auto-reconnect.
- **MCP Server**: Built-in HTTP+SSE server exposes `run_agent` — remote machines can invoke your local agent with full tool access. Token-authenticated (timing-safe comparison), 5-minute timeout, zombie-connection detection.

### 3.5 Security Architecture

| Layer | Mechanism |
|-------|-----------|
| **Shell confirmation bridge** | Dangerous commands trigger confirmation modal in UI; main process parks resolver in `pendingConfirms` map until user responds |
| **Three-tier sandbox** | `readOnly` (read cwd only) / `workspaceWrite` (write cwd only) / `fullAccess` |
| **SSRF protection** | Blocks private IPs (10.x, 172.16-31.x, 169.254.x, 192.168.x), cloud metadata endpoints, DNS rebinding attacks |
| **Error sanitization** | Errors returned to model have absolute paths and usernames stripped |
| **File snapshot** | Every `write_file`/`edit_file` saves original to `.kinet-snapshots/`; one-click rollback |
| **Encrypted storage** | API keys encrypted via `safeStorage` (Windows DPAPI / macOS Keychain / Linux libsecret) |

---

## 4. Model Introduction & Local Deployment Plan

### 4.1 Supported LLM Providers

KinetAios supports three protocol families, auto-detected by base URL:

| Protocol | Endpoint Pattern | Providers |
|----------|-----------------|-----------|
| **OpenAI-compatible** | `/v1/chat/completions` | GLM (Zhipu), DeepSeek, Qwen, Mistral, OpenAI, any OpenAI-compatible endpoint |
| **Anthropic** | `/v1/messages` | Claude (with `cache_control` for prefix caching) |
| **Ollama Native** | `/api/chat` | Any Ollama-hosted model (Llama, Qwen, DeepSeek, etc.) — 32K context auto-configured |

### 4.2 Local Deployment via Ollama (AMD Radeon GPU)

For fully private, offline inference, KinetAios connects to a local Ollama server running on AMD Radeon GPUs:

```yaml
# Architecture: KinetAios (UI + Agent Engine) → Ollama (Local Inference) → AMD Radeon GPU (ROCm)

# Step 1: Install Ollama on AMD Radeon system
curl -fsSL https://ollama.ai/install.sh | sh

# Step 2: Pull a model (ROCm auto-detected)
ollama pull qwen2.5:32b          # or llama3.3:70b, deepseek-v2:16b
# Ollama auto-detects AMD Radeon GPU via ROCm runtime
# GPU acceleration enabled out-of-the-box (no manual ROCm config needed)

# Step 3: Verify GPU utilization
rocm-smi                        # Confirm GPU is active
ollama ps                       # Shows model loaded on GPU

# Step 4: Configure KinetAios
# Settings → API:
#   Provider: OpenAI-compatible
#   Base URL: http://localhost:11434/v1
#   API Key: (leave empty — Ollama requires no auth)
#   Model: qwen2.5:32b
```

KinetAios's Ollama integration automatically:
- Detects `localhost:11434` and switches to native `/api/chat` endpoint
- Sets `num_ctx: 32768` (32K context window) — the default 4K is too small for agent workflows
- Uses `ollama` as dummy API key (Ollama requires no authentication)
- Reports `prompt_eval_count` / `eval_count` as token usage

### 4.3 Embedding Model for Memory System

| Mode | Configuration |
|------|---------------|
| **Cloud embedding** | GLM `embedding-3`, OpenAI `text-embedding-3-small`, or any `/v1/embeddings` endpoint |
| **Local embedding (Ollama)** | Auto-switches to `nomic-embed-text` when base URL contains `localhost:11434` |
| **Fallback** | If no embedding endpoint available, `recall_memory` falls back to FTS5 keyword search |

---

## 5. Optimization Description for Inference Speed on AMD Radeon GPU

### 5.1 ROCm + Ollama Integration

KinetAios does not implement GPU inference itself — it delegates to Ollama, which provides first-class AMD Radeon support through ROCm:

| Component | Role |
|-----------|------|
| **AMD Radeon GPU** (RX 7900 XTX / RX 7800 XT / MI250 / etc.) | Hardware accelerator for tensor operations |
| **ROCm 6.x runtime** | AMD's open-source GPU compute platform (analogous to CUDA) |
| **Ollama** | Model server with automatic ROCm backend detection and GGUF quantization |
| **KinetAios** | Agent engine, tool execution, memory, and UI — connects to Ollama via HTTP |

### 5.2 Streaming-First Architecture

All provider communication uses **Server-Sent Events (SSE) streaming** — the first token appears on screen as soon as the GPU generates it, not after the full response completes:

```
User sends prompt
       │
       ▼
KinetAios AgentLoop ──HTTP POST──► Ollama /api/chat (stream: true)
       │                                    │
       │  ◄──SSE token stream (NDJSON)─────┤  GPU generates tokens
       │                                    │  ROCm schedules kernels
       │  First token → UI immediately      │  on Radeon compute units
       │                                    │
       │  Tool calls detected mid-stream    │
       │  ──► pause stream, execute tool    │
       │  ──► resume with tool result       │
       │                                    │
       │  ◄──[DONE]────────────────────────┤
       ▼
  Turn complete → extract memory (background)
```

This means **perceived latency = time-to-first-token**, not total generation time. Even on a mid-range Radeon RX 7800 XT running a 32B model, users see the first token within 1–2 seconds.

### 5.3 Token Efficiency Optimizations

KinetAios implements several optimizations that reduce the number of tokens sent to the GPU, directly improving throughput:

| Optimization | Impact | Implementation |
|-------------|--------|----------------|
| **Per-need plugin injection** | ~60% fewer input tokens | Only tools matching keyword patterns are injected into each turn |
| **Memory retrieval injection** | ~80% fewer tokens vs. full injection | Only top-K relevant memories injected (FTS5 + embedding cosine), not the entire memory store |
| **Context compaction** | Prevents linear growth | LLM summarizes old turns when history exceeds budget; tail preserved |
| **Reactive trim** | Prevents OOM crashes | On context-too-long error: halve budget, retry once |
| **System prompt caching** | Reduces redundant computation | System prompt + rules stay stable across turns; Ollama/OpenAI auto-cache the prefix |
| **Orphan cleanup** | Prevents invalid API calls | Removes orphaned tool results after trimming |

### 5.4 Benchmark Expectations on AMD Radeon GPU

| GPU | Model | Quant | Expected tok/s | TTFT |
|-----|-------|-------|----------------|------|
| RX 7900 XTX (24GB) | Qwen2.5-32B | Q4_K_M | ~30–40 tok/s | <1s |
| RX 7800 XT (16GB) | Qwen2.5-14B | Q4_K_M | ~40–55 tok/s | <1s |
| RX 7600 XT (8GB) | Qwen2.5-7B | Q4_K_M | ~50–65 tok/s | <0.5s |
| RX 7900 XTX (24GB) | Llama3.3-70B | Q3_K_M | ~10–15 tok/s | ~2s |

*These are estimated ranges based on Ollama + ROCm benchmarks. Actual performance depends on prompt length, context window usage, and system configuration.*

### 5.5 Concurrent Session Support

KinetAios runs multiple conversations simultaneously, each with independent agent loops. On a multi-GPU or high-VRAM Radeon system, users can:

- Run a DirectV2 code audit session (using a 32B model for reasoning)
- Simultaneously run a lightweight Direct session (using a 7B model for quick lookups)
- Each session streams independently, with separate token/cost tracking

Ollama handles model scheduling — if VRAM is insufficient for two models simultaneously, it automatically swaps models with minimal delay.

---

## 6. Cross-Engine Pipeline & Multi-Agent Orchestration

### 6.1 Pipeline (Cross-Engine Orchestration)

Chain multiple stages, each specifying an engine + prompt. Previous stage's output auto-prepends to next stage's prompt:

```
Stage 1: Direct (explore codebase) → findings
    ↓
Stage 2: Claude Code (deep refactor) → changes
    ↓
Stage 3: Codex (review and verify) → final report
```

2-minute per-stage timeout with polling, fail-fast abort.

### 6.2 Sub-Agent Dispatch (`dispatch_agent`)

The main agent in a ReAct loop can dispatch read-only sub-agents:

- Each sub-agent gets **independent context** (doesn't pollute main history)
- Sub-agents have **read-only tools** only (safe by design)
- Optional `engine` parameter: sub-agent can run on Claude Code or Codex via one-shot CLI
- 3-minute timeout per sub-agent (prevents API hangs from blocking the main loop)
- Sub-agent results come back as a text summary to the main agent

---

## 7. Open Source & Reproducibility

### 7.1 Repository

| Item | Value |
|------|-------|
| GitHub | https://github.com/phinn/KinetAios |
| License | GPL v3 |
| Platforms | Windows 11, macOS |
| Language | TypeScript (100%) |
| Framework | Electron 28+ |
| Database | SQLite (better-sqlite3) + FTS5 |
| Bundler | esbuild |
| Frontend | Vanilla TS (no framework) |
| Version | v1.8.0 |

### 7.2 Build & Run

```bash
# Clone
git clone https://github.com/phinn/KinetAios.git
cd KinetAios

# Install (rebuilds better-sqlite3 for Electron)
npm install

# Build (TypeScript compile + esbuild renderer bundle)
npm run build

# Type check (primary verification — no test framework in repo)
npm run typecheck

# Launch
npm start

# Package for distribution
npm run dist    # Windows: NSIS installer (.exe)
```

### 7.3 Dependencies

| Dependency | Purpose |
|-----------|---------|
| `electron` | Desktop application framework |
| `better-sqlite3` | SQLite native module (FTS5 full-text search, embedding storage) |
| `esbuild` | Renderer bundler (IIFE format) |
| `typescript` | Type system (strict mode, separate configs for main/renderer) |
| `electron-rebuild` | Native module rebuild for Electron ABI |
| `electron-builder` | Packaging (NSIS installer / DMG) |

No runtime npm dependencies in the packaged app — everything is bundled or is a native module.

---

## 8. Team

**Solo developer.** 

The project was originally a macOS-native SwiftUI application, ported line-by-line to Electron + TypeScript for Windows 11 and cross-platform support. All code — the ReAct engine, 12 tools, memory system, MCP integration, plugin system, and UI — was built by one person.

GitHub: https://github.com/phinn/KinetAios
