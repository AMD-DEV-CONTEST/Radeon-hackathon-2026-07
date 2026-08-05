# AIOps Agent — Autonomous Hadoop Cluster Operations on AMD Radeon GPU

> **English** | [中文](./README_ZH.md)
>
> **Track 2: Development & Local Deployment of Private AI Agents**
>
> An autonomous AIOps agent that monitors, diagnoses, and repairs a Hadoop cluster — powered by a 27B LLM running locally on AMD Radeon GPU (ROCm/HIPBLAS), with zero-trust safety guardrails, knowledge base RAG, and a real-time web console.
>
> **Cluster modes:**
> - **Local single-node**: Direct install on AMD Cloud host (no Docker required, no HA)
> - **Remote 3-node HA**: Connect to a remote Docker-based Hadoop HA cluster via SSH
>
> **Note**: AMD Cloud JupyterLab containers do not support Docker-in-Docker (missing `CAP_SYS_ADMIN`, seccomp blocks user namespaces). The local single-node mode bypasses this limitation. See `docs/DESIGN.md` Appendix B for details.

---

## Table of Contents

- [Architecture](#architecture)
- [Key Features](#key-features)
- [Reproduction Guide](#reproduction-guide)
- [One-Click Demo](#one-click-demo)
- [Performance](#performance)
- [Safety Guardrail](#safety-guardrail-21-dual-axis-four-tier)
- [Web Console](#web-console)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [ROCm Optimization](#rocm--radeon-gpu-optimization)
- [Tech Stack](#tech-stack)

---

## Architecture

All components run on a single AMD Cloud instance:

```mermaid
graph TB
    subgraph "AMD Cloud Container (JupyterLab)"
        subgraph "Inference Layer"
            LLAMA["llama-server<br/>127.0.0.1:8080<br/>Qwen27B Q4_K_M + MTP<br/>ROCm/HIPBLAS, KV q8, FA"]
        end

        subgraph "Control Plane (Python)"
            AGENT["Orchestrator + ReActAgent<br/>FastAPI :8000<br/>REST API + WebSocket"]
            WEB["React Frontend<br/>Static files from FastAPI"]
            AGENT --- WEB
        end

        subgraph "Hadoop Cluster (Single-node Direct Install)"
            H1["hadoop01 (localhost)<br/>NN+DN+RM+NM+JHS<br/>HM+RS+ZK+HMS+HS2"]
            MYSQL["MySQL<br/>Metastore"]
            PROM["Prometheus"]
            GRAF["Grafana"]
        end

        TUNNEL["rc-tunnel<br/>:8000 → public URL"]

        LLAMA -->|HTTP local| AGENT
        AGENT -->|SSH :2222-2224| H1
        AGENT -->|HTTP| PROM
        H1 --- MYSQL
        PROM --- H1
        PROM --- GRAF
        AGENT -->|127.0.0.1:8000| TUNNEL
    end

    JUDGE["Judge's Browser"] -->|HTTPS| TUNNEL

    style LLAMA fill:#ff6b6b,color:#fff
    style AGENT fill:#4ecdc4,color:#fff
    style WEB fill:#45b7d1,color:#fff
    style TUNNEL fill:#f9ca24,color:#333
    style JUDGE fill:#6c5ce7,color:#fff
```

### System Layers

| Layer | Component | Technology |
|-------|-----------|------------|
| Inference | llama-server (local) | llama.cpp + ROCm/HIPBLAS, Qwen27B Q4_K_M, MTP speculative decoding |
| Control | Orchestrator + ReActAgent | Python, FastAPI, WebSocket |
| Data | Hadoop single-node (direct install) | HDFS + YARN + Hive + HBase + ZK + Tez, managed by supervisord |
| Monitoring | Prometheus + Grafana | JMX Exporter → Prometheus → Grafana dashboards |
| Frontend | React + Ant Design | Vite build → FastAPI static hosting (single port) |
| Knowledge | SQLite + bge-small-zh | Hybrid RAG: vector + BM25, CPU embedding |

---

## Key Features

1. **24h Autonomous Loop** — Periodic inspection (`/auto`) + alert-driven repair (`/fix`) with preemption
2. **LLM-Driven Anomaly Detection** — Agent analyzes `hdfs report` / `metrics` / `logs` output to detect unknown faults (not just pre-coded alerts)
3. **Safety Guardrails** — Risk classification (low → irreversible), dry-run, approval gate, audit log, circuit breaker, rollback
4. **Knowledge Base RAG** — Hybrid vector + BM25 search, agent writes runbooks after fixes (confidence-gated + human review)
5. **ROCm Optimization** — HIPBLAS compile, KV q8_0, Flash Attention, MTP speculative decoding (+30% throughput)
6. **Context Engineering** — One-shot context per session + DB state card + tool output pre-compression (keeps context ≤16k)

---

## Reproduction Guide

### Prerequisites

- An AMD Cloud instance with Radeon GPU (W7900D 48GB)
- JupyterLab terminal access (or SSH)
- ROCm pre-installed (AMD Cloud default)

### Step 1: Clone the Repository

```bash
cd /workspace
git clone <your-repo-url> Radeon-hackathon
cd Radeon-hackathon
```

### Step 2: One-Click Deploy

```bash
bash scripts/setup-cloud.sh
```

This script automatically performs **all** of the following (idempotent — safe to re-run):

| Step | Action | Time |
|------|--------|------|
| 1 | Compile llama.cpp with ROCm/HIPBLAS | ~10-15 min (first time) |
| 2 | Download model + start llama-server (via `bootstrap.sh`) | ~5-10 min |
| 3 | Hadoop cluster — single-node direct install (via `setup-hadoop-direct.sh`) | ~10-15 min |
| 4 | Install Python dependencies | ~1 min |
| 5 | Build React frontend (production) | ~1 min |
| 6 | Generate `.env` + start Agent + Web | ~10s |
| 7 | Expose via rc-tunnel (public URL) | ~5s |

**Total: ~20-30 min (first run), ~2 min (subsequent runs, everything cached)**

The script will prompt you to select a cluster mode:

```
Select Hadoop cluster mode:
  1) Local single-node — Direct Hadoop install on AMD Cloud host (no Docker, no HA)
  2) Remote HA cluster — Connect to remote Docker 3-node Hadoop HA
Enter 1 or 2 [default 1]:
```

- **Mode 1 (recommended for judges)**: Installs Hadoop/ZK/HBase/Hive/Tez/MySQL directly on the AMD Cloud host using `setup-hadoop-direct.sh`. No Docker required. Uses supervisord for process management and 3 SSH ports (2222/2223/2224) for the Agent to connect. All JMX exporter ports match the Docker version for monitoring compatibility.
- **Mode 2**: Connects to a pre-existing remote Docker 3-node Hadoop HA cluster via SSH. Requires the remote cluster to be already running.

Upon completion, the script prints the public URL:

```
############################################################
#  Deployment complete!
#
#  Local access:  http://127.0.0.1:8000
#  Public access: https://rc-xxxxx.radeon.firstdg.ai
#  Agent log:     /workspace/agent.log
#  LLM log:       /workspace/llama-server.log
#
#  Run demo:      bash scripts/inject-fault.sh
############################################################
```

### Step 3: Verify Deployment

```bash
# Check health
curl http://127.0.0.1:8000/health
# Expected: {"status":"healthy","llm_reachable":true,"db_ok":true}

# Check Hadoop cluster (single-node direct install)
/opt/hadoop/bin/hdfs dfsadmin -report | head -15

# Run unified health check
bash scripts/healthcheck.sh

# Open web console in browser
# Use the public URL printed by setup-cloud.sh
```

### Step 4: Run the Demo

```bash
bash scripts/inject-fault.sh
```

This script:
1. Injects a fault: stops DataNode
2. Waits for the Agent to detect, diagnose, and repair (≤120s)
3. Verifies cluster recovery (DataNode online)
4. Prints the repair session summary and audit log

### Manual Step-by-Step (Alternative to One-Click)

If you prefer to run each step manually:

```bash
# 1. Compile llama.cpp
bash scripts/build-llama.sh

# 2. Download model + start llama-server (local only, no rc-tunnel)
bash scripts/bootstrap.sh

# 3. Install Hadoop cluster (single-node direct install)
bash scripts/setup-hadoop-direct.sh

# 4. Run health check
bash scripts/healthcheck.sh

# 5. Install Python deps
pip3 install -r requirements.txt --break-system-packages

# 6. Build frontend
bash scripts/build-frontend.sh

# 7. Configure + start
cp .env.example .env
# Edit .env: set LLM_API_KEY, SSH_KEY_PATH, etc.
source .env
python3 -m main

# 8. Expose via rc-tunnel (expose web console, not LLM)
~/.local/bin/rc-tunnel expose --port 8000
```

---

## One-Click Demo

```bash
bash scripts/inject-fault.sh
```

**What happens:**

```
════════════════════════════════════════
 0/5 Pre-check
════════════════════════════════════════
  [PASS] Agent is running
  [PASS] Hadoop cluster is running
  [PASS] DataNode: 1/1 online

════════════════════════════════════════
 1/5 Inject fault: stop DataNode
════════════════════════════════════════
  [PASS] DataNode stopped

════════════════════════════════════════
 2/5 Wait for Agent auto-detect + repair (max 120s)
════════════════════════════════════════
  ... Agent is diagnosing ...
  [PASS] DataNode recovered! (waited 42s)

════════════════════════════════════════
 3/5 Verify cluster recovery
════════════════════════════════════════
  [PASS] HDFS DataNode: 1/1 online

════════════════════════════════════════
 4/5 Agent repair records
════════════════════════════════════════

════════════════════════════════════════
 5/5 Demo complete
════════════════════════════════════════
  ✓ Fault injected: DataNode STOPPED
  ✓ Agent autonomous: detect → diagnose → restart → verify
  ✓ Result: cluster recovered, 1/1 DataNode online
```

---

## Performance

### LLM Inference (AMD Radeon PRO W7900D 48GB, ROCm/HIPBLAS)

| Metric | Value |
|--------|-------|
| Model | Qwen27B Q4_K_M (16GB GGUF) |
| KV Cache | q8_0 (quality > size, 48GB has headroom) |
| Context Window | 128k tokens |
| Generation Speed | 29 t/s (short context), 23 t/s (32k context) |
| Prompt Processing | 265 t/s (4k), 106 t/s (32k) |
| TTFT | 0.25s (short), 1.5s (4k), 190s (32k) |
| VRAM Usage | 21.7GB / 51.5GB (42% utilization) |
| MTP Speculative Decoding | 37.5 t/s (+30% vs baseline 28.9 t/s, accept rate 77.4%) |

### MTP Benchmark

| Config | t/s (client) | Speedup | Accept Rate |
|--------|-------------|---------|-------------|
| baseline (no MTP) | 28.9 | — | — |
| **n_max=1 (optimal)** | **37.5** | **+30%** | 77.4% |
| n_max=2 | 34.2 | +18% | 61.0% |
| n_max=3 | 34.0 | +18% | 53.7% |
| n_max=5 | 31.7 | +10% | 44.6% |
| n_max=8 | 29.5 | +2% | 24.0% |

### Agent Fault Resolution (7 Test Cases)

| Fault | Type | Detect Time | Repair Time | Result |
|-------|------|-------------|-------------|--------|
| ZooKeeper STOPPED | Process crash | 8s | 42s | ✅ PASS |
| DataNode STOPPED | Process crash | 7s | 70s | ✅ PASS |
| NodeManager + RegionServer | Dual concurrent | 6s/49s | 32s/42s | ✅ PASS |
| HDFS Safe Mode ON | State anomaly | 0s | 108s | ✅ PASS |
| Disk Full + Safe Mode | Cascading | 0s | 108s | ✅ PASS |
| HDFS Corrupt Blocks | Data integrity | ~80s | ~120s | ✅ PASS |
| HiveServer2 OOM Crash | OOM | 2s | ~60s | ✅ PASS |

> Full test report: `docs/AGENT_TEST_REPORT.md`

---

## Safety Guardrail (§21 Dual-Axis Four-Tier)

| Tier | Typical Ops | Autonomous Behavior | Supervised Behavior |
|------|------------|---------------------|---------------------|
| low / medium | Read-only / restart non-core | Auto-execute | Auto-execute |
| recover | Restart DOWN service | Attempt throttle → auto-execute | Wait for approval |
| reversible | Config edit (backup first) | Auto-execute (forced backup) | Wait for approval |
| irreversible | hdfs format / rm | **Immediate reject + escalate** | Wait for approval |

Classification authority belongs to rules (DB), not the model. Fail-closed: unknown tools default to irreversible + not auto-executable.

---

## Web Console

- **Sidebar**: Agent Activity / Approval Center / Risk Rules (collapsible)
- **Agent Activity**: Session tree (master→auto/fix) + Timeline event stream (Markdown rendering + streaming output + collapsible JSON)
- **Approval Center**: Pending list + approve/reject + risk tags + badge counter
- **Risk Rules**: risk_rules CRUD (irreversible tier disables autonomous checkbox)
- **Cluster Status**: Service health cards (overall_health + per-service) when master session selected

---

## Project Structure

```
Radeon-hackathon/
├── scripts/                     # Deployment & demo scripts
│   ├── setup-cloud.sh           # ★ One-click deploy (AMD Cloud)
│   ├── setup-hadoop-direct.sh   # ★ Single-node Hadoop direct install
│   ├── inject-fault.sh          # ★ One-click demo (inject fault → repair)
│   ├── healthcheck.sh           # Hadoop cluster health check (Docker/direct)
│   ├── build-llama.sh           # Compile llama.cpp with ROCm
│   ├── build-frontend.sh        # Build React frontend (production)
│   ├── download-tarballs.sh     # Download Hadoop tarballs
│   ├── export-cluster.sh        # Export Docker image + volumes (for remote HA)
│   └── bootstrap.sh             # Start llama-server (model download)
├── main.py                      # Entry point: FastAPI + Orchestrator
├── src/                         # Python backend
│   ├── config.py                # Configuration (env var driven)
│   ├── orchestrator.py          # Master scheduler (rule-based)
│   ├── agent.py                 # ReAct agent (tool-calling LLM)
│   ├── llm_client.py            # LLM client (llama.cpp HTTP API)
│   ├── tools.py                 # Tool layer (SSH, Prometheus, KB)
│   ├── guardrails.py            # Risk classification + approval
│   ├── kb.py                    # Knowledge base (vector + BM25 RAG)
│   ├── db.py                    # SQLite store
│   └── web/
│       └── app.py               # FastAPI REST + WebSocket + static
├── web/                         # React frontend
│   ├── src/
│   │   ├── App.tsx              # Main layout (Ant Design dark theme)
│   │   └── components/          # AgentActivity, ApprovalCenter, etc.
│   └── vite.config.ts           # Vite build config
├── deploy/                      # Hadoop cluster deployment
│   ├── docker-compose.yml       # 3-node HA cluster + MySQL + monitoring
│   ├── image/Dockerfile         # Multi-role Hadoop image
│   ├── config/                  # Hadoop/Hive/HBase/ZK/Prometheus/Grafana
│   └── scripts/                 # init-cluster.sh, restart-daemons.sh
├── docs/                        # Design docs, test report, TODO
├── requirements.txt             # Python dependencies
└── .env.example                 # Environment variable template
```

---

## Configuration

All configuration is driven by environment variables (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_BASE_URL` | `http://127.0.0.1:8080/v1` | llama-server URL |
| `LLM_API_KEY` | (required) | API key for llama-server |
| `LLM_MODEL` | `/workspace/Qwopus3.6-...gguf` | Model file path |
| `AUTONOMY` | `supervised` | `supervised` (manual approval) or `autonomous` (auto-execute) |
| `PROMPT_LANGUAGE` | `en` | Prompt language (`en` / `zh`) |
| `CLUSTER_BACKEND` | `apache` | Cluster type (`apache` for Hadoop) |
| `SSH_KEY_PATH` | (from deploy) | SSH key for Hadoop nodes |

> `scripts/setup-cloud.sh` auto-generates `.env` with correct values.

---

## ROCm / Radeon GPU Optimization

| Optimization | Status | Details |
|-------------|--------|---------|
| HIPBLAS (ROCm) | ✅ Verified | `ldd` shows `libamdhip64.so`, `libhipblas.so` — not Vulkan |
| KV Cache Quantization | q8_0 | `-ctk q8_0 -ctv q8_0` (48GB VRAM has headroom) |
| Flash Attention | ✅ On | `-fa on` |
| mmap Loading | ✅ Default | No flag needed |
| Prompt Caching | ✅ Verified | 181/198 prompt tokens cache hit |
| MTP Speculative Decoding | ✅ Enabled | `--spec-type draft-mtp --spec-draft-n-max 1` (+30% throughput) |
| Context Pruning | ✅ Design | One-shot context per session, ≤16k working context |

---

## Tech Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Inference | llama.cpp (ROCm/HIPBLAS) | Native ROCm, not Vulkan (required by scoring rubric) |
| Backend | Python + FastAPI | Async HTTP, WebSocket, rapid development |
| Frontend | React + Ant Design | Dark theme admin console, real-time updates |
| Orchestration | Hand-written ReAct loop | No heavy framework, fully controllable |
| Database | SQLite (single file) | Events, audit, state card, KB — zero extra services |
| Monitoring | Prometheus + Grafana | Standard big-data monitoring stack |
| Cluster | Single-node direct install | No Docker needed, works on AMD Cloud |
