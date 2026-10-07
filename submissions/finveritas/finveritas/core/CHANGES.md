# Changelog

All notable changes to the FinVeritas OCR / Financial Analysis system.

---

## [AMD Hackathon] — Track 2: Private AI Agent — Self-Aware Edition

### Meta-Orchestrator Agent (`src/meta_agent.py`) — new

The core "self-aware" addition. After every analysis pipeline run, the Meta-Orchestrator:

- **Confidence scoring**: Scores each domain agent (Revenue, Liquidity, Balance Sheet, Sentiment, Cross Reference) 0–100 based on metric completeness and health (e.g. negative current ratio, extreme D/E). Deducts points for guardrail violations logged in SQLite.
- **Drift detection**: Queries the SQLite audit log for prior runs on the same entity and alerts when any key metric (CAGR, Current Ratio, D/E, Solvency Ratio) shifts > 25% vs the previous run.
- **Flag generation**: Produces a prioritised list of actionable flags: skipped agents, low-confidence outputs, drift alerts, guardrail hits.
- **LLM advisory**: When an LLM endpoint is configured, calls the model with only the structured assessment dict (never raw data) to generate a 4–6 sentence analyst advisory. Uses `_db.instrumented_invoke()` so the advisory prompt/response is logged to the `llm_calls` audit table.
- Entry point: `run_meta_agent(entity, outputs, run_id, base_url, model, api_key)` → `dict`.

### Meta-Orchestrator UI panel (`_render_meta_panel`) — new

New panel at the top of the Financial Analysis page:
- Overall confidence badge with score (0–100) and HIGH/MEDIUM/LOW colour-coded label.
- Per-agent confidence progress bars (colour: green ≥ 80, amber ≥ 55, red < 55, dark = 0).
- Inline flags: drift alerts in amber, guardrail violations in red, data issues in grey.
- LLM advisory block in a blue-bordered card (only when the advisory was generated).

### AMD ROCm / vLLM Provider Support

- Added **"vLLM (AMD ROCm)"** to the LLM provider dropdown in the sidebar.
- `_provider_defaults("vllm-rocm")` returns `http://localhost:8000/v1`, model `Qwen/Qwen2.5-7B-Instruct`, key `not-needed`.
- `_llm_config_error()` now recognises `not-needed` as a valid key (no remote API required for local vLLM).
- Provider alias map extended for `"vllm"` / `"vllm-rocm"` / `"rocm"` env var strings.
- When the provider is selected, the sidebar shows an AMD ROCm quick-start code block with the exact `vllm serve` command.

### `requirements-rocm.txt` — new

Step-by-step AMD ROCm setup guide as a pip requirements file:
- PyTorch ROCm wheel install instructions (rocm6.2 for RDNA3, rocm5.7 for RDNA2).
- vLLM install + `vllm serve` launch command with `HSA_OVERRIDE_GFX_VERSION`.
- Recommended open-source models by VRAM budget (7B float16, 3B float16, GPTQ 4-bit).
- `auto-gptq` + `optimum` for quantised low-VRAM deployments.

### Pipeline integration

- `_run_agent_pipeline()` now calls `_meta.run_meta_agent()` after all 5 domain agents complete.
- Meta-assessment stored in `st.session_state["meta_assessment"]` and logged to SQLite `agent_executions` table as agent `meta_agent`.

---

## [Unreleased] — Working Tree

### Compliance & Audit Infrastructure

- **SQLite run tracking**: Each analysis pipeline execution now generates a UUID (`run_id`) shared across all agents. Run metadata (entity, source type, credibility score, input SHA-256 hash, consent timestamp) is written to `output/finveritas.db` via `_db.log_run()`.
- **Per-agent logging**: Every agent (Revenue, Liquidity, Balance Sheet, Sentiment, Cross Reference) writes its status, duration (ms), metrics JSON, and LLM narrative to the `agent_executions` table via `_db_log_agent()`.
- **LLM call instrumentation**: All `llm.invoke()` calls replaced with `_db.instrumented_invoke()`, which logs every system prompt, human prompt, raw response, model, endpoint, attempt number, and any guardrail violations to `llm_calls` table in SQLite.
- **Tamper-evident JSONL audit log**: After every pipeline run, a summary entry is appended to `output/audit_log.jsonl` via `audit_append()`. The chain uses SHA-256 linking so any modification breaks `audit_verify_chain()`.

### New: Compliance & Audit Page

