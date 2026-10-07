# FinVeritas — Operational Runbook

**System**: Multi-agent financial analysis system with self-aware meta-orchestration  
**Stack**: Streamlit · LangChain · SQLite · ROCm/vLLM  
**Compliance**: DPDP Act 2023 · RBI Digital Lending Guidelines 2022 · RBI IT Framework

---

## Table of Contents

1. [System Requirements](#1-system-requirements)
2. [Installation](#2-installation)
3. [Configuration](#3-configuration)
4. [Starting the App](#4-starting-the-app)
5. [First-Time Setup (in-app)](#5-first-time-setup-in-app)
6. [LLM Provider Setup](#6-llm-provider-setup)
7. [Ingestion Paths](#7-ingestion-paths)
8. [Running the Agent Pipeline](#8-running-the-agent-pipeline)
9. [Reading Results](#9-reading-results)
10. [Compliance & Audit Operations](#10-compliance--audit-operations)
11. [Stopping & Cleanup](#11-stopping--cleanup)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. System Requirements

| Component | Minimum | Recommended |
|---|---|---|
| Python | 3.10 | 3.12 |
| RAM | 4 GB | 8 GB |
| Disk | 500 MB | 2 GB (for model weights if using vLLM) |
| GPU (optional) | — | AMD Radeon RX 6000 / 7000 series (ROCm) |
| OS | Linux / macOS | Ubuntu 22.04 / Arch |

> **No GPU required** for standard operation. GPU is only needed for local AMD ROCm/vLLM inference.

---

## 2. Installation

### 2a. Standard (CPU / remote LLM)

```bash
# Clone and enter the project
git clone <repo-url>
cd finveritas/core

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2b. AMD ROCm / vLLM (local GPU inference)

Run these steps **before** `pip install -r requirements.txt`:

```bash
# 1. Install PyTorch with ROCm support
#    Replace rocm6.2 with your ROCm version (rocm5.7 for RDNA2, rocm6.2 for RDNA3)
pip install torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/rocm6.2

# 2. Install vLLM (ROCm wheels included from v0.4+)
pip install vllm>=0.4.0

# 3. Install HuggingFace tooling and optional quantisation
pip install huggingface_hub>=0.23 transformers>=4.40
pip install auto-gptq optimum   # optional — for 4-bit GPTQ models

# 4. Install app dependencies
pip install -r requirements.txt
```

Check your GPU architecture before picking a ROCm version:
```bash
rocminfo | grep "gfx"
# gfx1100 → RDNA3 (RX 7000 series) → use rocm6.2
# gfx1030 → RDNA2 (RX 6000 series) → use rocm5.7
```

---

## 3. Configuration

All settings can be provided via a `.env` file in `finveritas/core/` (auto-loaded on startup) or set directly in the sidebar each session.

### `.env` file (recommended)

```dotenv
# LLM provider — options: local, gemini, groq, vllm-rocm, openai-compatible
LLM_PROVIDER=local

# LLM endpoint and model
LLM_BASE_URL=http://127.0.0.1:1234/v1
LLM_MODEL=qwen2.5-coder-1.5b-instruct-mlx

# API keys (leave blank for local/vLLM)
LLM_API_KEY=
GEMINI_API_KEY=
GROQ_API_KEY=

# Optional data sources
NEWS_API_KEY=        # newsapi.org — enables Sentiment Agent
FMP_API_KEY=         # financialmodelingprep.com — 250 req/day free
ALPHA_VANTAGE_API_KEY=  # alphavantage.co — 25 req/day free
```

The app loads `.env` from the working directory, then falls back to the repo root. Env vars already in the shell are never overwritten.

### Output directory

All analysis artefacts write to `output/` relative to where you run the app:

| File | Purpose |
|---|---|
| `output/finveritas.db` | SQLite audit DB — all runs, agent executions, LLM calls |
| `output/audit_log.jsonl` | SHA-256 chained tamper-evident log |
| `output/<Entity>.json` | Full payload written per ingestion |
| `output/<Entity>_revenue.json` | Revenue agent input |
| `output/<Entity>_liquidity.json` | Liquidity agent input |
| `output/<Entity>_balance_sheet.json` | Balance sheet agent input |

The `output/` directory is created automatically on first run.

---

## 4. Starting the App

```bash
cd finveritas/core
source .venv/bin/activate   # if using a venv

streamlit run app.py
```

Default port: **8501**. To use a different port:

```bash
streamlit run app.py --server.port 8080
```

For headless / server deployments:

```bash
streamlit run app.py --server.headless true --server.port 8501
```

The app is ready when you see:
```
Local URL: http://localhost:8501
```

---

## 5. First-Time Setup (in-app)

### DPDP Consent Gate

On first load a full-page consent notice appears (DPDP Act 2023 compliance). You must:

1. Tick **both** checkboxes confirming data processing rights.
2. Click **"I Agree & Continue"**.

The consent timestamp is recorded in session state and shown in the sidebar. This gate reappears on every new browser session.

---

## 6. LLM Provider Setup

Open the **LLM Settings** section in the sidebar. Select your provider:

### Local / LM Studio

| Field | Value |
|---|---|
| Base URL | `http://127.0.0.1:1234/v1` |
| Model | Your loaded model name (e.g. `qwen2.5-coder-1.5b-instruct-mlx`) |
| API Key | `local` |

Start LM Studio, load a model, and enable the local server before running analysis.

### Gemini (Google AI Studio)

| Field | Value |
|---|---|
| Base URL | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| Model | `gemini-2.0-flash` |
| API Key | Your Google AI Studio key (starts with `AIza`) |

### Groq

| Field | Value |
|---|---|
| Base URL | `https://api.groq.com/openai/v1` |
| Model | `llama-3.3-70b-versatile` |
| API Key | Your Groq key (starts with `gsk_`) |

### vLLM (AMD ROCm)

First, start the vLLM server on your AMD GPU:

```bash
# RDNA3 (RX 7000 series)
HSA_OVERRIDE_GFX_VERSION=11.0.0 \
ROCR_VISIBLE_DEVICES=0 \
vllm serve Qwen/Qwen2.5-7B-Instruct \
    --dtype float16 \
    --max-model-len 4096 \
    --port 8000

# Low VRAM alternative (3B, ~6 GB)
HSA_OVERRIDE_GFX_VERSION=11.0.0 \
vllm serve Qwen/Qwen2.5-3B-Instruct \
    --dtype float16 --max-model-len 4096 --port 8000

# 4-bit GPTQ for < 8 GB VRAM
HSA_OVERRIDE_GFX_VERSION=11.0.0 \
vllm serve TheBloke/Qwen2.5-7B-Instruct-GPTQ \
    --quantization gptq --dtype float16 --port 8000
```

Then in the sidebar:

| Field | Value |
|---|---|
| Provider | `vLLM (AMD ROCm)` |
| Base URL | `http://localhost:8000/v1` |
| Model | `Qwen/Qwen2.5-7B-Instruct` (must match what you served) |
| API Key | `not-needed` |

> The app validates API keys before running. `not-needed` is the correct literal value for vLLM — do not leave it blank.

---

## 7. Ingestion Paths

Navigate to **Upload Statement** in the sidebar. Four tabs are available:

### Tab 1 — Bloomberg PDF

1. Upload one or two Bloomberg PDF files (Income Statement + Balance Sheet).
2. The OCR pipeline parses them to structured JSON.
3. Upload both to enable all 5 agents; a single IS PDF enables Revenue Agent only.

### Tab 2 — Fetch by Ticker

1. Enter a stock ticker (e.g. `INFY.NS`, `AAPL`, `TCS.NS`).
2. Data is fetched from Yahoo Finance.
3. Optional: provide FMP and/or Alpha Vantage keys in the sidebar to auto-fill missing fields.

### Tab 3 — Private Company (CSV / Excel)

1. Download the template CSV using the download button.
2. Fill in your company's financials (revenue, balance sheet items by year).
3. Upload the completed file.

### Tab 4 — AA / RBI Consented Data

1. Download the sample ReBIT FI DEPOSIT JSON to understand the schema.
2. Upload a decrypted FI DEPOSIT JSON exported from your AA provider.
3. Enter the entity name and currency.
4. Click **"Load AA Consented Data"**.

> POC mode — production use requires FIU registration with RBI.

### After loading any source

The **Data Preview** and **Credibility Report** appear below the tabs. Review:
- The credibility score (0–100) and per-metric PASS/WARN/FAIL/SKIP badges.
- If any fields show FAIL or SKIP, use the **Supplemental Data** form to fill them manually or trigger auto-fetch.

---

## 8. Running the Agent Pipeline

After loading data and confirming the credibility report:

1. Scroll to **Run Agent Pipeline** on the Upload page.
2. Verify LLM provider is set in the sidebar.
3. Click **"▶ RUN FULL ANALYSIS"**.

The pipeline runs 6 agents in sequence with a spinner per stage:

| Agent | What it does |
|---|---|
| Revenue Agent | CAGR, YoY growth, volatility, trend |
| Liquidity Agent | Current/quick/cash ratio, burn rate, DSO/DPO |
| Balance Sheet Agent | D/E ratio, solvency, Altman Z-score proxy |
| Sentiment Agent | NewsAPI fetch + sentiment scoring (requires NewsAPI key) |
| Cross Reference Agent | Integrated narrative (requires all 3 core agents) |
| Meta-Orchestrator | Self-assessment: confidence scores, drift detection, advisory |

Skipped agents display a yellow info card — they do not block others.

On completion: **"Analysis complete — navigate to Financial Analysis to view results."**

---

## 9. Reading Results

Navigate to **Financial Analysis** in the sidebar.

### Meta-Orchestrator Panel (top)

- **Overall Confidence (0–100)**: weighted average of per-agent scores.
  - **HIGH (≥ 80)**: data is complete and internally consistent.
  - **MEDIUM (55–79)**: some fields missing or mild metric anomalies.
  - **LOW (< 55)**: significant data gaps or health flags — verify before use.
- **Per-agent bars**: green ≥ 80, amber ≥ 55, red < 55, dark = skipped/failed.
- **Flags**: drift alerts (amber), guardrail violations (red), data issues (grey).
- **Advisory**: LLM-generated analyst note referencing the specific flags.

### Agent Cards

Each agent card shows:
- Deterministic metrics (computed in Python — no LLM involved).
- LLM narrative (generated from metrics only, never raw data).
- Error message if the agent was skipped or failed.

### Raw JSON

Expand **Raw Agent Outputs** at the bottom of the page to inspect the full JSON for any agent.

---

## 10. Compliance & Audit Operations

Navigate to **Compliance & Audit** in the sidebar.

### Consent Status

Confirms whether DPDP consent was recorded in this session and the timestamp.

### Run History (SQLite)

Table of all analysis runs in `output/finveritas.db`. For each run:
- Expand to see per-agent execution table (status, duration, error).
- Expand **Metrics** to inspect computed ratios.
- Expand **LLM Narrative** to see the model's explanation text.
- Expand **LLM Call Log** to see every prompt, response, attempt number, and any guardrail violations.

#### Querying the DB directly

```bash
sqlite3 output/finveritas.db

.tables
-- runs  agent_executions  llm_calls

SELECT run_id, ts, entity, credibility_score FROM runs ORDER BY ts DESC LIMIT 10;

SELECT agent_name, status, duration_ms FROM agent_executions WHERE run_id = '<run_id>';

SELECT agent_name, attempt, model, violations_found FROM llm_calls WHERE run_id = '<run_id>';
```

### JSONL Audit Chain

`output/audit_log.jsonl` is a SHA-256-chained log. The page shows:
- **Chain intact** (green) — no entries have been modified since writing.
- **N violation(s)** (red) — one or more entries were tampered with.

Download the log with the **"⬇ audit_log.jsonl"** button.

Verify the chain offline:
```python
import json, hashlib

entries = [json.loads(l) for l in open("output/audit_log.jsonl")]
prev_hash = None
for i, e in enumerate(entries):
    claimed = e.get("prev_hash")
    if i > 0 and claimed != prev_hash:
        print(f"Chain broken at entry {i}")
    prev_hash = hashlib.sha256(
        json.dumps({k: v for k, v in e.items() if k != "prev_hash"},
                   sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
print("Verified", len(entries), "entries")
```

### Delete All Data (DPDP §13 Erasure)

In the sidebar **Data & Privacy** section:
1. Click **"Delete All Data"**.
2. Confirm with **"Yes, delete"**.

This removes all files written in the current session and clears session state. The SQLite DB and JSONL log in `output/` persist until manually deleted:

```bash
rm -rf output/
```

---

## 11. Stopping & Cleanup

### Stop the app

```bash
# Ctrl+C in the terminal where streamlit is running
# or kill by PID
kill $(lsof -ti:8501)
```

### Stop vLLM server (if running)

```bash
kill $(lsof -ti:8000)
```

### Remove generated output

```bash
rm -rf finveritas/core/output/
```

---

## 12. Troubleshooting

### App won't start — `ModuleNotFoundError`

```bash
# Ensure you're running from inside finveritas/core/
cd finveritas/core
pip install -r requirements.txt
streamlit run app.py
```

### `LLM configuration error: Missing/placeholder LLM API key`

- Check the **API Key** field in the sidebar is not empty or `local` when using a remote provider.
- For vLLM ROCm, the key must be the literal string `not-needed`.
- Set `LLM_API_KEY` in `.env` and click **"Reload LLM defaults from .env"**.

### `LLM returned empty cross-reference analysis` / `RuntimeError after retry`

- The LLM endpoint is reachable but returned no content.
- Check the model is loaded and the base URL is correct.
- Increase context window: for vLLM, add `--max-model-len 8192` to the serve command.

### Cross Reference Agent guardrail triggered

Logged in **Compliance & Audit → LLM Call Log** with "⚠ guardrail triggered".  
The system retried once automatically. If it fails twice, the error is surfaced in the agent card.  
Switch to a larger or instruction-tuned model for better compliance with the no-credit-decision constraint.

### Sentiment Agent skipped

Add a NewsAPI key (free at newsapi.org) in the sidebar **News** section.

### Liquidity / Balance Sheet Agent skipped — missing fields

Use the **Supplemental Data** form on the Upload page or provide FMP/Alpha Vantage keys for auto-fetch.

### vLLM: `No device found` / `ROCm not detected`

```bash
# Verify ROCm installation
rocminfo
# Verify PyTorch sees the GPU
python3 -c "import torch; print(torch.cuda.is_available(), torch.version.hip)"
# Force GFX version for unsupported cards
export HSA_OVERRIDE_GFX_VERSION=11.0.0
```

### SQLite DB locked

Occurs when multiple streamlit processes access the same DB simultaneously.  
Stop all instances and restart a single process.

### `chain broken at entry N` in JSONL audit

The `output/audit_log.jsonl` file was modified after writing.  
Do not edit this file manually. If corruption is suspected, archive it and start a new log by deleting it — the app will create a fresh one.
