# AGENTS.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Repository overview
This is a PBL-2 project implementing an **Explainable Financial Analysis System**. It ingests Bloomberg-exported financial-statement PDFs, extracts structured time-series data, and runs a multi-agent pipeline that computes deterministic financial metrics and uses a local LLM **only** for natural-language explanation.

The repository has three distinct components:

| Path | Purpose |
|------|---------|
| `ocr/` | Main project — Streamlit dashboard + full agent pipeline |
| `Agent/` | Standalone Revenue Stability Agent prototype (Groq API) |
| `financial_background_check.py` | Standalone multi-agent background check prototype (no LLM, no external APIs) |

`INS/p.py` is an unrelated Playfair cipher exercise.

---

## `ocr/` — Streamlit Financial Analysis Terminal

This is the primary codebase. A detailed breakdown is already in `ocr/AGENTS.md`.

### Setup
```sh
cd ocr
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### Run the Streamlit dashboard
```sh
# From within ocr/
streamlit run app.py
```

LLM settings are configured in the sidebar at runtime. Defaults point to a local **LM Studio** instance:
- Base URL: `http://127.0.0.1:1234/v1`
- Model: `qwen2.5-coder-1.5b-instruct-mlx`
- API Key: `local`

Any OpenAI-compatible endpoint works (change the sidebar fields).

### Run the OCR ingestion pipeline (CLI, no UI)
```sh
# From within ocr/  — scans input_pdfs/, writes to output/
python -m src.main

# Custom directories
python -m src.main --input path/to/pdfs --output path/to/output

# Verbose logging
python -m src.main --verbose
```

### No test suite or linter is configured.

---

## `Agent/` — Revenue Stability Agent prototype

Standalone script. Reads `Agent/as.json` (quarterly revenue data in the repo's JSON schema) and calls the **Groq API** for explanation.

### Setup
```sh
cd Agent
pip install -r requirements.txt
```

### Run
```sh
# Requires GROQ_API_KEY environment variable and as.json in the Agent/ directory
python Agent/revenue_stability_agent.py
```

---

## `financial_background_check.py` — Standalone multi-agent prototype

Pure Python, no external dependencies beyond `pandas`/`numpy`. Runs on mock data and prints a structured explainability report to stdout.

```sh
pip install pandas numpy
python financial_background_check.py
```

---

## Architecture: `ocr/` in depth

### Data flow
```
Bloomberg PDFs
    → ocr/pdf_parser.py        # writes bytes to a temp dir
    → src/extractor.py         # pdfplumber → PDFContent (pages + tables)
    → src/parser.py            # PDFContent → ParsedStatement
         ↳ src/mapper.py       # canonicalises Bloomberg line-item labels
    → src/builder.py           # merges statements per company → JSON
    → output/{company}.json    # one file per company
         ↳ {company}_revenue.json        (Income Statement fields)
         ↳ {company}_balance_sheet.json  (BS fields)
         ↳ {company}_liquidity.json      (liquidity fields)
```

### Agent pipeline (after OCR)
Each agent in `src/` follows the same pattern: **deterministic Python computation → LLM explanation only**.

- `src/revenue_agent.py` — YoY growth, CAGR, volatility, trend classification
- `src/balance_sheet_agent.py` — leverage ratio, asset/liability/equity growth, risk level
- `src/liquidity_agent.py` — current ratio, working capital trend, funding stability
- `agents/cross_reference_agent.py` — receives only pre-computed metrics from the three agents above; calls the LLM to produce an integrated narrative. **The LLM must not introduce new numbers.**

`agents/` contains thin wrappers (`run(json_path, base_url, model, api_key)`) that delegate to the corresponding `src/` implementations. `app.py` calls `agents/` exclusively.

### Streamlit app pages (`ocr/app.py`)
1. **Upload Statement** — file upload, OCR, metric cards, "RUN FULL ANALYSIS" button
2. **Agent Workflow** — interactive `streamlit-agraph` pipeline diagram with hover tooltips showing live agent outputs
3. **Financial Analysis** — full agent output cards (metrics + LLM explanations)
4. **Basel III Alignment** — static regulatory context panel

State flows through `st.session_state`: `ocr_cache` holds the parsed JSON payload and agent-specific file paths; `agent_outputs` holds the results from all four agents.

### OCR JSON schema
Every output JSON has two top-level keys:
- `entity`: `{entity_id, source, currency, source_files}`
- `time_series`: `{<canonical_field>: [{period: "YYYY-FY"|"YYYY-QN", value: float}, ...]}`

Canonical field names are defined in `src/mapper.py`. Adding a new field only requires updating `mapper.py`; it propagates through parser and builder automatically.

### Agent validation rules
All three deterministic agents require **≥ 4 aligned periods** and reject negative values for balance-sheet fields. Revenue agent additionally enforces chronological ordering and rejects nulls/NaNs.

### LLM integration constraint
The LLM is called via `langchain_openai.ChatOpenAI` with `temperature=0`. Agents pass only pre-computed metric dicts (never raw time-series) in the `HumanMessage`. System prompts explicitly forbid computing new numbers.