- Added a **Compliance & Audit Trail** page (5th navigation item) surfacing:
  - DPDP consent status for the current session.
  - Queryable run history table from SQLite.
  - Per-run drilldown: agent execution table, metrics JSON, LLM narratives, full LLM call log with prompt/response.
  - Guardrail violation indicators in the LLM call log.
  - JSONL chain integrity check with green/red status indicator.
  - Downloadable `audit_log.jsonl`.
  - Regulatory alignment summary table (DPDP Act 2023, RBI Digital Lending Guidelines 2022, RBI IT Framework, RBI AA Framework).

### New: DPDP Consent Gate

- On first load, a full-page **DPDP consent gate** (`_render_consent_gate()`) blocks access until the user ticks two explicit consent checkboxes and clicks "I Agree & Continue".
- Consent timestamp is stored in session state and displayed in the sidebar.
- Sidebar now shows a **Data & Privacy** section with consent date and a **Delete All Data** button (with confirmation step) that wipes all session files and state to fulfill DPDP §13 right to erasure.

### New: Account Aggregator (AA) Tab

- Added a 4th upload tab **AA / RBI Consented Data** for ingesting decrypted ReBIT FI DEPOSIT JSON from an Account Aggregator provider.
- Includes informational banner explaining the Sahamati/FinSAT ecosystem and POC scope.
- Sample JSON download button.
- Entity name + currency selector; parsed via `src.aa_ingestion.parse_aa_deposit()`.
- Aggregated quarterly credits used as a revenue proxy fed into the standard agent pipeline.

### Cross Reference Agent — Credit-Decision Guardrail

- Added six compiled regex patterns (`_CREDIT_DECISION_PATTERNS`) covering prohibited language per RBI Digital Lending Guidelines 2022: approve/reject/deny/decline, creditworthy, bankable, and credit-decision recommendation phrases.
- LLM generation now runs in a retry loop (max 2 attempts): if the first response matches any pattern, a correction prompt is injected and the model is called again. Raises `RuntimeError` if both attempts violate the guardrail.
- Guardrail violations are logged to SQLite `llm_calls.violations_found`.

### Financial Analysis Page

- Added a persistent **"NOT A CREDIT DECISION"** disclaimer banner at the top of the Financial Analysis page citing RBI Digital Lending Guidelines 2022 and DPDP Act 2023.

### Agent `run_id` Propagation

- `run_id: str | None` parameter added to all agent entry points:
  - `agents/balance_sheet_agent.run()`
  - `agents/liquidity_agent.run()`
  - `agents/revenue_agent.run()`
  - `agents/sentiment_agent.run()`
  - `agents/cross_reference_agent.run()`
  - `src/balance_sheet_agent.run_balance_sheet_agent()` + `generate_llm_explanation()`
  - `src/liquidity_agent.run_liquidity_agent()` + `generate_llm_explanation()`
  - `src/revenue_agent.run_revenue_agent()` + `generate_explanation()`
  - `src/sentiment_agent.run_sentiment_agent()`
- `run_id` is passed through to `_db.instrumented_invoke()` so every LLM call is traceable back to its originating run.

### Pipeline Timing

- Per-agent wall-clock timing using `time.monotonic()` — duration in milliseconds recorded in SQLite for every agent invocation.

### Session State

- `last_credibility_score` and `last_source_type` now persisted to session state after the verifier runs, so they are available to the pipeline logger.

---

## [315a47c] — 2026-04-03 · Improve LLM env handling and debug agent

### LLM Configuration

- Added `_load_dotenv_fallback()`: a zero-dependency `.env` loader that reads `key=value` pairs from `.env` files in the working directory and repo roots, setting env vars only when not already present.
- Environment variables `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `NEWS_API_KEY`, `FMP_API_KEY`, `ALPHA_VANTAGE_API_KEY` now seed all sidebar defaults automatically.
- Added `_env_default_api_key(provider)`: picks the most appropriate env var for a given provider (Groq → `GROQ_API_KEY`, Gemini → `GEMINI_API_KEY`, otherwise `LLM_API_KEY`).
- Added `_llm_config_error(base_url, api_key)`: validates API key format before running the pipeline — catches missing/placeholder keys, Gemini key prefix mismatch (`AIza`), and Groq key prefix mismatch (`gsk_`). Error is shown to the user and pipeline is stopped.

### New LLM Provider: Groq

- Added **Groq** to the provider dropdown.
- `_provider_defaults("groq")` returns `https://api.groq.com/openai/v1` and `llama-3.3-70b-versatile`.

### Sidebar Improvements

