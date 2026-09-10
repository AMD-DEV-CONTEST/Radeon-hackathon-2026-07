# MKO Universal AI Agents — Features Guide

**Track 2: Development & Local Deployment of Private AI Agents**

> A multi-provider, multi-agent chat platform with a Stripe credit system, GPU compute benchmarking, Retrieval-Augmented Generation, and a Mixture-of-Experts agent — all deployable locally with a single command, no secrets required.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Core Feature: Multi-Agent Chat System](#2-core-feature-multi-agent-chat-system)
3. [Core Feature: 5 LLM Providers](#3-core-feature-5-llm-providers)
4. [Core Feature: Slash Commands & Autocomplete](#4-core-feature-slash-commands--autocomplete)
5. [Core Feature: Mixture of Experts (MoE) Agent](#5-core-feature-mixture-of-experts-moe-agent)
6. [Core Feature: Agent DAG Canvas](#6-core-feature-agent-dag-canvas)
7. [Core Feature: GPU Compute Benchmark](#7-core-feature-gpu-compute-benchmark)
8. [Core Feature: Provider Latency Benchmark](#8-core-feature-provider-latency-benchmark)
9. [Core Feature: RAG (Retrieval-Augmented Generation)](#9-core-feature-rag-retrieval-augmented-generation)
10. [Monetization: Stripe Credit System](#10-monetization-stripe-credit-system)
11. [Admin Panel](#11-admin-panel)
12. [Settings Panel](#12-settings-panel)
13. [Deployment: Docker + ROCm](#13-deployment-docker--rocm)
14. [CI/CD: GitHub Actions](#14-cicd-github-actions)
15. [Security Gates: Hadolint & Trivy](#15-security-gates-hadolint--trivy)
16. [No-Secrets Architecture](#16-no-secrets-architecture)
17. [Local Runnability](#17-local-runnability)
18. [Test Suite](#18-test-suite)

---

## 1. Architecture Overview

```
┌───────────────────────────────────────────────────────────┐
│                    Browser (Vanilla JS)                     │
│  index.html → app.js → slash-commands.js → moe-graph.js   │
│  pricing.html | admin.html | styles.css                     │
└──────────────────────┬────────────────────────────────────┘
                       │  SSE (Server-Sent Events)
                       ▼
┌───────────────────────────────────────────────────────────┐
│              FastAPI + Uvicorn (Python)                    │
│  server.py ←→ llm_router.py                                │
│  /api/chat  /api/agents  /api/credits  /api/benchmark/run │
│  /api/rag/*  /api/stripe/*  /api/admin/*  /api/config      │
└──────┬──────────┬──────────┬──────────┬───────────────────┘
       │          │          │          │
       ▼          ▼          ▼          ▼
   Ollama      Groq      OpenAI    Anthropic
   (local)   (cloud)    (cloud)    (cloud)
                          ┌─────────┐
                          │ Qdrant  │  (optional RAG vector DB)
                          └─────────┘
                          ┌─────────────┐
                          │ AMD Radeon  │  (GPU benchmark via ROCm)
                          └─────────────┘
```

**Tech stack:**
- **Backend:** Python 3.10+, FastAPI, Uvicorn, httpx, Stripe, NumPy
- **Frontend:** Vanilla JavaScript (ES modules), CSS3, SVG (no framework dependencies)
- **AI Providers:** Ollama (local), Groq, HuggingFace, OpenAI, Anthropic
- **Optional Heavy Deps:** qdrant-client, sentence-transformers, PyTorch (comes with ROCm Docker image)
- **Deployment:** Docker, docker-compose, ROCm 6.2

---

## 2. Core Feature: Multi-Agent Chat System

Eight specialized agents, each with a distinct system prompt and icon:

| Agent | Icon | Purpose |
|---|---|---|
| **General** | 🧠 | All-purpose AI assistant for conversation and Q&A |
| **Planner** | 📋 | Breaks down tasks into actionable step-by-step plans with time estimates and dependencies |
| **Researcher** | 🔍 | Deep-dive research with structured findings, sources, and key takeaways |
| **Reasoner** | ⚖️ | Logical analysis and critical thinking with multiple perspectives |
| **Actor** | ⚡ | Task execution and workflow automation with structured output |
| **Memory** | 💾 | Contextual recall and persistent state tracking across the conversation |
| **RAG Agent** | 📚 | Retrieval-augmented generation from uploaded documents (requires Qdrant) |
| **MoE Agent** | 🔀 | Mixture of Experts — parallel calls to multiple LLMs with weighted synthesis |

Users switch agents via:
- The **agent dropdown** in the chat UI header
- **Slash commands** (`/plan`, `/research`, `/summary`)
- The **Settings panel** for default agent

Each agent costs credits per request (configurable). The system prompt is injected automatically behind the scenes — the user just chats naturally.

---

## 3. Core Feature: 5 LLM Providers

The platform routes chat requests through a unified `UniversalLLM` class that normalizes streaming responses from five providers:

| Provider | Type | Default Model | Local? | Free Tier? |
|---|---|---|---|---|
| **Ollama** | Local | `llama3.2` | ✅ Yes | ✅ Always free |
| **Groq** | Cloud | `llama-3.3-70b-versatile` | ❌ No | ✅ Free tier available |
| **HuggingFace** | Cloud | `zephyr-7b-beta` | ❌ No | ✅ Free tier available |
| **OpenAI** | Cloud | `gpt-4o-mini` | ❌ No | ❌ Paid |
| **Anthropic** | Cloud | `claude-3-5-haiku-20241022` | ❌ No | ❌ Paid |

**Key behaviors:**
- **All providers stream** responses token-by-token over Server-Sent Events (SSE)
- **No provider crashes the app** — missing API keys yield a friendly `⚠️` message mid-stream
- **Ollama gracefully degrades** — if the local Ollama server isn't running, it says so instead of erroring
- Provider switching is instant via the UI dropdown, slash commands, or Settings panel
- Each provider exposes its own model list via `/api/models`

---

## 4. Core Feature: Slash Commands & Autocomplete

Type `/` in the chat input to access the full command system. A live autocomplete dropdown lists every command as you type.

| Slash | What it does |
|---|---|
| `/plan <topic>` | Switch agent to **Planner**, seed the input with `<topic>` |
| `/research <query>` | Switch agent to **Researcher**, seed the input with `<query>` |
| `/summary <text>` | Switch to **General** agent, seed the input |
| `/model <provider>[/<model>]` | Swap active provider and optionally model; emits confirmation bubble |
| `/provider <name>` | Swap active provider (model resets to default); confirmation bubble |
| `/help` | Emit a multi-line system bubble listing every command live from the code |
| `/commands` | Terse alias for `/help` |

**Invariants:**
- Commands are **case-insensitive** (`/PLAN` works)
- Must be **at the start of the input** (`Hello /plan` is plain chat)
- **Trailing slashes are stripped** (`/model groq/` → provider `groq`)
- Unknown providers emit a `⚠️` hint listing valid ones
- A bare `/` emits a friendly hint suggesting `/plan` or `/model`
- Autocomplete navigation: ↑/↓ navigate, Tab/Enter complete, Escape dismisses
- Help text stays in sync with code — add a new command and `/help` auto-includes it

**Implementation:** Pure vanilla JS in `mko/webui/static/js/slash-commands.js` (UMD module). Tests: `tests/test_slash_commands.mjs` (47 cases).

---

## 5. Core Feature: Mixture of Experts (MoE) Agent

The MoE Agent runs multiple LLM calls **in parallel** and synthesizes their outputs through a weighted gate model.

**Architecture:**

```
User Query
     │
     ▼
 ┌─────────────────────────────────────────┐
 │           Gate / Router                  │
 │  (dispatches to each expert in parallel) │
 └────┬──────────┬──────────┬──────────────┘
      │          │          │
      ▼          ▼          ▼
  Expert 1   Expert 2   Expert 3
  (Groq)    (Ollama)   (OpenAI)
      │          │          │
      └──────────┼──────────┘
                 ▼
 ┌─────────────────────────────────────────┐
 │        Weighted Synthesis Gate           │
 │  Combines responses using configured     │
 │  weights into a single coherent answer   │
 └─────────────────────────────────────────┘
                 │
                 ▼
          Final Response
```

**How it works:**
1. **Configure experts** — pick any combination of providers (e.g., `["ollama", "groq", "openai"]`)
2. **Set weights** — control how much each expert influences the final output
3. **Parallel dispatch** — all experts are called simultaneously via `asyncio.gather`
4. **Debug telemetry** — each expert's latency (ms), token count, weight, and raw response are streamed down
5. **Weighted synthesis** — a gate model merges the expert outputs using the configured weights

**Configuration:** Via the Settings panel or `/api/moe/config` endpoint. Stored in gitignored `data/webui_config.json`.

**Cost:** MoE costs base credits per request (configurable), charged per expert call.

---

## 6. Core Feature: Agent DAG Canvas

When the MoE Agent streams its debug telemetry, an inline SVG graph renders **visually inside the assistant's chat bubble** — no extra dependencies.

**What it shows:**
- **Gate node** — top center, labeled "Gate"
- **Expert nodes** — one per expert, evenly spaced below, labeled with provider name
- **Directed edges** — gate → expert, with edge annotations at the midpoint showing:
  - **Weight** (e.g., `1x`)
  - **Latency** (e.g., `· 220ms`) — when present
  - **Tokens** (e.g., `· 332 tokens`) — when present
- **Deterministic colors** — each provider always gets the same color (DJB2 hash of name)
- **Arrow markers** — clear directional flow from gate to expert
- **Accessibility** — `<title>` and `<desc>` SVG elements provide screen reader support
- **Collapsible** — the DAG is inside the existing MoE debug panel, toggled by the `🔀` header

**Implementation:**
- Pure layout + renderer in `mko/webui/static/js/moe-graph.js` (UMD module, ~290 lines)
- DOM glue: a single `renderMoEDAG()` call in `app.js`
- Layout algorithm: gate at top center, N=1 expert shares gate X (single vertical edge), N>1 experts distributed evenly
- Tests: `tests/test_moe_graph.mjs` (33 cases, all pure — no DOM needed)
- SVG: `<defs>`, `<marker>`, arrow head, escapeXml-safe text, auto-sized background pills for edge labels

---

## 7. Core Feature: GPU Compute Benchmark

A real-time benchmark that measures matrix multiplication performance on CPU vs GPU.

**Endpoint:** `POST /api/benchmark/run` (Server-Sent Events stream)

**What it tests:**
- Matrix sizes: 500×500, 1000×1000, 2000×2000, 3000×3000
- **CPU:** NumPy `float32` matrix multiply
- **GPU:** PyTorch matrix multiply on CUDA or HIP (AMD ROCm) device

**Output (streamed as SSE events):**
- `progress` events with percentage and label (drives a progress bar in the UI)
- `benchmark_result` event with:
  - GPU name and memory (GB)
  - Per-matrix-size: CPU ms, GPU ms, speedup ratio
  - Average speedup
  - Estimated LLM tokens/sec (derived from speedup)
  - Backend detected (`cuda`, `rocm`, or `cpu`)

**Graceful degradation:**
- If PyTorch is not installed → runs CPU only, reports "CPU Only"
- If CUDA/HIP is unavailable → same graceful fallback
- Streams heartbeats so the UI never hangs

---

## 8. Core Feature: Provider Latency Benchmark

Tests time-to-first-token and total response time across configured LLM providers.

**Endpoint:** `GET /api/benchmark/providers` (SSE stream)

**Tested providers:** Ollama, Groq, OpenAI
**Metrics per provider:** Status, time-to-first-token (ms), total time (ms), error message (if any)
**Edge cases:** Missing API keys are gracefully reported as `"error: No API key"`, connection failures return clean errors.

---

## 9. Core Feature: RAG (Retrieval-Augmented Generation)

Upload documents and query them using semantic search.

**How it works:**
1. **Ingest** — `POST /api/rag/ingest` accepts a file upload (any text format)
2. **Chunking** — text is split into 500-word chunks
3. **Embedding** — `sentence-transformers/all-MiniLM-L6-v2` creates 384-dimension vectors
4. **Indexing** — vectors stored in Qdrant (local vector database at `data/qdrant_db/`)
5. **Query** — the RAG Agent searches all collections and returns the top-3 matching chunks as context

**Graceful degradation:**
- Missing Qdrant/sentence-transformers → returns a clean 400 error explaining which dependency to install
- No files uploaded → returns a helpful message directing the user to upload first
- No relevant match → returns "No relevant documents found"

**Dependencies:** `qdrant-client`, `sentence-transformers` (optional — not required for baseline operation)

---

## 10. Monetization: Stripe Credit System

A complete credit-based billing system with five tiered packs.

### Credit Packs

| Pack | Credits | Bonus | Total | Price | Credits/$ |
|---|---|---|---|---|---|
| Starter | 500 | 0 | 500 | $10 | 50.0 |
| Essential | 1,500 | 200 | 1,700 | $25 | 68.0 |
| Pro | 3,500 | 500 | 4,000 | $50 | 80.0 |
| Power | 8,000 | 1,500 | 9,500 | $100 | 95.0 |
| Ultimate | 15,000 | 5,000 | 20,000 | $150 | 133.3 |

### Demo Codes

Six built-in codes for testing (no Stripe required):

| Code | Credits |
|---|---|
| `MKO-TRIAL-50` | 50 |
| `MKO-STARTER-500` | 500 |
| `MKO-ESSENTIAL-1700` | 1,700 |
| `MKO-PRO-4000` | 4,000 |
| `MKO-POWER-9500` | 9,500 |
| `MKO-ULTIMATE-20000` | 20,000 |

### Endpoints

- `GET /api/stripe/config` — publishable key, enabled status, pack list
- `POST /api/stripe/create-checkout-session` — Stripe Checkout session creation
- `POST /api/stripe/webhook` — Stripe webhook handler (signature-verified)
- `GET /api/credits?username=demo` — check balance
- `POST /api/credits/redeem` — redeem demo/refund codes

**Without Stripe keys configured:** Checkout returns a 400 with a friendly explanation. The pricing UI still renders. Credits work via demo codes.

---

## 11. Admin Panel

A full admin interface at `/admin` with:

- **Login** — default password `admin123` (SHA-256 hashed, 24-hour session tokens)
- **User List** — see all users, their credits, total purchased, and per-model request counts
- **Issue Refunds** — add credits to any user with a reason (logged to refund codes)
- **Change Password** — secure password update with current-password verification
- **Statistics Dashboard** — total users, total credits in circulation, total purchases, total requests, per-model breakdown

All admin data is stored in `data/admin_config.json` (gitignored).

---

## 12. Settings Panel

A UI panel for runtime configuration (no file editing needed):

- **Provider selection** — choose active LLM provider
- **Model selection** — pick from available models for the chosen provider
- **API key management** — paste API keys for any provider (persisted to gitignored `data/webui_config.json`)
- **MoE Configuration** — select expert providers, set weights, and synthesis temperature
- **Status indicators** — green checkmark for configured providers, red for missing keys

**Env var override:** Environment variables (`GROQ_API_KEY`, `OPENAI_API_KEY`, etc.) take precedence over the Settings panel at request time.

---

## 13. Deployment: Docker + ROCm

Production-grade Docker deployment targeting AMD Radeon GPUs.

### Dockerfile

- **Base image:** `rocm/pytorch:rocm6.2_ubuntu22.04_py3.10_pytorch_2.3.0` — ROCm 6.2 native support for RDNA3 (RX 7000 / RX 9070) without compat hacks
- **Layer caching:** Python dependencies installed before source code for faster rebuilds
- **HEALTHCHECK:** `curl -fsS /api/agents` with 30s interval, 15s start period
- **Port:** 49239
- **Python:** 3.10 with PyTorch 2.3.0 (HIP-enabled) pre-installed

### Docker Compose

One-command bring-up: `docker compose up --build`

**What the compose file provides:**
- Port mapping `49239:49239`
- Bind-mount `./data:/app/data` (persists users, credits, settings across restarts)
- Optional `.env.local` and `.env` files (both gitignored)
- ROCm device passthrough: `/dev/kfd` and `/dev/dri`
- Group membership: `video`, `render`
- `SYS_PTRACE` capability and `seccomp:unconfined` for HSA introspection

**Verify GPU passthrough:**
```bash
docker compose exec mko python -c "import torch; print(f'GPU: {torch.cuda.is_available()}, HIP: {torch.version.hip}')"
```

---

## 14. CI/CD: GitHub Actions

Full CI pipeline at `.github/workflows/ci.yml` that runs on every push to `main` and every PR.

**Pipeline steps:**
1. **Checkout** — `actions/checkout@v4`
2. **Hadolint security gate** — Dockerfile linting, fails on warnings (DL3008 pinning, etc.)
3. **Build** — `docker/build-push-action@v6` with GHA layer caching
4. **Trivy security gate** — image CVE scan, fails on CRITICAL vulnerabilities
5. **Boot stack** — `docker compose up -d --wait --wait-timeout 240`
6. **Smoke tests:**
   - `GET /api/agents` → HTTP 200
   - `GET /api/credits?username=demo` → valid JSON with `.credits` (number) and `.username == "demo"`
   - Container HEALTHCHECK → status `"healthy"`
   - `torch.cuda.is_available()` → hard fail on self-hosted GPU runners, informational on GitHub-hosted CPU runners
7. **Tear down** — always runs, even on failure

**SARIF uploads:** Both Hadolint and Trivy results upload to GitHub code-scanning alerts (visible in Security tab).

---

## 15. Security Gates: Hadolint & Trivy

Two layers of container security in CI.

### Hadolint (Dockerfile Linter)

- Fails on **warnings** (DL3008 — pin versions in apt-get install)
- Supported rules: apt-get pinning (curl 7.81.0, ca-certificates 20230311), `--no-install-recommends`, `rm -rf /var/lib/apt/lists/*`
- Output: SARIF → GitHub code-scanning alerts

### Trivy (Image Vulnerability Scanner)

- Scans the **built image** (including the rocm/pytorch base layer)
- Fails on **CRITICAL** severity CVEs
- `ignore-unfixed: true` — only fail on CVEs with published fixes
- Scanners: `vuln` (OS packages + pip libraries)
- Output: SARIF → GitHub code-scanning alerts

---

## 16. No-Secrets Architecture

**This repository contains zero secrets.** Everything needed to evaluate runs without API keys.

### How it works

| Layer | What's committed | What's gitignored |
|---|---|---|
| **Source code** | All `.py`, `.js`, `.css`, `.html` files | Nothing |
| **Configuration** | `.env.example` (empty values) | `.env`, `.env.local`, `.env.*.local` |
| **Runtime state** | Nothing | `data/` (users, credits, API keys, Qdrant DB) |
| **Build** | `Dockerfile`, `docker-compose.yml` | Nothing — secrets are env-file-only |
| **CI** | `.github/workflows/ci.yml` | Nothing |
| **Operator docs** | `.freebuff/run.md`, `.freebuff/launch.py` | `.freebuff/*.log`, `.freebuff/*.pid` |

### Demo Mode (no API keys)

When no providers are configured, the app:
- ✅ Serves the full UI at `http://localhost:49239/`
- ✅ Returns all 8 agent descriptors at `/api/agents`
- ✅ Shows the pricing UI with all 5 credit packs
- ✅ Renders the Admin panel with default password `admin123`
- ✅ Streams friendly `⚠️ No <provider> API key configured…` messages instead of crashes
- ✅ Returns clean 400 from Stripe endpoints explaining how to enable them
- ✅ Runs GPU benchmarks (CPU-only fallback)
- ⚠️ **Does not** make real LLM calls (needs an API key or Ollama running)

### Verify no secrets leaked

```bash
grep -rE "gsk_[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|whsec_[A-Za-z0-9]+" \
  --exclude-dir=data --exclude-dir=.git .
```

---

## 17. Local Runnability

**The app runs entirely locally with no cloud dependencies.** Evaluators can verify every feature on their own machine.

### Quick Start (bare metal)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the server
python run.py

# 3. Open http://127.0.0.1:49239
```

No GPU required. No API keys required. No Docker required.

### Quick Start (Docker with AMD GPU)

```bash
docker compose up --build
# Opens at http://localhost:49239
```

### Verify it works

```bash
curl -fsS http://127.0.0.1:49239/                           # → HTML page
curl -fsS http://127.0.0.1:49239/api/agents                 # → 8 agents
curl -fsS "http://127.0.0.1:49239/api/credits?username=demo" # → credit balance
```

### Test suite (all local, no external services)

```bash
# JavaScript tests (Node 18+)
node --test tests/test_slash_commands.mjs   # 47 tests — slash command parser
node --test tests/test_moe_graph.mjs        # 33 tests — DAG layout + SVG renderer

# Python smoke tests
python -m unittest discover -s tests -p test_run_smoke.py  # 14 tests — wiring pins
```

---

## 18. Test Suite

Three test suites covering every layer of the application:

### `test_slash_commands.mjs` (47 tests)
Node.js native tests (`node:test`) exercising the slash command parser:
- Every command family (`/plan`, `/research`, `/summary`, `/model`, `/provider`, `/help`, `/commands`)
- Edge cases: trailing slashes, multi-slash models, case-insensitivity, mid-sentence slashes, quoted args, bare `/`
- Format confirmation helper validation
- KNOWN_PROVIDERS and KNOWN_AGENTS constants
- Autocomplete suggestions (`getSuggestions`)

### `test_moe_graph.mjs` (33 tests)
Pure-function tests (no DOM needed):
- Layout invariants: 0/1/3 experts, empty/null/malformed input, even-X spacing
- Edge annotations: weight-only, weight+time, weight+tokens, all three, absent fields
- SVG rendering: `<defs>`, `<marker>`, `<title>`, `<desc>`, aria-label pluralization
- XML safety in `<desc>` text
- Deterministic color hashing
- Drift pin: asserts `escapeXml` is called on provider/sublabel/weight

### `test_run_smoke.py` (14 tests)
End-to-end wiring verification:
- File existence pins (all JS, HTML, CSS, test files exist)
- Parser public surface (`MKOSlash` exported, `computeMoEGraphLayout` exposed)
- App.js integration (`renderMoEDAG` defined, `handleSlashCommand` referenced)
- Index.html load order (scripts in correct sequence)
- CSS rule presence (`.moe-dag`, `.mko-suggest`, `.moe-debug`)
- Documentation sync (run.md mentions all commands)

---

## Feature Summary Table

| Feature | Category | Dependencies | Requires API Key? | Local? |
|---|---|---|---|---|
| Multi-Agent Chat | Core | None | No (demo mode works) | ✅ |
| 5 LLM Providers | Core | httpx | Per-provider | ✅ (Ollama) |
| Slash Commands | UX | None | No | ✅ |
| MoE Agent | AI | httpx | For cloud experts | ✅ (Ollama only) |
| Agent DAG Canvas | Visualization | None | No | ✅ |
| GPU Benchmark | Compute | NumPy (required), PyTorch (optional) | No | ✅ |
| Provider Benchmark | Monitoring | httpx | For cloud providers | ✅ |
| RAG | AI | qdrant-client, sentence-transformers (optional) | No | ✅ |
| Stripe Credits | Billing | stripe | STRIPE_SECRET_KEY | ✅ (demo codes) |
| Admin Panel | Management | None | No (default pw) | ✅ |
| Docker + ROCm | Deployment | Docker, ROCm drivers | No | ✅ |
| CI/CD | DevOps | GitHub Actions | No | ✅ |
| Security Gates | Security | Hadolint, Trivy | No | Runs in CI |

---

*MKO Universal AI Agents — AMD Radeon Hackathon 2026, Track 2*
