# AIOps-Agent Design Document

> **中文版：[DESIGN_ZH.md](./DESIGN_ZH.md)**
>
> This document is the authoritative development reference. All subsequent development follows this document.
> Event: AMD AI DevMaster Hackathon — Track 2: Agentic AI
> Last updated: 2026-07-29

---

## 0. Table of Contents

1. [Project Positioning & Track Alignment](#1-project-positioning--track-alignment)
2. [Scenario Definition](#2-scenario-definition)
3. [Scoring Breakdown & Strategy](#3-scoring-breakdown--strategy)
4. [Runtime Environment & Inference Optimization](#4-runtime-environment--inference-optimization)
5. [Core Design: 24h Unattended Operation + Tiered Autonomy](#5-core-design-24h-unattended-operation--tiered-autonomy)
6. [System Architecture Overview](#6-system-architecture-overview)
7. [Orchestration Layer: Orchestrator + Master + Sub-sessions](#7-orchestration-layer-orchestrator--master--sub-sessions)
8. [Context Strategy: One-shot Context + DB State Passing](#8-context-strategy-one-shot-context--db-state-passing)
9. [Tool Layer: MCP Server](#9-tool-layer-mcp-server)
10. [Monitoring Platform Integration](#10-monitoring-platform-integration)
11. [Web Console](#11-web-console)
12. [Session Recording & Replay](#12-session-recording--replay)
13. [Knowledge Base RAG](#13-knowledge-base-rag)
14. [Technology Selection](#14-technology-selection)
15. [Core Data Flows](#15-core-data-flows)
16. [Data Model (SQLite Schema)](#16-data-model-sqlite-schema)
17. [Fault Scenarios (for Demo)](#17-fault-scenarios-for-demo)
18. [Development Order & Milestones](#18-development-order--milestones)
19. [Open Questions (Design Decisions)](#19-open-questions-design-decisions)

---

## 1. Project Positioning & Track Alignment

### 1.1 Track Requirements

Track 2 (Agentic AI) requires building an agent with reasoning / planning / **tool use** / memory / task execution. Example domains include enterprise copilot, workflow automation, local RAG assistant, and multi-agent systems. Scoring:

| Dimension | Points | Notes |
|---|---|---|
| Functional Completeness & Application Value | 60 | Main battleground |
| AMD Radeon GPU / ROCm Optimization | 40 | Includes local inference execution + inference speed optimization |

### 1.2 Project Alignment

- **Tool use**: Invoke monitoring APIs / SSH / config modification / service restarts via MCP
- **RAG**: Local ops knowledge base (runbooks / tuning experience / parameter recommendations)
- **Workflow automation**: Alert-triggered → diagnosis → repair closed loop
- **Multi-agent (logical)**: Master + inspection/repair/question sub-sessions
- **Reasoning + planning**: ReAct loop + structured operation plans
- **Memory**: DB-persisted event history and state cards
- **Local inference on Radeon**: llama.cpp + ROCm local inference

### 1.3 Differentiators

1. **24h unattended loop**: Periodic inspection + event-driven repair, with tiered approval and emergency override
2. **Comprehensive safety guardrails**: Risk grading + dry-run + approval gate + audit log + rollback + auto-circuit-breaker escalation
3. **Learning closed loop**: Post-resolution runbook writeback (confidence gating + human review)
4. **Context engineering**: One-shot context + DB state passing, avoiding long-context reasoning degradation

---

## 2. Scenario Definition

### 2.1 Objective

Autonomous operations agent for big data platforms (Hadoop ecosystem clusters): automatically inspect health status, trigger diagnosis and repair on alerts, with historical traceability and queryability.

### 2.2 Cluster Environment

- **3-node Hadoop cluster** (open-source stack; Cloudera CDP dropped to avoid licensing issues and ensure judge reproducibility)
  - Components: HDFS (NameNode/DataNode), YARN (ResourceManager/NodeManager), Hive (MetaStore/Server), HBase (Master/RegionServer)
  - Deployment: docker-compose with 3 nodes, fully reproducible
- **Monitoring stack**: Prometheus (metrics collection + alerting) + Alertmanager (alert routing + webhook) + Grafana (visualization)
- **Network**: LAN; agent accesses and operates the cluster via tools (HTTP API / SSH)

### 2.3 Agent Positioning

- **Does not replace the monitoring platform**: The monitoring platform collects metrics and emits alerts (what it's good at); the agent handles **cross-component correlation + root-cause interpretation + proactive deep inspection + repair execution** (what monitoring cannot do)
- Example: Monitoring reports "NameNode RPC latency high"; the agent correlates "DataNode3 heartbeat lost" + checks logs = identifies root cause and repairs

---

## 3. Scoring Breakdown & Strategy

| Sub-item | Strategy |
|---|---|
| Functional Completeness (60) | Multi-scenario closed loop + safety guardrails + 24h loop + learning writeback |
| Radeon/ROCm Optimization (40) | HIPBLAS build (not Vulkan), KV q4, FA, mmap, prompt-cache, context trimming for speed control |

**Demo-critical**: Judges cannot access the LAN cluster → must provide: ① End-to-end screen recording ② docker-compose reproducible environment ③ Architecture diagram + README reproduction steps ④ Performance data (tokens/s, TTFT, VRAM, fault resolution time).

---

## 4. Runtime Environment & Inference Optimization

### 4.1 Hardware & Environment (Dual Environment: Remote Inference + Local Orchestration)

**Deployment architecture (decided): Remote inference only, local runs Hadoop + agent + web**

- Remote: Only llama-server (inference service); local calls via SSH tunnel or exposed port
- Local: Docker (Hadoop 3 nodes + Prometheus + Alertmanager + Grafana) + agent orchestration + MCP tools + web UI
- Clear separation: Inference plane (remote GPU) / Data plane + Control plane (local CPU)

**Primary Environment (Remote AMD Cloud, Inference Service)**

- GPU: AMD Radeon PRO W7900D (48GB VRAM, gfx1100 / Navi 31, officially supported by ROCm)
- CPU: AMD EPYC 9334 32-Core / 128 threads
- Runs only llama-server, port 8080; API key injected via env var `LLAMA_API_KEY` (never hardcoded)
- Storage: `/workspace` persistent volume 20G (holds model + bootstrap.sh); overlay root is non-persistent
- llama-server binary: `/opt/llama.cpp/llama-server` (symlink → `build/bin/llama-server`)
- Connection: SSH `root@<REMOTE_IP> -p <PORT>` (security group already opened)
- **Local access to inference API: SSH tunnel `http://127.0.0.1:18080` → remote 8080** (tool-calling verified end-to-end)
- Tunnel command: `ssh -o ServerAliveInterval=30 -L 18080:127.0.0.1:8080 -p <PORT> root@<REMOTE_IP> -N`
- Note: Remote jupyter-lab is PID 1 (port 8888); do not kill it (will restart the container)

**Fallback Environment (Local 7900 XTX, used when remote is unavailable)**

- GPU + agent + Hadoop all run locally (inference + orchestration combined)
- GPU: AMD Radeon 7900 XTX (24GB VRAM, gfx1100 / Navi 31)
- Memory: 32GB RAM
- OS: Ubuntu minimal install, no GUI; BIOS + driver with Resizable BAR / Smart Access Memory enabled
- Resource-constrained; config needs downgrading (see §4.7 fallback startup command)

**Environment Configuration Differences**

| Item | Primary (W7900D 48GB) | Fallback (7900 XTX 24GB) |
|---|---|---|
| Model | Q4_K_M | Q4_K_M |
| KV Quantization | **q8_0** (spare VRAM → trade for quality) | **q4_0** (save VRAM) |
| Context | **128k** | **32–64k** (128k won't fit: 16+8+2=26GB > 24GB) |
| `-ngl` | 999 full offload | 999 full offload |
| Flash Attention | `-fa on` | `-fa on` |
| VRAM Usage | ~21.7GB / 51.5GB | ~20–22GB / 24GB (tight) |

> Fallback environment context limit 32–64k: consistent with the design goal of "normal 16–32k"; only rare deep diagnosis requires 128k (primary env only). Daily inspection/repair runs fine on the fallback environment.

### 4.2 System

- Primary env: Remote cloud container (Ubuntu); W7900D is gfx1100, officially supported by ROCm — **no HSA_OVERRIDE_GFX_VERSION needed**
- Fallback env: Local Ubuntu minimal; BIOS with Resizable BAR enabled
- Both environments use ROCm/HIP backend, not Vulkan

### 4.3 Inference Backend (Verified)

- **llama.cpp 035cd8f9a (build 9766)**, compiled with **ROCm/HIP backend** (`-DGGML_HIPBLAS=ON`)
- `ldd` confirms linkage to `libamdhip64.so` / `libhipblas.so` / `librocblas.so` and other ROCm libraries ✅
- **Vulkan disabled**: The 40-point scoring explicitly requires ROCm; Vulkan does not count toward ROCm score
- Single llama-server process occupies the GPU; all other components run on CPU

### 4.4 Model (Tested)

- Model: `Qwopus3.6-27B-v2-MTP-Q4_K_M.gguf` (Qwen-family 27B dense, supports tool-calling ✅ verified)
- Path: `/workspace/Qwopus3.6-27B-v2-MTP-Q4_K_M.gguf`
- Quantization: GGUF **Q4_K_M** (~16GB weights)
- **Thinking model**: Chat template `thinking=1`, outputs `<think>` reasoning. **Verified: `reasoning_content` is returned as a separate field** (not mixed into content); the agent reads it directly — no need to parse/strip tags manually
- **MTP (Multi-Token Prediction)**: GGUF contains MTP layers; speculative decoding enabled (`--spec-type draft-mtp --spec-draft-n-max 1`). Benchmark n_max=1~8; optimal n_max=1 achieves 37.5 t/s (+30% vs baseline 28.9 t/s), acceptance rate 77.4%. Larger n_max → faster acceptance decay (n_max=8 only 24%)
- KV quantization upgraded to **q8_0** (48GB VRAM has headroom; smaller long-context attention error, beneficial for log-reading agent)

### 4.5 Inference Optimization Checklist (Tested)

| Item | Status | Notes |
|---|---|---|
| HIPBLAS (ROCm) | ✅ Verified | `ldd` shows libamdhip64 etc.; not Vulkan |
| KV cache quantization | **q8_0** | `-ctk q8_0 -ctv q8_0` (48GB headroom, upgraded from q4 for quality) |
| Flash Attention | ✅ On | `-fa on` (this version requires value on/off/auto) |
| mmap loading | ✅ Default | No flag needed |
| Prompt caching | ✅ Verified | Tested: 181/198 prompt tokens cache hits |
| Context trimming | Required | See §8, core speed-control mechanism |
| Overclocking | Off | Not available on cloud; stability first |

### 4.6 Performance Baseline (Measured, Q4_K_M + KV q8 + 128k context, W7900D)

**Generation Speed (short prompt, long generation)**

| max_tokens | Generation t/s | Prompt t/s | TTFT |
|---|---|---|---|
| 2048 | 29.0 | 264.9 | 0.25s |
| 4096 | 29.1 | 228.5 | 0.22s |

**Context Decay Curve (long prompt, short generation 512 tokens)**

| Context | Generation t/s | Prompt processing t/s | TTFT | Wall clock |
|---|---|---|---|---|
| 4k | 28.6 | 341 | 1.5s | 8s |
| 16k | 25.9 | 213 | 71.5s | 78s |
| 32k | 22.9 | 106 | 189.8s | 199s |
| 64k | ~18–20 (trend) | ~60 (trend) | >5min | Very long |

**VRAM Usage**: ~21.7GB / 51.5GB (30GB headroom remaining)

**Key Findings (guiding agent design)**:
1. **Generation speed decays slowly**: 4k→32k only drops 20% (28.6→22.9 t/s); generation is not the bottleneck
2. **Prompt processing is the bottleneck**: TTFT explodes with context (4k=1.5s → 32k=190s), because KV q8 + FA is slower on long prompts
3. **Validates design**: One-shot context + DB state passing → each new session starts with a small context (very short TTFT), no long prompts
4. **Tool output pre-compression is more critical**: Stuffing large logs into the prompt = TTFT disaster; must pre-compress
5. **Target**: Keep normal working context under **16k** (TTFT < 2s, generation ~26 t/s); 32k+ only for rare deep diagnosis

### 4.7 Startup Commands

**Primary Environment (Remote W7900D 48GB, verified working)**

```bash
cd /opt/llama.cpp

HIP_VISIBLE_DEVICES=0 ./llama-server \
  -m /workspace/Qwopus3.6-27B-v2-MTP-Q4_K_M.gguf \
  -c 131072 \
  -ngl 999 \
  -ctk q8_0 -ctv q8_0 \
  -fa on \
  --jinja \
  -t 16 \
  -b 512 -ub 512 \
  -np 1 \
  --host 0.0.0.0 --port 8080 \
  --api-key "$LLAMA_API_KEY"
```

**Fallback Environment (Local 7900 XTX 24GB, used when remote is unavailable)**

```bash
cd /opt/llama.cpp   # or local llama.cpp path

HIP_VISIBLE_DEVICES=0 ./llama-server \
  -m /path/to/Qwopus3.6-27B-v2-MTP-Q4_K_M.gguf \
  -c 65536 \
  -ngl 999 \
  -ctk q4_0 -ctv q4_0 \
  -fa on \
  --jinja \
  -t 8 \
  -b 512 -ub 512 \
  -np 1 \
  --host 0.0.0.0 --port 8080 \
  --api-key "$LLAMA_API_KEY"
```

> Fallback differences: KV downgraded to q4_0, context reduced to 64k (128k won't fit in 24GB), `-t` tuned to local physical cores. Daily inspection/repair is unaffected; only rare deep diagnosis requiring 128k runs on the primary environment.

### 4.8 Restart Recovery Script

Remote container restarts lose the overlay layer (sshd/modelscope/processes all gone); `/workspace` persistent volume is preserved. Script placed at `/workspace/bootstrap.sh`; after restart, execute via cloud platform web terminal:

```bash
bash /workspace/bootstrap.sh
```

The script completes in one shot: ① Install + start sshd (restore public key auth) ② Install modelscope ③ Check model, download Q4_K_M via `modelscope download` if missing ④ Start llama-server in background (nohup, log at `/workspace/llama-server.log`). Idempotent and repeatable. Source: `scripts/bootstrap.sh` in the project.

---

## 5. Core Design: 24h Unattended Operation + Tiered Autonomy

> This section is the final implementation plan for safety guardrails, covering tiered autonomy, grading rules, execution policies, approval channels, and audit mechanisms.

### 5.1 Design Principles

- **Grading authority belongs to rules, not the model**: If the model participates in grading, it might classify an irreversible operation as "low risk, auto-execute." Risk tier must be determined by rules the model cannot reach.
- **Tool whitelist is naturally classifiable**: The agent can only invoke tools registered in `TOOL_DEFINITIONS`; there is no raw shell. Every action can be deterministically mapped to a tier — no need for the model to "understand intent."
- **Fail-closed**: Any tool not on the whitelist / without a matching rule is treated as `irreversible` + not auto-executable — never let it through.
- **The model's legitimate roles are only two**: ① Choose which tool (tool-use reasoning); ② Provide a reason text (written to audit / shown to humans). The reason does not participate in grading.

### 5.2 Dual-Axis Model

| Axis | Values | Meaning |
|---|---|---|
| Axis 1: Autonomy mode `AUTONOMY` | `supervised` / `autonomous` | **Who decides**: On-duty (wait for Web human approval) or unattended (policy-driven automatic) |
| Axis 2: Operation autonomy tier `tier` | `recover` / `reversible` / `irreversible` / `low` / `medium` | **How to act** |

Behavior of the four tiers under `autonomous` mode:

| Tier | Typical Operations | Autonomous Behavior | Supervised Behavior |
|---|---|---|---|
| `low` / `medium` | Read-only / restart non-critical | Auto-execute | Auto-execute |
| `recover` (recoverable idempotent) | Restart a service already `DOWN`/`STOPPED` | Auto-execute, subject to attempt throttling (retry limit + cooldown); escalate to human on consecutive failures | Wait for human approval |
| `reversible` (undoable) | Backup config → modify → restart | Auto-execute, forced backup first for rollback point; still writes audit | Wait for human approval |
| `irreversible` | `hdfs format` / `disk format` / `rm` critical files / `drop table` | **Never automatic**: abort + emit escalation alert | Wait for human approval; timeout = decline |

### 5.3 Grading: Pure Rules + DB-Backed + UI-Configurable

Grading is a **deterministic pure function** composed of two rule layers, neither invoking the model:

```
classify(tool_name, args) -> tier, autonomous:
    1) Query risk_rules table (with TTL cache):
       Among enabled rules where (tool_name==name AND match_json hits args), pick highest priority
    2) If none, use the default rule where tool_name=='*'
    3) If still none → code fallback (tier=irreversible, autonomous=False)  # fail-closed
    4) Runtime refinement (still rules, reading live cluster state):
       if tool == restart_service:
           state = get_service_state(args.service, args.node)
           if state in {STOPPED, DOWN, UNKNOWN}: keep as recover
           else (RUNNING but unhealthy): downgrade to human-wait (irreversible flow)
    5) Return (tier, autonomous)
```

**`risk_rules` table (authoritative grading source, UI-editable)**

```sql
CREATE TABLE risk_rules (
  id          TEXT PRIMARY KEY,
  tool_name   TEXT NOT NULL,   -- match tool name; '*' means default
  match_json  TEXT,            -- optional: sub-classify by args; NULL=any
  tier        TEXT NOT NULL,   -- recover|reversible|irreversible|low|medium
  autonomous  INTEGER NOT NULL DEFAULT 0,
  enabled     INTEGER NOT NULL DEFAULT 1,
  priority    INTEGER NOT NULL DEFAULT 0,
  updated_at  INTEGER,
  updated_by  TEXT
);
```

- **Seed data**: On first startup, if table is empty, populate default rules from `TOOL_RISK` (in `tools.py`) — works out of the box.
- **Cache**: `classify` queries DB with TTL cache to avoid hitting DB on every tool call.
- **UI guardrail**: The `irreversible` tier disables the `autonomous` checkbox on the admin page (code-enforced) — prevents admin mistakes.
- **Fail-closed fallback** retained in code constants; takes effect when DB rules are missing.

### 5.4 Execution Details per Tier

- **`recover`**: Auto-restart only when service state ∈ {STOPPED, DOWN, UNKNOWN} (already down; restart won't make it worse). If service is RUNNING but unhealthy (e.g., GC overhead / hung), do not proactively cause interruption — escalate to human or notify only. Restart via SSH, subject to §5.5 attempt throttling.
- **`reversible`**: Before execution, `cp file file.bak.<ts>`; after modification, reload/restart; rollback point is traceable. Tool `edit_remote_config` implements this tier.
- **`irreversible`**: Never automatic. Supervised waits for approval; autonomous directly aborts + escalates alert (no dumb timeout wait).
- **`low`/`medium`**: Auto-execute / execute + notify.

### 5.5 High-Risk Attempt Throttling (covers recover + reversible)

Circuit breaker only counts **failures** (`_failure_counts`). Added **attempt throttling** covering every autonomous execution of all high-risk tiers (successes count too):

- **Key**: `(tool, target)`, where target = service / node / path.
- **Count derived from `audit_log`** (no new state needed; naturally persistent, survives across sessions / restarts):

```sql
SELECT COUNT(*) FROM audit_log
 WHERE tool_name=? AND json_extract(args_json, '$.service')=? AND status='executed'
   AND ts > now - WINDOW;
```

- **Cooldown**: If interval between two autonomous executions < `cooldown`, reject.
- **Over-limit escalation**: `attempts >= MAX_ATTEMPTS` → mark escalated, stop autonomous execution for that key, emit escalation alert.
- Complementary to circuit breaker: breaker manages "keeps failing"; attempt throttle manages "tried N times without success, give up."

### 5.6 Other Safety Mechanisms

- **Tool whitelist**: SSH tools only allow whitelisted commands; model output is structurally parsed + validated before execution — never fed directly to shell.
- **Dry-run (preview)**: High-risk operations first return "what would happen" without actually executing — for agent self-validation + human preview before approval.
- **Audit log**: Every tool call (who / when / what / result / whether approved) written to `audit_log` table. 24h unattended operations must be traceable.
- **Rollback**: `edit_remote_config` automatically `cp .bak.<ts>` before modifying config; auto-rollback on replacement failure.

### 5.7 Approval Channel

- **Self-built Web approval page** (in web, along with other admin operations)
- Pure web without push = late-night high-risk approvals unseen → auto-decline / emergency override per timeout policy; logic is self-consistent.
- `AUTO_APPROVE` (`config.py`) has evolved into `AUTONOMY` mode (supervised/autonomous) — clearer semantics.
- Existing circuit breaker (`max_failures` / `cooldown`) retained for the failure side; attempt throttle for the attempt side.

---

## 6. System Architecture Overview

Three clear layers: **Inference plane (llama.cpp) / Data plane (Orchestrator+MCP+DB) / Control plane (web)**. GPU is dedicated to the inference layer; everything else runs on CPU.

```
┌─────────────────────────────────────────────────────────────────┐
│  Frontend  React + Ant Design (dark theme)                      │
│  ①Approval Center ②Agent Activity (thinking chain/tool timeline) │
│  ③Cluster Status (embed Grafana) ④Admin (KB/risk rules/config)   │
└───────────────┬──────────────────────────┬──────────────────────┘
         REST   │                    WS    │(realtime: inference stream/approval push)
┌──────────────▼──────────────────────────▼──────────────────────┐
│  Access Layer  FastAPI + WebSocket                                │
└───────────────┬─────────────────────────────────────────────────┘
┌───────────────▼─────────────────────────────────────────────────┐
│  Orchestration Layer  Orchestrator (daemon)                      │
│   ├─ Master scheduler (pure rules, no LLM): dispatch/preempt/prio│
│   ├─ Session manager: spawn ephemeral sub-sessions               │
│   └─ Approval service: risk grading/timeout/override/cooldown    │
└──────┬───────────────────────┬──────────────────────────────────┘
       │ HTTP(tools)           │ HTTP(chat/completions, stream)
┌──────▼──────────┐    ┌───────▼──────────────────────────────────┐
│  Tool Layer MCP  │    │  Inference Layer llama.cpp server         │
│  (Python SDK)    │    │  ROCm/HIPBLAS, Qwen27B Q4_K_M             │
│  Prometheus      │    │  KV q8_0, FA, mmap, prompt-cache, MTP      │
│  Alertmanager    │    │  Occupies GPU (weights 16G+KV)            │
│  SSH(whitelist)  │    └───────────────────────────────────────────┘
│  HDFS admin      │
└──────┬───────────┘
       │
┌──────▼──────────────────────────────────────────────────────────┐
│  Data Layer  SQLite (single file)                                 │
│   sessions / session_events / incidents / approvals / audit       │
│   + sqlite-vec (KB vectors) + bge-small(CPU encoding)             │
└──────────────────────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────────┐
│  External  Prometheus+Alertmanager+Grafana  ←->  Hadoop 3-node    │
└──────────────────────────────────────────────────────────────────┘
```

---

## 7. Orchestration Layer: Orchestrator + Master + Sub-sessions

### 7.1 Orchestrator (Daemon Process)

```
Orchestrator (daemon)
  ├─ Master scheduler (pure rules, no LLM, holds global state card)
  │    ├─ Periodically spawn inspection sub-session (fresh context: last state card + current metrics)
  │    ├─ Alert spawn repair sub-session (preempts inspection, fresh context: incident KB + full toolset)
  │    └─ Query spawn question sub-session (fresh context: history DB retrieval)
  │    Each sub-session: done → conclusion to DB + summary back to master → context released
  ├─ Session manager
  └─ Approval service
```

### 7.2 Master Scheduler (Pure Rules, No LLM)

The master does not read logs or diagnose; it only decides "dispatch inspection or repair now? To whom?" using rules:

- Has alert → dispatch repair (**preempts inspection**: pause current inspection, save state)
- Timer fires (e.g., every 5min) → dispatch inspection
- Has user query → dispatch question
- Multiple alerts → sort by severity + impact scope

Pure rules = high determinism + saves one LLM call + doesn't consume context. Only sub-sessions spend LLM.

### 7.3 Sub-session (One-shot Context)

- **Sub-session = independent context window on the same llama.cpp server + dedicated system prompt + tool subset** — not a separate process, no extra VRAM
- Single GPU cannot truly parallelize → /fix preempts /auto, **serial execution, not concurrent** (when the cluster has issues, inspection results are noise anyway)
- The value of sub-agents is **context isolation** (not concurrency): the pile of logs /fix reads doesn't pollute /auto's context, and vice versa
- Ephemeral: on completion, conclusion is structured to DB + one-line summary back to master; context released

### 7.4 Three Sub-session Types

| Mode | Trigger | System Prompt Focus | Toolset |
|---|---|---|---|
| /auto Inspection | Periodic | Cross-component correlation + root-cause interpretation + proactive deep inspection | Read-only tools |
| /fix Repair | Alert preemption | Diagnosis + repair execution | Full tools (including high-risk) |
| /question Query | User query | Summarize history + KB | Read-only + retrieval tools |

---

## 8. Context Strategy: One-shot Context + DB State Passing

Goal: Keep normal context at 16–32k (≈35–40 t/s), avoiding long-context decay. More efficient and stable than "rolling summary within a single long context."

### 8.1 Core Mechanism

- **Event-level isolation**: Each incident gets a fresh context; no accumulation between events
- **Ephemeral sub-sessions**: On completion, conclusion goes to DB; next session is a fresh context reading state from DB
- **State passed via DB, not via prompt memory**

### 8.2 Hot/Warm/Cold Layering (raw data never enters LLM context)

| Layer | Content | Location |
|---|---|---|
| Hot | Last 2–3 ReAct steps + current tool result | LLM context |
| Warm | Earlier steps in this event, summarized | Compressed into one paragraph in context |
| Cold | Full raw logs / tool outputs | DB/files; agent retrieves on demand via tools |

### 8.3 Tool Output Pre-compression (saves the bulk of tokens)

- `read_logs` doesn't return 5000 lines of raw text; returns "3 ERROR lines from the last 1000: [L1, L2, L3]"
- Need more? Call again with a filter

### 8.4 Rolling Summary (Fallback)

- If context reaches threshold (e.g., 32k) within a single sub-session → compress the oldest N rounds into a summary paragraph, keep recent raw text, loop continues

### 8.5 Structured State in DB

- The incident's "what's been tried / current hypothesis" stored as SQLite JSON
- Each round injects only one compact "state card" — not the full history into the prompt

### 8.6 RAG On-Demand Retrieval

- Knowledge base top-k retrieval injected as needed; not pre-loaded

---

## 9. Tool Layer: MCP Server

Unified as a Python tool layer; the agent only invokes registered tools, never touching raw shell. Validation / whitelist lives inside the tool layer.

### 9.1 Tool Inventory

| Category | Tool | Description |
|---|---|---|
| Monitoring | `get_service_status(service)` | SSH execute jps/process check; returns service health status |
| Monitoring | `get_alerts()` | Iterate service health checks; returns active alerts |
| Monitoring | `get_metrics(host)` | SSH execute free/df/top; returns system resource metrics |
| Diagnosis | `read_logs(node, svc, filter, tail_n)` | **Pre-compressed**; returns summary lines, not raw text |
| Diagnosis | `hdfs_admin(cmd)` | SSH execute dfsadmin/fsck/dfs read-only commands |
| Execution | `restart_service(svc)` | SSH restart a stopped service; includes risk grading |
| Execution | `edit_remote_config(node, file, key, value)` | SSH backup + validate + reload; not raw editing |
| Knowledge | `search_kb(query)` | Hybrid retrieval: vector + BM25; auto-degrades when deps missing |
| Knowledge | `write_runbook(summary)` | Post-resolution writeback; **confidence gating + human review** prevents KB pollution |

### 9.2 write_runbook Learning Closed Loop

Differentiator: Post-resolution runbook writeback. Risk: incorrect experience gets remembered and pollutes KB → added confidence gating + human review (web admin review).

---

## 10. Monitoring Platform Integration

### 10.1 Selection

**Prometheus + Grafana** (dropped Zabbix: outdated API, poor demo experience).

### 10.2 Integration

- **Prometheus HTTP API = Tool layer**: `get_metrics` / `get_alerts` obtained via SSH + Prometheus API
- **Grafana dashboards**: 4 panels configured (Cluster Overview / HDFS / YARN / HBase+ZK); Web console can link/jump to view

---

## 11. Web Console

### 11.1 Positioning

Control plane + demo plane. Approvals, admin operations, inference process viewing, session replay — all in the web.

### 11.2 Four Functional Areas

1. **Approval Center**: WebSocket real-time push of pending approvals + one-click approve/reject
2. **Agent Activity**: Thinking chain / tool calls / event history timeline (active session streams via WS; history replayed from DB)
3. **Cluster Status**: Service health status cards + Grafana jump links
4. **Admin**: KB CRUD, monitoring integration config (Prometheus address/components), whitelist/risk rule config

### 11.3 Tech Stack

- Backend: **FastAPI + WebSocket** (async pairs perfectly with llama.cpp HTTP)
- Frontend: **React + Ant Design** (use admin template, don't build from scratch)
- Realtime: WebSocket pushes inference stream + approval notifications
- Notification (optional): webhook to Feishu/DingTalk; approval links point back to web

---

## 12. Session Recording & Replay

### 12.1 Mechanism

- Each sub-session is ephemeral (context released)
- But **session call relationships + history records** are saved for web replay
- Master → sub-session `parent_id` forms a tree; web can drill into any session to see the full ReAct timeline

### 12.2 Realtime vs History

- **Realtime inference viewing**: Active session's LLM streaming tokens pushed to frontend via WebSocket
- **History replay**: Query from `session_events` table

### 12.3 Schema (see §16)

```
sessions(id, parent_id, type, trigger, status, summary, started_at, ended_at)
session_events(id, session_id, seq, kind, content_json, ts)
```

---

## 13. Knowledge Base RAG

### 13.1 Purpose

Local ops knowledge base: tuning experience, parameter recommendations, common fault runbooks.

### 13.2 Storage

- **sqlite-vec** (SQLite vector extension, in-process) shares **the same `.db` file** as events/audit/state cards — zero extra services/processes
- Embedding model: **bge-small-zh (~100MB) runs on CPU** — does not touch GPU
- Scale: hundreds of runbooks; CPU encoding is sufficient

### 13.3 Fallback

If even 100MB CPU embedding is too tight → fall back to **SQLite FTS5 for BM25** (pure keyword, zero extra resources). Ops runbooks are keyword-heavy (DataNode/OOM/GC overhead); BM25 works well enough.

---

## 14. Technology Selection

### 14.1 Key Insight

The model is the resource heavyweight, running fixed on llama.cpp server (separate process, ROCm). The orchestrator only sends HTTP + runs tools + manages state; memory footprint ~100–300MB, negligible compared to 16GB model. **Don't choose language to save orchestrator resources; choose by development speed + ecosystem.**

### 14.2 Selection

| Component | Choice | Rationale |
|---|---|---|
| Orchestration/Backend | **Python + FastAPI** | MCP official SDK, asyncio pairs with llama.cpp HTTP, native data processing, fastest iteration |
| Frontend | React + Ant Design | Admin template for rapid setup |
| Inference | llama.cpp (ROCm/HIPBLAS) | Track requirement: ROCm |
| Tool Protocol | MCP (Python SDK) | Unified tool layer; bonus points |
| DB | SQLite | Events/audit/state cards + sqlite-vec KB in one file |
| Embedding | bge-small-zh (CPU) | Does not occupy GPU |
| Monitoring | Prometheus+Alertmanager+Grafana | Big data standard, API-friendly |

### 14.3 What We Don't Use

- **No LangGraph or heavy frameworks**: Hand-written ReAct orchestrator is more controllable, easier to explain to judges, and more resource-efficient
- **No separate framework for sub-agents**: = same server, independent context; a logical concept, resource-neutral
- **No DAG framework**: Planner produces a dependency-ordered operation step graph; executor runs in topological order — ~50 lines of Python

---

## 15. Core Data Flows

### 15.1 Inspection Loop (Periodic, e.g., 5min)

```
Master timer fires → spawn inspection sub-session (fresh context)
  → Read DB last state card + MCP call get_metrics/get_alerts
  → LLM inference (streaming tokens via WS to frontend)
  → Conclusion to DB (new state card + session_events) + summary back to master
  → Context released
```

### 15.2 Alert Repair (Event-Driven, Preempts Inspection)

```
Alertmanager webhook → Orchestrator → master pauses inspection (save state)
  → spawn repair sub-session (fresh context: incident KB retrieval + full toolset)
  → LLM ReAct loop: diagnose → call tool → observe → ...
  → Encounter high-risk op: go to 15.3 approval
  → Execute repair → result to DB → summary back to master → resume inspection
```

### 15.3 Approval Flow (with Timeout / Emergency Override)

```
Sub-session requests high-risk op → approval service records to DB (pending) + WS push to frontend
  → Human approves ────────────────────→ execute/decline, write audit
  → Timeout (10min) → rule decides:
       Normal high-risk: decline + alert
       Emergency (service critical + not in cooldown + under attempt limit): execute predefined playbook + post-alert + count
       Emergency ineffective: stop + escalate to human
```

### 15.4 Query Replay (User-Driven)

```
Web initiates → spawn question sub-session
  → Query DB history (incidents/sessions) + KB retrieval (sqlite-vec)
  → LLM summarize → return to frontend + record to session_events
```

---

## 16. Data Model (SQLite Schema)

```sql
-- Sub-session record
sessions(
  id            TEXT PRIMARY KEY,
  parent_id     TEXT,                 -- master or parent session
  type          TEXT,                 -- inspect / fix / question
  trigger       TEXT,                 -- cron / alert_id / user_query
  status        TEXT,                 -- running / done / failed / aborted
  summary       TEXT,                 -- post-run summary returned to master
  started_at    INTEGER,
  ended_at      INTEGER
);

-- Events within a session (ReAct timeline, for web replay)
session_events(
  id            INTEGER PRIMARY KEY,
  session_id    TEXT,
  seq           INTEGER,              -- sequence number
  kind          TEXT,                 -- thought / tool_call / tool_result / llm_msg / approval
  content_json  TEXT,                 -- structured content
  ts            INTEGER
);

-- Incident
incidents(
  id            TEXT PRIMARY KEY,
  alert_payload TEXT,                 -- raw Alertmanager alert
  status        TEXT,                 -- active / resolved / escalated
  linked_session_ids TEXT,            -- associated repair sessions
  resolution    TEXT,
  created_at    INTEGER,
  updated_at    INTEGER
);

-- Approval
approvals(
  id            TEXT PRIMARY KEY,
  session_id    TEXT,
  operation     TEXT,                 -- requested operation
  risk_level    TEXT,                 -- medium / high / destructive
  status        TEXT,                 -- pending / approved / declined / timeout_override
  requested_at  INTEGER,
  decided_at    INTEGER,
  decided_by    TEXT,                 -- user / system_timeout_override
  decision_note TEXT
);

-- Audit log (append-only)
audit(
  id            INTEGER PRIMARY KEY,
  session_id    TEXT,
  tool          TEXT,
  params_json   TEXT,
  result_json   TEXT,
  risk_level    TEXT,
  approved      INTEGER,              -- 0/1
  ts            INTEGER
);

-- Global state card (latest cluster health snapshot held by master)
cluster_state(
  id            INTEGER PRIMARY KEY,
  snapshot_json TEXT,                 -- current health/active incidents/pending approvals
  updated_at    INTEGER
);

-- KB runbook
runbooks(
  id            TEXT PRIMARY KEY,
  title         TEXT,
  content       TEXT,
  source        TEXT,                 -- manual / agent_generated (pending review)
  status        TEXT,                 -- approved / pending_review
  embedding     BLOB,                 -- sqlite-vec vector
  created_at    INTEGER
);
```

---

## 17. Fault Scenarios (for Demo)

Each scenario runs through the "diagnosis → repair" closed loop. Recommended coverage:

1. **HDFS DataNode Offline**: Heartbeat lost → locate → restart DataNode
2. **YARN NodeManager OOM**: GC overhead → locate → tune memory params / restart
3. **HBase RegionServer Crash**: Process exit → locate → restart
4. **Disk Full**: Log/data disk full → clean / expand
5. **Hive Slow Query**: Query stuck → analyze execution plan → kill / tune params

Each scenario can be injected in the docker-compose environment (kill process / fill disk / break config) for demo and judge reproducibility.

> **Field Note**: Hive MetaStore serves as a natural demo fault point — configure JVM heap to only 50MB (`-Xmx52428800`, official recommendation ≥256MB); any moderate Hive query triggers Full GC/OOM, reproducing the full closed loop "MetaStore OOM → Agent diagnosis → tune heap → restart → verify → writeback runbook" without any manual sabotage.

---

## 18. Development Order & Milestones

**Principle: Agent core closed loop first (console + log validation), then wrap web UI. Don't build UI before agent.**

### M1 — Inference Foundation (Get model running) ✅ Completed
- [x] llama.cpp ROCm/HIPBLAS compile verification (ldd confirms ROCm libs)
- [x] Qwen 27B Q4_K_M + KV **q8_0** + FA(`-fa on`) + mmap + prompt-cache running
- [x] Tool-calling format verification (returns `tool_calls`)
- [x] Performance baseline: generation 26 t/s, prompt 50 t/s, VRAM 21.7GB/51.5GB
- [x] Thinking model confirmed (`reasoning_content` as separate field)

### M2 — Tool Layer + Single-session ReAct (console) ✅ Completed
- [x] Tool layer: SSH real implementation, integrated with docker-compose Hadoop cluster
  - `get_service_status` → SSH execute jps/process check
  - `get_alerts` → iterate service health checks
  - `get_metrics` → SSH execute free/df/top
  - `read_logs` → SSH read remote logs, pre-compressed return
  - `search_kb` → hybrid retrieval (vector + BM25)
  - `restart_service` → SSH restart stopped service (✅ verified successful repair)
  - `hdfs_admin` → SSH execute dfsadmin/fsck/dfs read-only commands
  - `edit_remote_config` → SSH backup + modify + reload
- [x] Hand-written ReAct loop + single session runs fault scenario (console + logs)
- [x] docker-compose 3-node Hadoop + Prometheus + Grafana — **Delivered**: HDFS HA(2NN+3DN+3JN+ZKFC) + YARN HA(2RM+3NM+JHS) + Hive(MR engine) + HBase + ZK quorum + Prometheus + Grafana(4 dashboards) + SSH passwordless

### M3 — Orchestration Layer (master + sub-sessions + preemption) ✅ Completed
- [x] Orchestrator daemon + master pure-rule scheduler
- [x] Session manager (spawn ephemeral)
- [x] /auto inspection periodic loop + /fix preemption (alert-driven preempts inspection)
- [x] SQLite persistence (sessions/events/cluster_state)
- [x] Context strategy: one-shot context + DB state card passing + tool output pre-compression
- [x] End-to-end validation (round 1): Inspection → manual stop DataNode → detect alert → /fix diagnosis repair (15 ReAct rounds, restart_service failed due to JAVA_HOME)
- [x] End-to-end validation (round 2): Inspection → manual stop NameNode → detect alert → /fix diagnosis (check logs SIGTERM → check KB → check metrics exclude OOM → check jps confirm process gone) → restart_service CM API commands/start → hdfs_admin report verify recovery ✅ Full closed loop

### M4 — Safety Guardrails ✅ Completed
- [x] Risk grading: low (auto) / medium (execute+notify) / high (dry-run+approval) / destructive (backup+approval)
- [x] Dry-run preview: high-risk ops first return "what would happen" without executing
- [x] Approval gate: high-risk ops recorded to approvals table; console mode auto-approves, web mode waits for human
- [x] Audit log: all tool calls written to audit_log table (session/tool/args/risk/status/result/ts)
- [x] Circuit breaker escalation: consecutive failures ≥ 3 → auto-circuit-break, 5min cooldown, subsequent ops escalate to human
- [x] Rollback mechanism: `edit_remote_config` first `cp .bak.<ts>` backup then modify then reload; auto-rollback on replacement failure (§5.4 implemented)

### M5 — KB + Learning Closed Loop ✅ Completed
- [x] `runbooks` table + FTS5 full-text index + trigger sync; 6 seed runbooks
- [x] `kb.py`: bge-small-zh embedding (CPU lazy-load) + numpy cosine vector retrieval + BM25 hybrid retrieval; auto-degrades when deps missing
- [x] `write_runbook` writeback (confidence gating <0.7 reject + pending_review) + Web review flow
- [x] `agent.py` learning closed loop: after fix succeeds, auto-prompt runbook writeback
- [x] Tests `tests/test_m5_kb.py` (DB/FTS/CRUD/write_runbook/review/confidence gating)

### M6 — Web Console ✅ Completed
- [x] Backend FastAPI: REST API (/api/sessions /api/approvals /api/audit /api/cluster/snapshot) + WebSocket (/ws event push)
- [x] Event bus EventBus: thread-safe queue.Queue bridging agent sync code and WebSocket async push
- [x] Frontend React + Vite + Ant Design (dark theme):
  - Login page (localStorage token)
  - Sider collapsible menu + Header (user info/notification Badge/theme toggle) + Breadcrumb
  - Agent Activity: Session tree (master→auto/fix, time display, LIVE Badge) + Timeline event stream
  - Event rendering: Markdown (react-markdown + remark-gfm tables) + collapsible JSON (Collapse)
  - Approval Center: Table (pending/decided grouped, risk tags, approve/reject buttons)
  - Cluster Status card: selected master session shows Statistic + Descriptions service status
- [x] Streaming output: llm_client.chat_stream (SSE) + agent on_chunk callback pushes tokens to WebSocket
  - Frontend real-time assembly: stream_reasoning/stream_content incremental append, complete event replaces stream content
  - First-token latency normal (thinking model reasoning phase)
- [x] Smart scrolling: scrollRef + atBottomRef; auto-scroll only when user at bottom; scrolling up to view history doesn't interrupt
- [x] Full Chinese UI
> Pending items (Grafana iframe embedding, frontend beautification) tracked in `docs/TODO.md` M6.

### M7 — Demo & Submission

> Checklist in `docs/TODO.md` M7 (includes multi-fault scenarios / screen recording / README reproduction / performance data).

---

## 19. Open Questions (Design Decisions)

> Implementation TODOs have been consolidated into `docs/TODO.md` (including implementation steps, M7 demo checklist, pending parameters). This section retains only **design-level open decisions**; no duplicate TODOs.

| Item | Status | Notes |
|---|---|---|
| Is MTP supported by llama.cpp | ✅ Enabled | `--spec-type draft-mtp --spec-draft-n-max 1`. Benchmark (n_max=1~8): n_max=1 optimal 37.5 t/s (+30% vs baseline 28.9 t/s), acceptance rate 77.4%. Larger n_max → faster acceptance decay (n_max=8 only 24%); optimal value is 1 |
| Exact model & official GGUF | ✅ Confirmed | `Qwopus3.6-27B-v2-MTP-Q4_K_M.gguf`, 27B dense + tool-calling works |
| Thinking model handling | ✅ Confirmed | `reasoning_content` as separate field; agent reads directly, no `<think>` parsing needed |
| Emergency override thresholds/count/cooldown | ✅ Resolved in §5 | Attempt throttling (per `(tool,target)` query audit_log, over-limit escalates to human); specific values in TODO pending |
| KB retrieval: vector or BM25 | ✅ Decided | Hybrid retrieval: vector top-k + BM25 top-k merge dedup, vector-first; auto-degrades to BM25 when bge missing (M5 completed) |
| Approval timeout / inspection period / `-t` threads | Tentative | 10min / 5min / 16, all adjustable (see TODO pending) |
| restart_service startup failure | ✅ Fixed | SSH restart, does not depend on JAVA_HOME |
| Cluster environment | ✅ docker-compose delivered | 3-node Hadoop HA + Prometheus + Grafana + SSH, Docker Bridge 10.20.0.0/24 |

---

## Appendix: Key Constraints Memo

- **Dual environment**: Primary = remote AMD cloud W7900D 48GB + EPYC 9334 128 threads; Fallback = local 7900 XTX 24GB + 32GB RAM
- Primary env VRAM 21.7GB/51.5GB with ample headroom, KV q8_0; Fallback 24GB tight, KV q4_0 + context reduced to 64k
- GPU dedicated to llama-server; all other components on CPU
- Single GPU cannot truly parallelize → /fix preempts /auto, serial (`-np 1`)
- Normal context target 16–32k; 128k only for rare deep diagnosis (primary env only)
- Stability > marginal speedup (no overclocking)
- Thinking model: `reasoning_content` as separate field; agent reads directly
- Reproducibility: docker-compose + screen recording + README (judges cannot access LAN)
- Primary env persistent storage: `/workspace` 20G persistent volume (holds model); overlay root is non-persistent

---

## Appendix B: AMD Cloud Container Capability Exploration

> Tested on AMD Cloud JupyterLab container (Ubuntu 24.04 noble) on 2026-07-29. Confirmed that the container **does not support Docker-in-Docker**. Exploration process and findings below.

### Environment

| Item | Value |
|------|-------|
| Container | Ubuntu 24.04 (noble), JupyterLab pod |
| Kernel | Shared host kernel, `unprivileged_userns_clone=1` |
| CapEff | `0xa80425fb` (has `CAP_SYS_CHROOT`, `CAP_MKNOD`, **no `CAP_SYS_ADMIN`**) |

### Approaches Tried and Results

| Approach | Result | Failure Reason |
|----------|--------|-----------------|
| **Docker-in-Docker** (dockerd --storage-driver=vfs --iptables=false) | ❌ daemon starts, but `docker load` fails: `unshare: operation not permitted` | Missing `CAP_SYS_ADMIN`; `unshare(CLONE_NEWNS)` blocked |
| **Podman rootful** (overlay) | ❌ `mount overlay: permission denied` | Same as above; overlay requires real mount |
| **Podman rootful** (vfs) | ❌ `remount /, flags: 0x44000: permission denied` | Layer application requires `MS_PRIVATE\|MS_REC` remount, needs `CAP_SYS_ADMIN` |
| **Podman rootless** (non-root user) | ❌ `newuidmap: write to uid_map failed: Operation not permitted` | seccomp policy blocks `/proc/PID/uid_map` writes, even with `unprivileged_userns_clone=1` |
| **unshare -Ur** (root kernel built-in mapping) | Not confirmed working | `unshare(CLONE_NEWUSER)` likely also blocked by seccomp |
| **chroot** (has `CAP_SYS_CHROOT`) | ⚠️ supervisord runs, Java fails (`libjli.so` missing, ldconfig doesn't fix), no `/proc`/`/sys` | Library path issues + missing procfs; no separate network namespaces for 3 nodes |

### Conclusions

- AMD Cloud JupyterLab container **does not allow creating any namespaces** (mount/user/net all blocked by seccomp)
- Docker, Podman, and all containerization approaches are infeasible
- `export-cluster.sh` backup (image + data volumes) **cannot be used on AMD Cloud** (`docker load` fails)
- Backup files are only usable on **local Docker environments** or remote standalone servers

### Fallback Plans

| Plan | Status | Description |
|------|--------|-------------|
| **Single-node direct install** | ✅ Completed | Install Hadoop/ZK/HBase/Hive/Tez/MySQL directly on host + supervisord + 3 SSH ports. Demo effect unchanged. Script: `scripts/setup-hadoop-direct.sh` |
| **Unified health check** | ✅ Completed | `scripts/healthcheck.sh` — dual-mode compatible (Docker 3-node HA / single-node direct install), auto-detects mode |
| **Remote HA cluster** | Pending | Run Docker 3-node HA on standalone server; AMD Cloud agent connects via SSH tunnel |