- Provider list expanded to `["Local / OpenAI-compatible", "Gemini", "Groq", "Other OpenAI-compatible"]`.
- Session state seeded once per session for all LLM/API key fields, preventing resets on re-render.
- Provider alias map normalises env var strings (`"local"`, `"openai-compatible"`, etc.) to display labels.
- Sidebar field defaults update when the provider is changed but fields are still at placeholder/empty values.

### New: `src/debug_news_agent.py`

- Standalone debug script for testing the Sentiment Agent's NewsAPI integration in isolation without launching the full Streamlit app.

### `.gitignore` Updates

- Added entries to ignore generated artifacts and local environment files.

---

## [ca721dd] — Dev Container

- Added `.devcontainer/devcontainer.json` for one-click VS Code / GitHub Codespaces development environment.

---

## [138a875] — Initial Commit

### Core Application (`app.py`)

- Multi-page Streamlit app with Bloomberg-terminal dark theme.
- Pages: Upload Statement, Agent Workflow, Financial Analysis, Basel III Alignment.
- Three ingestion tabs: Bloomberg PDF, Fetch by Ticker (yfinance), Private Company (CSV/Excel).
- Data Verifier integration (`src/data_verifier.py`) with credibility scoring and PASS/WARN/FAIL/SKIP status per metric.
- Missing-data supplemental form with auto-fetch from FMP and Alpha Vantage APIs.
- Agent pipeline runner (`_run_agent_pipeline`) with `st.spinner` progress, safe error isolation (`_safe_run`), and cross-agent result aggregation.

### Agents (`agents/`)

- **`balance_sheet_agent.py`** — thin wrapper delegating to `src/balance_sheet_agent.py`.
- **`liquidity_agent.py`** — thin wrapper delegating to `src/liquidity_agent.py`.
- **`revenue_agent.py`** — thin wrapper delegating to `src/revenue_agent.py`.
- **`sentiment_agent.py`** — thin wrapper delegating to `src/sentiment_agent.py`.
- **`cross_reference_agent.py`** — LLM agent that synthesises Revenue, Liquidity, Balance Sheet, and (optionally) Sentiment outputs into a single narrative. Constraint: no new number computation, no credit decisions.

### Source Agents (`src/`)

- **`revenue_agent.py`** — Computes revenue CAGR, YoY growth, volatility, trend direction, peak/trough identification. LLM explains using only pre-computed metrics.
- **`liquidity_agent.py`** — Computes current ratio, quick ratio, cash ratio, operating cash flow ratio, cash burn rate, DSO, DPO, WCC. Includes credit-decision guardrail (retry loop) on LLM output.
- **`balance_sheet_agent.py`** — Computes D/E ratio, total liabilities/assets, solvency ratio, equity growth trend, Altman Z-score proxy. LLM explains using only pre-computed metrics.
- **`sentiment_agent.py`** — Fetches news via NewsAPI, computes deterministic sentiment metrics (positive/negative/neutral ratio, article count, top headlines, sentiment label). LLM synthesises into narrative.
- **`data_verifier.py`** — Multi-source verifier cross-checking extracted data against yfinance and FMP. Returns `CredibilityReport` with per-metric status and overall score.
- **`supplemental_fetchers.py`** — Auto-fetches missing financial fields from FMP and Alpha Vantage.
- **`private_company_ingestion.py`** — CSV/Excel ingestion for unlisted companies with field validation and template generation.
- **`yfinance_ingestion.py`** — Ticker-based data ingestion via yfinance for listed companies.
- **`parser.py`** — Parses Bloomberg PDF OCR JSON into structured time-series payload.
- **`extractor.py`** — Field extraction helpers.
- **`mapper.py`** — Maps raw field names to normalised keys.
- **`builder.py`** — Builds agent-ready JSON files from parsed payload.
- **`main.py`** — CLI entry point.

### OCR Layer (`ocr/`)

- **`pdf_parser.py`** — PDF-to-JSON OCR pipeline using a vision LLM.

### UI Layer (`ui/`)

- **`dashboard_components.py`** — Reusable Bloomberg-styled Streamlit components: section headers, metric cards, agent result panels, credibility panels, tooltips.
- **`styles.css`** — Full custom Bloomberg terminal CSS theme.

### Supporting Files

- **`requirements.txt`** — Python dependencies.
- **`AGENTS.md`** — Agent design documentation and constraints.
- **`README.md`** — Project overview and setup instructions.
- Sample output JSONs for Apple Inc., Infosys Ltd., TCS Ltd., Reliance Industries, FAT Brands Inc., Suzlon Energy, Yes Bank.
- Sample input PDFs (`input_pdfs/`).
